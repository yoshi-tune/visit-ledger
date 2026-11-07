// @ts-check
// 公開版（審査用の URL）のログイン。入れたら、開こうとしていた画面（無ければ受付）へ移る。
import { api } from "./common.js";

const form = /** @type {HTMLFormElement} */ (document.getElementById("form"));
const error = /** @type {HTMLElement} */ (document.getElementById("error"));

/** 開こうとしていた画面。この店のアプリの中の道だけに限る（外のサイトへは移さない）。無ければ受付（README の順：受付 → 効果） */
function nextPath() {
  const next = new URLSearchParams(location.search).get("next") || "";
  if (!next.startsWith("/")) return "/desk";
  // 「/<タブ>/外のサイト」のような形も、ブラウザーは外のサイトとして読むので、読んだ後の行き先で確かめる
  const url = new URL(next, location.origin);
  return url.origin === location.origin ? url.pathname + url.search + url.hash : "/desk";
}

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  error.textContent = "";
  const user = /** @type {HTMLInputElement} */ (document.getElementById("user")).value.trim();
  const password = /** @type {HTMLInputElement} */ (document.getElementById("password")).value;
  try {
    await api("/api/login", { json: { user, password } });
    location.href = nextPath();
  } catch (e) {
    error.textContent = /** @type {Error} */ (e).message;
  }
});
