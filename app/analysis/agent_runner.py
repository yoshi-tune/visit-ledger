"""分析エージェント（Claude Managed Agents）を1回動かす。

書き出しの CSV と集計の JSON をファイルとして渡し、エージェントにサンドボックスの中で集計させる。
エージェントが使った道具（コードの実行など）と結果は、アプリの側で出来事の流れから拾って記録する。
"""

from __future__ import annotations

import json
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


# 採点で直しを求められても、この回数まで書き直す（outcomes の max_iterations）。改善の画面と判定の理由もこの数を使う
MAX_GRADES = 3

def run(analysis_id: str, files: dict[str, str], funnel: dict,
        on_log: Callable[[dict], None], model: str = config.DEFAULT_MODEL,
        previous: dict | None = None, system: str | None = None) -> dict:
    """system を渡すと、このセッションだけ指示文を差し替える（改善の試し。本番のエージェントの版は変えない）。"""
    if not IDS.exists():
        raise RunError("分析エージェントの準備がまだです。`uv run python scripts/setup_agent.py` を先に回してください。")
    ids = json.loads(IDS.read_text(encoding="utf-8"))
    client = anthropic.Anthropic()

    uploads = {
        **{name: (text, "text/csv") for name, text in files.items()},
        "funnel.json": (json.dumps(funnel, ensure_ascii=False, indent=1), "application/json"),
        # 前回の分析の「次の一手」とその時の数字。前回が無い時も {"had_previous": false} を必ず置く
        "previous.json": (json.dumps(previous or {"had_previous": False}, ensure_ascii=False, indent=1),
                          "application/json"),
        "report_schema.json": ((AGENT_DIR / "report_schema.json").read_text(encoding="utf-8"),
                               "application/json"),
    }
    resources = []
    for name, (text, mime) in uploads.items():
        f = client.files.upload(file=(name, text.encode("utf-8"), mime))
        resources.append({"type": "file", "file_id": f.id, "mount_path": f"{MOUNT}/{name}"})

    agent = {"type": "agent_with_overrides", "id": ids["agent_id"], "version": ids["agent_version"],
             "model": model}
    if system is not None:
        agent["system"] = system
    session = client.beta.sessions.create(
        # 店長が選んだモデルで、このセッションだけ動かす（エージェントの版は変えない）
        agent=agent,
        environment_id=ids["environment_id"],
        title=f"visit-ledger {analysis_id}",
        resources=resources,
        # 1回の分析で使う量の上限（セント単位の文字列。既定 $3.00）。続きの質問もこの中で答える
        budget={"type": "limit",
                "max_list_cost": {"amount": str(config.BUDGET_CENTS),
                                  "currency": "USD"}},
    )
    on_log({"kind": "session", "session_id": session.id, "model": model})

    rubric = (AGENT_DIR / "rubric.md").read_text(encoding="utf-8")
    stop, _ = _drive(client, session.id, {
        "type": "user.define_outcome",
        "description": DESCRIPTION,
        "rubric": {"type": "text", "content": rubric},
        "max_iterations": MAX_GRADES,
    }, on_log)
    if stop == "budget_reached":
        raise RunError("1回の分析の上限（VL_BUDGET_CENTS）に達したので止めました。")
    return _fetch_report(client, session.id)


ANSWER_RULES = (
    "\n\n（答え方：店長が読む短い日本語で、結論を先に書く。新しく数える時は "
    "/workspace/steps/chat_NN.py にスクリプトを書いて実行し、その数字だけを使う。根拠のスクリプト名を添える。"
    "report.json は書き直さない。台帳に無いことは「台帳に無いので確かめられない」と書く。"
    "原因を言い切らない。専門用語は使わない。結論は1文、続けて箇条書きを4つまで（入れ子にしない）。表は使わない）"
)


def answer(session_id: str, text: str, on_log: Callable[[dict], None]) -> str:
    """分析を終えたセッションに、店長の続きの質問を送り、答えの文を返す。"""
    client = anthropic.Anthropic()
    stop, texts = _drive(client, session_id, {
        "type": "user.message",
        "content": [{"type": "text", "text": f"店長からの質問です：{text}{ANSWER_RULES}"}],
    }, on_log)
    if stop == "budget_reached":
        raise RunError("この分析の上限（VL_BUDGET_CENTS）に達したので、これ以上は答えられません。新しく分析を頼んでください。")
    if not texts:
        raise RunError("答えの文が返ってきませんでした。聞き方を変えて、もう一度聞いてください。")
    return texts[-1]


def _drive(client: anthropic.Anthropic, session_id: str, first_event: dict,
           on_log: Callable[[dict], None]) -> tuple[str | None, list[str]]:
    """出来事の流れを開いてから1つ送り、止まるまで道具の記録と答えの文を拾う。"""
    pending: dict[str, dict] = {}
    texts: list[str] = []
    stop = None
    with client.beta.sessions.events.stream(session_id=session_id) as stream:
        client.beta.sessions.events.send(session_id=session_id, events=[first_event])
        for event in stream:
            t = event.type
            if t == "agent.message":
                body = "".join(b.text for b in (event.content or []) if getattr(b, "type", "") == "text")
                if body.strip():
                    texts.append(body.strip())
            elif t == "agent.tool_use":
                pending[event.id] = {"kind": "tool", "id": event.id, "tool": event.name,
                                     "input": _jsonable(event.input)}
                if getattr(event, "evaluated_permission", None) == "ask":
                    # 誰も見ていない処理なので、確認待ちの道具は断る
                    client.beta.sessions.events.send(
                        session_id=session_id,
                        events=[{"type": "user.tool_confirmation", "tool_use_id": event.id,
                                 "result": "deny"}],
                    )
            elif t == "agent.tool_result":
                key = getattr(event, "tool_use_id", None)
                entry = pending.pop(key, None) if key else None
                # 対応が取れない時は、取り違えないよう「対応不明」として残す
                entry = entry or {"kind": "tool", "id": key, "tool": "対応不明", "input": None}
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
    return stop, texts


def session_cost_cents(session_id: str) -> int | None:
    """セッションがここまでに使った額（定価で数えた目安・セント）。取れなければ None。"""
    try:
        usage = anthropic.Anthropic().beta.sessions.retrieve(session_id).usage
        return int(round(float(usage.list_cost.amount)))
    except Exception:  # 費用が取れなくても、分析や答えは失敗にしない
        return None


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
