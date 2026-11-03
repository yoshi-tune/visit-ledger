"""分析担当の改善：答えの分かっている2つの台帳で確かめながら、分析担当の指示文を直す（docs/IMPROVE.md）。

    1. 物差し：仕込みあり・なしの見本の台帳で、指示文を差し替えたセッションを並べて回し、
       報告の形・検算・採点の回数・費用と、決まった問いの確かめ（agent/judge.md）を数える
    2. 直す役：Claude（Opus）が、採点で直しを求められた理由と物差しの結果を読み、指示文の直しを出す
       直してよい節は決まっている（数え方・言わないこと・出力 はコードで止める）
    3. 残す／戻すはコードの決まりで決める（直す役の言い分では決めない）。次の回は前の回の結果を読んで直す
    4. 本番に使うかは人が決める（画面の「本番に使う」→ agent/analyst_system.md を書き換え、エージェントの版を上げる）

採点基準（agent/rubric.md）と物差し（agent/judge.md・このファイルの決まり）は、直す役から変えられない。
"""

from __future__ import annotations

import difflib
import importlib.util
import json
import re
import tempfile
import threading
from pathlib import Path

from app import config, export, funnel, ledger
from app.analysis import RunError, check_report

AGENT_DIR = config.ROOT / "agent"
SYSTEM_PATH = AGENT_DIR / "analyst_system.md"
IMPROVER_MODEL = "claude-opus-5-5"
JUDGE_MODEL = "claude-sonnet-5-5"

# 指示文の節と、図に出す呼び名・役目（店長に向けた言い方）。並びは分析担当の仕事の流れ
SECTIONS = (
    ("はじめに", "役目", "誰のために何を調べるか"),
    ("渡されるもの", "受け取る台帳", "どの表を受け取るか"),
    ("数え方", "数え方", "アプリと同じ数え方"),
    ("進め方", "調べる順番", "検算 → 見立て → 集計を重ねる → 振り返り"),
    ("集計の決まり", "集計のしかた", "数字はコードで出す・件数が少ない時の注意"),
    ("言わないこと", "言わないこと", "言い過ぎを防ぐ決まり"),
    ("書く量", "書く量", "報告を短くする決まり"),
    ("出力", "報告の形", "報告のファイルと形"),
    ("報告の後の質問", "質問への答え方", "チャットでの答え方"),
)
# 直す役に変えさせない節（数え方はアプリと合わせる・言わないことと報告の形は人が決める）
LOCKED = ("数え方", "言わないこと", "出力")


# ---- 指示文の節 ----------------------------------------------------------------

def split_sections(text: str) -> dict[str, str]:
    """指示文を「## 見出し」で節に分ける。見出しの前は「はじめに」。見出しは括弧の前までで呼ぶ。"""
    out: dict[str, str] = {}
    name, buf = "はじめに", []
    for line in text.replace("\r\n", "\n").split("\n"):
        m = re.match(r"^## (.+?)(?:（.*）)?\s*$", line)
        if m:
            out[name] = "\n".join(buf).strip("\n")
            name, buf = m.group(1).strip(), [line]
        else:
            buf.append(line)
    out[name] = "\n".join(buf).strip("\n")
    return out


def norm(name: str) -> str:
    """節の呼び名をそろえる（見出しの括弧書きを落とす）。"""
    return re.sub(r"（.*）\s*$", "", name.strip().lstrip("#").strip())


def join_sections(sections: dict[str, str]) -> str:
    return "\n\n".join(sections[k] for k in sections) + "\n"


def section_diff(before: str, after: str) -> list[dict]:
    """節ごとの本当の差分（変わった節だけ）。行ごとに 足した／消した を返す。"""
    a, b = split_sections(before), split_sections(after)
    out = []
    for name in dict.fromkeys([*a, *b]):
        x, y = a.get(name, ""), b.get(name, "")
        if x == y:
            continue
        lines = []
        for op in difflib.ndiff(x.split("\n"), y.split("\n")):
            if op.startswith(("- ", "+ ")):
                lines.append({"op": "del" if op[0] == "-" else "add", "text": op[2:]})
        out.append({"section": name, "lines": lines})
    return out


# ---- 物差し --------------------------------------------------------------------

def _sample_module():
    spec = importlib.util.spec_from_file_location("make_sample", config.ROOT / "scripts" / "make_sample.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _inputs(plant: bool, workdir: Path) -> tuple[dict, dict]:
    """見本の台帳を作業用の場所に作り、書き出しと集計を返す（本番の台帳には触らない・前回の分析も渡さない）。"""
    path = workdir / f"{'plant' if plant else 'noplant'}.db"
    _sample_module().build(path, plant=plant)
    conn = ledger.connect(path)
    try:
        snap = ledger.snapshot(conn, config.STORE_ID, config.PERIOD_FROM.isoformat(), config.cohort_to().isoformat())
    finally:
        conn.close()
    files, _ = export.build(snap)
    return files, funnel.compute(snap, config.TODAY, config.PERIOD_FROM, config.cohort_to())


def _rounds(log: list[dict]) -> int | None:
    """採点の何回目で合格したか（1始まり）。合格しなければ None。"""
    for i, e in enumerate([e for e in log if e.get("kind") == "grade"], 1):
        if e.get("result") == "satisfied":
            return i
    return None


def _judge(report: dict, plant: bool) -> dict:
    import anthropic

    rule = (AGENT_DIR / "judge.md").read_text(encoding="utf-8")
    schema = {"type": "object", "additionalProperties": False, "required": ["ok", "reason"],
              "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}}}
    which = "仕込みあり" if plant else "仕込みなし"
    resp = anthropic.Anthropic().beta.messages.create(
        model=JUDGE_MODEL, max_tokens=2000, system=rule,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": f"台帳：{which}\n\n報告：\n```json\n{json.dumps(report, ensure_ascii=False)}\n```"}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(text)


def from_saved_run(run: dict, plant: bool) -> dict:
    """前に回した分析（agent/sample_run.json の形）を、物差しの結果の形にする（その版の点数を取り直す費用を省く）。"""
    log = run["tool_log"]
    report = run["report"]
    out = {"ledger": "plant" if plant else "noplant", "reused": True, "schema_ok": True,
           "matches": bool(report["reconciliation"]["matches"]), "notes": check_report(report, log),
           "judge": _judge(report, plant), "report": report, "rounds": _rounds(log),
           "grader_feedback": [e.get("explanation") for e in log if e.get("kind") == "grade"
                               and e.get("result") != "satisfied" and e.get("explanation")],
           "cost_cents": run.get("cost_cents"), "tool_calls": sum(1 for e in log if e.get("kind") == "tool")}
    return out


def evaluate_one(system: str, plant: bool, model: str = config.DEFAULT_MODEL) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        return _one(system, plant, Path(tmp), model)


def _one(system: str, plant: bool, workdir: Path, model: str) -> dict:
    from app.analysis import agent_runner

    files, fun = _inputs(plant, workdir)
    log: list[dict] = []
    out: dict = {"ledger": "plant" if plant else "noplant"}
    try:
        report = agent_runner.run(f"eval-{out['ledger']}", files, fun, log.append, model,
                                  {"had_previous": False}, system=system)
        out["notes"] = check_report(report, log)
        out["schema_ok"] = True
        out["matches"] = bool(report["reconciliation"]["matches"])
        out["judge"] = _judge(report, plant)
        out["report"] = report
    except RunError as e:
        out.update(schema_ok=False, error=str(e))
    session = next((e["session_id"] for e in log if e.get("kind") == "session"), None)
    out["rounds"] = _rounds(log)
    out["grader_feedback"] = [e.get("explanation") for e in log if e.get("kind") == "grade"
                              and e.get("result") != "satisfied" and e.get("explanation")]
    out["cost_cents"] = agent_runner.session_cost_cents(session) if session else None
    out["tool_calls"] = sum(1 for e in log if e.get("kind") == "tool")
    return out


def evaluate(system: str, model: str = config.DEFAULT_MODEL) -> dict:
    """仕込みあり・なしの台帳で並べて回し、物差しの結果を返す（鍵が要る・1回 $2 前後）。"""
    results: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        def go(plant: bool) -> None:
            results["plant" if plant else "noplant"] = _one(system, plant, Path(tmp), model)
        threads = [threading.Thread(target=go, args=(p,)) for p in (True, False)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    return summarize(results)


def summarize(results: dict[str, dict]) -> dict:
    p, n = results["plant"], results["noplant"]
    rounds = [r.get("rounds") for r in (p, n)]
    costs = [r.get("cost_cents") for r in (p, n)]
    return {
        "plant": p, "noplant": n,
        "all_schema_ok": bool(p.get("schema_ok") and n.get("schema_ok")),
        "all_judge_ok": bool(p.get("judge", {}).get("ok") and n.get("judge", {}).get("ok")),
        # 合格しなかった回は 4 として数える（採点は最大3回）
        "total_rounds": sum(r if r else 4 for r in rounds),
        "total_cost_cents": sum(c or 0 for c in costs) if all(c is not None for c in costs) else None,
    }


def decide(base: dict, cand: dict) -> tuple[str, str]:
    """残すか戻すか。物差しの決まり（コード）だけで決める。"""
    if not cand["all_schema_ok"]:
        return "reverted", "報告の形が合わない回があった"
    if not cand["all_judge_ok"]:
        return "reverted", "中身の確かめ（仕込みありで日数の差を見つける・仕込みなしででっち上げない）に通らなかった"
    if base["all_judge_ok"] is False:
        return "kept", "前の版は中身の確かめに通らず、新しい版は通った"
    if cand["total_rounds"] < base["total_rounds"]:
        return "kept", f"採点の回数が減った（{base['total_rounds']} → {cand['total_rounds']}）"
    bc, cc = base["total_cost_cents"], cand["total_cost_cents"]
    if cand["total_rounds"] == base["total_rounds"] and bc and cc is not None and cc <= bc * 0.9:
        return "kept", f"採点の回数は同じで、費用が1割以上減った（${bc / 100:.2f} → ${cc / 100:.2f}）"
    return "reverted", f"良くならなかった（採点の回数 {base['total_rounds']} → {cand['total_rounds']}）"


# ---- 直す役 --------------------------------------------------------------------

PROPOSAL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["eli5", "changes", "sections"],
    "properties": {
        "eli5": {"type": "string", "description": "店長に向けて、たとえを使った1〜2文で何を直すか"},
        "changes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["section", "summary", "why", "field_effect"],
            "properties": {
                "section": {"type": "string", "description": "直す節の名前（指示文の見出し）"},
                "summary": {"type": "string", "description": "何をどう直すか（1文）"},
                "why": {"type": "string", "description": "直す理由。採点で直しを求められた理由のどれに当たるか"},
                "field_effect": {"type": "string", "description": "店長が読む報告で何が変わる見込みか（見込みであって確かめた結果ではない）"},
            }}},
        "sections": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["section", "text"],
            "properties": {"section": {"type": "string"}, "text": {"type": "string", "description": "その節の新しい全文（見出しの行を含む）"}},
        }},
    },
}

IMPROVER_SYSTEM = f"""あなたは、地域の店の分析担当（別の Claude）の指示文を直す係です。
分析担当は、答えの分かっている2つの見本の台帳（仕込みあり・なし）で確かめられています。採点の係に直しを求められた理由と、物差しの結果を読み、
次の回で「採点の1回目で合格し、中身の確かめにも通る」ように、指示文の節を直してください。

決まり：
- 直してよいのは次の節だけ：{"・".join(s for s, _, _ in SECTIONS if s not in LOCKED)}。{"・".join(LOCKED)} の節は変えない（変えた案は捨てられる）
- 採点の基準と物差しは変えられない。採点を甘くする方向ではなく、分析担当が最初から基準を満たす書き方にする
- 直すのは少しだけ（1〜3か所）。理由の無い言い換えはしない。前の回の結果（戻された理由）があれば、それを踏まえる
- 直した節は全文を返す（見出しの行を含む）。changes には直した節ごとに1件、店長が読んで分かる言葉で書く
- eli5 は、店長に向けて「分析担当の手順書のどのページを、なぜ書き直すか」をたとえで1〜2文
"""


def propose(system: str, base_eval: dict, history: list[dict]) -> dict:
    """直しの案を出す（Opus を1回）。直せない節に触れた案は RunError で捨てる。"""
    import anthropic

    feedback = {k: base_eval[k].get("grader_feedback", []) for k in ("plant", "noplant")}
    table = {k: {"rounds": base_eval[k].get("rounds"), "cost_cents": base_eval[k].get("cost_cents"),
                 "schema_ok": base_eval[k].get("schema_ok"), "judge": base_eval[k].get("judge"),
                 "notes": base_eval[k].get("notes")} for k in ("plant", "noplant")}
    past = [{"iteration": h["iteration"], "decision": h["decision"], "reason": h["reason"],
             "changes": json.loads(h["proposal_json"] or "{}").get("changes", [])} for h in history]
    content = (f"## 今の指示文\n```markdown\n{system}\n```\n\n"
               f"## 採点で直しを求められた理由（台帳ごと）\n```json\n{json.dumps(feedback, ensure_ascii=False, indent=1)}\n```\n\n"
               f"## 物差しの結果\n```json\n{json.dumps(table, ensure_ascii=False, indent=1)}\n```\n\n"
               f"## これまでの回\n```json\n{json.dumps(past, ensure_ascii=False, indent=1)}\n```")
    resp = anthropic.Anthropic().beta.messages.create(
        model=IMPROVER_MODEL, max_tokens=16000, system=IMPROVER_SYSTEM,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": PROPOSAL_SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    proposal = json.loads(next((b.text for b in resp.content if b.type == "text"), "{}"))
    return proposal


def apply_proposal(system: str, proposal: dict) -> str:
    """案の節を差し込んだ新しい指示文。直せない節・知らない節に触れていたら RunError。"""
    sections = split_sections(system)
    for s in proposal["sections"]:
        name = split_sections(s["text"]).keys() - {"はじめに"} or {"はじめに"}
        name = next(iter(name))
        if name in LOCKED or norm(s["section"]) in LOCKED:
            raise RunError(f"直してはいけない節（{name}）に触れた案なので捨てました")
        if name not in sections:
            raise RunError(f"指示文に無い節（{name}）を足そうとした案なので捨てました")
        sections[name] = s["text"].strip("\n")
    candidate = join_sections(sections)
    for name in LOCKED:  # 念のため、本当の差分でも確かめる
        if split_sections(system).get(name) != split_sections(candidate).get(name):
            raise RunError(f"直してはいけない節（{name}）が変わっていたので捨てました")
    return candidate


def explain(system: str, candidate: str, proposal: dict) -> dict:
    """画面に出す形：図（節ごとに 変わる／変わらない／直せない）・本当の差分・説明の無い変更。"""
    diff = section_diff(system, candidate)
    changed = {d["section"] for d in diff}
    stated = {norm(c["section"]) for c in proposal.get("changes", [])}
    return {
        "eli5": proposal.get("eli5", ""),
        "flow": [{"section": s, "label": label, "role": role,
                  "state": "locked" if s in LOCKED else "changed" if s in changed else "same"}
                 for s, label, role in SECTIONS],
        "changes": proposal.get("changes", []),
        "diff": diff,
        "unexplained": sorted(changed - stated),  # 差分はあるのに説明が無い節
        "claimed_not_changed": sorted(stated - changed),  # 説明はあるのに差分が無い節
    }
