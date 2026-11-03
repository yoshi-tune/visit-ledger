"""来店までの道のり（漏斗）と予約の内訳の集計（docs/DESIGN.md §3）。

台帳の写し（ledger.snapshot の戻り値）を受け取り、数え方の決まりを当てるだけ。SQL は書かない。
比べるのはすべて日付の単位（アプリの「今日」と確定日）。
"""

from __future__ import annotations

import json

from datetime import date

from app.ledger import UNKNOWN

NOTE = ("ネット予約で追えた分だけです。電話だけの予約・飛び込みの来店は入っていません"
        "（LP のクーポンを店で使った予約なしの来店だけは、クーポンの欄に別に数えます）")

STAGES = (
    ("lp_sessions", "LP を開いたセッション"),
    ("tap_sessions", "予約ボタンを押したセッション"),
    ("reserved_sessions", "予約を送ったセッション"),
)


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def reservation_state(reservation: dict, visited: bool, today: date) -> str:
    """予約1件を内訳の欄に振り分ける。"""
    status = reservation["status"]
    if status == "cancelled":
        return status
    if visited:
        return "visited"
    if _day(reservation["confirmed_for"]) >= today:
        return "waiting"
    return "unrecorded"


def visit_rate(visited: int, unrecorded: int) -> float | None:
    """来店 ÷（来店 ＋ 来店未記録）。分母が 0 なら None（算出不可）。"""
    denominator = visited + unrecorded
    return visited / denominator if denominator else None


def compute(snapshot: dict, today: date, period_from: date, period_to: date) -> dict:
    visited_nos = {v["reserve_no"] for v in snapshot["visits"]}
    session_src = {s["session_id"]: (s["campaign"], s["src"]) for s in snapshot["sessions"]}

    def empty_breakdown() -> dict:
        return {k: 0 for k in ("total", "cancelled", "waiting", "visited", "unrecorded")}

    groups: dict[tuple[str, str], dict] = {}
    for c in snapshot["campaigns"]:
        key = (c["campaign"], c["src"])
        groups[key] = {
            "campaign": c["campaign"],
            "src": c["src"],
            "distributed": c["distributed"],  # 参考の値。分母にしない
            "lp": set(), "tap": set(), "reserved": set(),
            "breakdown": empty_breakdown(),
            "coupons": {"shown": 0, "used": 0, "used_with_reservation": 0, "used_without_reservation": 0},
        }

    for e in snapshot["events"]:
        key = session_src.get(e["session_id"])
        if key is None:
            continue
        groups[key]["lp" if e["name"] == "lp_view" else "tap"].add(e["session_id"])

    for r in snapshot["reservations"]:
        g = groups[(r["campaign"], r["src"])]
        g["reserved"].add(r["session_id"])
        b = g["breakdown"]
        b["total"] += 1
        b[reservation_state(r, r["reserve_no"] in visited_nos, today)] += 1

    # クーポン：LP で出した数と、店で使った数（予約あり／予約なし）。来店率には入れない
    for c in snapshot.get("coupons", []):
        key = session_src.get(c["session_id"])
        if key is None:
            continue
        k = groups[key]["coupons"]
        k["shown"] += 1
        if c["redeemed_at"]:
            k["used"] += 1
            k["used_with_reservation" if c["reserve_no"] else "used_without_reservation"] += 1

    campaigns, unknown = [], None
    for key in sorted(groups):
        g = groups[key]
        counts = {
            "lp_sessions": len(g["lp"]),
            "tap_sessions": len(g["tap"]),
            "reserved_sessions": len(g["reserved"]),
        }
        b = g["breakdown"]
        item = {
            "campaign": g["campaign"],
            "src": g["src"],
            "distributed": g["distributed"],
            "stages": _stages(counts),
            "reservations": b,
            "visit_rate": visit_rate(b["visited"], b["unrecorded"]),
            "coupons": g["coupons"],
        }
        if key[0] == UNKNOWN:
            unknown = {"lp_sessions": counts["lp_sessions"], "reservations": b["total"]}
        else:
            campaigns.append(item)

    return {
        "period": {"from": period_from.isoformat(), "to": period_to.isoformat()},
        "as_of": today.isoformat(),
        "note": NOTE,
        "campaigns": campaigns,
        "unknown": unknown or {"lp_sessions": 0, "reservations": 0},
        # 前日のお知らせ：結果ごとの記録の数・記録のある予約の数と、受付に足したタブ（条件・あった期間）。
        # 来店率は分析担当が CSV から数える
        "reminders": {
            **{r: sum(1 for m in snapshot.get("reminders", []) if m["result"] == r) for r in ("sent", "replied", "rescheduled")},
            "reservations": len({m["reserve_no"] for m in snapshot.get("reminders", [])}),
            "tabs": desk_tab_history(snapshot.get("settings_versions", [])),
        },
    }


def _stages(counts: dict[str, int]) -> list[dict]:
    """段ごとの数と、前の段からの離脱数・離脱率。"""
    out, previous = [], None
    for key, label in STAGES:
        n = counts[key]
        stage = {"key": key, "label": label, "count": n, "drop": None, "drop_rate": None}
        if previous is not None:
            stage["drop"] = previous - n
            stage["drop_rate"] = (previous - n) / previous if previous else None
        out.append(stage)
        previous = n
    return out


def desk_tab_history(versions: list[dict]) -> list[dict]:
    """受付に足したタブが、いつからいつまであったか（設定の版から作る）。until が None なら今もある。"""
    out: dict[str, dict] = {}
    for v in versions:
        ids = set()
        for t in json.loads(v["settings_json"]).get("desk_tabs", []):
            ids.add(t["id"])
            if t["id"] not in out or out[t["id"]]["until"] is not None:
                out[t["id"]] = {"id": t["id"], "title": t["title"], "conditions": t["conditions"],
                                "since": v["created_at"], "until": None}
        for tid, t in out.items():
            if tid not in ids and t["until"] is None:
                t["until"] = v["created_at"]
    return list(out.values())

