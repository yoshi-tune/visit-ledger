"""アプリ全体で使う設定。アプリの「今日」はここで1つだけ決める（docs/DESIGN.md §2）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# アプリの「今日」。見本データもアプリもこの日付で数える（時刻では比べない）
TODAY = date(2026, 11, 7)

# 施策期間（この間に始まった LP のセッションが集計の対象）
PERIOD_FROM = date(2026, 10, 1)
PERIOD_TO = date(2026, 10, 31)

STORE_ID = "S-EKI"

DB_PATH = ROOT / "data" / "ledger.db"
