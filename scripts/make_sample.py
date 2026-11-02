"""見本の台帳を作る（docs/DESIGN.md §6）。

    uv run python scripts/make_sample.py               # 仕込みあり → data/ledger.db
    uv run python scripts/make_sample.py --no-plant    # 仕込みなし（でっち上げないかの確認用）

乱数の種と入力の並び順を固定しているので、誰が回しても同じ台帳になる。
来店の結果はさいころで決めず、(媒体 × 予約から確定日までの日数) のマスごとに件数の割合で割り当てる。

## 仕込み（明かしておく）

- 来店率は「予約を送った日から確定日までの日数」で変わる：3日以内 90%・4〜7日 80%・8日以上 60%
- チラシの予約は先の日に入りやすく、LINE の予約は近い日に入りやすい
- そのため媒体別に見るとチラシの来店率が低く見えるが、日数で分けると同じ日数の中では差が消える
- --no-plant では、どの日数でも来店率 82%（日数の割合は同じ）。媒体の差も日数の差も出ない
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ledger  # noqa: E402

SEED = 20261102
TODAY = date(2026, 11, 7)  # アプリの「今日」（DESIGN §2）
PERIOD_FROM, PERIOD_TO = date(2026, 10, 1), date(2026, 10, 31)
STORE_ID, STORE_NAME = "S-EKI", "駅前店"
CAMPAIGN = "autumn_check_202610"
STAFF = ("A", "B")

# 予約から確定日までの日数のマス：(最小, 最大)
BUCKETS = ((1, 3), (4, 7), (8, 14))
VISIT_RATE = {"plant": (0.90, 0.80, 0.60), "no_plant": (0.82, 0.82, 0.82)}

# 媒体ごとの量。buckets は予約の件数をマスごとに割ったもの（チラシは先の日に、LINE は近い日に寄る）
SOURCES = {
    "flyer": {"distributed": 3000, "sessions": 250, "tap_sessions": 70, "buckets": (13, 12, 25)},
    "line": {"distributed": 1200, "sessions": 600, "tap_sessions": 100, "buckets": (42, 21, 7)},
}
SRC_ORDER = ("flyer", "line")

# メニューの割合（どちらの媒体でも同じ。比べる軸を媒体だけにするため）
MENU_SHARE = (("オイル交換", 0.40), ("タイヤ交換", 0.35), ("秋の点検", 0.25))

N_REQUESTED = 2     # 店から未連絡のまま
N_TODAY = 3         # 確定日が「今日」（受付の一覧に出す）
N_DECLINED = 3
N_CANCELLED = 4
N_RESCHEDULED = 10
N_LATE_RECORD = 2   # 押し忘れて翌日に記録した来店
N_UNDO = 1          # 間違えて付けて取り消した来店


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def at_time(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute))


def bucket_of(lead_days: int) -> int:
    for i, (lo, hi) in enumerate(BUCKETS):
        if lo <= lead_days <= hi:
            return i
    raise ValueError(lead_days)


def day_weights(src: str) -> list[float]:
    days = (PERIOD_TO - PERIOD_FROM).days + 1
    if src == "flyer":  # 月初に配って、少しずつ減る
        return [math.exp(-d / 10) for d in range(days)]
    sends = (2, 16)  # LINE は 10/3 と 10/17 に配信。開かれるのは配信直後に集中
    return [sum(math.exp(-(d - s) / 1.5) for s in sends if d >= s) + 0.02 for d in range(days)]


def quota(total: int, shares: tuple[tuple[str, float], ...]) -> list[str]:
    """割合どおりの並びを作る（端数は先頭から）。"""
    counts = [int(total * s) for _, s in shares]
    for i in range(total - sum(counts)):
        counts[i % len(counts)] += 1
    return [name for (name, _), c in zip(shares, counts) for _ in range(c)]


def build(out: Path, plant: bool) -> None:
    rng = random.Random(SEED)
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    conn = ledger.connect(out)
    ledger.init_schema(conn)

    ledger.add_store(conn, STORE_ID, STORE_NAME)
    for src in SRC_ORDER:
        ledger.add_campaign(
            conn, CAMPAIGN, src, STORE_ID, SOURCES[src]["distributed"],
            PERIOD_FROM.isoformat(), PERIOD_TO.isoformat(),
        )

    # ---- セッション ---------------------------------------------------------
    sessions: list[dict] = []
    for src in SRC_ORDER:
        weights = day_weights(src)
        for _ in range(SOURCES[src]["sessions"]):
            d = PERIOD_FROM + timedelta(days=rng.choices(range(len(weights)), weights)[0])
            start = at_time(d, rng.randint(8, 21), rng.randint(0, 59))
            sessions.append({"src": src, "campaign": CAMPAIGN, "start": start})
    # 施策不明（古いチラシの URL など）
    for _ in range(2):
        d = PERIOD_FROM + timedelta(days=rng.randint(5, 25))
        sessions.append({"src": "flyer", "campaign": "oldflyer_202609",
                         "start": at_time(d, rng.randint(9, 20), rng.randint(0, 59))})
    sessions.sort(key=lambda s: (s["start"], s["src"], s["campaign"]))
    used_ids: set[str] = set()
    for s in sessions:
        sid = f"{rng.getrandbits(48):012x}"
        while sid in used_ids:
            sid = f"{rng.getrandbits(48):012x}"
        used_ids.add(sid)
        s["id"] = sid
        s["reservations"] = 0

    # ---- 予約の下書き（媒体 × 日数のマスの件数どおり） ------------------------
    drafts: list[dict] = []
    for src in SRC_ORDER:
        n_total = sum(SOURCES[src]["buckets"])
        menus = quota(n_total, MENU_SHARE)
        rng.shuffle(menus)
        specs = [b for b, n in enumerate(SOURCES[src]["buckets"]) for _ in range(n)]
        pool = [s for s in sessions if s["src"] == src and s["campaign"] == CAMPAIGN]
        # 長い日数から先に割り当てる（確定日が「今日」より前に収まるセッションを選ぶため）
        for b in sorted(specs, reverse=True):
            lead = rng.randint(*BUCKETS[b])
            free = [s for s in pool if s["reservations"] == 0]
            if b == len(BUCKETS) - 1:
                free = [s for s in free if s["start"].date() + timedelta(days=lead) < TODAY]
            s = rng.choice(free)
            s["reservations"] += 1
            drafts.append({"src": src, "session": s, "lead": lead, "menu": menus.pop()})
    # 1つのセッションから2台分の予約
    line_short = [d for d in drafts if d["src"] == "line" and bucket_of(d["lead"]) == 0]
    first, second = line_short[0], line_short[1]
    second["session"]["reservations"] -= 1
    second["session"] = first["session"]
    second["same_session_offset"] = 8
    first["session"]["reservations"] += 1
    # 施策不明のセッションからの予約
    unknown = [s for s in sessions if s["campaign"] != CAMPAIGN][0]
    unknown["reservations"] = 1
    drafts.append({"src": "unknown", "session": unknown, "lead": 2, "menu": "オイル交換"})

    for d in drafts:
        tap = d["session"]["start"] + timedelta(minutes=rng.randint(1, 5))
        d["tap"] = tap
        d["created"] = tap + timedelta(minutes=rng.randint(2, 6) + d.get("same_session_offset", 0))
        d["confirmed_for"] = at_time(d["created"].date() + timedelta(days=d["lead"]),
                                     rng.randint(9, 16))
        d["kind"] = "confirmed"
    drafts.sort(key=lambda d: (d["created"], d["src"], d["session"]["id"]))

    # ---- 例外の割り当て -------------------------------------------------------
    plain = [d for d in drafts if d["src"] != "unknown"]
    latest = sorted(plain, key=lambda d: d["created"], reverse=True)
    for d in [x for x in latest if bucket_of(x["lead"]) == 0][:N_REQUESTED]:
        d["kind"] = "requested"
    for d in [x for x in latest if x["kind"] == "confirmed"
              and 1 <= (TODAY - x["created"].date()).days <= 14][:N_TODAY]:
        d["kind"] = "today"
        d["confirmed_for"] = at_time(TODAY, rng.choice((10, 13, 15)))
    rest = [d for d in plain if d["kind"] == "confirmed" and bucket_of(d["lead"]) < 2]
    picked = rng.sample(rest, N_DECLINED + N_CANCELLED)
    for d in picked[:N_DECLINED]:
        d["kind"] = "declined"
    for d in picked[N_DECLINED:]:
        d["kind"] = "cancelled"
    confirmed = [d for d in drafts if d["kind"] in ("confirmed", "today")]
    for d in rng.sample(confirmed, N_RESCHEDULED):
        d["rescheduled"] = True

    # 希望日時：日時を変えた予約は、確定日時とずらす（送った日より後に収める）
    for d in drafts:
        req = d["confirmed_for"]
        if d.get("rescheduled"):
            shift = rng.choice((-2, -1, 1, 2))
            cand = req + timedelta(days=shift)
            req = cand if cand.date() > d["created"].date() else req + timedelta(days=abs(shift))
        d["requested_for"] = req

    # 来店：マスごとに件数の割合で割り当てる（確定日が「今日」より前のものだけが対象）
    rates = VISIT_RATE["plant" if plant else "no_plant"]
    for src in (*SRC_ORDER, "unknown"):
        for b in range(len(BUCKETS)):
            cell = [d for d in drafts if d["src"] == src and d["kind"] == "confirmed"
                    and bucket_of(d["lead"]) == b and d["confirmed_for"].date() < TODAY]
            n_visit = round(len(cell) * rates[b]) if src != "unknown" else len(cell)
            for d in rng.sample(cell, n_visit):
                d["visited"] = True
    visited = [d for d in drafts if d.get("visited")]
    for d in rng.sample(visited, N_LATE_RECORD):
        d["late_record"] = True
    not_recorded = [d for d in drafts if d["kind"] == "confirmed" and not d.get("visited")
                    and d["confirmed_for"].date() < TODAY]
    for d in rng.sample(not_recorded, N_UNDO):
        d["undo"] = True

    # ---- 台帳に書く（保存の層を通して、出来事の順に再生する） -----------------
    tapped = {d["session"]["id"] for d in drafts}
    for src in SRC_ORDER:
        extra = SOURCES[src]["tap_sessions"] - len(
            {d["session"]["id"] for d in drafts if d["src"] == src})
        candidates = [s for s in sessions if s["src"] == src and s["campaign"] == CAMPAIGN
                      and s["id"] not in tapped]
        tapped |= {s["id"] for s in rng.sample(candidates, extra)}
    tapped.add(next(s["id"] for s in sessions if s["campaign"] != CAMPAIGN and s["reservations"] == 0))
    first_tap: dict[str, datetime] = {}
    for d in drafts:
        sid = d["session"]["id"]
        first_tap[sid] = min(first_tap.get(sid, d["tap"]), d["tap"])

    for s in sessions:
        ledger.create_session(conn, s["id"], fmt(s["start"]), s["campaign"], s["src"], STORE_ID)
        ledger.add_event(conn, s["id"], fmt(s["start"]), "lp_view")
        if rng.random() < 0.08:  # 読み込み直し
            ledger.add_event(conn, s["id"], fmt(s["start"] + timedelta(minutes=rng.randint(1, 9))),
                             "lp_view")
        if s["id"] in tapped:
            tap = first_tap.get(s["id"], s["start"] + timedelta(minutes=rng.randint(1, 5)))
            ledger.add_event(conn, s["id"], fmt(tap), "reserve_tap")
            if rng.random() < 0.06:  # 連打
                ledger.add_event(conn, s["id"], fmt(tap + timedelta(seconds=2)), "reserve_tap")

    used_nos: set[str] = set()
    for i, d in enumerate(drafts, start=1):
        no = f"R{rng.randint(100000, 999999)}"
        while no in used_nos:
            no = f"R{rng.randint(100000, 999999)}"
        used_nos.add(no)
        key = f"{rng.getrandbits(64):016x}"
        staff = rng.choice(STAFF)
        created = d["created"]
        args = dict(
            reserve_no=no, submit_key=key, session_id=d["session"]["id"], menu=d["menu"],
            requested_for=fmt(d["requested_for"]), created_at=fmt(created),
            customer_name=f"見本 {i:03d}", customer_phone=f"090-0000-{i:04d}",
        )
        ledger.create_reservation(conn, **args)
        if i % 17 == 0:  # 2重送信：同じ送信キーなら同じ予約番号が返り、行は増えない
            assert ledger.create_reservation(conn, **args) == no
        if d["kind"] == "requested":
            continue

        # 店からの連絡：送った数時間後〜翌日。確定日の朝と「今日」の朝より前に収める
        limit = min(at_time(d["confirmed_for"].date(), 8), at_time(TODAY, 8))
        contact = min(created + timedelta(hours=rng.randint(1, 20)), limit)
        contact = max(contact, created + timedelta(minutes=10))
        if d["kind"] == "declined":
            ledger.decline(conn, no, fmt(contact), staff)
            continue
        if d.get("rescheduled"):
            ledger.confirm(conn, no, fmt(d["requested_for"]), fmt(contact), staff)
            contact = min(contact + timedelta(hours=rng.randint(2, 30)), limit)
            contact = max(contact, created + timedelta(minutes=20))
        ledger.confirm(conn, no, fmt(d["confirmed_for"]), fmt(contact), staff)
        if d["kind"] == "cancelled":
            ledger.cancel(conn, no, fmt(min(contact + timedelta(hours=rng.randint(3, 48)), limit)),
                          staff)
            continue
        if d.get("visited"):
            visited_at = d["confirmed_for"] + timedelta(minutes=rng.randint(-10, 20))
            recorded = (at_time(visited_at.date() + timedelta(days=1), 9, 10)
                        if d.get("late_record") else visited_at)
            ledger.record_visit(conn, no, fmt(visited_at), fmt(recorded), staff)
        elif d.get("undo"):
            mistaken = d["confirmed_for"]
            ledger.record_visit(conn, no, fmt(mistaken), fmt(mistaken), staff)
            ledger.cancel_visit(conn, no, fmt(mistaken + timedelta(minutes=3)), staff)

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "ledger.db")
    parser.add_argument("--no-plant", action="store_true", help="仕込みなしの台帳を作る")
    args = parser.parse_args()
    build(args.out, plant=not args.no_plant)
    print(f"作成しました: {args.out}（仕込み{'なし' if args.no_plant else 'あり'}）")


if __name__ == "__main__":
    main()
