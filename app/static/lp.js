// @ts-check
// LP：開いた時にサーバーでセッションを作る。同じタブで同じ施策の URL なら同じセッションを使い直す。
// メニューを押しても、下のボタンを押しても「予約ボタンのタップ」として1回記録して予約へ進む。
import { api, byId, el } from "./common.js";
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
  byId("guide").append(say("ネットで希望を送るだけ。日時は店から電話で決めますよ。", "happy"));
  const list = byId("menus");
  for (const m of conf.menus) {
    const b = el("button", { type: "button", class: "choice" }, [
      el("span", { class: "title" }, [m]),
      el("span", { class: "desc" }, [MENU_DESC[/** @type {keyof typeof MENU_DESC} */ (m)] || ""]),
    ]);
    b.addEventListener("click", () => go(m));
    list.append(b);
  }
  if (!sessionId) {
    const s = await api("/api/sessions", { json: { store, campaign, src } });
    sessionId = /** @type {string} */ (s.session_id);
    sessionStorage.setItem(key, sessionId);
  }
  byId("reserve").addEventListener("click", () => go());
}

main().catch((e) => { byId("error").textContent = `読み込めませんでした: ${e.message}`; });
