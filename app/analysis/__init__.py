"""分析の依頼と結果（docs/DESIGN.md §8）。

依頼を受けたら、1回の読み取りで作った書き出しと集計を analysis_runs に固定して保存し、
裏の処理で分析エージェント（または予備の Messages API）を動かす。

    VL_ANALYSIS_MODE=agent     … Claude Managed Agents（既定）。先に scripts/setup_agent.py を回す
    VL_ANALYSIS_MODE=messages  … 予備。Messages API を1回呼ぶ（追加の集計はできない）
"""

from __future__ import annotations

import json
import os
import threading
import traceback
import uuid

from app import config, export, ledger

REQUIRED_KEYS = ("reconciliation", "first_view", "revised_view", "observations", "hypotheses",
                 "next_action")


class RunError(Exception):
    """店長に見せてよい言葉で書いた失敗の理由。"""


def start(conn, snapshot: dict, funnel: dict) -> dict:
    files, id_map = export.build(snapshot)
    analysis_id = f"an_{uuid.uuid4().hex[:12]}"
    ledger.create_analysis_run(
        conn, analysis_id, funnel["as_of"],
        status="queued",
        export_csv=json.dumps(files, ensure_ascii=False),
        id_map_json=json.dumps(id_map),
        funnel_json=json.dumps(funnel, ensure_ascii=False),
        tool_log="[]",
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
        "tool_log": json.loads(run["tool_log"] or "[]"),
        "report": None,
        "error": None,
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
        ledger.update_analysis_run(conn, analysis_id, tool_log=json.dumps(log, ensure_ascii=False))

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
        report = runner.run(analysis_id, files, funnel, on_log)

        missing = [k for k in REQUIRED_KEYS if k not in report]
        if missing:
            raise RunError(f"報告に足りない項目があります: {', '.join(missing)}")
        report["mode"] = mode
        ledger.update_analysis_run(
            conn, analysis_id, status="done", report_json=json.dumps(report, ensure_ascii=False)
        )
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
