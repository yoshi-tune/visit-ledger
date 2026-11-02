// @ts-check
// クーポン（お客様の画面）：QR と番号を出す。予約もしたい人は、同じセッションのまま予約へ進む。
import { api, byId, pageLoading } from "./common.js";
import { say } from "./mascot.js";

const code = decodeURIComponent(location.pathname.split("/").pop() || "");
const session = new URLSearchParams(location.search).get("s");

async function main() {
  const [conf, c] = await Promise.all([api("/api/config"), api(`/api/coupons/${encodeURIComponent(code)}/public`)]);
  if (conf.store) byId("store-name").textContent = conf.store.name;
  byId("code").textContent = c.code;
  /** @type {HTMLImageElement} */ (byId("qr")).src = `/api/coupons/${encodeURIComponent(c.code)}/qr.svg`;
  byId("guide").append(c.used
    ? say("このクーポンは使用済みです。ご来店ありがとうございました！", "cheer", { size: 90, cls: "center" })
    : say("受付でこの画面を見せてくださいね。", "happy", { size: 90, cls: "center" }));
  if (c.used) byId("used").textContent = "使用済み";
  const reserve = /** @type {HTMLAnchorElement} */ (byId("reserve"));
  if (session) {
    reserve.addEventListener("click", async (e) => {
      e.preventDefault();
      // LP の予約ボタンと同じく「予約ボタンのタップ」として1回記録して予約へ進む
      await api("/api/events", { json: { session_id: session, name: "reserve_tap" } });
      location.href = `/reserve?${new URLSearchParams({ s: session })}`;
    });
  } else {
    reserve.parentElement?.parentElement?.remove();
  }
}

main().finally(pageLoading()).catch((e) => { byId("error").textContent = `読み込めませんでした: ${e.message}`; });
