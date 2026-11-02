// @ts-check
// 受付：店の確定・受けられない・取消、来店の記録と取り消し、名前での検索、押し忘れの後日記録。
// 名前での検索は画面の中だけで行う（名前を URL やログに出さない）。
import { api, byId, el, fmtDateTime, srcLabel } from "./common.js";

/** @typedef {{reserve_no: string, menu: string, requested_for: string, confirmed_for: string | null,
 *   status: string, src: string, customer_name: string, customer_phone: string,
 *   visited_at: string | null, recorded_at: string | null}} Reservation */

/** @type {Reservation[]} */
let all = [];
let today = "";
const staff = /** @type {HTMLSelectElement} */ (byId("staff"));
const q = /** @type {HTMLInputElement} */ (byId("q"));
const pastDate = /** @type {HTMLInputElement} */ (byId("past-date"));

const STATUS = {
  requested: "未連絡", confirmed: "確定", visited: "来店", declined: "受けられない", cancelled: "取消",
};

/** @param {string} msg @param {boolean} [bad] */
function say(msg, bad = false) {
  const m = byId("message");
  m.textContent = msg;
  m.className = bad ? "error" : "ok";
}

/** @param {string} path @param {object} body @param {string} done @param {string} [method] */
async function act(path, body, done, method) {
  try {
    await api(path, { json: { staff: staff.value, ...body }, method });
    say(done);
    await load();
  } catch (e) {
    say(`できませんでした: ${/** @type {Error} */ (e).message}`, true);
  }
}

/** @param {string} iso */
const toInput = (iso) => (iso || "").slice(0, 16);

/** @param {Reservation} r @param {{pastDay?: string}} [opt] */
function actions(r, opt = {}) {
  const box = el("div", { class: "row" });
  const no = encodeURIComponent(r.reserve_no);
  const btn = (/** @type {string} */ label, /** @type {() => void} */ fn, cls = "") => {
    const b = el("button", cls ? { class: cls } : {}, [label]);
    b.addEventListener("click", fn);
    return b;
  };
  if (opt.pastDay) {
    box.append(btn("この日に来店", () => act("/api/visits",
      { reserve_no: r.reserve_no, visited_on: opt.pastDay }, `${r.reserve_no} を ${opt.pastDay} の来店として記録しました`)));
    return box;
  }
  if (r.status === "requested" || r.status === "confirmed") {
    const input = /** @type {HTMLInputElement} */ (el("input", { type: "datetime-local" }));
    input.value = toInput(r.confirmed_for || r.requested_for);
    box.append(input, btn(r.status === "requested" ? "確定" : "日時を変える", () => act(
      `/api/reservations/${no}/confirm`, { confirmed_for: input.value }, `${r.reserve_no} を確定しました`), "secondary"));
  }
  if (r.status === "confirmed") {
    box.append(btn("来店", () => act("/api/visits", { reserve_no: r.reserve_no }, `${r.reserve_no} の来店を記録しました`)));
  }
  if (r.status === "requested") {
    box.append(btn("受けられない", () => act(`/api/reservations/${no}/decline`, {}, `${r.reserve_no} を受けられないにしました`), "danger"));
  }
  if (r.status === "requested" || r.status === "confirmed") {
    box.append(btn("取消", () => act(`/api/reservations/${no}/cancel`, {}, `${r.reserve_no} を取消にしました`), "danger"));
  }
  if (r.status === "visited") {
    box.append(btn("来店の取り消し", () => act(`/api/visits/${no}`, {}, `${r.reserve_no} の来店を取り消しました`, "DELETE"), "danger"));
  }
  return box;
}

/** @param {Reservation[]} rows @param {{pastDay?: string}} [opt] */
function table(rows, opt = {}) {
  if (!rows.length) return el("p", { class: "muted" }, ["ありません"]);
  const t = el("table");
  t.append(el("tr", {}, ["番号", "状態", "メニュー", "希望", "確定", "お名前・電話", "経路", "操作"].map((h) => el("th", {}, [h]))));
  for (const r of rows) {
    t.append(el("tr", {}, [
      el("td", {}, [r.reserve_no]),
      el("td", {}, [STATUS[/** @type {keyof typeof STATUS} */ (r.status)] || r.status]),
      el("td", {}, [r.menu]),
      el("td", {}, [fmtDateTime(r.requested_for)]),
      el("td", {}, [fmtDateTime(r.confirmed_for)]),
      el("td", {}, [`${r.customer_name} ${r.customer_phone}`]),
      el("td", {}, [srcLabel(r.src)]),
      el("td", {}, [actions(r, opt)]),
    ]));
  }
  return t;
}

/** @param {string} id @param {Node} node */
function put(id, node) {
  const box = byId(id);
  box.replaceChildren(node);
}

function render() {
  const day = (/** @type {string | null} */ iso) => (iso || "").slice(0, 10);
  const requested = all.filter((r) => r.status === "requested");
  const todayList = all.filter((r) => r.status === "confirmed" && day(r.confirmed_for) === today);
  const visited = all.filter((r) => r.status === "visited" && day(r.recorded_at) === today);
  byId("n-requested").textContent = `${requested.length}件`;
  byId("n-today").textContent = `${todayList.length}件`;
  byId("n-visited").textContent = `${visited.length}件`;
  put("requested", table(requested));
  put("today-list", table(todayList));
  put("visited", table(visited));

  const word = q.value.trim();
  put("search", word ? table(all.filter((r) => r.customer_name.includes(word))) : el("span"));

  const p = pastDate.value;
  put("past", p
    ? table(all.filter((r) => r.status === "confirmed" && day(r.confirmed_for) === p), { pastDay: p })
    : el("span"));
}

async function load() {
  const data = await api("/api/reservations");
  all = data.reservations;
  today = data.today;
  render();
}

async function main() {
  const conf = await api("/api/config");
  byId("store").textContent = conf.store ? conf.store.name : "";
  byId("today").textContent = conf.today;
  for (const s of conf.staff) staff.append(el("option", { value: s }, [s]));
  pastDate.max = conf.today;
  q.addEventListener("input", render);
  pastDate.addEventListener("change", render);
  await load();
}

main().catch((e) => say(`読み込めませんでした: ${e.message}`, true));
