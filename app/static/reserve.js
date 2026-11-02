// @ts-check
// 予約：1画面に1問。メニュー → 日にち → 時間 → お名前・電話 → 確認 の順に進み、送った時点で確定する。
// 選べるのは空いている日時だけ（休みの日・満席の時間帯は押せない）。空きは店のマスタと台帳からサーバーが数える。
// フォームはセッション番号と送信キーだけを持ち、施策はサーバーがセッションから決める。
import { api, byId, dow, el, fmtDay, pageLoading } from "./common.js";
import { say } from "./mascot.js";

const params = new URLSearchParams(location.search);
const sessionId = params.get("s") || "";
const keyName = `vl:submit:${sessionId}`;
// 送信キー：同じキーで2回送っても、予約は1件にしかならない
let submitKey = sessionStorage.getItem(keyName);
if (!submitKey) {
  submitKey = crypto.randomUUID();
  sessionStorage.setItem(keyName, submitKey);
}

const state = {
  menu: params.get("menu") || "",
  day: "",
  slot: "",
  name: "",
  phone: "",
};
const STEPS = ["menu", "day", "slot", "contact", "confirm"];
let index = state.menu ? 1 : 0;
/** @type {any} */
let conf = null;
/** @type {{day: string, closed: boolean, slots: {slot: string, left: number}[]}[]} */
let avail = [];

const stepBox = byId("step");
const next = /** @type {HTMLButtonElement} */ (byId("next"));
const back = /** @type {HTMLButtonElement} */ (byId("back"));
const error = byId("error");

async function loadAvailability() {
  avail = (await api(`/api/availability?days=${conf.days_ahead}`)).days;
}

/** @param {string} title @param {string} lead @param {Node[]} body @param {"normal" | "happy"} [mood] */
function screen(title, lead, body, mood = "normal") {
  stepBox.replaceChildren(el("h1", {}, [title]), say(lead, mood, { size: 64 }), ...body);
}

/** 選ぶボタンの一覧
 * @param {{value: string, title: string, desc?: string, cls?: string, disabled?: boolean}[]} items
 * @param {string} current @param {(v: string) => void} pick @param {string} listClass */
function choices(items, current, pick, listClass) {
  const box = el("div", { class: listClass, role: "group" });
  for (const it of items) {
    const b = /** @type {HTMLButtonElement} */ (el("button", { type: "button", class: `choice ${it.cls || ""}`.trim(), "aria-pressed": String(it.value === current) }, [
      el("span", { class: "title" }, [it.title]),
      ...(it.desc ? [el("span", { class: "desc" }, [it.desc])] : []),
    ]));
    b.disabled = Boolean(it.disabled);
    b.addEventListener("click", () => {
      pick(it.value);
      for (const x of box.children) x.setAttribute("aria-pressed", String(x === b));
      update();
    });
    box.append(b);
  }
  return box;
}

function render() {
  error.textContent = "";
  const step = STEPS[index];
  const bars = STEPS.map((_, i) => el("i", { class: i <= index ? "on" : "" }));
  byId("progress").replaceChildren(...bars, el("span", {}, [`${index + 1}/${STEPS.length}`]));
  back.classList.toggle("hidden", index === 0);
  next.textContent = step === "confirm" ? "この内容で予約する" : "次へ";

  if (step === "menu") {
    screen("メニューを選んでください", "迷ったら「秋の点検」でも大丈夫。当日お店で相談できますよ。",
      [choices(conf.menus.map((/** @type {string} */ m) => ({ value: m, title: m })), state.menu, (v) => { state.menu = v; }, "choice-list")]);
  } else if (step === "day") {
    const items = avail.map((d, i) => {
      const w = dow(d.day);
      const left = d.slots.reduce((n, s) => n + s.left, 0);
      return {
        value: d.day, title: `${Number(d.day.slice(5, 7))}/${Number(d.day.slice(8, 10))}`,
        desc: d.closed ? "休み" : left === 0 ? "満席" : i === 0 ? "今日" : `${w}曜日`,
        cls: w === "土" ? "sat" : w === "日" ? "sun" : "",
        disabled: d.closed || left === 0,
      };
    });
    screen("ご来店の日は？", "空いている日だけ選べます。休みと満席の日は押せませんよ。",
      [choices(items, state.day, (v) => { state.day = v; state.slot = ""; }, "choice-list day-list")]);
  } else if (step === "slot") {
    const d = avail.find((x) => x.day === state.day);
    const items = (d ? d.slots : []).map((s) => ({
      value: s.slot, title: s.slot, desc: s.left > 0 ? `残り${s.left}` : "満席", disabled: s.left <= 0,
    }));
    screen("ご来店の時間は？", `${fmtDay(state.day)} の空いている時間です。`,
      [choices(items, state.slot, (v) => { state.slot = v; }, "slot-grid")]);
  } else if (step === "contact") {
    const name = /** @type {HTMLInputElement} */ (el("input", { class: "input", id: "name", autocomplete: "name", enterkeyhint: "next" }));
    const phone = /** @type {HTMLInputElement} */ (el("input", { class: "input", id: "phone", type: "tel", inputmode: "tel", autocomplete: "tel", placeholder: "090-0000-0000", enterkeyhint: "done" }));
    name.value = state.name;
    phone.value = state.phone;
    name.addEventListener("input", () => { state.name = name.value.trim(); update(); });
    phone.addEventListener("input", () => { state.phone = phone.value.trim(); update(); });
    screen("ご連絡先", "お店から連絡が必要な時だけ使います。",
      [el("label", { class: "field" }, [el("span", {}, ["お名前"]), name]),
       el("label", { class: "field" }, [el("span", {}, ["電話番号"]), phone])]);
  } else {
    const row = (/** @type {string} */ k, /** @type {string} */ v) => el("div", {}, [el("dt", {}, [k]), el("dd", {}, [v])]);
    screen("この内容で予約します", "押したらその場で予約が確定しますよ。", [
      el("dl", { class: "summary" }, [
        row("メニュー", state.menu), row("ご来店", `${fmtDay(state.day)} ${state.slot}`),
        row("お名前", state.name), row("電話番号", state.phone),
      ]),
    ], "happy");
  }
  update();
  window.scrollTo({ top: 0 });
}

function valid() {
  const step = STEPS[index];
  if (step === "menu") return Boolean(state.menu);
  if (step === "day") return Boolean(state.day);
  if (step === "slot") return Boolean(state.slot);
  if (step === "contact") return Boolean(state.name) && /^[0-9０-９\-－ ]{10,14}$/.test(state.phone);
  return true;
}

function update() {
  next.disabled = !valid();
}

next.addEventListener("click", async () => {
  if (!valid()) return;
  if (STEPS[index] !== "confirm") {
    index += 1;
    render();
    return;
  }
  next.disabled = true;
  next.textContent = "予約しています…";
  try {
    const r = await api("/api/reservations", {
      json: {
        session_id: sessionId, submit_key: submitKey, menu: state.menu,
        reserved_for: `${state.day}T${state.slot}`, customer_name: state.name, customer_phone: state.phone,
      },
    });
    sessionStorage.removeItem(keyName);
    location.href = `/reserve/done/${encodeURIComponent(r.reserve_no)}`;
  } catch (e) {
    const msg = /** @type {Error} */ (e).message;
    if (msg.includes("満席") || msg.includes("休み")) {
      // 選んでいる間に、ほかの人が先に予約した。空きを読み直して、時間の選び直しに戻す
      await loadAvailability();
      state.slot = "";
      index = STEPS.indexOf("slot");
      render();
      error.textContent = "ちょうど今、その時間が埋まってしまいました。ほかの時間を選んでください。";
      return;
    }
    error.textContent = `予約できませんでした。もう一度お試しください（${msg}）`;
    next.disabled = false;
    next.textContent = "この内容で予約する";
  }
});

back.addEventListener("click", () => {
  if (index > 0) { index -= 1; render(); }
});

async function main() {
  if (!sessionId) {
    stepBox.replaceChildren(el("h1", {}, ["店のページから開き直してください"]));
    next.classList.add("hidden");
    back.classList.add("hidden");
    return;
  }
  conf = await api("/api/config");
  if (conf.store) byId("store-name").textContent = conf.store.name;
  if (state.menu && !conf.menus.includes(state.menu)) { state.menu = ""; index = 0; }
  await loadAvailability();
  render();
}

main().finally(pageLoading()).catch((e) => { error.textContent = `読み込めませんでした: ${e.message}`; });
