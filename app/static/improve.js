// @ts-check
// ナットクの改善：分析担当の見直しを、現場の言葉で見せる。ひとことで言うと → 届く報告の前と後 → 確かめた結果 → 使うかのボタン。
// 手順書の図・物差しの数字・本当の差分は「詳しく（直す人向け）」に畳む。本番に使うかは人が押して決める。
import { api, byId, el, fmtDateTime, pageLoading, toast } from "./common.js";
import { say } from "./mascot.js";
import { plainWords } from "./plain_words.js";

const DECISION = {
  kept: ["残した", "good"],
  reverted: ["戻した", "warn"],
  rejected: ["捨てた", "bad"],
};

/** @param {number | null | undefined} c */
const usd = (c) => (c === null || c === undefined ? "—" : `$${(c / 100).toFixed(2)}`);
/** @param {number | null | undefined} r */
const rounds = (r) => (r ? `${r}回目で合格` : "合格せず");

/** 分析担当の仕事の流れの図。変わる節に色、直せない節に鍵 @param {any[]} flow */
function flowDiagram(flow) {
  const boxes = [];
  flow.forEach((f, i) => {
    if (i) boxes.push(el("div", { class: "flow-arrow", "aria-hidden": "true" }, ["→"]));
    const mark = f.state === "changed" ? "ここを直す" : f.state === "locked" ? "🔒 直せない" : "そのまま";
    boxes.push(el("div", { class: `flow-box ${f.state}` }, [
      el("div", { class: "flow-mark" }, [mark]),
      el("div", { class: "flow-label" }, [f.label]),
      el("div", { class: "flow-role" }, [f.role]),
    ]));
  });
  return el("div", { class: "flow", role: "img", "aria-label": "分析担当の手順書のうち、直す節の図" }, boxes);
}

/** 物差しの前 → 後 @param {any} b @param {any} c */
function metrics(b, c) {
  /** @param {string} label @param {string} before @param {string} after @param {boolean | null} better */
  const row = (label, before, after, better) => el("tr", {}, [
    el("th", {}, [label]), el("td", {}, [before]), el("td", { "aria-hidden": "true" }, ["→"]),
    el("td", { class: better === null ? "" : better ? "good" : "bad" }, [after]),
  ]);
  /** @param {any} j */
  const ok = (j) => (j ? (j.ok ? "○" : "×") : "—");
  const rows = [
    row("採点（仕込みあり）", rounds(b.plant.rounds), c ? rounds(c.plant.rounds) : "回している途中",
      c ? (c.plant.rounds || 4) <= (b.plant.rounds || 4) : null),
    row("採点（仕込みなし）", rounds(b.noplant.rounds), c ? rounds(c.noplant.rounds) : "回している途中",
      c ? (c.noplant.rounds || 4) <= (b.noplant.rounds || 4) : null),
    row("日数の差を見つけたか（仕込みあり）", ok(b.plant.judge), c ? ok(c.plant.judge) : "—", c ? Boolean(c.plant.judge?.ok) : null),
    row("無い差をでっち上げなかったか（仕込みなし）", ok(b.noplant.judge), c ? ok(c.noplant.judge) : "—", c ? Boolean(c.noplant.judge?.ok) : null),
    row("費用（2つの台帳の合計）", usd(b.total_cost_cents), c ? usd(c.total_cost_cents) : "—",
      c && b.total_cost_cents && c.total_cost_cents !== null ? c.total_cost_cents <= b.total_cost_cents : null),
  ];
  return el("table", { class: "metrics" }, [
    el("thead", {}, [el("tr", {}, [el("th", {}, ["物差し"]), el("th", {}, ["前の版"]), el("th", {}, [""]), el("th", {}, ["直した版"])])]),
    el("tbody", {}, rows),
  ]);
}

/** 本当の差分（節ごと・行ごと） @param {any[]} diff */
function diffView(diff) {
  return el("div", { class: "diff" }, diff.map((d) => el("div", { class: "diff-section" }, [
    el("div", { class: "muted" }, [`節：${d.section}`]),
    ...d.lines.map((/** @type {any} */ l) => el("div", { class: `diff-line ${l.op}` }, [l.op === "add" ? "＋ " : "－ ", l.text])),
  ])));
}

/** 確かめた結果（現場の言葉・前 → 後） @param {any} b @param {any} c */
function checks(b, c) {
  /** @param {any} j */
  const ok = (j) => (j ? (j.ok ? "○" : "×") : "—");
  /** @param {any} e */
  const tries = (e) => `${e.total_rounds}回${[e.plant, e.noplant].some((x) => !x.rounds) ? "（通らなかった台帳あり）" : ""}`;
  /** @param {string} label @param {string} before @param {string} after @param {boolean | null} better */
  const row = (label, before, after, better) => el("tr", {}, [
    el("th", {}, [label]), el("td", {}, [before]), el("td", { "aria-hidden": "true" }, ["→"]),
    el("td", { class: better === null ? "" : better ? "good" : "bad" }, [after]),
  ]);
  const rows = [
    row("チラシが低く見える本当の理由（予約が先の日に多い）を見つけたか（台帳A）", ok(b.plant.judge), c ? ok(c.plant.judge) : "—", c ? Boolean(c.plant.judge?.ok) : null),
    row("差の無い台帳で、無い差を言い切らなかったか（台帳B）", ok(b.noplant.judge), c ? ok(c.noplant.judge) : "—", c ? Boolean(c.noplant.judge?.ok) : null),
    row("採点に通るまでに書いた回数（2つの台帳の合計・少ないほど良い）", tries(b), c ? tries(c) : "—", c ? c.total_rounds <= b.total_rounds : null),
    row("1回の確かめにかかった費用（2つの台帳の合計）", usd(b.total_cost_cents), c ? usd(c.total_cost_cents) : "—",
      c && b.total_cost_cents && c.total_cost_cents !== null ? c.total_cost_cents <= b.total_cost_cents : null),
  ];
  return el("table", { class: "metrics" }, [
    el("thead", {}, [el("tr", {}, [el("th", {}, ["確かめたこと"]), el("th", {}, ["前の版"]), el("th", {}, [""]), el("th", {}, ["直した版"])])]),
    el("tbody", {}, rows),
  ]);
}

/** 届く報告の前と後（同じ見本の台帳で実際に書いた報告から抜き出したもの） @param {any[]} list */
function reportChanges(list) {
  return el("div", { class: "report-changes" }, list.map((c) => el("div", { class: "rc" }, [
    el("div", { class: "rc-head" }, [el("b", {}, [`報告の「${c.part_label}」の欄`]), el("span", { class: "muted" }, [`　${c.ledger_label}`])]),
    el("div", { class: "rc-pair" }, [
      el("div", { class: "rc-box before" }, [el("div", { class: "rc-tag" }, ["前の版"]), plainWords(c.before)]),
      el("div", { class: "rc-arrow", "aria-hidden": "true" }, ["→"]),
      el("div", { class: "rc-box after" }, [el("div", { class: "rc-tag" }, ["直した版"]), plainWords(c.after)]),
    ]),
    el("p", { class: "rc-plain" }, [c.plain]),
  ])));
}

/** 直す人向けの詳しい中身（手順書の図・説明・物差し・本当の差分） @param {any} it */
function details(it) {
  const ex = it.explain;
  const body = [];
  if (it.reason) body.push(el("p", {}, [`判定（決まりのとおり）：${it.reason}`]));
  if (it.eli5) body.push(el("p", {}, [`直す役のたとえ：${it.eli5}`]));
  if (ex) {
    body.push(el("h3", {}, ["手順書のどこが変わるか"]), flowDiagram(ex.flow));
    body.push(el("div", { class: "change-list" }, ex.changes.map((/** @type {any} */ c) => el("div", { class: "change" }, [
      el("div", { class: "change-section" }, [c.section]),
      el("div", { class: "change-summary" }, [c.summary]),
      el("dl", {}, [
        el("dt", {}, ["なぜ"]), el("dd", {}, [c.why]),
        el("dt", {}, ["報告で変わる見込み"]), el("dd", {}, [c.field_effect, el("span", { class: "muted" }, ["（直す役の見込み）"])]),
      ]),
    ]))));
  }
  if (it.eval_base) body.push(el("h3", {}, ["物差し（台帳ごと）"]), metrics(it.eval_base, it.eval_cand));
  if (ex && ex.diff.length) body.push(el("h3", {}, ["手順書の本当の差分"]), diffView(ex.diff));
  return el("details", { class: "fold" }, [el("summary", {}, ["詳しく（直す人向け：手順書の図・差分）"]), el("div", { class: "fold-body" }, body)]);
}

/** @param {any} it */
function card(it) {
  const [label, tone] = DECISION[/** @type {keyof typeof DECISION} */ (it.decision)] || [it.status === "running" ? "回している途中" : "失敗", "warn"];
  const ex = it.explain;
  const plain = it.plain;
  const children = [
    el("div", { class: "improve-head" }, [
      el("h2", {}, [`第${it.iteration}回の見直し`]),
      el("span", { class: `badge ${tone}` }, [label]),
      el("span", { class: "muted" }, [fmtDateTime(it.created_at)]),
    ]),
  ];
  const headline = plain?.headline || it.eli5;
  if (headline) children.push(say(`ひとことで言うと：${headline}`, it.decision === "kept" ? "cheer" : "think"));
  const why = plain?.decision_plain || it.reason;
  if (why) children.push(el("p", { class: "decision-plain" }, [`${it.decision === "kept" ? "残した理由" : "止めた理由"}：${why}`]));
  if (plain?.report_changes?.length) {
    children.push(el("h3", {}, [it.decision === "kept" ? "届く報告がこう変わる" : "直した版の報告で、止めた所"]));
    children.push(el("p", { class: "muted" }, ["同じ見本の台帳で、前の版と直した版が実際に書いた報告から抜き出しています（中の名前は、報告の画面と同じく店の言葉に置き換えて出しています）"]));
    children.push(reportChanges(plain.report_changes));
  }
  if (ex && ex.unexplained.length) {
    children.push(el("p", { class: "error-box" }, ["説明の無い書き換えがあります。下の「詳しく」で確かめてから使ってください"]));
  }
  if (it.eval_base) children.push(el("h3", {}, ["確かめた結果"]), checks(it.eval_base, it.eval_cand));
  if (it.decision === "kept") {
    if (it.applied_at) {
      children.push(el("p", { class: "muted" }, [`本番に使っています（${fmtDateTime(it.applied_at)}）`]));
    } else {
      const b = /** @type {HTMLButtonElement} */ (el("button", { class: "btn", type: "button" }, ["この版を本番に使う"]));
      b.addEventListener("click", async () => {
        if (!confirm("分析担当の仕事のやり方を、この版に切り替えます。よいですか？")) return;
        b.disabled = true;
        try {
          await api(`/api/improvements/${it.id}/apply`, { json: {} });
          toast("本番の分析担当を、この版にしました");
          await load();
        } catch (e) { toast(/** @type {Error} */ (e).message, true); b.disabled = false; }
      });
      children.push(el("div", { style: "margin-top:12px" }, [b]));
    }
  }
  if (ex || it.eval_base) children.push(details(it));
  return el("section", { class: "card improve-card" }, children);
}

async function load() {
  const { items } = await api("/api/improvements");
  byId("list").replaceChildren(...items.map(card));
  byId("guide").replaceChildren(items.length
    ? say("答えの分かっている見本の台帳で試して、良くなった時だけ残しています。報告の前と後を見て、使うか決めてくださいね。", "normal")
    : say("まだ見直しをしていません。見直しを回すと、ここに出ます。", "think"));
}

async function main() {
  const conf = await api("/api/config");
  if (conf.store) byId("store").textContent = conf.store.name;
  await load();
}

main().finally(pageLoading()).catch((e) => { byId("error").textContent = e.message; });
