"""アプリ全体で使う設定。アプリの「今日」はここで1つだけ決める（docs/DESIGN.md §2）。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# アプリの「今日」。見本データもアプリもこの日付で数える（時刻では比べない）
TODAY = date(2026, 11, 7)

# 施策期間（秋の点検キャンペーン）。集計の対象は、この期間のうち「今日」までに始まった LP のセッション
PERIOD_FROM = date(2026, 10, 1)
PERIOD_TO = date(2026, 11, 15)

# 見本データのセッションを作る期間（デモの日の操作は、この上に乗る）
SAMPLE_FROM = date(2026, 10, 1)
SAMPLE_TO = date(2026, 10, 31)

STORE_ID = "S-EKI"

DB_PATH = ROOT / "data" / "ledger.db"


def now() -> datetime:
    """アプリの「今」：日付は「今日」に固定し、時刻だけ実際の時計を使う。"""
    return datetime.combine(TODAY, datetime.now().time().replace(microsecond=0))


def cohort_to() -> date:
    """集計の対象の終わり：施策期間の終わりと「今日」の早い方。"""
    return min(PERIOD_TO, TODAY)
