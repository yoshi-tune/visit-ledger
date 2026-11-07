// @ts-check
// 分析の報告と、案内役のひと言（効果の画面と分析の画面で使う）。
import { el } from "./common.js";
import { say } from "./mascot.js";
import { plainReport } from "./plain_words.js";

/** @param {string} title @param {(Node | string)[]} children */
const block = (title, children) => el("section", {}, [el("h3", {}, [title]), ...children]);

/** 開いた時だけ見る欄 @param {(Node | string)[]} head @param {(Node | string)[]} body @param {boolean} [open] */
const fold = (head, body, open = false) => {
  const d = el("details", { class: "fold" }, [el("summary", {}, head), el("div", { class: "fold-body" }, body)]);
  /** @type {HTMLDetailsElement} */ (d).open = open;
  return d;
};

/** @param {any} run */
export function renderReport(run) {
  const out = [];
  if (run.error) out.push(el("div", { class: "error-box" }, [run.error]));
  // 中の名前（step_01・funnel.json・列の名前など）は、画面に出す時だけ店の言葉に置き換える
  const r = run.report ? plainReport(run.report) : null;
  if (r) {
    if (r.mode === "sample") {
      out.push(el("p", { class: "banner" }, [
        `見本の報告です。作ったばかりの見本の台帳で Claude（${run.model_label || run.model}）が実際に分析した結果を保存したものです（鍵が無い時や、公開版で費用の上限・ほかの人の分析と重なった時に出します）。画面で来店などを記録した後は、効果の画面の数字と合いません。`,
      ]));
    }
    if (r.mode === "messages") {
      out.push(el("p", { class: "banner" }, ["予備の形（1回の呼び出し）で書いた報告です。コードでの追加の集計はしていません。"]));
    }
    // 前回の分析の「次の一手」のその後（前回がある時だけ。項目が無い前の報告・見本の報告には出さない）
    const pr = r.previous_review;
    if (pr && pr.had_previous) {
      out.push(block("前回の一手のその後", [
        el("p", { class: "muted" }, [`前回の一手：${pr.action}`]),
        el("div", { class: "views" }, [
          el("div", { class: "view" }, [el("div", { class: "muted" }, ["前回の分析の時点"]), el("p", {}, [pr.before])]),
          el("div", { class: "arrow", "aria-hidden": "true" }, ["→"]),
          el("div", { class: "view after" }, [el("div", { class: "muted" }, ["今"]), el("p", {}, [pr.after])]),
        ]),
        el("p", {}, [pr.finding]),
      ]));
    }
    // 前日のお知らせのその後（記録がある時だけ。欄が無い前の報告・見本の報告には出さない）。並べるのは観測まで
    const rr = r.reminder_review;
    if (rr && rr.had_reminders) {
      const t = el("table");
      t.append(el("tr", {}, [el("th", {}, [""]), el("th", { class: "r" }, ["来店 ／（来店＋来店未記録）"]), el("th", { class: "r" }, ["来店待ち"])]));
      for (const g of rr.groups) {
        t.append(el("tr", {}, [
          el("td", {}, [g.label]),
          el("td", { class: "r" }, [g.denominator ? `${g.visited} / ${g.denominator}（${Math.round((g.visited / g.denominator) * 100)}%）` : "— / 0（算出不可）"]),
          el("td", { class: "r" }, [String(g.waiting)]),
        ]));
      }
      out.push(block("前日のお知らせのその後（今の条件で数え直した参考の集計。連絡した時の対象を固定したものではなく、効いたとは言いません）", [el("div", { class: "table-wrap" }, [t]), el("p", {}, [rr.finding])]));
    }
    const rec = r.reconciliation;
    // 先に読むもの：見立ての変化・次の一手・仮説。残りは開いた時だけ見る（検算は食い違いがある時だけ開いておく）
    const views = block("見立ての変化", [el("div", { class: "views" }, [
      el("div", { class: "view" }, [el("div", { class: "muted" }, ["最初の見立て"]), el("p", {}, [r.first_view])]),
      el("div", { class: "arrow", "aria-hidden": "true" }, ["→"]),
      el("div", { class: "view after" }, [el("div", { class: "muted" }, ["集計を重ねた後"]), el("p", {}, [r.revised_view])]),
    ])]);
    const n = r.next_action;
    out.push(el("section", { class: "next-action" }, [
      el("div", { class: "small" }, ["次の一手（店全体で1つ）"]),
      el("div", { class: "action" }, [n.action]),
      el("dl", {}, [
        el("dt", {}, ["手間"]), el("dd", {}, [n.effort]),
        el("dt", {}, ["見る数字"]), el("dd", {}, [n.metric]),
        el("dt", {}, ["比べる相手"]), el("dd", {}, [n.comparison]),
        el("dt", {}, ["仮置きの目標"]), el("dd", {}, [n.provisional_target]),
      ]),
      // 次の一手を受付の仕事にする（依頼の文は下書きを出す。反映するかは人が決める）
      el("a", { class: "btn ask", href: `/maintenance?from=${encodeURIComponent(run.analysis_id)}` }, ["ナットクに頼む（受付でできるようにする）"]),
    ]));
    out.push(views);  // 結論（次の一手）を先に読み、その根拠の見立ての変化を後に置く
    out.push(block("原因の仮説（言い切りません）", (r.hypotheses || []).map((/** @type {any} */ h) =>
      el("div", { class: "card", style: "box-shadow:none;margin-bottom:8px" }, [
        el("p", {}, [el("b", {}, [h.statement])]),
        el("p", { class: "small" }, [`支える観測：${h.supporting}`]),
        el("p", { class: "small muted" }, [`確かめ方：${h.how_to_check}`]),
      ]))));

    out.push(fold([
      el("span", { class: rec.matches ? "ok-badge" : "bad-badge" }, [rec.matches ? "✓ 検算：アプリの数字と一致" : "! 検算：食い違いあり"]),
    ], [
      el("p", {}, [rec.summary]),
      ...rec.differences.map((/** @type {string} */ d) => el("p", { class: rec.matches ? "muted" : "input-error" }, [d])),
      ...(rec.matches ? [el("p", { class: "muted" }, ["同じ入力に対する2つの集計が一致した、という意味です（台帳そのものの正しさの証明ではありません）。"])] : []),
    ], !rec.matches));
    out.push(fold([`集計の記録（主なもの ${(r.steps || []).length}件）`], [el("ol", { class: "timeline" }, (r.steps || []).map((/** @type {any} */ s) =>
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
    out.push(fold([`観測した事実（台帳の数字で言えること・${(r.observations || []).length}件）`], [el("div", { class: "table-wrap" }, [obs])]));
    out.push(fold([`台帳だけでは確かめられないこと（${(r.to_check || []).length}件）`], [el("ul", {}, (r.to_check || []).map((/** @type {string} */ t) => el("li", {}, [t])))]));
  }
  const tools = (run.tool_log || []).filter((/** @type {any} */ e) => e.kind === "tool");
  if (tools.length) {
    const d = el("details", {}, [el("summary", {}, [`Claude が実行した道具の記録（${tools.length}件・アプリの側で記録）`])]);
    d.append(el("p", { class: "muted" }, ["記録の中の step_01.py などは、報告の「集計1」などに当たります（記録は元の名前のまま出しています）。"]));
    for (const e of tools) {
      const input = typeof e.input === "string" ? e.input : JSON.stringify(e.input, null, 1);
      d.append(el("p", { class: "muted" }, [`${e.tool}${e.is_error ? "（失敗）" : ""}`]), el("pre", {}, [input || ""]),
        el("pre", {}, [e.output || ""]));
    }
    out.push(d);
  }
  return out;
}

/** 分析ごとに、この画面で最初に「調べている」と見た時刻 @type {Map<string, number>} */
const seenAt = new Map();

/** 案内役のひと言（分析の進み具合に合わせて表情を変える） @param {any} run */
export function guide(run) {
  const tools = (run.tool_log || []).filter((/** @type {any} */ e) => e.kind === "tool").length;
  if (run.status === "queued" || run.status === "running") {
    // 経過の時間は、この画面で最初に見た時から数える（目安を出して、止まっていないと分かるように）
    const since = seenAt.get(run.analysis_id) ?? Date.now();
    seenAt.set(run.analysis_id, since);
    const sec = Math.floor((Date.now() - since) / 1000);
    const text = el("span", { style: "display:grid;gap:4px" }, [
      el("span", { class: "row", style: "display:flex;gap:8px;align-items:center" }, [
        el("span", { class: "spinner", "aria-hidden": "true" }),
        el("b", {}, ["Claude が台帳を数え直しています"]),
      ]),
      el("span", { class: "small" }, [`ふつう4〜7分かかります・経過 ${Math.floor(sec / 60)}分${sec % 60}秒${tools ? `・集計の実行 ${tools}回` : ""}`]),
      el("span", { class: "small muted" }, ["この画面を閉じても分析は続きます。効果の画面の「分析の画面を開く」から戻れます。"]),
    ]);
    return say(text, "work");
  }
  if (run.status === "done" && run.report && run.report.mode === "sample") {
    return say("見本の報告です（理由は下の帯）。まず、結論の「次の一手」から読んでください。", "think");
  }
  if (run.status === "done" && run.report) {
    // 項目が無い前の報告だけ、文字の比較で代わりにする
    const changed = typeof run.report.view_changed === "boolean"
      ? run.report.view_changed
      : run.report.first_view !== run.report.revised_view;
    return say(changed
      ? "調べ終わりました！集計を重ねて、見立てが変わりました。気になることは、チャットで続けて聞いてくださいね。"
      : "調べ終わりました。見立ては変わりませんでしたが、根拠と次の一手をまとめました。気になることは、チャットで聞いてくださいね。", "cheer");
  }
  return say("うまく調べられませんでした。理由は下に書いてあります。", "think");
}

