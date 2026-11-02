"""分析エージェント（Claude Managed Agents）を1回動かす。

書き出しの CSV と集計の JSON をファイルとして渡し、エージェントにサンドボックスの中で集計させる。
エージェントが使った道具（コードの実行など）と結果は、アプリの側で出来事の流れから拾って記録する。
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable

import anthropic

from app import config
from app.analysis import RunError

AGENT_DIR = config.ROOT / "agent"
IDS = config.ROOT / "data" / "agent_ids.json"
MOUNT = "/ledger"  # → /mnt/session/uploads/ledger/
OUTPUT_LIMIT = 4000  # 記録に残す道具の出力の長さ

DESCRIPTION = (
    "/mnt/session/uploads/ledger/ の台帳の書き出しを、指示文の進め方どおりに調べ、"
    "/mnt/session/outputs/report.json に報告を書いてください。"
)


def run(analysis_id: str, files: dict[str, str], funnel: dict,
        on_log: Callable[[dict], None]) -> dict:
    if not IDS.exists():
        raise RunError("分析エージェントの準備がまだです。`uv run python scripts/setup_agent.py` を先に回してください。")
    ids = json.loads(IDS.read_text(encoding="utf-8"))
    client = anthropic.Anthropic()

    uploads = {
        **{name: (text, "text/csv") for name, text in files.items()},
        "funnel.json": (json.dumps(funnel, ensure_ascii=False, indent=1), "application/json"),
        "report_schema.json": ((AGENT_DIR / "report_schema.json").read_text(encoding="utf-8"),
                               "application/json"),
    }
    resources = []
    for name, (text, mime) in uploads.items():
        f = client.files.upload(file=(name, text.encode("utf-8"), mime))
        resources.append({"type": "file", "file_id": f.id, "mount_path": f"{MOUNT}/{name}"})

    session = client.beta.sessions.create(
        agent={"type": "agent", "id": ids["agent_id"], "version": ids["agent_version"]},
        environment_id=ids["environment_id"],
        title=f"visit-ledger {analysis_id}",
        resources=resources,
        # 1回の分析で使う量の上限（セント単位の文字列。既定 $3.00）
        budget={"type": "limit",
                "max_list_cost": {"amount": os.environ.get("VL_BUDGET_CENTS", "300"),
                                  "currency": "USD"}},
    )
    on_log({"kind": "session", "session_id": session.id})

    rubric = (AGENT_DIR / "rubric.md").read_text(encoding="utf-8")
    pending: dict[str, dict] = {}
    stop = None
    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(
            session_id=session.id,
            events=[{
                "type": "user.define_outcome",
                "description": DESCRIPTION,
                "rubric": {"type": "text", "content": rubric},
                "max_iterations": 3,
            }],
        )
        for event in stream:
            t = event.type
            if t == "agent.tool_use":
                pending[event.id] = {"kind": "tool", "id": event.id, "tool": event.name,
                                     "input": _jsonable(event.input)}
                if getattr(event, "evaluated_permission", None) == "ask":
                    # 誰も見ていない処理なので、確認待ちの道具は断る
                    client.beta.sessions.events.send(
                        session_id=session.id,
                        events=[{"type": "user.tool_confirmation", "tool_use_id": event.id,
                                 "result": "deny"}],
                    )
            elif t == "agent.tool_result":
                key = getattr(event, "tool_use_id", None)
                entry = pending.pop(key, None) if key else None
                if entry is None and pending:  # 対応が取れない時は、一番古い呼び出しに付ける
                    entry = pending.pop(next(iter(pending)))
                entry = entry or {"kind": "tool", "id": key, "tool": "?", "input": None}
                entry["output"] = _text(getattr(event, "content", None))[:OUTPUT_LIMIT]
                entry["is_error"] = bool(getattr(event, "is_error", False))
                on_log(entry)
            elif t == "span.outcome_evaluation_end":
                on_log({"kind": "grade", "iteration": getattr(event, "iteration", None),
                        "result": getattr(event, "result", None),
                        "explanation": getattr(event, "explanation", None)})
            elif t == "session.error":
                on_log({"kind": "error", "detail": _text(getattr(event, "error", None)) or str(event)})
            elif t == "session.status_idle":
                stop = getattr(getattr(event, "stop_reason", None), "type", None)
                if stop != "requires_action":
                    break
            elif t == "session.status_terminated":
                stop = "terminated"
                break

    if stop == "budget_reached":
        raise RunError("1回の分析の上限（VL_BUDGET_CENTS）に達したので止めました。")
    return _fetch_report(client, session.id)


def _fetch_report(client: anthropic.Anthropic, session_id: str) -> dict:
    # 出力のファイルが一覧に出るまで少し遅れることがある
    for _ in range(5):
        listed = client.beta.files.list(scope_id=session_id, betas=["managed-agents-2026-04-01"])
        for f in listed.data:
            if f.filename.endswith("report.json"):
                body = client.files.download(f.id)
                raw = body.read() if hasattr(body, "read") else body.content
                try:
                    return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                except json.JSONDecodeError as e:
                    raise RunError(f"エージェントの報告が JSON として読めません: {e}") from e
        time.sleep(2)
    raise RunError("エージェントが報告（report.json）を書きませんでした。")


def _text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text(c) for c in content)
    text = getattr(content, "text", None)
    if isinstance(text, str):
        return text
    if hasattr(content, "model_dump"):
        return json.dumps(content.model_dump(), ensure_ascii=False)
    return str(content)


def _jsonable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump()
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
