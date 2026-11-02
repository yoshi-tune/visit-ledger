"""分析エージェント（Claude Managed Agents）の準備。最初に1回だけ回す。

    uv run python scripts/setup_agent.py

環境（サンドボックス）とエージェントを作り、その ID を data/agent_ids.json に書く（git には入れない）。
指示文（agent/analyst_system.md）を直した後にもう一度回すと、同じエージェントを更新して版が上がる。
鍵は環境変数 ANTHROPIC_API_KEY から読む。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent.parent
IDS = ROOT / "data" / "agent_ids.json"
MODEL = "claude-opus-5-5"
NAME = "visit-ledger 分析エージェント"

TOOLS = [
    {
        "type": "agent_toolset_20260401",
        # サンドボックスには許可した列だけの CSV しか無く、外への通信も無いので、道具は確認なしで使わせる
        "default_config": {"enabled": True, "permission_policy": {"type": "always_allow"}},
        "configs": [
            {"name": "web_fetch", "enabled": False},
            {"name": "web_search", "enabled": False},
        ],
    }
]


def main() -> None:
    client = anthropic.Anthropic()
    system = (ROOT / "agent" / "analyst_system.md").read_text(encoding="utf-8")
    ids = json.loads(IDS.read_text(encoding="utf-8")) if IDS.exists() else {}

    if not ids.get("environment_id"):
        env = client.beta.environments.create(
            name="visit-ledger-analysis",
            # 外へは出さない（パッケージも入れない。Python の標準ライブラリだけで集計する）
            config={"type": "cloud", "networking": {"type": "limited"}},
        )
        ids["environment_id"] = env.id
        print("環境を作りました:", env.id)

    if ids.get("agent_id"):
        current = client.beta.agents.retrieve(ids["agent_id"])
        agent = client.beta.agents.update(
            ids["agent_id"], version=current.version, model=MODEL, system=system, tools=TOOLS,
        )
        print("エージェントを更新しました:", agent.id, "版", agent.version)
    else:
        agent = client.beta.agents.create(name=NAME, model=MODEL, system=system, tools=TOOLS)
        print("エージェントを作りました:", agent.id, "版", agent.version)
    ids["agent_id"] = agent.id
    ids["agent_version"] = agent.version

    IDS.parent.mkdir(parents=True, exist_ok=True)
    IDS.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")
    print("書きました:", IDS)


if __name__ == "__main__":
    try:
        main()
    except anthropic.AuthenticationError:
        sys.exit("鍵が使えません。ANTHROPIC_API_KEY を設定してから回してください。")
