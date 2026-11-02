"""予備：Messages API を1回呼んで報告を書かせる（エージェントが動かない時の切替先）。

同じ入力・同じ報告の形を使うが、コードで集計を重ねることはできない。
そのため画面では「追加の集計はしていない」と出す（docs/DESIGN.md §8）。
"""

from __future__ import annotations

import json
from collections.abc import Callable

import anthropic

from app import config
from app.analysis import RunError

MODEL = "claude-opus-5-5"
AGENT_DIR = config.ROOT / "agent"

NOTE = (
    "\n\n## この呼び出しでの違い\n"
    "コードを実行する道具はありません。CSV は下に本文として貼ってあります。"
    "`steps` には、表を読んで確かめたことを書き、`step` は `read_01` のように書いてください。"
    "数え直せなかった数字は funnel.json の値を使い、そう書いてください。"
    "報告は JSON だけを返してください（ファイルには書かない）。"
)


def run(analysis_id: str, files: dict[str, str], funnel: dict,
        on_log: Callable[[dict], None], model: str = MODEL) -> dict:
    client = anthropic.Anthropic()
    system = (AGENT_DIR / "analyst_system.md").read_text(encoding="utf-8") + NOTE
    schema = json.loads((AGENT_DIR / "report_schema.json").read_text(encoding="utf-8"))

    parts = [f"## funnel.json\n```json\n{json.dumps(funnel, ensure_ascii=False, indent=1)}\n```"]
    parts += [f"## {name}\n```csv\n{text}```" for name, text in files.items()]
    on_log({"kind": "note", "detail": "予備の形（Messages API を1回）で分析しました。追加の集計はしていません。"})

    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
    )
    if response.stop_reason == "refusal":
        raise RunError("Claude が今回の依頼に答えませんでした（refusal）。")
    if response.stop_reason == "max_tokens":
        raise RunError("報告が長すぎて途中で切れました。")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RunError(f"報告が JSON として読めません: {e}") from e
