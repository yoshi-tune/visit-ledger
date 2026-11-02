// @ts-check
// 分析の画面（別の窓）：報告と、同じエージェントのセッションに続けて質問するチャット。
import { api, byId, el, fmtDay, pageLoading } from "./common.js";
import { mascot, say } from "./mascot.js";
import { guide, renderReport } from "./report.js";

const id = decodeURIComponent(location.pathname.split("/").pop() || "");
const form = /** @type {HTMLFormElement} */ (byId("chat-form"));
const input = /** @type {HTMLTextAreaElement} */ (byId("chat-input"));
const send = /** @type {HTMLButtonElement} */ (byId("chat-send"));

const SUGGEST = [
  "金曜日に来る予定だった予約だけで見るとどうなる？",
  "来店未記録の予約は、どんな予約が多い？",
  "次の一手を店で試すなら、最初の1週間で何をすればいい？",
];

/** @param {number} cents */
const usd = (cents) => `$${(cents / 100).toFixed(2)}`;

/** 最後に描いた中身（変わった時だけ描き直し、読んでいる場所を動かさない） */
let lastReport = "";
let lastChat = "";
/** @type {ReturnType<typeof setTimeout> | undefined} */
let timer;

/** 答えの文の、太字（**…**）・コード（`…`）・箇条書き（- …）だけを描く。HTML としては読まない
 * @param {string} text */
function rich(text) {
  return text.split("\n").map((line) => {
    const m = /^(\s*)[-*]\s+(.*)$/.exec(line);
    const depth = m ? Math.floor(m[1].length / 2) : 0;
    const body = m ? m[2] : line;
    const parts = body.split(/(\*\*[^*]+\*\*|`[^`]+`)/).filter(Boolean).map((p) =>
      p.startsWith("**") ? el("b", {}, [p.slice(2, -2)])
        : p.startsWith("`") ? el("code", {}, [p.slice(1, -1)]) : document.createTextNode(p));
    return el("div", { class: m ? "li" : line.trim() ? "p" : "gap", style: m ? `margin-left:${depth * 14}px` : "" }, parts);
  });
}

/** @param {any} m */
function bubble(m) {
  if (m.role === "user") return el("div", { class: "msg user" }, [el("div", { class: "text" }, [m.text])]);
  const tools = (m.tool_log || []).filter((/** @type {any} */ e) => e.kind === "tool").length;
  if (m.status === "pending") {
    return el("div", { class: "msg bot" }, [mascot("work", 36), el("div", { class: "text" }, [
      el("span", { class: "spinner", "aria-hidden": "true" }), ` 数え直しています…${tools ? `（実行 ${tools}回）` : ""}`,
    ])]);
  }
  const body = el("div", { class: `text rich${m.status === "failed" ? " failed" : ""}` }, rich(m.text || ""));
  if (tools) body.append(el("div", { class: "muted small" }, [`台帳を集計し直しました（実行 ${tools}回）`]));
  return el("div", { class: "msg bot" }, [mascot(m.status === "failed" ? "think" : "happy", 36), body]);
}

/** @param {any} run */
function renderChat(run) {
  const key = JSON.stringify([run.can_ask, run.messages.map((/** @type {any} */ m) => [m.status, m.text, m.tool_log.length])]);
  if (key === lastChat) return;
  lastChat = key;
  const log = byId("chat-log");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.replaceChildren(...(run.messages.length ? run.messages.map(bubble)
    : [say(run.can_ask ? "報告を読んで気になったことを聞いてください。台帳を数え直して答えます。"
      : run.report?.mode === "sample" ? "見本の報告には質問できません。鍵を設定して本物の分析を頼むと、ここで続けて聞けます。"
      : "報告ができたら、ここで続けて聞けます。", "normal", { size: 48 })]));
  if (atBottom || run.messages.length) log.scrollTop = log.scrollHeight;

  const busy = run.messages.some((/** @type {any} */ m) => m.status === "pending");
  input.disabled = send.disabled = !run.can_ask || busy;
  byId("suggest").replaceChildren(...(run.can_ask && !busy ? SUGGEST.map((q) => {
    const b = el("button", { type: "button", class: "chip" }, [q]);
    b.addEventListener("click", () => { input.value = q; input.focus(); });
    return b;
  }) : []));
}

async function refresh() {
  clearTimeout(timer);
  /** @type {any} */
  let run;
  try {
    run = await api(`/api/analysis/${encodeURIComponent(id)}`);
  } catch (e) {
    byId("status").replaceChildren(say(`読み込めませんでした（${/** @type {Error} */ (e).message}）。少し待ってつなぎ直します。`, "think"));
    timer = setTimeout(refresh, 5000);
    return;
  }
  const cost = run.cost_cents == null ? "" : `・費用の目安 ${usd(run.cost_cents)}（上限 ${usd(run.budget_cents)}）`;
  byId("meta").textContent = `${run.model_label || run.model}・基準日 ${fmtDay(run.as_of)}${cost}`;
  byId("status").replaceChildren(guide(run));
  const key = JSON.stringify([run.status, run.report, run.error, run.tool_log.length]);
  if (key !== lastReport) {
    lastReport = key;
    byId("report").replaceChildren(...renderReport(run));
  }
  renderChat(run);
  const busy = run.status === "queued" || run.status === "running"
    || run.messages.some((/** @type {any} */ m) => m.status === "pending");
  if (busy) timer = setTimeout(refresh, 3000);
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  byId("chat-error").textContent = "";
  send.disabled = true;
  try {
    await api(`/api/analysis/${encodeURIComponent(id)}/messages`, { json: { text } });
    input.value = "";
  } catch (err) {
    byId("chat-error").textContent = /** @type {Error} */ (err).message;
  }
  await refresh();
});
input.addEventListener("keydown", (e) => {
  // Enter で送る・Shift+Enter で改行。日本語の変換を確定する Enter では送らない
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
    e.preventDefault();
    if (!send.disabled) form.requestSubmit();
  }
});

refresh().finally(pageLoading());
