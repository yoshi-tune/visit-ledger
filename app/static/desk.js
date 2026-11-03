// @ts-check
// 受付：今日の予約に来店を付ける・来店の取り消し・日時の変更・取消・名前で探す・押し忘れの後日記録。
// 予約はお客様が送った時点で確定しているので、店から電話で確定する作業は無い。
// 名前での検索は画面の中だけで行う（名前を URL やログに出さない）。
// 「ナットクに頼む」で足したタブ（例：前日のお知らせ）は、当てはまる予約をサーバーが数えて返し、ここでは並べて記録を付けるだけ。
import { addDays, api, availabilityPicker, byId, el, fmtDateTime, fmtDay, pageLoading, srcLabel, toast } from "./common.js";
import { mascot, say } from "./mascot.js";

/** @typedef {{reserve_no: string, menu: string, requested_for: string, confirmed_for: string,
 *   status: string, src: string, customer_name: string, customer_phone: string,
 *   visited_at: string | null, recorded_at: string | null, created_at: string}} Reservation */

const STATUS = { confirmed: "予約", visited: "来店", cancelled: "取消" };
const HINT = {
  today: "お客様が来たら「来店」。時間の早い順に並んでいます。",
  visited: "今日来たお客様です。間違えて押した来店は「来店を取り消す」で予約に戻せます。",
  upcoming: "明日からの予約です。お客様から連絡があったら、日時を変えるか取消にします。",
  search: "お名前の一部で探せます（すべての予約から）。",
  past: "来店予定日がその日で、来店の記録が無い予約を出します。来ていたら「この日に来店」。",
};
/** 一覧が空の時のひと言 */
const EMPTY = {
  today: ["今日の予約は、ほかにありません。", "normal"],
  visited: ["今日の来店はまだありません。", "normal"],
  upcoming: ["明日からの予約は、まだありません。", "normal"],
  search: ["見つかりませんでした。別の書き方でも探してみてください。", "think"],
  past: ["この日が来店予定で、来店の記録が無い予約はありません。", "happy"],
};
const REFRESH_MS = 30000;

/** @type {Reservation[]} */
let all = [];
/** @type {any} */
let conf = null;
// 「ナットクに頼む」の「受付で見る」からは、足したタブを直接開く（/desk?tab=x:tab1）
let tab = new URLSearchParams(location.search).get("tab") || sessionStorage.getItem("vl:desk-tab") || "today";
if (!(tab in HINT) && !tab.startsWith("x:")) tab = "today";
/** 足したタブ（サーバーが条件で選んだ予約番号つき） @type {{id: string, title: string, conditions_text: string[], reserve_nos: string[]}[]} */
let extraTabs = [];
/** 予約番号 → お知らせの記録 @type {Record<string, {at: string, result: string, handled_by: string}[]>} */
let reminders = {};
const REMINDER = { sent: "送った", replied: "返事あり", rescheduled: "日時を変えた" };
/** 受付で押す記録（「日時を変えた」は「日時を変える」で変えた時に自動で残る） */
const REMINDER_BUTTONS = { sent: "送った", replied: "返事あり" };
/** @returns {typeof extraTabs[number] | undefined} */
const currentExtra = () => extraTabs.find((t) => `x:${t.id}` === tab);
let staff = sessionStorage.getItem("vl:staff") || "A";
let query = "";
let pastDay = "";
/** 開いている「日時を変える」欄 */
let openPicker = "";
/** @type {any[]} */
let avail = [];

const day = (/** @type {string | null} */ iso) => (iso || "").slice(0, 10);

/** @param {string} path @param {object} body @param {string} done @param {string} [method] @param {boolean} [cheer] */
async function act(path, body, done, method, cheer = false) {
  try {
    await api(path, { json: { staff, ...body }, method });
    toast(done, false, cheer ? mascot("cheer", 30) : undefined);
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
  const top = el("div", { class: "top" }, [
    el("div", {}, [
      el("div", { class: "name" }, [`${r.customer_name} 様`]),
      el("a", { href: `tel:${r.customer_phone}`, class: "small" }, [r.customer_phone]),
    ]),
    isToday
      ? el("div", { class: "time" }, [r.confirmed_for.slice(11, 16)])
      : el("span", { class: `status ${r.status}` }, [STATUS[/** @type {keyof typeof STATUS} */ (r.status)] || r.status]),
  ]);
  const meta = el("div", { class: "meta" }, [
    el("span", {}, [r.menu]),
    el("span", {}, [`来店予定 ${fmtDateTime(r.confirmed_for)}`]),
    el("span", { class: "tag" }, [el("span", { class: `dot ${r.src}` }), srcLabel(r.src)]),
    el("span", { class: "muted" }, [r.reserve_no]),
  ]);
  const actions = el("div", { class: "actions" });
  const box = el("div", { class: "card rcard" }, [top, meta, actions]);

  const extra = currentExtra();
  // お知らせの記録は、どのタブからでも見える（翌日の返事も付けられる）
  const done = reminders[r.reserve_no] || [];
  if (done.length) {
    const last = done[done.length - 1];
    box.insertBefore(el("div", { class: "small muted" }, [
      `お知らせ：${done.map((d) => REMINDER[/** @type {keyof typeof REMINDER} */ (d.result)] || d.result).join(" → ")}（最後 ${fmtDateTime(last.at)}・${last.handled_by}）`,
    ]), actions);
  }
  // 記録のボタンは、足したタブでは予約中のカードに、他のタブでは記録が始まった予約中のカードに出す（実際には送らず、記録だけ）
  if (r.status === "confirmed" && (extra || done.length)) {
    for (const [result, label] of Object.entries(REMINDER_BUTTONS)) {
      actions.append(btn(label, () => act("/api/reminders", { reserve_no: r.reserve_no, result, desk_tab_id: extra ? extra.id : null },
        `${r.customer_name} 様：「${label}」を記録しました`), "btn soft sm"));
    }
  }
  if (tab === "past") {
    actions.append(btn(`${fmtDay(pastDay)} に来店`, () => act("/api/visits",
      { reserve_no: r.reserve_no, visited_on: pastDay }, `${r.customer_name} 様の来店を ${fmtDay(pastDay)} に記録しました`, undefined, true), "btn block"));
    return box;
  }
  if (r.status === "confirmed") {
    if (day(r.confirmed_for) <= conf.today) {
      actions.append(btn("来店", () => act("/api/visits", { reserve_no: r.reserve_no }, `${r.customer_name} 様、いらっしゃいませ！来店を記録しました`, undefined, true), "btn lg"));
    }
    actions.append(btn("日時を変える", async () => {
      openPicker = openPicker === r.reserve_no ? "" : r.reserve_no;
      if (openPicker) avail = (await api(`/api/availability?days=${conf.days_ahead}`)).days;
      render();
    }, "btn soft"));
  }
  if (r.status === "visited") {
    actions.append(btn("来店を取り消す", () => {
      if (confirm(`${r.customer_name} 様の来店の記録を取り消して、予約に戻しますか？`)) {
        act(`/api/visits/${no}`, {}, "来店を取り消しました", "DELETE");
      }
    }, "btn danger"));
  }
  if (openPicker === r.reserve_no) {
    /** @type {string | null} */
    let chosen = r.confirmed_for.slice(0, 16);
    const ok = /** @type {HTMLButtonElement} */ (btn("この日時に変える", () => {
      if (chosen) act(`/api/reservations/${no}/reschedule`, { confirmed_for: chosen, desk_tab_id: extra ? extra.id : null },
        done.length ? `${fmtDateTime(chosen)} に変えました（お知らせに「日時を変えた」も記録）` : `${fmtDateTime(chosen)} に変えました`);
    }, "btn block"));
    ok.disabled = true;
    const picker = availabilityPicker({
      today: conf.today, days: avail, value: chosen,
      onChange: (v) => { chosen = v; ok.disabled = !v || v === r.confirmed_for.slice(0, 16); },
    });
    const more = el("div", { class: "actions" }, [
      btn("お客様の都合で取消", () => {
        if (confirm("この予約を取消にしますか？（枠が空きます）")) act(`/api/reservations/${no}/cancel`, {}, "取消にしました");
      }, "btn danger sm"),
    ]);
    box.append(el("div", { class: "picker" }, [picker, ok, more]));
  }
  return box;
}

function render() {
  const todayList = all.filter((r) => r.status === "confirmed" && day(r.confirmed_for) === conf.today);
  // 今日の来店は「来た日」で出す（昨日の来店を今日記録したものは入れない）
  const visited = all.filter((r) => r.status === "visited" && day(r.visited_at) === conf.today);
  const upcoming = all.filter((r) => r.status === "confirmed" && day(r.confirmed_for) > conf.today);
  byId("c-today").textContent = String(todayList.length);
  byId("c-visited").textContent = String(visited.length);
  byId("c-upcoming").textContent = String(upcoming.length);
  for (const b of document.querySelectorAll(".tabs button")) {
    b.setAttribute("aria-selected", String(/** @type {HTMLElement} */ (b).dataset.tab === tab));
  }
  renderTabs();
  const extraTab = currentExtra();
  if (tab.startsWith("x:") && !extraTab) tab = "today";  // 取り消されたタブを開いていた時
  byId("hint").textContent = extraTab
    ? `条件：${extraTab.conditions_text.join("・")}。送ったら「送った」、返事があれば「返事あり」を押してください（実際には送りません・記録だけ）。日時は「日時を変える」から変えると、「日時を変えた」も記録されます。`
    : HINT[/** @type {keyof typeof HINT} */ (tab)];

  const extra = byId("extra");
  /** @type {Reservation[]} */
  let rows = [];
  if (extraTab) { const set = new Set(extraTab.reserve_nos); rows = all.filter((r) => set.has(r.reserve_no)); extra.replaceChildren(); }
  else if (tab === "today") { rows = todayList; extra.replaceChildren(); }
  else if (tab === "visited") { rows = visited; extra.replaceChildren(); }
  else if (tab === "upcoming") { rows = upcoming; extra.replaceChildren(); }
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
  list.replaceChildren(...(rows.length ? rows.map(card) : [emptyState()]));
}

/** 足したタブのボタン（はじめからあるタブの後ろに並べる） */
function renderTabs() {
  const bar = /** @type {HTMLElement} */ (document.querySelector(".tabs"));
  for (const b of bar.querySelectorAll("button[data-extra]")) b.remove();
  for (const t of extraTabs) {
    const b = el("button", { role: "tab", "data-tab": `x:${t.id}`, "data-extra": "1" },
      [t.title, el("span", { class: "count hot" }, [String(t.reserve_nos.length)])]);
    bar.append(b);
  }
  for (const b of bar.querySelectorAll("button")) {
    b.setAttribute("aria-selected", String(/** @type {HTMLElement} */ (b).dataset.tab === tab));
  }
}

function emptyState() {
  const [text, mood] = currentExtra()
    ? ["条件に合う予約は、今はありません。", "normal"]
    : tab === "search" && !query
    ? ["お名前の一部を入れると探せますよ。", "normal"]
    : EMPTY[/** @type {keyof typeof EMPTY} */ (tab)];
  return el("div", { class: "empty", style: "grid-column:1/-1" }, [
    say(text, /** @type {"normal" | "happy" | "think" | "cheer"} */ (mood), { size: 96, cls: "center" }),
  ]);
}

async function load() {
  const [data, tabs] = await Promise.all([api("/api/reservations"), api("/api/desk-tabs")]);
  all = data.reservations;
  extraTabs = tabs.tabs;
  reminders = tabs.reminders;
  const t = new Date();
  byId("updated").textContent = `最終更新 ${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
  render();
}

/** 開きっぱなしでも新しい予約に気づけるよう、定期的に読み直す。日時を選んでいる途中は邪魔しない */
async function refresh() {
  if (openPicker || document.hidden) return;
  try { await load(); } catch { byId("updated").textContent = "更新できませんでした（通信を確かめてください）"; }
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
  // 足したタブは後から並ぶので、タブの並び全体で押されたボタンを受ける
  /** @type {HTMLElement} */ (document.querySelector(".tabs")).addEventListener("click", (e) => {
    const b = /** @type {HTMLElement | null} */ (/** @type {HTMLElement} */ (e.target).closest("button[data-tab]"));
    if (!b) return;
    tab = b.dataset.tab || "today";
    sessionStorage.setItem("vl:desk-tab", tab);
    openPicker = "";
    byId("extra").replaceChildren();
    render();
  });
  await load();
  setInterval(refresh, REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
}

main().finally(pageLoading()).catch((e) => toast(`読み込めませんでした：${e.message}`, true));
