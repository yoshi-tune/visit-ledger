"""分析エージェントに渡す書き出し（docs/DESIGN.md §7・§8）。

許可した列だけを出す（許可していない列は、表に足されても自動では出ない）。
予約番号とセッション番号は書き出すたびに仮の番号に置き換え、対応表は別に返す（外に出さない）。
"""

from __future__ import annotations

import csv
import io

# 表ごとに、外に出してよい列（この順で書き出す）
ALLOWED: dict[str, tuple[str, ...]] = {
    "sessions": ("session_id", "started_at", "campaign", "src", "store_id"),
    "events": ("session_id", "at", "name"),
    "reservations": (
        "reserve_no", "session_id", "campaign", "src", "store_id", "menu",
        "requested_for", "confirmed_for", "status", "created_at",
    ),
    "visits": ("reserve_no", "visited_at", "recorded_at"),
    "reservation_changes": ("reserve_no", "at", "from_status", "to_status", "confirmed_for"),
    "campaigns": ("campaign", "src", "store_id", "distributed", "started_on", "ended_on"),
    # クーポン1枚に1行。reserve_no は使った時に結んだ予約（予約なしの来店なら空）。番号（code）は出さない
    "coupons": ("session_id", "issued_at", "redeemed_at", "reserve_no"),
}

# どの表にあっても出さない列（許可の表を書き換えた時の安全柵）
FORBIDDEN = ("customer_name", "customer_phone", "handled_by", "submit_key", "updated_at", "code")


def build(snapshot: dict) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """(表名 → CSV の文字列, 仮の番号の対応表) を返す。"""
    for table, cols in ALLOWED.items():
        bad = set(cols) & set(FORBIDDEN)
        if bad:
            raise ValueError(f"{table} に出してはいけない列があります: {sorted(bad)}")

    session_map = {
        s["session_id"]: f"S{i:04d}"
        for i, s in enumerate(sorted(snapshot["sessions"], key=lambda s: (s["started_at"], s["session_id"])), 1)
    }
    reserve_map = {
        r["reserve_no"]: f"R{i:03d}"
        for i, r in enumerate(sorted(snapshot["reservations"], key=lambda r: (r["created_at"], r["reserve_no"])), 1)
    }

    def swap(row: dict) -> dict:
        out = dict(row)
        if "session_id" in out:
            out["session_id"] = session_map[out["session_id"]]
        if out.get("reserve_no"):
            out["reserve_no"] = reserve_map[out["reserve_no"]]
        return out

    files: dict[str, str] = {}
    for table, cols in ALLOWED.items():
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(cols)
        for row in snapshot[table]:
            row = swap(row)
            writer.writerow(["" if row[c] is None else row[c] for c in cols])
        files[f"{table}.csv"] = buf.getvalue()

    id_map = {
        "sessions": {v: k for k, v in session_map.items()},
        "reservations": {v: k for k, v in reserve_map.items()},
    }
    return files, id_map
