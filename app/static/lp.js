// @ts-check
// LP：開いた時にサーバーでセッションを作る。同じタブで同じ施策の URL なら同じセッションを使い直す。
// メニューを押しても、下のボタンを押しても「予約ボタンのタップ」として1回記録して予約へ進む。
// 「クーポン」はこのセッションのクーポンを出してクーポンの画面へ（もう一度押しても同じ番号）。
import { api, byId, el, pageLoading } from "./common.js";
import { say } from "./mascot.js";

const MENU_DESC = {
  "オイル交換": "エンジンオイルの交換（30分ほど）",
  "タイヤ交換": "冬タイヤへの履き替え（40分ほど）",
  "秋の点検": "ブレーキ・バッテリーなどの点検（60分ほど）",
};

const store = location.pathname.split("/").filter(Boolean)[1] || "";
const params = new URLSearchParams(location.search);
const campaign = params.get("campaign") || "";
const src = params.get("src") || "";
const key = `vl:session:${store}:${campaign}:${src}`;

/** @type {string | null} */
let sessionId = sessionStorage.getItem(key);

/** @param {string} [menu] */
async function go(menu) {
  if (!sessionId) return;
  await api("/api/events", { json: { session_id: sessionId, name: "reserve_tap" } });
  const q = new URLSearchParams({ s: sessionId });
  if (menu) q.set("menu", menu);
  location.href = `/reserve?${q}`;
}

async function main() {
  const conf = await api("/api/config");
  if (conf.store) {
    byId("store-name").textContent = conf.store.name;
    document.title = `秋の点検キャンペーン｜${conf.store.name}`;
  }
  byId("guide").append(say("空いている日時を選ぶだけで、その場で予約が確定しますよ。", "happy"));
  const list = byId("menus");
  for (const m of conf.menus) {
    const b = el("button", { type: "button", class: "choice" }, [
      el("span", { class: "title" }, [m]),
      el("span", { class: "desc" }, [MENU_DESC[/** @type {keyof typeof MENU_DESC} */ (m)] || ""]),
    ]);
    b.addEventListener("click", () => go(m));
    list.append(b);
  }
  // 施策の名前と期間（店の設定の画面で足した施策も、その名前で出す。見つからなければ秋の見本のまま）
  if (campaign) {
    try {
      const c = await api(`/api/campaigns/${encodeURIComponent(campaign)}/public`);
      if (c.title !== byId("title").textContent) byId("lead").textContent = "空いている日時を選ぶだけで、その場で予約が確定します。";
      byId("title").textContent = c.title;
      document.title = c.title;
      const md = (/** @type {string} */ d) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`;
      if (c.started_on && c.ended_on) byId("period").textContent = `${md(c.started_on)} 〜 ${md(c.ended_on)}`;
    } catch { /* 見本のまま */ }
  }
  if (!sessionId) {
    const s = await api("/api/sessions", { json: { store, campaign, src } });
    sessionId = /** @type {string} */ (s.session_id);
    sessionStorage.setItem(key, sessionId);
  }
  byId("reserve").addEventListener("click", () => go());
  byId("coupon").addEventListener("click", async () => {
    if (!sessionId) return;
    const c = await api("/api/coupons", { json: { session_id: sessionId } });
    location.href = `/coupon/${encodeURIComponent(c.code)}?${new URLSearchParams({ s: sessionId })}`;
  });
}

main().finally(pageLoading()).catch((e) => { byId("error").textContent = `読み込めませんでした: ${e.message}`; });
