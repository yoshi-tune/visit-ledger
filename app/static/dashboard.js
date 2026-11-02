// @ts-check
// 効果の画面：媒体ごとの来店率（数字の札）、LP から予約までの漏斗（横棒）、予約の内訳。
// 分析の依頼と、結果・実行の記録の表示。
import { api, byId, el, fmtDay, fmtRate, srcLabel } from "./common.js";
import { say } from "./mascot.js";

const ask = /** @type {HTMLButtonElement} */ (byId("ask"));

/** @param {any} c */
function kpi(c) {
  const b = c.reservations;
  return el("section", { class: "card kpi" }, [
    el("div", { class: "label" }, [el("span", { class: `dot ${c.src}` }), `${srcLabel(c.src)} 経由の来店率`]),
    el("div", { class: "value" }, [fmtRate(c.visit_rate)]),
    el("div", { class: "sub" }, [`来店 ${b.visited} ÷（来店 ${b.visited} ＋ 来店未記録 ${b.unrecorded}）`]),
    el("div", { class: "mini" }, [
      el("div", {}, [el("b", {}, [String(b.total)]), el("span", {}, ["予約"])]),
      el("div", {}, [el("b", {}, [String(b.waiting)]), el("span", {}, ["来店待ち"])]),
      el("div", {}, [el("b", {}, [String(b.requested)]), el("span", {}, ["未連絡"])]),
    ]),
  ]);
}

/** @param {any} c */
function funnelCard(c) {
  const top = c.stages[0].count || 1;
  const rows = c.stages.map((/** @type {any} */ s) => {
    const pct = Math.max(0.5, (s.count / top) * 100);
    const drop = s.drop === null ? "" : `前の段から ${s.drop} 抜けた（${fmtRate(s.drop_rate)}）`;
    return el("div", { class: "row", title: `${s.label}：${s.count}${drop ? `・${drop}` : ""}` }, [
      el("div", { class: "head" }, [el("span", {}, [s.label]), el("b", {}, [String(s.count)])]),
      el("div", { class: "track" }, [el("div", { class: `bar ${c.src}`, style: `width:${pct}%` })]),
      ...(drop ? [el("div", { class: "drop" }, [drop])] : []),
    ]);
  });
  const b = c.reservations;
  const cells = [
    ["予約", b.total], ["未連絡", b.requested], ["受けられない", b.declined], ["取消", b.cancelled],
    ["来店待ち", b.waiting], ["来店", b.visited], ["来店未記録", b.unrecorded],
  ].map(([k, v]) => el("div", {}, [el("b", {}, [String(v)]), el("span", {}, [String(k)])]));
  return el("section", { class: "card" }, [
    el("h2", {}, [`${srcLabel(c.src)}：LP から予約まで`]),
    el("div", { class: "funnel" }, rows),
    el("h3", { style: "font-size:0.9375rem;margin-top:16px" }, ["予約のその後"]),
    el("div", { class: "breakdown" }, cells),
    el("p", { class: "muted", style: "margin-top:10px" }, [`参考：配った数 ${c.distributed ?? "—"}（漏斗の分母にはしていません）`]),
  ]);
}

async function loadFunnel() {
  const f = await api("/api/funnel");
  byId("note").textContent = f.note;
  byId("period").textContent = `集計の対象：${fmtDay(f.period.from)} 〜 ${fmtDay(f.period.to)} に始まった LP のセッション`;
  byId("asof").textContent = `基準日 ${fmtDay(f.as_of)}`;
  byId("kpis").replaceChildren(...f.campaigns.map(kpi));
  byId("funnels").replaceChildren(...f.campaigns.map(funnelCard));
  byId("unknown").textContent = `施策が分からない分（漏斗の外）：LP のセッション ${f.unknown.lp_sessions}・予約 ${f.unknown.reservations}`;
}

/** @param {string} title @param {(Node | string)[]} children */
const block = (title, children) => el("section", {}, [el("h3", {}, [title]), ...children]);

/** @param {any} run */
function renderReport(run) {
  const out = [];
  if (run.error) out.push(el("div", { class: "error-box" }, [run.error]));
  const r = run.report;
  if (r) {
    if (r.mode === "messages") {
      out.push(el("p", { class: "banner" }, ["予備の形（1回の呼び出し）で書いた報告です。コードでの追加の集計はしていません。"]));
    }
    const rec = r.reconciliation;
    out.push(block("検算", [
      el("span", { class: rec.matches ? "ok-badge" : "bad-badge" }, [rec.matches ? "✓ アプリの数字と一致" : "! 食い違いあり"]),
      el("p", { style: "margin-top:8px" }, [rec.summary]),
      ...rec.differences.map((/** @type {string} */ d) => el("p", { class: "input-error" }, [d])),
      ...(rec.matches ? [el("p", { class: "muted" }, ["同じ入力に対する2つの集計が一致した、という意味です（台帳そのものの正しさの証明ではありません）。"])] : []),
    ]));
    out.push(block("見立ての変化", [el("div", { class: "views" }, [
      el("div", { class: "view" }, [el("div", { class: "muted" }, ["最初の見立て"]), el("p", {}, [r.first_view])]),
      el("div", { class: "arrow", "aria-hidden": "true" }, ["→"]),
      el("div", { class: "view after" }, [el("div", { class: "muted" }, ["集計を重ねた後"]), el("p", {}, [r.revised_view])]),
    ])]));
    out.push(block("集計を重ねた記録", [el("ol", { class: "timeline" }, (r.steps || []).map((/** @type {any} */ s) =>
      el("li", {}, [
        el("div", { class: "step-name" }, [s.step]),
        el("div", {}, [el("b", {}, [s.question])]),
        el("div", {}, [s.finding]),
        el("div", { class: "muted" }, [`→ ${s.decision}`]),
      ])))]));
    const obs = el("table");
    obs.append(el("tr", {}, [el("th", {}, ["観測した事実"]), el("th", { class: "r" }, ["数"]), el("th", {}, ["条件"]), el("th", {}, ["根拠"])]));
    for (const o of r.observations || []) {
      obs.append(el("tr", {}, [
        el("td", {}, [o.statement]),
        el("td", { class: "r" }, [`${o.numerator} / ${o.denominator}`]),
        el("td", {}, [o.condition]),
        el("td", { class: "muted" }, [(o.steps || []).join(", ")]),
      ]));
    }
    out.push(block("観測した事実（台帳の数字で言えること）", [el("div", { class: "table-wrap" }, [obs])]));
    out.push(block("原因の仮説（言い切りません）", (r.hypotheses || []).map((/** @type {any} */ h) =>
      el("div", { class: "card", style: "box-shadow:none;margin-bottom:8px" }, [
        el("p", {}, [el("b", {}, [h.statement])]),
        el("p", { class: "small" }, [`支える観測：${h.supporting}`]),
        el("p", { class: "small muted" }, [`確かめ方：${h.how_to_check}`]),
      ]))));
    out.push(block("台帳だけでは確かめられないこと", [el("ul", {}, (r.to_check || []).map((/** @type {string} */ t) => el("li", {}, [t])))]));
    const n = r.next_action;
    const dl = el("dl", {}, [
      el("dt", {}, ["手間"]), el("dd", {}, [n.effort]),
      el("dt", {}, ["見る数字"]), el("dd", {}, [n.metric]),
      el("dt", {}, ["比べる相手"]), el("dd", {}, [n.comparison]),
      el("dt", {}, ["仮置きの目標"]), el("dd", {}, [n.provisional_target]),
    ]);
    out.push(el("section", { class: "next-action" }, [
      el("div", { class: "small" }, ["次の一手（店全体で1つ）"]),
      el("div", { class: "action" }, [n.action]), dl,
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
  byId("report").replaceChildren(...out);
}

/** 案内役のひと言（分析の進み具合に合わせて表情を変える） @param {any} run */
function guide(run) {
  const tools = (run.tool_log || []).filter((/** @type {any} */ e) => e.kind === "tool").length;
  if (run.status === "queued" || run.status === "running") {
    const text = el("span", { class: "row", style: "display:flex;gap:8px;align-items:center" }, [
      el("span", { class: "spinner", "aria-hidden": "true" }),
      `Claude が台帳を調べています…${tools ? `（集計の実行 ${tools}回）` : ""}`,
    ]);
    return say(text, "think");
  }
  if (run.status === "done" && run.report) {
    const changed = run.report.first_view !== run.report.revised_view;
    return say(changed
      ? "調べ終わりました！集計を重ねて、見立てが変わりました。次の一手は下にまとめましたよ。"
      : "調べ終わりました。見立ては変わりませんでしたが、根拠と次の一手は下にまとめましたよ。", "cheer");
  }
  return say("うまく調べられませんでした。理由は下に書いてあります。", "think");
}

/** @param {string} id */
async function poll(id) {
  const run = await api(`/api/analysis/${encodeURIComponent(id)}`);
  const busy = run.status === "queued" || run.status === "running";
  byId("status").replaceChildren(guide(run));
  renderReport(run);
  if (busy) {
    setTimeout(() => poll(id), 3000);
  } else {
    ask.disabled = false;
    ask.textContent = "もう一度頼む";
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
    byId("status").textContent = `頼めませんでした：${/** @type {Error} */ (e).message}`;
    ask.disabled = false;
  }
});

async function main() {
  const conf = await api("/api/config");
  if (conf.store) byId("store").textContent = conf.store.name;
  await loadFunnel();
  byId("status").replaceChildren(say("数字の裏側を、Claude といっしょに調べますよ。終わったら次の一手をお届けします。", "normal"));
  const last = sessionStorage.getItem("vl:analysis");
  if (last) await poll(last).catch(() => sessionStorage.removeItem("vl:analysis"));
}

main().catch((e) => { byId("error").textContent = `読み込めませんでした：${e.message}`; });
