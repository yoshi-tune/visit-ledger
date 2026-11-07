// @ts-check
// 公開版（審査用の URL）のログイン。入れたら、開こうとしていた画面（無ければ効果の画面）へ移る。
import { api } from "./common.js";

const form = /** @type {HTMLFormElement} */ (document.getElementById("form"));
const error = /** @type {HTMLElement} */ (document.getElementById("error"));

/** 開こうとしていた画面。この店のアプリの中の道だけに限る（外のサイトへは移さない） */
function nextPath() {
  const next = new URLSearchParams(location.search).get("next") || "";
  return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/dashboard";
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
