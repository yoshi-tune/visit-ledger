"""分析担当の改善を回す（app/improve.py・docs/IMPROVE.md）。鍵が要る。1回の改善で本物の分析が2回（$2 前後）。

    uv run python scripts/improve_analyst.py --iterations 2
    uv run python scripts/improve_analyst.py --iterations 2 --reuse-plant agent/sample_run.json

--reuse-plant：今の版の「仕込みあり」の点数は、前に回した分析（今の指示文で回したもの）から取る（1回分の費用を省く）。
結果は台帳の improvements に残り、画面「ナットクの改善」（/improve）に出る。
本番に使うかは画面で人が決める（ここでは agent/analyst_system.md もエージェントも変えない）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, improve, ledger  # noqa: E402
from app.analysis import RunError  # noqa: E402


def slim(ev: dict) -> str:
    """台帳に残す形（報告の全文も残す。画面と次の回の直す役が読む）。"""
    return json.dumps(ev, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--reuse-plant", type=Path, help="今の版の仕込みありの点数に使う、前の分析（sample_run.json の形）")
    args = parser.parse_args()

    conn = ledger.connect(config.DB_PATH)
    ledger.upgrade_schema(conn)
    system = improve.SYSTEM_PATH.read_text(encoding="utf-8")

    t0 = time.time()
    print("今の版の点数を取ります…", flush=True)
    if args.reuse_plant:
        saved = json.loads(args.reuse_plant.read_text(encoding="utf-8"))
        base = improve.summarize({"plant": improve.from_saved_run(saved, True),
                                  "noplant": improve.evaluate_one(system, False)})
    else:
        base = improve.evaluate(system)
    print(f"  採点の回数 {base['total_rounds']}・費用 {base['total_cost_cents']}¢・中身 {base['all_judge_ok']}"
          f"（{time.time() - t0:.0f}秒）", flush=True)

    history: list[dict] = []
    for i in range(1, args.iterations + 1):
        now = config.now().isoformat(timespec="seconds")
        row = ledger.add_improvement(conn, now, i, system, slim(base))
        try:
            print(f"[{i}] 直しの案を作ります…", flush=True)
            proposal = improve.propose(system, base, history)
            try:
                candidate = improve.apply_proposal(system, proposal)
            except RunError as e:
                ledger.update_improvement(conn, row, status="done", decision="rejected", reason=str(e),
                                          proposal_json=json.dumps(proposal, ensure_ascii=False))
                print(f"[{i}] 捨てた：{e}", flush=True)
                history.append(ledger.get_improvement(conn, row))
                continue
            shown = {**proposal, "explain": improve.explain(system, candidate, proposal)}
            ledger.update_improvement(conn, row, candidate_system=candidate,
                                      proposal_json=json.dumps(shown, ensure_ascii=False))
            print(f"[{i}] 案で回します（仕込みあり・なしを並べて）…", flush=True)
            cand = improve.evaluate(candidate)
            decision, reason = improve.decide(base, cand)
            ledger.update_improvement(conn, row, status="done", decision=decision, reason=reason,
                                      eval_cand_json=slim(cand))
            print(f"[{i}] {decision}：{reason}（採点の回数 {cand['total_rounds']}・費用 {cand['total_cost_cents']}¢）",
                  flush=True)
            if decision == "kept":  # 次の回は残した版から直す
                system, base = candidate, cand
        except Exception as e:  # 途中で失敗しても、それまでの記録は残す
            ledger.update_improvement(conn, row, status="failed", reason=f"{type(e).__name__}: {e}")
            print(f"[{i}] 失敗：{e}", flush=True)
            raise
        history.append(ledger.get_improvement(conn, row))
    print(f"終わりました（{time.time() - t0:.0f}秒）。画面：http://127.0.0.1:8000/improve", flush=True)


if __name__ == "__main__":
    main()
