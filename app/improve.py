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
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
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
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
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


def rounds_text(base: dict, cand: dict | None = None) -> str:
    """台帳ごとの「採点の何回目で合格したか」（合計の点は合格しなかった台帳を4と数えるので、画面と理由には出さない）。"""
    f = lambda r: f"{r}回目で合格" if r else "3回で通らず"
    parts = []
    for k, label in (("plant", "A"), ("noplant", "B")):
        parts.append(f"台帳{label} {f(base[k].get('rounds'))}" + (f" → {f(cand[k].get('rounds'))}" if cand else ""))
    return "・".join(parts)


def decide(base: dict, cand: dict) -> tuple[str, str]:
    """残すか戻すか。物差しの決まり（コード）だけで決める。
    残すには、報告の形・検算の一致・両方の台帳で採点に合格・中身の確かめ、のすべてを満たし、前の版より良いこと。"""
    if not cand["all_schema_ok"]:
        return "reverted", "報告の形が合わない回があった"
    if not all(cand[k].get("matches") for k in ("plant", "noplant")):
        return "reverted", "検算がアプリの集計と合わない台帳があった"
    if not cand["all_judge_ok"]:
        return "reverted", "中身の確かめ（台帳Aで本当の理由を見つける・台帳Bで偶然かもしれない差を確かな差のように言い切らない）に通らなかった"
    if not all(cand[k].get("rounds") for k in ("plant", "noplant")):
        return "reverted", f"採点に合格しなかった台帳があった（{rounds_text(base, cand)}）"
    if base["all_judge_ok"] is False:
        return "kept", "前の版は中身の確かめに通らず、新しい版は通った"
    # 合計の点：採点の何回目で合格したかを足す（合格しなかった台帳は4と数える）。小さいほど良い
    if cand["total_rounds"] < base["total_rounds"]:
        return "kept", f"採点に合格するまでが短くなった（{rounds_text(base, cand)}）"
    bc, cc = base["total_cost_cents"], cand["total_cost_cents"]
    if cand["total_rounds"] == base["total_rounds"] and bc and cc is not None and cc <= bc * 0.9:
        return "kept", f"採点に合格するまでは同じで、費用が1割以上減った（${bc / 100:.2f} → ${cc / 100:.2f}）"
    return "reverted", f"良くならなかった（{rounds_text(base, cand)}）"


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
- eli5・summary・why・field_effect は店長が読む。英字の言葉（ファイル名・欄の名前・step_01・スクリプトなど）を使わず、「報告の◯◯の欄」「集計」のように言う
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


# ---- 現場の言葉で言い直す ----------------------------------------------------------
# 直す役の説明は手順書の話になりやすい。現場の人が知りたいのは「届く報告がどう変わるか」なので、
# 前の版と直した版が同じ見本の台帳で実際に書いた報告から、変わった所を抜き出して並べる。
# 抜き出した文が本当にその報告にあるかはコードで確かめる（無ければ捨てる）。

PLAIN_MODEL = JUDGE_MODEL
REPORT_PARTS = {
    "reconciliation": "数え直しの結果", "first_view": "最初の見立て", "steps": "調べた順番",
    "revised_view": "調べた後の見立て", "observations": "分かったこと", "hypotheses": "考えられる理由",
    "to_check": "店で確かめること", "next_action": "次の一手",
}
LEDGER_LABEL = {"plant": "見本の台帳A（チラシが低く見える仕掛けあり）", "noplant": "見本の台帳B（媒体の差が無い）"}
# 現場向けの文に混ざってはいけない言葉（ファイル名・欄の英字名など）
JARGON = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{2,}")
FIELD_WORDS = {"LINE", "QR", "Web", "AI"}  # 現場でも使う言葉

PLAIN_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["headline", "decision_plain", "report_changes"],
    "properties": {
        "headline": {"type": "string", "description": "店長に向けて、この直しで届く報告がどう変わるか（1文）"},
        "decision_plain": {"type": "string", "description": "残した／戻した理由を店長の言葉で（1〜2文）"},
        "report_changes": {"type": "array", "description": "1〜3件", "items": {
            "type": "object", "additionalProperties": False, "required": ["ledger", "part", "before", "after", "plain"],
            "properties": {
                "ledger": {"type": "string", "enum": list(LEDGER_LABEL)},
                "part": {"type": "string", "enum": list(REPORT_PARTS)},
                "before": {"type": "string", "description": "前の版の報告のその欄から、そのまま写した文（1〜2文）"},
                "after": {"type": "string", "description": "直した版の報告のその欄から、そのまま写した文（1〜2文）"},
                "plain": {"type": "string", "description": "店長に向けて、何が変わったか（1文）"},
            }}},
    },
}

PLAIN_SYSTEM = """あなたは、店の分析担当（AI）の仕事のやり方の直しを、店長に説明する係です。店長は IT に詳しくありません。
渡されるもの：直しの説明（作る人向け）、残した／戻した理由、決まった問いの確かめの理由、
同じ見本の台帳で「前の版」と「直した版」が実際に書いた報告（欄ごと）。

書くこと：
- headline：届く報告がどう変わるかを1文。手順書・指示文・節の話ではなく、報告の話をする
- decision_plain：残した／戻した理由を1〜2文。戻した時は、直した版の報告のどこが言い過ぎだったかを言う
- report_changes：直しで変わった所を1〜3件。before と after は、その欄の文から**一字一句そのまま**写す（要約・言い換え・つなぎ合わせをしない。1〜2文に切り出すのはよい）。
  戻した時は、言い過ぎた文を after に入れる
- plain：その変化を店長の言葉で1文

決まり：
- 英字の言葉（ファイル名・欄の名前・step_01・JSON・CSV・スクリプトなど）を使わない。「報告の◯◯の欄」「集計」と言う
- 確かめていないことを言わない。見込みは見込みと言う
"""


def _part_text(report: dict | None, part: str) -> str:
    """報告の欄の文を1つの文字列にする（抜き出しが本当にあるかを確かめる用）。"""
    if not report:
        return ""
    v = report.get(part)
    out: list[str] = []
    def walk(x) -> None:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for y in x.values():
                walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(v)
    return "\n".join(out)


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def check_plain(plain: dict, base: dict, cand: dict) -> dict:
    """抜き出しが本当に報告にあるか・英字の言葉が混ざっていないかを確かめ、画面に出す形にする。"""
    kept, dropped = [], 0
    for c in plain.get("report_changes", []):
        b = _part_text(base[c["ledger"]].get("report"), c["part"])
        a = _part_text(cand[c["ledger"]].get("report"), c["part"])
        if _squash(c["before"]) in _squash(b) and _squash(c["after"]) in _squash(a) and c["before"] and c["after"]:
            kept.append({**c, "part_label": REPORT_PARTS[c["part"]], "ledger_label": LEDGER_LABEL[c["ledger"]]})
        else:
            dropped += 1
    words = sorted({w for t in [plain.get("headline", ""), plain.get("decision_plain", "")] + [c["plain"] for c in kept]
                    for w in JARGON.findall(t) if w not in FIELD_WORDS})
    return {"headline": plain.get("headline", ""), "decision_plain": plain.get("decision_plain", ""),
            "report_changes": kept[:3], "dropped": dropped, "jargon": words}


def plain_explain(proposal: dict, decision: str, reason: str, base: dict, cand: dict) -> dict:
    """現場の言葉で言い直す（Sonnet を1回）。"""
    import anthropic

    reports = {k: {"前の版": {p: base[k].get("report", {}).get(p) for p in REPORT_PARTS},
                   "直した版": {p: cand[k].get("report", {}).get(p) for p in REPORT_PARTS}} for k in LEDGER_LABEL}
    judge = {k: {"前の版": base[k].get("judge"), "直した版": cand[k].get("judge")} for k in LEDGER_LABEL}
    content = (f"## 直しの説明（作る人向け）\n```json\n{json.dumps(proposal.get('changes', []), ensure_ascii=False, indent=1)}\n```\n\n"
               f"## 判定\n{decision}：{reason}\n\n"
               f"## 決まった問いの確かめ\n```json\n{json.dumps(judge, ensure_ascii=False, indent=1)}\n```\n\n"
               f"## 台帳の呼び名\n{json.dumps(LEDGER_LABEL, ensure_ascii=False)}\n"
               f"## 報告の欄の呼び名\n{json.dumps(REPORT_PARTS, ensure_ascii=False)}\n\n"
               f"## 報告（台帳ごと・欄ごと）\n```json\n{json.dumps(reports, ensure_ascii=False, indent=1)}\n```")
    out: dict = {}
    # 空で返ってきたら1回だけ聞き直す。断られた時（出力が無い）は Opus で聞き直す
    for model in (PLAIN_MODEL, IMPROVER_MODEL):
        resp = anthropic.Anthropic().beta.messages.create(
            model=model, max_tokens=4000, system=PLAIN_SYSTEM,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"format": {"type": "json_schema", "schema": PLAIN_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
        plain = json.loads(next((b.text for b in resp.content if b.type == "text"), "{}"))
        out = check_plain(plain, base, cand)
        if out["headline"] and out["report_changes"]:
            break
    return out
