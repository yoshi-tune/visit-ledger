// @ts-check
// 効果の画面：施策ごとの漏斗と予約の内訳。分析の依頼と、結果・実行の記録の表示。
import { api, byId, el, fmtRate, srcLabel } from "./common.js";

const ask = /** @type {HTMLButtonElement} */ (byId("ask"));

/** @param {any} c */
function campaignCard(c) {
  const card = el("section", { class: "card" });
  card.append(el("h2", {}, [`${srcLabel(c.src)}（${c.campaign}）`]));
  card.append(el("p", {}, ["来店率 ", el("span", { class: "rate" }, [fmtRate(c.visit_rate)])]));
  const b = c.reservations;
  card.append(el("p", { class: "muted" }, [
    `来店 ${b.visited} ÷（来店 ${b.visited} ＋ 来店未記録 ${b.unrecorded}）`,
  ]));

  const stages = el("table");
  stages.append(el("tr", {}, ["段", "数", "前の段から抜けた"].map((h, i) => el("th", i ? { class: "num" } : {}, [h]))));
  for (const s of c.stages) {
    stages.append(el("tr", {}, [
      el("td", {}, [s.label]),
      el("td", { class: "num" }, [String(s.count)]),
      el("td", { class: "num" }, [s.drop === null ? "—" : `${s.drop}（${fmtRate(s.drop_rate)}）`]),
    ]));
  }
  card.append(stages);

  const rows = [
    ["予約の件数", b.total], ["未連絡", b.requested], ["受けられない", b.declined], ["取消", b.cancelled],
    ["来店待ち", b.waiting], ["来店", b.visited], ["来店未記録", b.unrecorded],
  ];
  const t = el("table");
  t.append(el("tr", {}, [el("th", {}, ["予約の内訳"]), el("th", { class: "num" }, ["件数"])]));
  for (const [k, v] of rows) t.append(el("tr", {}, [el("td", {}, [String(k)]), el("td", { class: "num" }, [String(v)])]));
  card.append(t);
  card.append(el("p", { class: "muted" }, [`参考：配った数 ${c.distributed ?? "—"}（漏斗の分母にはしていません）`]));
  return card;
}

async function loadFunnel() {
  const f = await api("/api/funnel");
  byId("note").textContent = f.note;
  byId("period").textContent = `集計の対象：${f.period.from} 〜 ${f.period.to} に始まった LP のセッション ・ 基準日 ${f.as_of}`;
  byId("campaigns").replaceChildren(...f.campaigns.map(campaignCard));
  byId("unknown").textContent = `施策不明：LP のセッション ${f.unknown.lp_sessions}・予約 ${f.unknown.reservations}（漏斗の外）`;
}

/** @param {string} title @param {(Node | string)[]} children */
const block = (title, children) => el("div", {}, [el("h3", {}, [title]), ...children]);

/** @param {any} run */
function renderReport(run) {
  const box = byId("report");
  const out = [];
  if (run.error) out.push(el("p", { class: "error" }, [run.error]));
  const r = run.report;
  if (r) {
    if (r.mode === "messages") {
      out.push(el("p", { class: "note" }, ["予備の形（1回の呼び出し）で書いた報告です。コードでの追加の集計はしていません。"]));
    }
    const rec = r.reconciliation;
    out.push(block("検算", [el("p", { class: rec.matches ? "ok" : "error" }, [
      rec.matches ? "アプリの数字と一致しました（同じ入力に対する2つの集計の一致です）" : "アプリの数字と食い違いがあります"]),
      el("p", {}, [rec.summary]), ...rec.differences.map((/** @type {string} */ d) => el("p", { class: "error" }, [d]))]));
    out.push(block("最初の見立て", [el("p", {}, [r.first_view])]));
    const steps = el("table");
    steps.append(el("tr", {}, ["集計", "確かめたこと", "出たこと", "どう決めたか"].map((h) => el("th", {}, [h]))));
    for (const s of r.steps || []) {
      steps.append(el("tr", {}, [s.step, s.question, s.finding, s.decision].map((v) => el("td", {}, [v]))));
    }
    out.push(block("集計を重ねた記録", [steps]));
    out.push(block("見直した見立て", [el("p", {}, [r.revised_view])]));
    const obs = el("table");
    obs.append(el("tr", {}, ["観測した事実", "数", "条件", "根拠"].map((h) => el("th", {}, [h]))));
    for (const o of r.observations || []) {
      obs.append(el("tr", {}, [
        el("td", {}, [o.statement]),
        el("td", { class: "num" }, [`${o.numerator}/${o.denominator}`]),
        el("td", {}, [o.condition]),
        el("td", {}, [(o.steps || []).join(", ")]),
      ]));
    }
    out.push(block("観測した事実（台帳の数字で言えること）", [obs]));
    out.push(block("原因の仮説（言い切りません）", (r.hypotheses || []).map((/** @type {any} */ h) =>
      el("p", {}, [`・${h.statement}（支える観測：${h.supporting}／確かめ方：${h.how_to_check}）`]))));
    out.push(block("台帳だけでは確かめられないこと", (r.to_check || []).map((/** @type {string} */ t) => el("p", {}, [`・${t}`]))));
    const n = r.next_action;
    out.push(block("次の一手（店全体で1つ）", [
      el("p", { class: "big" }, [n.action]),
      el("p", {}, [`手間：${n.effort}`]), el("p", {}, [`見る数字：${n.metric}`]),
      el("p", {}, [`比べる相手と期間：${n.comparison}`]), el("p", {}, [`仮置きの目標：${n.provisional_target}`]),
    ]));
  }
  const tools = (run.tool_log || []).filter((/** @type {any} */ e) => e.kind === "tool");
  if (tools.length) {
    const d = el("details", {}, [el("summary", {}, [`Claude が実行した道具の記録（${tools.length}件・アプリの側で記録）`])]);
    for (const e of tools) {
      const input = typeof e.input === "string" ? e.input : JSON.stringify(e.input, null, 1);
      d.append(el("p", { class: "muted" }, [`${e.tool}${e.is_error ? "（失敗）" : ""}`]), el("pre", {}, [input || ""]),
        el("pre", {}, [e.output || ""]));
    }
    out.push(d);
  }
  box.replaceChildren(...out);
}

const STATUS = { queued: "受け付けました", running: "Claude が調べています…", done: "終わりました", failed: "失敗しました" };

/** @param {string} id */
async function poll(id) {
  const run = await api(`/api/analysis/${encodeURIComponent(id)}`);
  const tools = (run.tool_log || []).filter((/** @type {any} */ e) => e.kind === "tool").length;
  byId("status").textContent = `${STATUS[/** @type {keyof typeof STATUS} */ (run.status)] || run.status}` +
    (tools ? `（実行した道具 ${tools}件）` : "");
  renderReport(run);
  if (run.status === "queued" || run.status === "running") {
    setTimeout(() => poll(id), 3000);
  } else {
    ask.disabled = false;
  }
}

ask.addEventListener("click", async () => {
  ask.disabled = true;
  byId("report").replaceChildren();
  try {
    const r = await api("/api/analysis", { json: {} });
    sessionStorage.setItem("vl:analysis", r.analysis_id);
    await poll(r.analysis_id);
  } catch (e) {
    byId("status").textContent = `頼めませんでした: ${/** @type {Error} */ (e).message}`;
    ask.disabled = false;
  }
});

async function main() {
  const conf = await api("/api/config");
  byId("store").textContent = conf.store ? conf.store.name : "";
  await loadFunnel();
  const last = sessionStorage.getItem("vl:analysis");
  if (last) await poll(last).catch(() => sessionStorage.removeItem("vl:analysis"));
}

main().catch((e) => { byId("error").textContent = `読み込めませんでした: ${e.message}`; });
