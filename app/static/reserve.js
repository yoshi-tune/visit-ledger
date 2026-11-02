// @ts-check
// 予約の希望：フォームはセッション番号と送信キーだけを持つ。施策はサーバーがセッションから決める。
import { api, byId, el } from "./common.js";

const sessionId = new URLSearchParams(location.search).get("s") || "";
const keyName = `vl:submit:${sessionId}`;
// 送信キー：同じキーで2回送っても、予約は1件にしかならない
let submitKey = sessionStorage.getItem(keyName);
if (!submitKey) {
  submitKey = crypto.randomUUID();
  sessionStorage.setItem(keyName, submitKey);
}

const form = /** @type {HTMLFormElement} */ (byId("form"));
const menu = /** @type {HTMLSelectElement} */ (byId("menu"));
const when = /** @type {HTMLInputElement} */ (byId("requested_for"));
const name = /** @type {HTMLInputElement} */ (byId("name"));
const phone = /** @type {HTMLInputElement} */ (byId("phone"));
const button = /** @type {HTMLButtonElement} */ (byId("submit"));

async function main() {
  if (!sessionId) {
    byId("error").textContent = "店のページから開き直してください。";
    button.disabled = true;
    return;
  }
  const conf = await api("/api/config");
  for (const m of conf.menus) menu.append(el("option", { value: m }, [m]));
  // 希望日時の初期値：「今日」の翌日 10:00
  const next = new Date(`${conf.today}T10:00:00`);
  next.setDate(next.getDate() + 1);
  const pad = (/** @type {number} */ n) => String(n).padStart(2, "0");
  when.value = `${next.getFullYear()}-${pad(next.getMonth() + 1)}-${pad(next.getDate())}T10:00`;
}

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  button.disabled = true;
  try {
    const r = await api("/api/reservations", {
      json: {
        session_id: sessionId, submit_key: submitKey, menu: menu.value,
        requested_for: when.value, customer_name: name.value, customer_phone: phone.value,
      },
    });
    sessionStorage.removeItem(keyName);
    location.href = `/reserve/done/${encodeURIComponent(r.reserve_no)}`;
  } catch (e) {
    byId("error").textContent = `送れませんでした: ${/** @type {Error} */ (e).message}`;
    button.disabled = false;
  }
});

main().catch((e) => { byId("error").textContent = `読み込めませんでした: ${e.message}`; });
