"""人の承認つきのループ（docs/LOOP.md）。

台帳に記録 → アプリが数える → Claude が分析（検算と採点つき）→ 次の一手を、決まった部品だけで受付のタブに提案
→ 【人】反映する → 受付で記録 → 次の分析が振り返る。

ここは「提案」の段：人が「ナットクに頼む」で頼んだ時（main.py）と、分析が終わった時（自動）の両方から使う。
自動で作るのは提案まで。反映は必ず人が押す（このファイルは反映しない）。分析のやり方の見直しは、ここからは回さない。
"""

from __future__ import annotations

import json
import threading
import traceback

from app import config, ledger, maintenance, public

AUTO_BY = "ナットク（自動）"  # 分析の後に自動で作った提案の「頼んだ人」


class ProposalCallError(Exception):
    """ナットク（Claude）を呼べなかった（通信・鍵など）。記録は「失敗」で残してある。"""


def propose(conn, requested_by: str, text: str, source_analysis_id: str | None) -> int:
    """依頼の文から、受付のタブの提案を作って記録する（反映はしない）。記録の番号を返す。
    部品から外れた案は捨て、部品で表せない依頼は「やめた」で残す（理由つき）。"""
    _, settings = ledger.current_settings(conn)
    with public.LOCK:  # 公開版の全体の上限：確かめと記録（見込みに数える）を続けて行う
        force_sample = public.refuse_proposal(conn)
        rid = ledger.add_change_request(conn, config.now().strftime("%Y-%m-%dT%H:%M:%S"), requested_by, text,
                                        source_analysis_id)
    mode = None
    try:
        proposal, mode = maintenance.propose(text, settings, force_sample=force_sample)
        tab = maintenance.check_proposal(proposal, settings)
    except maintenance.ProposalError as e:
        ledger.update_change_request(conn, rid, status="failed", reason=f"提案を捨てました：{e}",
                                     proposal_json=json.dumps({"mode": mode}, ensure_ascii=False))
        return rid
    except Exception as e:  # 呼び出しの失敗（通信・鍵など）
        ledger.update_change_request(conn, rid, status="failed", reason=f"提案を作れませんでした：{type(e).__name__}")
        raise ProposalCallError() from e
    record = {"mode": mode, "reply": proposal.get("reply"), "raw": proposal, "tab_checked": tab,
              **({"sample_text": maintenance.sample_text()} if mode == "sample" else {})}
    ledger.update_change_request(conn, rid, proposal_json=json.dumps(record, ensure_ascii=False),
                                 **({} if tab else {"status": "rejected", "reason": "決まった部品では表せない依頼でした"}))
    return rid


def after_analysis(analysis_id: str) -> None:
    """分析が終わった後：その分析の次の一手から、提案まで自動で作る（同じ分析から2回は作らない）。"""
    conn = ledger.connect(config.DB_PATH)
    try:
        run = ledger.get_analysis_run(conn, analysis_id)
        if not run or run["status"] != "done" or not run["report_json"]:
            return
        report = json.loads(run["report_json"])
        text = maintenance.draft_text(report.get("next_action"))
        if not text or ledger.change_request_for_analysis(conn, analysis_id):
            return
        propose(conn, AUTO_BY, text, analysis_id)
    except Exception:  # 裏の処理。提案が作れなくても、分析の報告はそのまま使える
        traceback.print_exc()
    finally:
        conn.close()


def start_after(analysis_id: str) -> None:
    threading.Thread(target=after_analysis, args=(analysis_id,), daemon=True).start()
