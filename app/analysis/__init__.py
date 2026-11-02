"""分析の依頼と結果（docs/DESIGN.md §8）。

依頼を受けたら、1回の読み取りで作った書き出しと集計を analysis_runs に固定して保存し、
裏の処理で分析エージェント（または予備の Messages API）を動かす。

    VL_ANALYSIS_MODE=agent     … Claude Managed Agents（既定）。先に scripts/setup_agent.py を回す
    VL_ANALYSIS_MODE=messages  … 予備。Messages API を1回呼ぶ（追加の集計はできない）
"""

from __future__ import annotations

import json
import os
import re
import threading
import traceback
import uuid

from app import config, export, ledger

# 報告の形（エージェントにも同じファイルを渡している）
REPORT_SCHEMA = json.loads((config.ROOT / "agent" / "report_schema.json").read_text(encoding="utf-8"))
# 基準（rubric）の件数の上限。超えても失敗にはせず、記録に注意として残す（採点が先に見ている）
LIMITS = {"observations": 8, "hypotheses": 3, "to_check": 4, "steps": 4}


class RunError(Exception):
    """店長に見せてよい言葉で書いた失敗の理由。"""


def start(conn, snapshot: dict, funnel: dict, model: str = config.DEFAULT_MODEL) -> dict:
    files, id_map = export.build(snapshot)
    analysis_id = f"an_{uuid.uuid4().hex[:12]}"
    ledger.create_analysis_run(
        conn, analysis_id, funnel["as_of"],
        status="queued",
        export_csv=json.dumps(files, ensure_ascii=False),
        id_map_json=json.dumps(id_map),
        funnel_json=json.dumps(funnel, ensure_ascii=False),
        tool_log="[]",
        model=model,
    )
    threading.Thread(target=_run, args=(analysis_id,), daemon=True).start()
    return {"analysis_id": analysis_id, "status": "queued"}


def get(conn, analysis_id: str) -> dict | None:
    """画面に返す形。書き出しの中身と仮の番号の対応表は返さない。"""
    run = ledger.get_analysis_run(conn, analysis_id)
    if not run:
        return None
    report = json.loads(run["report_json"]) if run["report_json"] else None
    out = {
        "analysis_id": run["analysis_id"],
        "as_of": run["as_of"],
        "status": run["status"],
        "model": run["model"] or config.DEFAULT_MODEL,
        "model_label": config.MODELS.get(run["model"] or config.DEFAULT_MODEL, {}).get("label"),
        "tool_log": json.loads(run["tool_log"] or "[]"),
        "report": None,
        "error": None,
        "can_ask": bool(_session_id(run)) and run["status"] == "done",
        "cost_cents": run["cost_cents"],
        "budget_cents": config.BUDGET_CENTS,
        "messages": [
            {"id": m["id"], "at": m["at"], "role": m["role"], "status": m["status"], "text": m["text"],
             "tool_log": json.loads(m["tool_log"] or "[]")}
            for m in ledger.list_analysis_messages(conn, analysis_id)
        ],
    }
    if report and "error" in report:
        out["error"] = report["error"]
    else:
        out["report"] = report
    return out


def _run(analysis_id: str) -> None:
    conn = ledger.connect(config.DB_PATH)
    log: list[dict] = []

    def on_log(entry: dict) -> None:
        log.append(entry)
        extra = {"session_id": entry["session_id"]} if entry.get("kind") == "session" else {}
        ledger.update_analysis_run(conn, analysis_id, tool_log=json.dumps(log, ensure_ascii=False),
                                   **extra)

    try:
        run = ledger.get_analysis_run(conn, analysis_id)
        files = json.loads(run["export_csv"])
        funnel = json.loads(run["funnel_json"])
        mode = os.environ.get("VL_ANALYSIS_MODE", "agent")
        ledger.update_analysis_run(conn, analysis_id, status="running")

        if mode == "messages":
            from app.analysis import messages_runner as runner
        else:
            from app.analysis import agent_runner as runner
        model = run["model"] or config.DEFAULT_MODEL
        report = runner.run(analysis_id, files, funnel, on_log, model)

        for note in check_report(report, log if mode != "messages" else None):
            on_log({"kind": "note", "detail": note})
        report["mode"] = mode
        ledger.update_analysis_run(
            conn, analysis_id, status="done", report_json=json.dumps(report, ensure_ascii=False)
        )
        _record_cost(conn, analysis_id)
    except Exception as e:  # 裏の処理なので、理由を記録して画面に出す
        message = str(e) if isinstance(e, RunError) else _describe(e)
        ledger.update_analysis_run(
            conn, analysis_id, status="failed",
            report_json=json.dumps({"error": message}, ensure_ascii=False),
        )
        if not isinstance(e, RunError):
            traceback.print_exc()
    finally:
        conn.close()


# ---- 報告の検査 ------------------------------------------------------------------

def check_report(report: dict, log: list[dict] | None) -> list[str]:
    """報告を確かめる。形（report_schema.json）に合わなければ RunError で「失敗」にする。
    形は合っているが基準から外れる所は、注意の文として返す（記録に残して画面に出す）。
    log を渡すと、観測の根拠のスクリプト名が、実際に実行したコードに出てくるかも確かめる。"""
    import jsonschema

    errors = sorted(jsonschema.Draft202012Validator(REPORT_SCHEMA).iter_errors(report),
                    key=lambda e: list(e.absolute_path))
    if errors:
        where = lambda e: "/".join(str(p) for p in e.absolute_path) or "（全体）"
        lines = [f"{where(e)}: {e.message}" for e in errors[:5]]
        more = f" ほか{len(errors) - 5}件" if len(errors) > 5 else ""
        raise RunError("エージェントの報告が決めた形に合いません: " + "／".join(lines) + more)

    notes = []
    for key, limit in LIMITS.items():
        if len(report[key]) > limit:
            notes.append(f"報告の検査：{key} が {len(report[key])} 件（基準は {limit} 件まで）。")
    for i, o in enumerate(report["observations"], 1):
        if o["denominator"] <= 0 or o["numerator"] > o["denominator"]:
            notes.append(f"報告の検査：観測 {i} の分子・分母がおかしい（{o['numerator']}/{o['denominator']}）。")
        if not o["steps"]:
            notes.append(f"報告の検査：観測 {i} に根拠のスクリプト名がありません。")
    if log is not None:
        ran = json.dumps([e.get("input") for e in log if e.get("kind") == "tool"], ensure_ascii=False)
        cited = {s for o in report["observations"] for s in o["steps"]} | {s["step"] for s in report["steps"]}
        unseen = sorted(s for s in cited if re.fullmatch(r"step_\d+", s) and s not in ran)
        if unseen:
            notes.append("報告の検査：根拠に挙げたスクリプトのうち、実行の記録に見当たらないもの："
                         + "、".join(unseen) + "。")
    return notes


# ---- 分析の続きの質問（壁打ち） ------------------------------------------------

# 電話番号らしき数字の並び（10桁以上）。名前は見分けられないので、画面で書かないよう頼む
_PHONE = re.compile(r"(?:\d[-‐ー－\s]?){10,}")


def _session_id(run: dict) -> str | None:
    if run.get("session_id"):
        return run["session_id"]
    for e in json.loads(run.get("tool_log") or "[]"):  # 列を足す前の分析は、記録から拾う
        if e.get("kind") == "session":
            return e.get("session_id")
    return None


def ask(conn, analysis_id: str, text: str) -> dict:
    run = ledger.get_analysis_run(conn, analysis_id)
    if not run:
        raise RunError("分析がありません。")
    session_id = _session_id(run)
    if run["status"] != "done" or not session_id:
        raise RunError("この分析には続けて質問できません（エージェントの分析が終わった後だけ聞けます）。")
    if _PHONE.search(text):
        raise RunError("電話番号のような数字が入っています。お客様の情報は書かずに聞いてください。")
    messages = ledger.list_analysis_messages(conn, analysis_id)
    if any(m["status"] == "pending" for m in messages):
        raise RunError("前の質問に答えている途中です。答えが出てから聞いてください。")
    at = config.now().isoformat(timespec="seconds")
    ledger.add_analysis_message(conn, analysis_id, at, "user", "done", text.strip())
    reply_id = ledger.add_analysis_message(conn, analysis_id, at, "assistant", "pending")
    threading.Thread(target=_answer, args=(analysis_id, session_id, reply_id, text.strip()),
                     daemon=True).start()
    return {"message_id": reply_id, "status": "pending"}


# ---- サーバーを立ち上げ直した時 -------------------------------------------------

def resume_unfinished(conn) -> None:
    """前回のサーバーで終わらなかった分析を引き継ぐ。エージェントのセッションは Anthropic の側で
    動き続けているので、セッションがあれば終わるのを待って報告を受け取る。無ければ「失敗」にする。"""
    ledger.fail_pending_messages(conn)
    for run in ledger.list_unfinished_runs(conn):
        session_id = _session_id(run)
        if session_id:
            threading.Thread(target=_resume, args=(run["analysis_id"], session_id), daemon=True).start()
        else:
            ledger.update_analysis_run(conn, run["analysis_id"], status="failed", report_json=json.dumps(
                {"error": "サーバーが途中で止まったため、分析が終わりませんでした。もう一度頼んでください。"},
                ensure_ascii=False))


def _resume(analysis_id: str, session_id: str) -> None:
    import time

    import anthropic

    from app.analysis import agent_runner

    conn = ledger.connect(config.DB_PATH)
    try:
        run = ledger.get_analysis_run(conn, analysis_id)
        log = json.loads(run["tool_log"] or "[]")
        log.append({"kind": "note", "detail": "サーバーを立ち上げ直したので、エージェントの続きを待って受け取りました。"})
        ledger.update_analysis_run(conn, analysis_id, status="running",
                                   tool_log=json.dumps(log, ensure_ascii=False))
        client = anthropic.Anthropic()
        for _ in range(80):  # 最大でおよそ20分待つ
            if client.beta.sessions.retrieve(session_id).status in ("idle", "terminated"):
                break
            time.sleep(15)
        report = agent_runner._fetch_report(client, session_id)
        for note in check_report(report, log):
            log.append({"kind": "note", "detail": note})
        report["mode"] = "agent"
        ledger.update_analysis_run(conn, analysis_id, status="done",
                                   report_json=json.dumps(report, ensure_ascii=False),
                                   tool_log=json.dumps(log, ensure_ascii=False))
        _record_cost(conn, analysis_id)
    except Exception as e:
        message = str(e) if isinstance(e, RunError) else _describe(e)
        ledger.update_analysis_run(conn, analysis_id, status="failed",
                                   report_json=json.dumps({"error": message}, ensure_ascii=False))
    finally:
        conn.close()


def _record_cost(conn, analysis_id: str) -> None:
    run = ledger.get_analysis_run(conn, analysis_id)
    session_id = _session_id(run) if run else None
    if not session_id:
        return
    from app.analysis import agent_runner

    cents = agent_runner.session_cost_cents(session_id)
    if cents is not None:
        ledger.update_analysis_run(conn, analysis_id, cost_cents=cents)


def costs(conn) -> dict:
    return {"budget_cents": config.BUDGET_CENTS, "by_model": ledger.analysis_cost_summary(conn, config.DEFAULT_MODEL)}


def _answer(analysis_id: str, session_id: str, reply_id: int, text: str) -> None:
    from app.analysis import agent_runner

    conn = ledger.connect(config.DB_PATH)
    log: list[dict] = []

    def on_log(entry: dict) -> None:
        log.append(entry)
        ledger.update_analysis_message(conn, reply_id, tool_log=json.dumps(log, ensure_ascii=False))

    try:
        answer = agent_runner.answer(session_id, text, on_log)
        ledger.update_analysis_message(conn, reply_id, status="done", text=answer)
    except Exception as e:
        message = str(e) if isinstance(e, RunError) else _describe(e)
        ledger.update_analysis_message(conn, reply_id, status="failed", text=message)
        if not isinstance(e, RunError):
            traceback.print_exc()
    finally:
        _record_cost(conn, analysis_id)
        conn.close()


def _describe(e: Exception) -> str:
    import anthropic

    text = str(e).lower()
    if isinstance(e, anthropic.AuthenticationError) or "authentication method" in text or (
        isinstance(e, anthropic.AnthropicError) and "api_key" in text
    ):
        return ("Claude の鍵が設定されていません（または使えません）。"
                "環境変数 ANTHROPIC_API_KEY を設定してからアプリを起動し直してください。")
    if isinstance(e, anthropic.RateLimitError):
        return "Claude の利用の上限に当たりました。少し待ってからもう一度頼んでください。"
    if isinstance(e, anthropic.APIConnectionError):
        return "Claude につながりませんでした。ネットワークを確かめてください。"
    if isinstance(e, anthropic.APIStatusError):
        return f"Claude の呼び出しが失敗しました（{e.status_code}）: {e.message}"
    return f"分析の途中で失敗しました: {type(e).__name__}: {e}"
