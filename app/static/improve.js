// @ts-check
// ナットクの改善：分析担当の手順書（指示文）の直しを、図（どの節が変わるか）・ひとことで言うと・
// 物差しの数字（前 → 後）・本当の差分 の順に見せる。本番に使うかは人が押して決める。
import { api, byId, el, fmtDateTime, pageLoading, toast } from "./common.js";
import { say } from "./mascot.js";

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

/** @param {any} it */
function card(it) {
  const [label, tone] = DECISION[/** @type {keyof typeof DECISION} */ (it.decision)] || [it.status === "running" ? "回している途中" : "失敗", "warn"];
  const ex = it.explain;
  const children = [
    el("div", { class: "improve-head" }, [
      el("h2", {}, [`第${it.iteration}回の直し`]),
      el("span", { class: `badge ${tone}` }, [label]),
      el("span", { class: "muted" }, [fmtDateTime(it.created_at)]),
    ]),
  ];
  if (it.reason) children.push(el("p", {}, [`判定：${it.reason}`]));
  if (it.eli5) children.push(say(`ひとことで言うと：${it.eli5}`, it.decision === "kept" ? "cheer" : "think"));
  if (ex) {
    children.push(el("h3", {}, ["どこが変わるか"]), flowDiagram(ex.flow));
    children.push(el("div", { class: "change-list" }, ex.changes.map((/** @type {any} */ c) => el("div", { class: "change" }, [
      el("div", { class: "change-section" }, [c.section]),
      el("div", { class: "change-summary" }, [c.summary]),
      el("dl", {}, [
        el("dt", {}, ["なぜ"]), el("dd", {}, [c.why]),
        el("dt", {}, ["報告で変わる見込み"]), el("dd", {}, [c.field_effect, el("span", { class: "muted" }, ["（直す役の見込み。確かめた結果は下の物差し）"])]),
      ]),
    ]))));
    if (ex.unexplained.length) {
      children.push(el("p", { class: "error-box" }, [`説明の無い変更があります：${ex.unexplained.join("・")}（下の差分で確かめてください）`]));
    }
  }
  if (it.eval_base) children.push(el("h3", {}, ["物差し（前 → 後）"]), metrics(it.eval_base, it.eval_cand));
  if (ex && ex.diff.length) {
    const d = el("details", { class: "fold" }, [el("summary", {}, ["手順書の本当の差分を見る"]), el("div", { class: "fold-body" }, [diffView(ex.diff)])]);
    children.push(d);
  }
  if (it.decision === "kept") {
    if (it.applied_at) {
      children.push(el("p", { class: "muted" }, [`本番に使っています（${fmtDateTime(it.applied_at)}）`]));
    } else {
      const b = /** @type {HTMLButtonElement} */ (el("button", { class: "btn", type: "button" }, ["この版を本番に使う"]));
      b.addEventListener("click", async () => {
        if (!confirm("分析担当の手順書をこの版に書き換え、エージェントの版を上げます。よいですか？")) return;
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
  return el("section", { class: "card improve-card" }, children);
}

async function load() {
  const { items } = await api("/api/improvements");
  byId("list").replaceChildren(...items.map(card));
  byId("guide").replaceChildren(items.length
    ? say("答えの分かっている台帳で確かめた結果だけを残しています。本番に使うかは、図と数字を見て決めてくださいね。", "normal")
    : say("まだ改善を回していません。`scripts/improve_analyst.py` で回すと、ここに出ます。", "think"));
}

async function main() {
  const conf = await api("/api/config");
  if (conf.store) byId("store").textContent = conf.store.name;
  await load();
}

main().finally(pageLoading()).catch((e) => { byId("error").textContent = e.message; });
