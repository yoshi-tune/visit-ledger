// @ts-check
// クーポンの受付：番号（または QR で開いた URL）からクーポンを確かめ、「使った」を押した時だけ記録する。
// そのクーポンを出した LP のセッションに予約があれば、その予約と結ぶ（無ければ予約なしの来店）。
// 予約のある人は来店とクーポンを1回で記録できる。間違えて押した「使った」は取り消せる（取り消した記録は台帳に残る）。
import { api, byId, el, fmtDateTime, pageLoading, srcLabel, toast } from "./common.js";
import { say } from "./mascot.js";

let staff = sessionStorage.getItem("vl:staff") || "A";
let busy = false;

const STATUS = { confirmed: "予約中", visited: "来店済み", cancelled: "取消" };

/** @param {string} code */
async function show(code) {
  const result = byId("result");
  byId("error").textContent = "";
  const c = await api(`/api/coupons/${encodeURIComponent(code)}`);
  history.replaceState(null, "", `/desk/coupon/${encodeURIComponent(c.code)}`);
  const r = c.reservation;
  const row = (/** @type {string} */ k, /** @type {Node | string} */ v) => el("div", {}, [el("dt", {}, [k]), el("dd", {}, [v])]);
  const used = Boolean(c.redeemed_at);
  const card = el("section", { class: "card" }, [
    el("h3", {}, [`点検 ¥500 引き（${srcLabel(c.src)}）`]),
    el("dl", { class: "summary" }, [
      row("番号", c.code),
      row("出した日時", fmtDateTime(c.issued_at)),
      row("状態", used ? `使用済み（${fmtDateTime(c.redeemed_at)}・担当 ${c.handled_by || "—"}）` : "未使用"),
      row("予約", r
        ? `${r.reserve_no}・${r.customer_name} 様・${r.menu}・${fmtDateTime(r.confirmed_for)}（${STATUS[/** @type {keyof typeof STATUS} */ (r.status)] || r.status}）`
        : used ? "なし（予約なしの来店）" : "なし（予約なしの来店として記録します）"),
    ]),
  ]);
  const actions = el("div", { class: "row", style: "display:flex;gap:10px;flex-wrap:wrap;margin-top:12px" });
  /** @param {string} label @param {string} cls @param {() => Promise<void>} fn @param {string} [ask] 押す前に確かめる文 */
  const button = (label, cls, fn, ask) => {
    const b = /** @type {HTMLButtonElement} */ (el("button", { class: cls, type: "button" }, [label]));
    b.addEventListener("click", () => { if (!ask || confirm(ask)) act(b, fn); });
    actions.append(b);
  };
  const canVisit = Boolean(r && r.status === "confirmed");
  if (!used && canVisit) {
    // 予約のある人：来店とクーポンを1回で記録する（片方だけ押し忘れないように）
    button("来店とクーポンを記録する", "btn", async () => {
      await api(`/api/coupons/${encodeURIComponent(c.code)}/redeem`, { json: { staff, with_visit: true } });
      toast("来店とクーポンの利用を記録しました");
      await show(c.code);
    });
    button("クーポンだけ記録する", "btn ghost", async () => {
      await api(`/api/coupons/${encodeURIComponent(c.code)}/redeem`, { json: { staff } });
      toast("クーポンの利用を記録しました（来店はまだです）");
      await show(c.code);
    });
  } else if (!used) {
    button("クーポンを使った（記録する）", "btn", async () => {
      await api(`/api/coupons/${encodeURIComponent(c.code)}/redeem`, { json: { staff } });
      toast("クーポンの利用を記録しました");
      await show(c.code);
    });
  } else {
    if (canVisit && r) {
      button("この予約の来店も記録する", "btn", async () => {
        await api("/api/visits", { json: { staff, reserve_no: r.reserve_no } });
        toast("来店を記録しました");
        await show(c.code);
      });
    }
    // 間違えて押した時に、その場で戻せるように（取り消した記録は台帳に残る）
    button("「使った」を取り消す", "btn ghost", async () => {
      await api(`/api/coupons/${encodeURIComponent(c.code)}/undo`, { json: { staff } });
      toast("「使った」を取り消しました");
      await show(c.code);
    }, "このクーポンの「使った」を取り消します。来店の記録は取り消しません（来店の取り消しは受付の画面から）。よいですか？");
  }
  card.append(actions);
  result.replaceChildren(card);
  byId("guide").replaceChildren(say(used ? "このクーポンは使用済みです。" : r
    ? "予約のあるお客様です。来店とクーポンは、1回で一緒に記録できますよ。"
    : "予約なしで来たお客様です。どの施策で来たかが台帳に残ります。", used ? "think" : "happy"));
}

/** 押している間は同じボタンを押せないようにする @param {HTMLButtonElement} b @param {() => Promise<void>} fn */
async function act(b, fn) {
  if (busy) return;
  busy = true;
  b.disabled = true;
  try { await fn(); } catch (e) { toast(/** @type {Error} */ (e).message, true); b.disabled = false; } finally { busy = false; }
}

async function main() {
  const conf = await api("/api/config");
  if (conf.store) byId("store").textContent = conf.store.name;
  const seg = byId("staff");
  for (const s of conf.staff) {
    const b = el("button", { type: "button", "aria-pressed": String(s === staff) }, [s]);
    b.addEventListener("click", () => {
      staff = s;
      sessionStorage.setItem("vl:staff", s);
      for (const x of seg.children) x.setAttribute("aria-pressed", String(x === b));
    });
    seg.append(b);
  }
  const input = /** @type {HTMLInputElement} */ (byId("code"));
  byId("find").addEventListener("submit", (e) => {
    e.preventDefault();
    const code = input.value.trim().toUpperCase();
    if (code) show(code).catch((err) => { byId("result").replaceChildren(); byId("error").textContent = err.message; });
  });
  const fromUrl = decodeURIComponent(location.pathname.split("/")[3] || "");
  if (fromUrl) {
    input.value = fromUrl;
    await show(fromUrl);
  } else {
    byId("guide").append(say("お客様のクーポンの番号を入れてください。", "normal"));
    input.focus();
  }
}

main().finally(pageLoading()).catch((e) => { byId("error").textContent = e.message; });
