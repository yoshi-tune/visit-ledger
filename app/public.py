"""公開版（審査用の公開 URL）だけで効く守り。環境変数 VL_PUBLIC=1 の時だけ使う。手元の起動では何もしない。

- ログイン：テスト用の ID とパスワードを環境変数から読み、署名した合札（クッキー）で入った人を見分ける
- 開けてよい道：ログインしていない人は、LP・予約・クーポン（お客様の側）と、それらが使う API だけ
- 全体の上限：台帳に残った分析・提案の費用の目安の合計が上限に近ければ、新しく Claude を呼ばない
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import threading
import time
from collections import deque

from app import config, ledger

PUBLIC = os.environ.get("VL_PUBLIC") == "1"
COOKIE = "vl_login"
LOGIN_DAYS = 7

# 公開版で Claude に使ってよい額の合計（セント）。Anthropic Console のワークスペースの上限とは別の、アプリの側の歯止め
TOTAL_BUDGET_CENTS = int(os.environ.get("VL_TOTAL_BUDGET_CENTS", "2000"))
PROPOSAL_CENTS = 3  # タブの提案1回の目安（Sonnet で1回呼ぶ）
QUESTION_CENTS = 100  # 答えている途中の続きの質問1つで見込む額（答えた後の額は分析の費用に入る）

# 上限の確かめと、分析・質問・提案の記録を続けて行うための錠（プロセスは1つなので、これで同時に押されてもすり抜けない）
LOCK = threading.Lock()

# ログインの失敗：10分のうちに20回を超えたら、しばらく受け付けない（総当たりを止める）
_FAILURES: deque[float] = deque()
_FAIL_WINDOW = 600
_FAIL_MAX = 20


def _secret() -> bytes:
    s = os.environ.get("VL_SESSION_SECRET", "")
    if PUBLIC and len(s) < 32:
        raise RuntimeError("公開版では VL_SESSION_SECRET（32文字以上）を設定してください")
    return s.encode()


def _prune() -> None:
    while _FAILURES and _FAILURES[0] < time.time() - _FAIL_WINDOW:
        _FAILURES.popleft()


def too_many_failures() -> bool:
    _prune()
    return len(_FAILURES) >= _FAIL_MAX


def record_failure() -> None:
    _prune()
    _FAILURES.append(time.time())


def check_password(user: str, password: str) -> bool:
    want_user = os.environ.get("VL_TEST_USER", "")
    want_pass = os.environ.get("VL_TEST_PASS", "")
    if not want_user or not want_pass:
        return False
    ok_user = hmac.compare_digest(user.encode(), want_user.encode())
    ok_pass = hmac.compare_digest(password.encode(), want_pass.encode())
    return ok_user and ok_pass


def make_token(user: str) -> str:
    exp = str(int(time.time()) + LOGIN_DAYS * 86400)
    body = f"{user}|{exp}"
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


def valid_token(token: str | None) -> bool:
    if not token or token.count("|") != 2:
        return False
    user, exp, sig = token.split("|")
    want = hmac.new(_secret(), f"{user}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig.encode(), want.encode()):  # 文字ではなくバイトで比べる（日本語などが入っても落ちない）
        return False
    return exp.isdigit() and int(exp) > time.time() and user == os.environ.get("VL_TEST_USER", "")


# ログインしていなくても開ける道（LP・予約・お客様のクーポンと、それらが使う API）。(メソッド, 正規表現)
_OPEN = [
    ("GET", r"/login"), ("POST", r"/api/login"), ("GET", r"/logout"),
    ("GET", r"/static/.+"),
    ("GET", r"/lp/[^/]+"), ("GET", r"/reserve"), ("GET", r"/reserve/done/[^/]+"), ("GET", r"/coupon/[^/]+"),
    ("GET", r"/api/config"), ("GET", r"/api/availability"),
    ("POST", r"/api/sessions"), ("POST", r"/api/events"), ("POST", r"/api/coupons"),
    ("GET", r"/api/coupons/[^/]+/public"), ("GET", r"/api/coupons/[^/]+/qr\.svg"),
    ("POST", r"/api/reservations"), ("GET", r"/api/reservations/[^/]+/public"), ("GET", r"/api/campaigns/[^/]+/public"),
    ("GET", r"/about"),  # Render の死活の確かめに使う（台帳の中身は出さない画面）
]
_OPEN_RE = [(m, re.compile(p + r"/?")) for m, p in _OPEN]


def is_open(method: str, path: str) -> bool:
    method = "GET" if method == "HEAD" else method
    return any(m == method and r.fullmatch(path) for m, r in _OPEN_RE)


# ---- 全体の上限 -------------------------------------------------------------------

def committed_cents(conn) -> tuple[int, int]:
    """(使った額と、動いている分析に見込む額の合計, 動いている分析の数)。見本の報告は数えない。
    費用の記録が無い本物の分析は、1回の上限（VL_BUDGET_CENTS）を使ったとみなす（少なく数えないため）。"""
    return ledger.public_spend(conn, config.BUDGET_CENTS, PROPOSAL_CENTS, QUESTION_CENTS)


def refuse_analysis(conn) -> str | None:
    """新しい分析を本物で回してはいけない理由（よければ None）。"""
    if not PUBLIC:
        return None
    spent, running = committed_cents(conn)
    if running:
        return "ほかの人の分析が動いているので、今回は見本の報告を出しました（公開版では、本物の分析は一度に1つまでです）"
    if spent + config.BUDGET_CENTS > TOTAL_BUDGET_CENTS:
        return "公開版で Claude に使う額の上限に達したので、見本の報告を出しました"
    return None


def refuse_question(conn) -> str | None:
    if PUBLIC and committed_cents(conn)[0] + QUESTION_CENTS > TOTAL_BUDGET_CENTS:
        return "公開版で Claude に使う額の上限に達したので、これ以上は質問できません。"
    return None


def refuse_proposal(conn) -> bool:
    return PUBLIC and committed_cents(conn)[0] + PROPOSAL_CENTS > TOTAL_BUDGET_CENTS


if PUBLIC:
    _secret()  # 署名の鍵が足りなければ、起動の時に止める（画面ごとに 500 になって気づけない、を防ぐ）
