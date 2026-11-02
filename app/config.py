"""アプリ全体で使う設定。アプリの「今日」はここで1つだけ決める（docs/DESIGN.md §2）。"""

from __future__ import annotations

import os
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

# 店のマスタの初期値（見本データを作る時に入れる。あとは受付側の「店の設定」で変える）
DEFAULT_SLOTS = ("10:00", "11:00", "13:00", "14:00", "15:00", "16:00")
DEFAULT_CAPACITY = 2          # 時間帯ごとに受けられる台数（作業場が2つ）
DEFAULT_CLOSED_WEEKDAYS = (2,)  # 毎週水曜は休み（0=月 … 6=日）

DB_PATH = ROOT / "data" / "ledger.db"

# 分析に使えるモデル（効果の画面で選ぶ）。既定は Opus 5.5
MODELS = {
    "claude-opus-5-5": {"label": "Opus 5.5", "note": "じっくり調べる（1回 $1 前後）"},
    "claude-sonnet-5-5": {"label": "Sonnet 5.5", "note": "速め・安め"},
    "claude-haiku-5-5": {"label": "Haiku 5.5", "note": "いちばん速く安い（掘り下げは浅くなりやすい）"},
}
DEFAULT_MODEL = "claude-opus-5-5"

# 1回の分析（続きの質問を含む）で使ってよい額の上限。セント。環境変数 VL_BUDGET_CENTS で変えられる
BUDGET_CENTS = int(os.environ.get("VL_BUDGET_CENTS", "300"))


def now() -> datetime:
    """アプリの「今」：日付は「今日」に固定し、時刻だけ実際の時計を使う。"""
    return datetime.combine(TODAY, datetime.now().time().replace(microsecond=0))


def cohort_to() -> date:
    """集計の対象の終わり：施策期間の終わりと「今日」の早い方。"""
    return min(PERIOD_TO, TODAY)
