// @ts-check
// 受付：店の確定・受けられない・取消、来店の記録と取り消し、名前での検索、押し忘れの後日記録。
// 名前での検索は画面の中だけで行う（名前を URL やログに出さない）。
import { addDays, api, byId, dateTimePicker, el, fmtDateTime, fmtDay, srcLabel, toast } from "./common.js";

/** @typedef {{reserve_no: string, menu: string, requested_for: string, confirmed_for: string | null,
 *   status: string, src: string, customer_name: string, customer_phone: string,
 *   visited_at: string | null, recorded_at: string | null}} Reservation */

const STATUS = { requested: "未連絡", confirmed: "確定", visited: "来店", declined: "受けられない", cancelled: "取消" };
const HINT = {
  requested: "電話で日時を決めたら、日にちと時間を選んで「確定」。",
  today: "お客様が来たら「来店」。時間の早い順に並んでいます。",
  visited: "間違えて押した来店は「取り消す」で確定に戻せます。",
  search: "お名前の一部で探せます（すべての予約から）。",
  past: "確定日がその日で、来店の記録が無い予約を出します。来ていたら「この日に来店」。",
};

/** @type {Reservation[]} */
let all = [];
/** @type {any} */
let conf = null;
let tab = sessionStorage.getItem("vl:desk-tab") || "requested";
let staff = sessionStorage.getItem("vl:staff") || "A";
let query = "";
let pastDay = "";
/** 開いている「日時を選ぶ」欄 */
let openPicker = "";

const day = (/** @type {string | null} */ iso) => (iso || "").slice(0, 10);

/** @param {string} path @param {object} body @param {string} done @param {string} [method] */
async function act(path, body, done, method) {
  try {
    await api(path, { json: { staff, ...body }, method });
    toast(done);
    openPicker = "";
    await load();
  } catch (e) {
    toast(`できませんでした：${/** @type {Error} */ (e).message}`, true);
  }
}

/** @param {string} label @param {() => void} fn @param {string} [cls] */
function btn(label, fn, cls = "btn") {
  const b = el("button", { type: "button", class: cls }, [label]);
  b.addEventListener("click", fn);
  return b;
}

/** @param {Reservation} r */
function card(r) {
  const no = encodeURIComponent(r.reserve_no);
  const isToday = tab === "today" || tab === "visited";
  const when = r.confirmed_for || r.requested_for;
  const top = el("div", { class: "top" }, [
    el("div", {}, [
      el("div", { class: "name" }, [`${r.customer_name} 様`]),
      el("a", { href: `tel:${r.customer_phone}`, class: "small" }, [r.customer_phone]),
    ]),
    isToday
      ? el("div", { class: "time" }, [(r.confirmed_for || "").slice(11, 16)])
      : el("span", { class: `status ${r.status}` }, [STATUS[/** @type {keyof typeof STATUS} */ (r.status)] || r.status]),
  ]);
  const meta = el("div", { class: "meta" }, [
    el("span", {}, [r.menu]),
    el("span", {}, [r.status === "requested" ? `希望 ${fmtDateTime(r.requested_for)}` : `確定 ${fmtDateTime(when)}`]),
    el("span", { class: "tag" }, [el("span", { class: `dot ${r.src}` }), srcLabel(r.src)]),
    el("span", { class: "muted" }, [r.reserve_no]),
  ]);
  const actions = el("div", { class: "actions" });
  const box = el("div", { class: "card rcard" }, [top, meta, actions]);

  if (tab === "past") {
    actions.append(btn(`${fmtDay(pastDay)} に来店`, () => act("/api/visits",
      { reserve_no: r.reserve_no, visited_on: pastDay }, `${r.customer_name} 様の来店を ${fmtDay(pastDay)} に記録しました`), "btn btn block"));
    return box;
  }
  if (r.status === "requested") {
    actions.append(btn("日時を決めて確定", () => { openPicker = openPicker === r.reserve_no ? "" : r.reserve_no; render(); }, "btn"));
  }
  if (r.status === "confirmed") {
    actions.append(btn("来店", () => act("/api/visits", { reserve_no: r.reserve_no }, `${r.customer_name} 様の来店を記録しました`), "btn lg"));
    actions.append(btn("日時を変える", () => { openPicker = openPicker === r.reserve_no ? "" : r.reserve_no; render(); }, "btn soft"));
  }
  if (r.status === "visited") {
    actions.append(btn("来店を取り消す", () => {
      if (confirm(`${r.customer_name} 様の来店の記録を取り消して、確定に戻しますか？`)) {
        act(`/api/visits/${no}`, {}, "来店を取り消しました", "DELETE");
      }
    }, "btn danger"));
  }
  if (openPicker === r.reserve_no) {
    /** @type {string | null} */
    let chosen = (r.confirmed_for || r.requested_for).slice(0, 16);
    const ok = /** @type {HTMLButtonElement} */ (btn("この日時で確定", () => {
      if (chosen) act(`/api/reservations/${no}/confirm`, { confirmed_for: chosen }, `${fmtDateTime(chosen)} で確定しました`);
    }, "btn block"));
    const picker = dateTimePicker({
      today: conf.today, days: conf.days_ahead, slots: conf.slots, value: chosen,
      onChange: (v) => { chosen = v; ok.disabled = !v; },
    });
    const more = el("div", { class: "actions" });
    if (r.status === "requested") {
      more.append(btn("受けられない", () => {
        if (confirm("この希望を「受けられない」にしますか？")) act(`/api/reservations/${no}/decline`, {}, "受けられないにしました");
      }, "btn danger sm"));
    }
    more.append(btn("お客様の都合で取消", () => {
      if (confirm("この予約を取消にしますか？")) act(`/api/reservations/${no}/cancel`, {}, "取消にしました");
    }, "btn danger sm"));
    box.append(el("div", { class: "picker" }, [picker, ok, more]));
  }
  return box;
}

function render() {
  const requested = all.filter((r) => r.status === "requested");
  const todayList = all.filter((r) => r.status === "confirmed" && day(r.confirmed_for) === conf.today)
    .sort((a, b) => (a.confirmed_for || "").localeCompare(b.confirmed_for || ""));
  const visited = all.filter((r) => r.status === "visited" && day(r.recorded_at) === conf.today);
  const setCount = (/** @type {string} */ id, /** @type {number} */ n, hot = false) => {
    const c = byId(id);
    c.textContent = String(n);
    c.className = hot && n ? "count hot" : "count";
  };
  setCount("c-requested", requested.length, true);
  setCount("c-today", todayList.length);
  setCount("c-visited", visited.length);
  for (const b of document.querySelectorAll(".tabs button")) {
    b.setAttribute("aria-selected", String(/** @type {HTMLElement} */ (b).dataset.tab === tab));
  }
  byId("hint").textContent = HINT[/** @type {keyof typeof HINT} */ (tab)];

  const extra = byId("extra");
  /** @type {Reservation[]} */
  let rows = [];
  if (tab === "requested") { rows = requested; extra.replaceChildren(); }
  else if (tab === "today") { rows = todayList; extra.replaceChildren(); }
  else if (tab === "visited") { rows = visited; extra.replaceChildren(); }
  else if (tab === "search") {
    if (!extra.querySelector("input")) {
      const input = /** @type {HTMLInputElement} */ (el("input", { class: "input search", placeholder: "お名前の一部", "aria-label": "お名前" }));
      input.value = query;
      input.addEventListener("input", () => { query = input.value.trim(); render(); });
      extra.replaceChildren(el("div", { style: "margin-bottom:16px" }, [input]));
      input.focus();
    }
    rows = query ? all.filter((r) => r.customer_name.includes(query)) : [];
  } else {
    if (!pastDay) pastDay = addDays(conf.today, -1);
    if (!extra.querySelector(".day-row")) {
      const days = el("div", { class: "day-row", style: "margin-bottom:12px" });
      for (let i = 14; i >= 1; i--) {
        const d = addDays(conf.today, -i);
        const b = el("button", { type: "button", class: "choice", "aria-pressed": String(d === pastDay) }, [
          el("span", { class: "dow" }, [i === 1 ? "昨日" : fmtDay(d).slice(-2, -1)]),
          el("span", { class: "date" }, [`${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`]),
        ]);
        b.addEventListener("click", () => {
          pastDay = d;
          for (const x of days.children) x.setAttribute("aria-pressed", String(x === b));
          render();
        });
        days.append(b);
      }
      extra.replaceChildren(days);
      requestAnimationFrame(() => { days.scrollLeft = days.scrollWidth; });
    }
    rows = all.filter((r) => r.status === "confirmed" && day(r.confirmed_for) === pastDay);
  }

  const list = byId("list");
  list.replaceChildren(...(rows.length ? rows.map(card)
    : [el("div", { class: "empty", style: "grid-column:1/-1" }, [tab === "search" && !query ? "お名前を入れてください" : "ありません"])]));
}

async function load() {
  const data = await api("/api/reservations");
  all = data.reservations;
  render();
}

async function main() {
  conf = await api("/api/config");
  if (conf.store) byId("store").textContent = conf.store.name;
  byId("today").textContent = `今日 ${fmtDay(conf.today)}`;
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
  for (const b of document.querySelectorAll(".tabs button")) {
    b.addEventListener("click", () => {
      tab = /** @type {HTMLElement} */ (b).dataset.tab || "requested";
      sessionStorage.setItem("vl:desk-tab", tab);
      openPicker = "";
      byId("extra").replaceChildren();
      render();
    });
  }
  await load();
}

main().catch((e) => toast(`読み込めませんでした：${e.message}`, true));
