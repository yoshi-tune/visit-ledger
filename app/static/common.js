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
  if (res.status === 401 && location.pathname !== "/login") {
    // 公開版でログインの期限が切れた時：ログインの画面へ移り、入ったらこの画面に戻る
    location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;
  }
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

/** @typedef {{day: string, closed: boolean, slots: {slot: string, capacity: number, booked: number, left: number}[]}} DayAvail */

/**
 * 空き枠を見ながら日時を選ぶ部品（日にちの列＋時間帯の格子）。休みの日と満席の時間帯は押せない。
 * 選んだ値は onChange で "YYYY-MM-DDTHH:MM" を返す。
 * @param {{today: string, days: DayAvail[], value?: string | null, onChange: (value: string | null) => void}} opt
 */
export function availabilityPicker(opt) {
  let day = opt.value ? opt.value.slice(0, 10) : "";
  let slot = opt.value ? opt.value.slice(11, 16) : "";
  const wrap = el("div", { class: "picker-inner" });
  const daysRow = el("div", { class: "day-row", role: "group", "aria-label": "日にち" });
  const slotBox = el("div", { class: "slot-grid", role: "group", "aria-label": "時間帯" });
  const emit = () => opt.onChange(day && slot ? `${day}T${slot}` : null);
  const byDay = new Map(opt.days.map((d) => [d.day, d]));

  const drawSlots = () => {
    const d = byDay.get(day);
    if (!d) { slotBox.replaceChildren(el("p", { class: "muted" }, ["日にちを選んでください"])); return; }
    slotBox.replaceChildren(...d.slots.map((s) => {
      const full = s.left <= 0 && s.slot !== slot;
      const b = /** @type {HTMLButtonElement} */ (el("button", {
        type: "button", class: "choice", "aria-pressed": String(s.slot === slot),
      }, [el("span", { class: "title" }, [s.slot]), el("span", { class: "desc" }, [full ? "満席" : `残り${s.left}`])]));
      b.disabled = full;
      b.addEventListener("click", () => {
        slot = s.slot;
        for (const x of slotBox.children) x.setAttribute("aria-pressed", String(x === b));
        emit();
      });
      return b;
    }));
  };

  for (const d of opt.days) {
    const w = dow(d.day);
    const left = d.slots.reduce((n, s) => n + s.left, 0);
    const b = /** @type {HTMLButtonElement} */ (el("button", {
      type: "button", class: `choice${w === "土" ? " sat" : w === "日" ? " sun" : ""}`,
      "aria-pressed": String(d.day === day),
    }, [
      el("span", { class: "dow" }, [d.day === opt.today ? "今日" : w]),
      el("span", { class: "date" }, [`${Number(d.day.slice(5, 7))}/${Number(d.day.slice(8, 10))}`]),
      el("span", { class: "dow" }, [d.closed ? "休み" : left === 0 ? "満席" : `空き${left}`]),
    ]));
    b.disabled = (d.closed || left === 0) && d.day !== day;
    b.addEventListener("click", () => {
      day = d.day;
      slot = "";
      for (const x of daysRow.children) x.setAttribute("aria-pressed", String(x === b));
      drawSlots();
      emit();
    });
    daysRow.append(b);
  }
  drawSlots();
  wrap.append(daysRow, slotBox);
  // 選んである日にちが見えるように、日にちの列だけを横に送る（画面全体は動かさない）
  requestAnimationFrame(() => {
    const on = /** @type {HTMLElement | null} */ (daysRow.querySelector('[aria-pressed="true"]'));
    if (on) daysRow.scrollLeft = on.offsetLeft - daysRow.offsetLeft - (daysRow.clientWidth - on.offsetWidth) / 2;
  });
  return wrap;
}

/**
 * 画面を開いた時の読み込み中の表示（ナットクがナットを締める）。
 * 手元では一瞬で終わるので、そのタブで最初に開いた時だけ最低 minMs は見せる（2回目からは待たせない）。返した関数を呼ぶと消える。
 * @param {number} [minMs]
 */
export function pageLoading(minMs = 700) {
  // 自動操作（デモ動画の撮影）の時は出さない。撮影は場面ごとに新しいブラウザで開くので、毎回1秒ほど入ってしまうため
  if (navigator.webdriver) return () => {};
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
