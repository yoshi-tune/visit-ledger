// @ts-check
// LP：開いた時にサーバーでセッションを作る。同じタブで同じ施策の URL なら同じセッションを使い直す。
import { api, byId, el } from "./common.js";

const store = location.pathname.split("/").filter(Boolean)[1] || "";
const params = new URLSearchParams(location.search);
const campaign = params.get("campaign") || "";
const src = params.get("src") || "";
const key = `vl:session:${store}:${campaign}:${src}`;

async function main() {
  const conf = await api("/api/config");
  byId("store-name").textContent = conf.store ? conf.store.name : store;
  const list = byId("menus");
  for (const m of conf.menus) list.append(el("li", {}, [m]));

  let sessionId = sessionStorage.getItem(key);
  if (!sessionId) {
    const s = await api("/api/sessions", { json: { store, campaign, src } });
    sessionId = /** @type {string} */ (s.session_id);
    sessionStorage.setItem(key, sessionId);
  }

  byId("reserve").addEventListener("click", async () => {
    await api("/api/events", { json: { session_id: sessionId, name: "reserve_tap" } });
    location.href = `/reserve?s=${encodeURIComponent(/** @type {string} */ (sessionId))}`;
  });
}

main().catch((e) => { byId("error").textContent = `読み込めませんでした: ${e.message}`; });
