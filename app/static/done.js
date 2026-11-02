// @ts-check
// 受付の完了：予約番号とメニュー・希望日時だけを出す（名前・電話は出さない）。
import { api, byId, el, fmtDateTime } from "./common.js";
import { say } from "./mascot.js";

byId("guide").append(say("ありがとうございます！店からの電話を待っていてくださいね。", "cheer", { size: 110, cls: "center" }));

const no = decodeURIComponent(location.pathname.split("/").pop() || "");

async function main() {
  const [conf, r] = await Promise.all([
    api("/api/config"),
    api(`/api/reservations/${encodeURIComponent(no)}/public`),
  ]);
  if (conf.store) byId("store-name").textContent = conf.store.name;
  byId("no").textContent = r.reserve_no;
  const row = (/** @type {string} */ k, /** @type {string} */ v) => el("div", {}, [el("dt", {}, [k]), el("dd", {}, [v])]);
  byId("summary").replaceChildren(row("メニュー", r.menu), row("希望の日時", fmtDateTime(r.requested_for)));
}

main().catch((e) => { byId("error").textContent = `読み込めませんでした: ${e.message}`; });
