// @ts-check
// 効果の画面（ダッシュボード）：主な数字の札（チラシ／LINE を並べて）、来店までの道のりの図（LP を 100% とした割合で
// 2つの媒体を重ねて比べる）、Claude の見立て（いちばん新しい分析の次の一手）と分析の依頼。細かい件数は下にたたむ。
// 報告とチャットは analysis.js。
import { api, byId, el, fmtDay, fmtRate, pageLoading, srcLabel } from "./common.js";
import { say } from "./mascot.js";

const ask = /** @type {HTMLButtonElement} */ (byId("ask"));

/** 主な数字の札：1つの札にチラシと LINE を並べる（色は点で、文字は文字の色）
 * @param {string} label @param {any[]} campaigns @param {(c: any) => string} value @param {boolean} [hero] */
function tile(label, campaigns, value, hero = false) {
  return el("section", { class: `card tile${hero ? " tile-hero" : ""}` }, [
    el("div", { class: "tile-label" }, [label]),
    ...campaigns.map((c) => el("div", { class: "tile-row" }, [
      el("span", { class: "tile-src" }, [el("i", { class: `dot ${c.src}` }), srcLabel(c.src)]),
      el("b", {}, [value(c)]),
    ])),
  ]);
}

/** @param {any[]} cs */
function kpis(cs) {
  const stage = (/** @type {any} */ c, /** @type {string} */ key) => c.stages.find((/** @type {any} */ s) => s.key === key)?.count ?? 0;
  return [
    tile("LP を開いた", cs, (c) => String(stage(c, "lp_sessions"))),
    tile("予約", cs, (c) => String(c.reservations.total)),
    tile("来店", cs, (c) => String(c.reservations.visited)),
    tile("来店率（来店 ÷ 来店＋来店未記録）", cs, (c) => fmtRate(c.visit_rate), true),
    tile("クーポンを店で使った", cs, (c) => String(c.coupons?.used ?? "—")),
  ];
}

/** 来店までの道のり：段ごとに、チラシと LINE の棒を並べる（LP を 100% とした割合・1本の軸） @param {any[]} cs */
function journey(cs) {
  const steps = [
    { label: "LP を開いた", count: (/** @type {any} */ c) => c.stages[0].count },
    { label: "予約ボタンを押した", count: (/** @type {any} */ c) => c.stages[1]?.count ?? 0 },
    { label: "予約を送った", count: (/** @type {any} */ c) => c.stages[2]?.count ?? 0 },
    { label: "来店した", count: (/** @type {any} */ c) => c.reservations.visited },
  ];
  return steps.map((st) => el("div", { class: "jrow" }, [
    el("div", { class: "jlabel" }, [st.label]),
    el("div", { class: "jbars" }, cs.map((c) => {
      const top = c.stages[0].count || 1;
      const n = st.count(c);
      const pct = n / top;
      const tip = `${srcLabel(c.src)}・${st.label}：${n}件（LP の ${fmtRate(pct)}）`;
      return el("div", { class: "jbar-row", title: tip, tabindex: "0", "aria-label": tip }, [
        el("div", { class: "jtrack" }, [el("div", { class: `jbar ${c.src}`, style: `width:${Math.max(0.6, pct * 100)}%` })]),
        el("span", { class: "jval" }, [`${fmtRate(pct)}`, el("small", {}, [` ${n}件`])]),
      ]);
    })),
  ]));
}

/** 次の一手から自動で作った提案の状態（人が反映するまでがループ。docs/LOOP.md） @param {any} p */
function proposalLine(p) {
  if (!p && latestTries < 6) return [el("p", { class: "loop-line wait" }, ["ナットクが、この次の一手から受付のタブの提案を作っています…（数秒）"])];
  if (!p) return [el("a", { class: "loop-line todo", href: "/maintenance" }, ["この次の一手の提案はまだありません。次の一手の画面でナットクに頼めます →"])];
  if (p.status === "proposed") {
    return [el("a", { class: "loop-line todo", href: "/maintenance" }, [`人の番です：受付のタブ「${p.title}」の提案が反映待ちです →`])];
  }
  if (p.status === "applied") {
    return [el("a", { class: "loop-line done", href: "/desk" }, [`反映済み：受付に「${p.title}」のタブが出ています →`])];
  }
  if (p.reason?.includes("同じ名前のタブ")) {
    return [el("a", { class: "loop-line done", href: "/desk" }, ["この一手の受付のタブは、もう出ています（前の月に反映済み）→"])];
  }
  if (p.status === "rejected" && p.reason?.includes("部品")) {
    return [el("a", { class: "loop-line todo", href: "/desk?tab=past" },
      ["この一手は受付のタブの部品では表せません。過去の来店未記録は、受付の「押し忘れ」タブで確かめられます →"])];
  }
  return [el("a", { class: "loop-line", href: "/maintenance" }, [`提案：${p.reason || "やめた・取り消した"}（次の一手の画面で見る →）`])];
}

/** Claude の見立て：いちばん新しい分析の次の一手。無ければ頼み方を案内する @param {any} run */
function latestCard(run) {
  if (!run) {
    byId("ask-box").setAttribute("open", "");
    return [say("まだ分析がありません。下の「分析を頼む」で、Claude が台帳を数え直して次の一手を出します。", "normal", { size: 44 })];
  }
  const href = `/analysis/${encodeURIComponent(run.analysis_id)}`;
  return [
    el("p", { class: "muted latest-meta" }, [
      `${fmtDay(run.as_of)} の分析（店全体の台帳）・${run.model_label}`,
      run.mode === "sample" ? "（見本の報告）" : "",
      run.matches === true ? "・✓ 検算：アプリの数字と一致" : "",
    ]),
    el("div", { class: "latest-next" }, [el("div", { class: "small" }, ["次の一手"]), el("p", {}, [run.next_action || "—"])]),
    el("p", { class: "latest-view" }, [el("b", {}, ["見立て："]), run.revised_view || "—"]),
    ...proposalLine(run.proposal),
    el("div", { class: "latest-actions" }, [
      el("a", { class: "btn sm", href, target: "vl-analysis" }, ["報告を読む →"]),
      el("a", { class: "btn sm soft", href: `/maintenance?from=${encodeURIComponent(run.analysis_id)}` }, ["ナットクに頼む（受付の仕事にする）"]),
    ]),
  ];
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
  // キャンペーン（施策の番号）ごとに、チラシと LINE を並べて見る。店の設定で足した施策は、ここで選ぶ
  /** @type {Map<string, any[]>} */
  const groups = new Map();
  for (const c of f.campaigns) groups.set(c.campaign, [...(groups.get(c.campaign) || []), c]);
  const wanted = new URLSearchParams(location.search).get("campaign") || "";
  const sel = groups.has(wanted) ? wanted : [...groups.keys()][0];
  const cs = groups.get(sel) || [];
  byId("campaign-title").textContent = cs[0]?.title || "施策がありません";
  byId("campaign-pick").replaceChildren(...(groups.size > 1 ? [...groups.entries()].map(([code, list]) =>
    el("a", { class: "chip", href: `?campaign=${encodeURIComponent(code)}`, "aria-current": code === sel ? "true" : "false" }, [list[0].title])) : []));
  byId("kpis").replaceChildren(...kpis(cs));
  byId("journey").replaceChildren(...journey(cs));
  byId("funnels").replaceChildren(...cs.map(funnelCard));
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
  byId("status").replaceChildren(say(el("span", {}, ["分析は新しいタブで進めています（ふつう4〜7分）。閉じてしまった時は ", link, " から戻れます。"]), "work"));
}

ask.addEventListener("click", async () => {
  ask.disabled = true;
  // 止められないよう、押した瞬間に新しいタブを開けておき、番号が決まってから行き先を入れる（小さな別窓にはしない）
  const win = window.open("about:blank", "vl-analysis");
  try {
    const r = await api("/api/analysis", { json: { model } });
    sessionStorage.setItem("vl:analysis", r.analysis_id);
    const url = `/analysis/${encodeURIComponent(r.analysis_id)}`;
    if (win) win.location.href = url; else location.href = url;
    showLast(r.analysis_id);
    if (r.notice) byId("status").append(el("p", { class: "muted" }, [r.notice]));  // 公開版で見本の報告に切り替えた時の理由
  } catch (e) {
    win?.close();
    byId("status").textContent = `頼めませんでした：${/** @type {Error} */ (e).message}`;
  } finally {
    ask.disabled = false;
  }
});

/** 自動の提案ができるのを待った回数（4秒ごと。6回で待つのをやめ、頼む画面へ案内する） */
let latestTries = 0;

async function refreshLatest() {
  latestTries += 1;
  const latest = await api("/api/analysis-latest").catch(() => ({ run: null }));
  byId("latest").replaceChildren(...latestCard(latest.run));
  if (latest.run && !latest.run.proposal && latestTries < 6) setTimeout(refreshLatest, 4000);
}

async function main() {
  const conf = await api("/api/config");
  if (conf.store) byId("store").textContent = conf.store.name;
  costs = await api("/api/analysis-costs").catch(() => costs);
  renderModels(conf);
  renderCostNote();
  await loadFunnel();
  const latest = await api("/api/analysis-latest").catch(() => ({ run: null }));
  byId("latest").replaceChildren(...latestCard(latest.run));
  if (latest.run && !latest.run.proposal) setTimeout(refreshLatest, 4000);  // 自動の提案ができたら出し直す
  const last = sessionStorage.getItem("vl:analysis");
  if (last && last !== latest.run?.analysis_id) showLast(last);  // 頼んだばかりで、まだ終わっていない分析への入口
}

main().finally(pageLoading()).catch((e) => { byId("error").textContent = `読み込めませんでした：${e.message}`; });
