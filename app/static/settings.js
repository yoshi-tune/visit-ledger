// @ts-check
// 店の設定：時間帯ごとの台数・休みの曜日・休みの日（店のマスタ）を変える。
// 保存しても、すでに入っている予約は動かさない（サーバーの側でもそうしている）。
import { api, byId, dow, el, fmtDay, pageLoading, toast } from "./common.js";
import { mascot, say } from "./mascot.js";

/** @type {{slots: {slot: string, capacity: number}[], closed_weekdays: number[], closed_dates: {day: string, note: string | null}[]}} */
let master = { slots: [], closed_weekdays: [], closed_dates: [] };
/** @type {any} */
let conf = null;
let dirty = false;
let staff = sessionStorage.getItem("vl:staff") || "A";

function markDirty() {
  dirty = true;
  byId("dirty").textContent = "まだ保存していない変更があります";
}

/** @param {string} label @param {() => void} fn @param {string} [cls] */
function btn(label, fn, cls = "btn soft sm") {
  const b = el("button", { type: "button", class: cls }, [label]);
  b.addEventListener("click", fn);
  return b;
}

function renderSlots() {
  master.slots.sort((a, b) => a.slot.localeCompare(b.slot));
  byId("slots").replaceChildren(...master.slots.map((s, i) => el("div", { class: "setting-row" }, [
    el("b", { class: "num" }, [s.slot]),
    el("div", { class: "stepper" }, [
      btn("−", () => { if (s.capacity > 0) { s.capacity -= 1; markDirty(); renderSlots(); } }),
      el("span", { class: "num" }, [`${s.capacity}台`]),
      btn("＋", () => { s.capacity += 1; markDirty(); renderSlots(); }),
    ]),
    btn("外す", () => { master.slots.splice(i, 1); markDirty(); renderSlots(); }, "btn danger sm"),
  ])));
}

function renderWeekdays() {
  byId("weekdays").replaceChildren(...conf.weekdays.map((/** @type {string} */ w, /** @type {number} */ i) => {
    const on = master.closed_weekdays.includes(i);
    const b = el("button", { type: "button", class: "choice", "aria-pressed": String(on) }, [w]);
    b.addEventListener("click", () => {
      master.closed_weekdays = on ? master.closed_weekdays.filter((x) => x !== i) : [...master.closed_weekdays, i];
      markDirty();
      renderWeekdays();
    });
    return b;
  }));
}

function renderDates() {
  master.closed_dates.sort((a, b) => a.day.localeCompare(b.day));
  byId("dates").replaceChildren(...(master.closed_dates.length ? master.closed_dates.map((d, i) => el("div", { class: "setting-row" }, [
    el("b", {}, [fmtDay(d.day)]),
    el("span", { class: "muted" }, [d.note || ""]),
    btn("外す", () => { master.closed_dates.splice(i, 1); markDirty(); renderDates(); }, "btn danger sm"),
  ])) : [el("p", { class: "muted" }, ["まだありません"])]));
}

async function renderPreview() {
  const data = await api(`/api/availability?days=14`);
  byId("preview").replaceChildren(...data.days.map((/** @type {any} */ d) => {
    const left = d.slots.reduce((/** @type {number} */ n, /** @type {any} */ s) => n + s.left, 0);
    const cap = d.slots.reduce((/** @type {number} */ n, /** @type {any} */ s) => n + s.capacity, 0);
    const w = dow(d.day);
    return el("div", { class: `avail-day${d.closed ? " closed" : left === 0 ? " full" : ""}` }, [
      el("div", { class: `dow ${w === "土" ? "sat" : w === "日" ? "sun" : ""}` }, [d.day === conf.today ? "今日" : w]),
      el("div", { class: "date" }, [`${Number(d.day.slice(5, 7))}/${Number(d.day.slice(8, 10))}`]),
      el("div", { class: "left" }, [d.closed ? "休み" : `空き ${left}/${cap}`]),
    ]);
  }));
}

async function main() {
  conf = await api("/api/config");
  if (conf.store) byId("store").textContent = conf.store.name;
  master = await api("/api/master");
  byId("guide").append(say("時間帯ごとの台数と休みを決めると、お客様の予約の画面にすぐ反映されますよ。", "normal"));
  renderSlots();
  renderWeekdays();
  renderDates();
  await renderPreview();

  byId("add-slot").addEventListener("click", () => {
    const input = /** @type {HTMLInputElement} */ (byId("new-slot"));
    const v = input.value.slice(0, 5);
    if (!/^\d\d:\d\d$/.test(v)) { toast("時刻を入れてください", true); return; }
    if (master.slots.some((s) => s.slot === v)) { toast(`${v} はもうあります`, true); return; }
    master.slots.push({ slot: v, capacity: 1 });
    input.value = "";
    markDirty();
    renderSlots();
  });
  byId("add-date").addEventListener("click", () => {
    const d = /** @type {HTMLInputElement} */ (byId("new-date"));
    const n = /** @type {HTMLInputElement} */ (byId("new-note"));
    if (!d.value) { toast("日にちを選んでください", true); return; }
    if (master.closed_dates.some((x) => x.day === d.value)) { toast("その日はもう休みです", true); return; }
    master.closed_dates.push({ day: d.value, note: n.value.trim() || null });
    d.value = ""; n.value = "";
    markDirty();
    renderDates();
  });
  byId("save").addEventListener("click", async () => {
    try {
      master = await api("/api/master", { method: "PUT", json: { staff, ...master } });
      dirty = false;
      byId("dirty").textContent = "";
      renderSlots(); renderWeekdays(); renderDates();
      await renderPreview();
      toast("保存しました。すでに入っている予約はそのままです", false, mascot("cheer", 30));
    } catch (e) {
      toast(`保存できませんでした：${/** @type {Error} */ (e).message}`, true);
    }
  });
  window.addEventListener("beforeunload", (e) => { if (dirty) e.preventDefault(); });
}

main().finally(pageLoading()).catch((e) => toast(`読み込めませんでした：${e.message}`, true));
