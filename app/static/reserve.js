// @ts-check
// 予約の希望：1画面に1問。メニュー → 日にち → 時間 → お名前・電話 → 確認 の順に進む。
// フォームはセッション番号と送信キーだけを持ち、施策はサーバーがセッションから決める。
import { addDays, api, byId, dow, el, fmtDay } from "./common.js";

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

const stepBox = byId("step");
const next = /** @type {HTMLButtonElement} */ (byId("next"));
const back = /** @type {HTMLButtonElement} */ (byId("back"));
const error = byId("error");

/** @param {string} title @param {string} lead @param {Node[]} body */
function screen(title, lead, body) {
  stepBox.replaceChildren(el("h1", {}, [title]), el("p", { class: "lead" }, [lead]), ...body);
}

/** 選ぶボタンの一覧 @param {{value: string, title: string, desc?: string, cls?: string}[]} items
 * @param {string} current @param {(v: string) => void} pick @param {string} listClass */
function choices(items, current, pick, listClass) {
  const box = el("div", { class: listClass, role: "group" });
  for (const it of items) {
    const b = el("button", { type: "button", class: `choice ${it.cls || ""}`.trim(), "aria-pressed": String(it.value === current) }, [
      el("span", { class: "title" }, [it.title]),
      ...(it.desc ? [el("span", { class: "desc" }, [it.desc])] : []),
    ]);
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
  next.textContent = step === "confirm" ? "この内容で希望を送る" : "次へ";

  if (step === "menu") {
    screen("メニューを選んでください", "あとから店との電話で変えることもできます。",
      [choices(conf.menus.map((/** @type {string} */ m) => ({ value: m, title: m })), state.menu, (v) => { state.menu = v; }, "choice-list")]);
  } else if (step === "day") {
    const items = [];
    for (let i = 0; i < conf.days_ahead; i++) {
      const d = addDays(conf.today, i);
      const w = dow(d);
      items.push({ value: d, title: `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`,
        desc: i === 0 ? "今日" : `${w}曜日`, cls: w === "土" ? "sat" : w === "日" ? "sun" : "" });
    }
    screen("ご希望の日は？", "店から電話で確定します。だいたいの希望で大丈夫です。",
      [choices(items, state.day, (v) => { state.day = v; }, "choice-list day-list")]);
  } else if (step === "slot") {
    screen("ご希望の時間は？", `${fmtDay(state.day)} の希望の時間を選んでください。`,
      [choices(conf.slots.map((/** @type {string} */ s) => ({ value: s, title: s })), state.slot, (v) => { state.slot = v; }, "slot-grid")]);
  } else if (step === "contact") {
    const name = /** @type {HTMLInputElement} */ (el("input", { class: "input", id: "name", autocomplete: "name", enterkeyhint: "next" }));
    const phone = /** @type {HTMLInputElement} */ (el("input", { class: "input", id: "phone", type: "tel", inputmode: "tel", autocomplete: "tel", placeholder: "090-0000-0000", enterkeyhint: "done" }));
    name.value = state.name;
    phone.value = state.phone;
    name.addEventListener("input", () => { state.name = name.value.trim(); update(); });
    phone.addEventListener("input", () => { state.phone = phone.value.trim(); update(); });
    screen("ご連絡先", "日時を確定する電話をかけるために使います。",
      [el("label", { class: "field" }, [el("span", {}, ["お名前"]), name]),
       el("label", { class: "field" }, [el("span", {}, ["電話番号"]), phone])]);
  } else {
    const row = (/** @type {string} */ k, /** @type {string} */ v) => el("div", {}, [el("dt", {}, [k]), el("dd", {}, [v])]);
    screen("この内容で送ります", "送ったあと、店から電話で日時を確定します。", [
      el("dl", { class: "summary" }, [
        row("メニュー", state.menu), row("希望の日時", `${fmtDay(state.day)} ${state.slot}`),
        row("お名前", state.name), row("電話番号", state.phone),
      ]),
    ]);
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
  next.textContent = "送っています…";
  try {
    const r = await api("/api/reservations", {
      json: {
        session_id: sessionId, submit_key: submitKey, menu: state.menu,
        requested_for: `${state.day}T${state.slot}`, customer_name: state.name, customer_phone: state.phone,
      },
    });
    sessionStorage.removeItem(keyName);
    location.href = `/reserve/done/${encodeURIComponent(r.reserve_no)}`;
  } catch (e) {
    error.textContent = `送れませんでした。もう一度お試しください（${/** @type {Error} */ (e).message}）`;
    next.disabled = false;
    next.textContent = "この内容で希望を送る";
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
  render();
}

main().catch((e) => { error.textContent = `読み込めませんでした: ${e.message}`; });
