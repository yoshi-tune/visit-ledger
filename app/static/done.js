// @ts-check
// 受付の完了：予約番号とメニュー・希望日時だけを出す（名前・電話は出さない）。
import { api, byId, fmtDateTime } from "./common.js";

const no = decodeURIComponent(location.pathname.split("/").pop() || "");

api(`/api/reservations/${encodeURIComponent(no)}/public`)
  .then((r) => {
    byId("no").textContent = r.reserve_no;
    byId("detail").textContent = `${r.menu}（希望：${fmtDateTime(r.requested_for)}）`;
  })
  .catch((e) => { byId("error").textContent = `読み込めませんでした: ${e.message}`; });
