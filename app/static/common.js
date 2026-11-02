// @ts-check
// 画面どうしで使う小さな道具。API の呼び出し、日時・割合の表示、日にちと時間帯の選び方、知らせ、読み込み中の表示。
import { loader } from "./mascot.js";

/**
 * @param {string} path
 * @param {RequestInit & {json?: unknown}} [opts]
 * @returns {Promise<any>}
 */
export async function api(path, opts = {}) {
  /** @type {RequestInit} */
  const init = { method: opts.method || (opts.json === undefined ? "GET" : "POST") };
  if (opts.json !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  }
  const res = await fetch(path, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    throw new Error(detail || `${res.status}`);
  }
  return body;
}

const DOW = ["日", "月", "火", "水", "木", "金", "土"];

/** "YYYY-MM-DD" を足し引きする（時差の影響を受けないよう UTC で数える）
 * @param {string} day @param {number} n */
export function addDays(day, n) {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** @param {string} day */
export function dow(day) {
  return DOW[new Date(`${day}T00:00:00Z`).getUTCDay()];
}

/** "11/7（土）" の形 @param {string} day */
export function fmtDay(day) {
  const [, m, d] = day.split("-");
  return `${Number(m)}/${Number(d)}（${dow(day)}）`;
}

/** @param {string | null | undefined} iso */
export function fmtDateTime(iso) {
  if (!iso) return "—";
  return `${fmtDay(iso.slice(0, 10))} ${iso.slice(11, 16)}`;
}

/** @param {number | null | undefined} rate */
export function fmtRate(rate) {
  return rate === null || rate === undefined ? "算出不可" : `${Math.round(rate * 100)}%`;
}

/** @param {string} src */
export function srcLabel(src) {
  return { flyer: "チラシ", line: "LINE", unknown: "施策不明" }[src] || src;
}

/**
 * @param {string} tag
 * @param {Record<string, string>} [attrs]
 * @param {(Node | string)[]} [children]
 */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

/** @param {string} id */
export function byId(id) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`#${id} がありません`);
  return node;
}

/** 画面の下に短い知らせを出す @param {string} msg @param {boolean} [bad] @param {Node} [icon] */
export function toast(msg, bad = false, icon) {
  const t = el("div", { class: bad ? "toast bad" : "toast", role: "status" }, icon ? [icon, msg] : [msg]);
  document.body.append(t);
  setTimeout(() => t.remove(), bad ? 5000 : 2600);
}

/**
 * 日にちのボタンの列と、時間帯のボタンの格子を作る。選んだ値は onChange で "YYYY-MM-DDTHH:MM" を返す。
 * @param {{today: string, days: number, slots: string[], value?: string | null,
 *   onChange: (value: string | null) => void, pastDays?: number}} opt
 */
export function dateTimePicker(opt) {
  let day = opt.value ? opt.value.slice(0, 10) : "";
  let slot = opt.value ? opt.value.slice(11, 16) : "";
  const wrap = el("div", { class: "picker-inner" });
  const days = el("div", { class: "day-row", role: "group", "aria-label": "日にち" });
  const slots = el("div", { class: "slot-grid", role: "group", "aria-label": "時間帯" });
  const emit = () => opt.onChange(day && slot ? `${day}T${slot}` : null);

  const start = -(opt.pastDays || 0);
  /** @type {string[]} */
  const list = [];
  for (let i = start; i < opt.days; i++) list.push(addDays(opt.today, i));
  if (day && !list.includes(day)) list.unshift(day);
  for (const d of list) {
    const w = dow(d);
    const b = el("button", {
      type: "button", class: `choice${w === "土" ? " sat" : w === "日" ? " sun" : ""}`,
      "aria-pressed": String(d === day),
    }, [
      el("span", { class: "dow" }, [d === opt.today ? "今日" : w]),
      el("span", { class: "date" }, [`${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`]),
    ]);
    b.addEventListener("click", () => {
      day = d;
      for (const x of days.children) x.setAttribute("aria-pressed", String(x === b));
      emit();
    });
    days.append(b);
  }
  const slotList = [...opt.slots];
  if (slot && !slotList.includes(slot)) slotList.push(slot);
  for (const s of slotList) {
    const b = el("button", { type: "button", class: "choice", "aria-pressed": String(s === slot) }, [s]);
    b.addEventListener("click", () => {
      slot = s;
      for (const x of slots.children) x.setAttribute("aria-pressed", String(x === b));
      emit();
    });
    slots.append(b);
  }
  wrap.append(days, slots);
  // 選んである日にちが見えるように、日にちの列だけを横に送る（画面全体は動かさない）
  requestAnimationFrame(() => {
    const on = /** @type {HTMLElement | null} */ (days.querySelector('[aria-pressed="true"]'));
    if (on) days.scrollLeft = on.offsetLeft - days.offsetLeft - (days.clientWidth - on.offsetWidth) / 2;
  });
  return wrap;
}

/**
 * 画面を開いた時の読み込み中の表示（ナットクがナットを締める）。
 * 手元では一瞬で終わるので、そのタブで最初に開いた時だけ最低 minMs は見せる（2回目からは待たせない）。返した関数を呼ぶと消える。
 * @param {number} [minMs]
 */
export function pageLoading(minMs = 700) {
  const key = `vl:loaded:${location.pathname}`;
  let seen = false;
  try { seen = sessionStorage.getItem(key) === "1"; sessionStorage.setItem(key, "1"); } catch { /* 保存できなくても動く */ }
  if (seen) return () => {};
  const started = performance.now();
  const cover = el("div", { class: "page-loader" }, [loader()]);
  document.body.append(cover);
  return () => {
    const wait = Math.max(0, minMs - (performance.now() - started));
    setTimeout(() => {
      cover.classList.add("out");
      setTimeout(() => cover.remove(), 300);
    }, wait);
  };
}
