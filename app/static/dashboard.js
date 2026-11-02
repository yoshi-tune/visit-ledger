// @ts-check
// 効果の画面：媒体ごとの来店率（数字の札）、来店までの道のり（横棒）、予約の内訳。
// 分析の依頼（モデルを選び、別の画面で開く）。報告とチャットは analysis.js。
import { api, byId, el, fmtDay, fmtRate, pageLoading, srcLabel } from "./common.js";
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
      el("div", {}, [el("b", {}, [String(b.cancelled)]), el("span", {}, ["取消"])]),
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
    ["予約", b.total], ["取消", b.cancelled], ["来店待ち", b.waiting], ["来店", b.visited], ["来店未記録", b.unrecorded],
  ].map(([k, v]) => el("div", {}, [el("b", {}, [String(v)]), el("span", {}, [String(k)])]));
  return el("section", { class: "card" }, [
    el("h2", {}, [`${srcLabel(c.src)}：来店までの道のり`]),
    el("div", { class: "funnel" }, rows),
    el("h3", { style: "font-size:0.9375rem;margin-top:16px" }, ["予約のその後"]),
    el("div", { class: "breakdown" }, cells),
    ...couponRows(c),
    el("p", { class: "muted", style: "margin-top:10px" }, [`参考：配った数 ${c.distributed ?? "—"}（割合の分母にはしていません）`]),
  ]);
}

/** クーポン：LP で出した数と、店で使った数（予約あり／予約なし）。来店率には入れない @param {any} c */
function couponRows(c) {
  const k = c.coupons;
  if (!k) return [];
  const cells = [
    ["LP で出した", k.shown], ["店で使った", k.used], ["うち予約あり", k.used_with_reservation], ["うち予約なし", k.used_without_reservation],
  ].map(([label, v]) => el("div", {}, [el("b", {}, [String(v)]), el("span", {}, [String(label)])]));
  return [
    el("h3", { style: "font-size:0.9375rem;margin-top:16px" }, ["クーポン（点検 ¥500 引き）"]),
    el("div", { class: "breakdown" }, cells),
    el("p", { class: "muted", style: "margin-top:6px" }, ["「予約なし」は、ネット予約の数字には出てこない来店です（来店率には入れていません）"]),
  ];
}

async function loadFunnel() {
  const f = await api("/api/funnel");
  byId("note").textContent = f.note;
  byId("period").textContent = `集計の対象：${fmtDay(f.period.from)} 〜 ${fmtDay(f.period.to)} に始まった LP のセッション`;
  byId("asof").textContent = `基準日 ${fmtDay(f.as_of)}`;
  byId("kpis").replaceChildren(...f.campaigns.map(kpi));
  byId("funnels").replaceChildren(...f.campaigns.map(funnelCard));
  byId("unknown").textContent = `施策が分からない分（道のりの数字には入れていません）：LP のセッション ${f.unknown.lp_sessions}・予約 ${f.unknown.reservations}`;
}

/** @type {string} */
let model = "";

/** @param {number} cents */
const usd = (cents) => `$${(cents / 100).toFixed(2)}`;
/** @type {any} */
let costs = { budget_cents: 300, by_model: [] };

/** @param {any} conf */
function renderModels(conf) {
  model = localStorage.getItem("vl:model") || conf.default_model;
  if (!conf.models.some((/** @type {any} */ m) => m.id === model)) model = conf.default_model;
  byId("models").replaceChildren(...conf.models.map((/** @type {any} */ m) => {
    const b = el("button", { type: "button", class: "choice", "aria-pressed": String(m.id === model) }, [
      el("span", { class: "title" }, [m.label + (m.id === conf.default_model ? "（既定）" : "")]),
      el("span", { class: "desc" }, [m.note]),
      ...measured(m.id),
    ]);
    b.addEventListener("click", () => {
      model = m.id;
      try { localStorage.setItem("vl:model", model); } catch { /* 覚えられなくても動く */ }
      renderModels(conf);
    });
    return b;
  }));
}

/** これまでに実際にかかった額（目安） @param {string} id */
function measured(id) {
  const c = costs.by_model.find((/** @type {any} */ x) => x.model === id);
  return c ? [el("span", { class: "desc cost" }, [`これまで ${c.runs}回・1回 平均 ${usd(c.avg_cents)}`])] : [];
}

function renderCostNote() {
  const total = costs.by_model.reduce((/** @type {number} */ n, /** @type {any} */ c) => n + (c.total_cents || 0), 0);
  byId("cost-note").textContent = `1回の上限 ${usd(costs.budget_cents)}（続けての質問も含む）`
    + (total ? `・これまでの合計の目安 ${usd(total)}` : "")
    + "。目安は定価で数えた額です。正しい額は Claude Console で確かめてください。";
}

/** 前に頼んだ分析への入口 @param {string} id */
function showLast(id) {
  const link = el("a", { href: `/analysis/${encodeURIComponent(id)}`, target: "vl-analysis" }, ["分析の画面を開く"]);
  byId("status").replaceChildren(say(el("span", {}, ["分析は別の画面で進めています。閉じてしまった時は ", link, " から戻れます。"]), "work"));
}

ask.addEventListener("click", async () => {
  ask.disabled = true;
  // ポップアップを止められないよう、押した瞬間に窓を開けておき、番号が決まってから行き先を入れる
  const win = window.open("about:blank", "vl-analysis", "popup,width=1200,height=880");
  try {
    const r = await api("/api/analysis", { json: { model } });
    sessionStorage.setItem("vl:analysis", r.analysis_id);
    const url = `/analysis/${encodeURIComponent(r.analysis_id)}`;
    if (win) win.location.href = url; else location.href = url;
    showLast(r.analysis_id);
  } catch (e) {
    win?.close();
    byId("status").textContent = `頼めませんでした：${/** @type {Error} */ (e).message}`;
  } finally {
    ask.disabled = false;
  }
});

async function main() {
  const conf = await api("/api/config");
  if (conf.store) byId("store").textContent = conf.store.name;
  costs = await api("/api/analysis-costs").catch(() => costs);
  renderModels(conf);
  renderCostNote();
  await loadFunnel();
  const last = sessionStorage.getItem("vl:analysis");
  if (last) showLast(last);
  else byId("status").replaceChildren(say("数字の裏側を、Claude といっしょに調べますよ。終わったら、続けてチャットで聞けます。", "normal"));
}

main().finally(pageLoading()).catch((e) => { byId("error").textContent = `読み込めませんでした：${e.message}`; });
