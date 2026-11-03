"""台帳の保存の層。SQL と状態の移り変わりの決まりは、このファイルにだけ書く（docs/DESIGN.md §3・§5）。

日時はすべて呼び出し側から渡す（この層では「今」を読まない）。形式は "YYYY-MM-DDTHH:MM:SS"（店の現地時刻）。

予約は、お客様が送った時点で確定する（11/2 に「希望の受付＋店から電話で確定」から切り替えた）。
空き枠（時間帯ごとの台数）と休み（曜日・日付）は店のマスタとして台帳に持ち、予約を作る時にここで確かめる。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

MENUS = ("オイル交換", "タイヤ交換", "秋の点検")
EVENT_NAMES = ("lp_view", "reserve_tap")
UNKNOWN = "unknown"
WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")  # date.weekday() の順

# 状態ごとに、次に移れる状態（DESIGN §3）
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "confirmed": ("confirmed", "visited", "cancelled"),
    "visited": ("confirmed",),
    "cancelled": (),
}
# 枠を使っている状態（取消は枠を空ける）
HOLDING = ("confirmed", "visited")

SCHEMA = """
CREATE TABLE stores (
    store_id TEXT PRIMARY KEY,
    name     TEXT NOT NULL
);

CREATE TABLE campaigns (
    campaign    TEXT NOT NULL,
    src         TEXT NOT NULL,
    store_id    TEXT NOT NULL REFERENCES stores(store_id),
    distributed INTEGER,
    started_on  TEXT,
    ended_on    TEXT,
    PRIMARY KEY (campaign, src, store_id)
);

-- 店のマスタ：時間帯ごとに受けられる台数
CREATE TABLE slot_rules (
    store_id TEXT NOT NULL REFERENCES stores(store_id),
    slot     TEXT NOT NULL CHECK (length(slot) = 5),
    capacity INTEGER NOT NULL CHECK (capacity >= 0),
    PRIMARY KEY (store_id, slot)
);

-- 店のマスタ：休みの曜日（0=月 … 6=日）と、休みの日
CREATE TABLE closed_weekdays (
    store_id TEXT NOT NULL REFERENCES stores(store_id),
    weekday  INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    PRIMARY KEY (store_id, weekday)
);

CREATE TABLE closed_dates (
    store_id TEXT NOT NULL REFERENCES stores(store_id),
    day      TEXT NOT NULL,
    note     TEXT,
    PRIMARY KEY (store_id, day)
);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    campaign   TEXT NOT NULL,
    src        TEXT NOT NULL,
    store_id   TEXT NOT NULL,
    FOREIGN KEY (campaign, src, store_id) REFERENCES campaigns(campaign, src, store_id)
);

CREATE TABLE events (
    id         INTEGER PRIMARY KEY,
    at         TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    name       TEXT NOT NULL CHECK (name IN ('lp_view', 'reserve_tap'))
);

CREATE TABLE reservations (
    reserve_no     TEXT PRIMARY KEY,
    submit_key     TEXT NOT NULL UNIQUE,
    session_id     TEXT NOT NULL REFERENCES sessions(session_id),
    campaign       TEXT NOT NULL,
    src            TEXT NOT NULL,
    store_id       TEXT NOT NULL,
    menu           TEXT NOT NULL,
    requested_for  TEXT NOT NULL,
    confirmed_for  TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('confirmed', 'visited', 'cancelled')),
    handled_by     TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    customer_name  TEXT NOT NULL,
    customer_phone TEXT NOT NULL,
    FOREIGN KEY (campaign, src, store_id) REFERENCES campaigns(campaign, src, store_id)
);

CREATE TABLE reservation_changes (
    id            INTEGER PRIMARY KEY,
    reserve_no    TEXT NOT NULL REFERENCES reservations(reserve_no),
    at            TEXT NOT NULL,
    from_status   TEXT,
    to_status     TEXT NOT NULL,
    confirmed_for TEXT,
    handled_by    TEXT
);

CREATE TABLE visits (
    reserve_no  TEXT PRIMARY KEY REFERENCES reservations(reserve_no),
    visited_at  TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE analysis_runs (
    analysis_id  TEXT PRIMARY KEY,
    as_of        TEXT NOT NULL,
    status       TEXT NOT NULL,
    export_csv   TEXT,
    id_map_json  TEXT,
    funnel_json  TEXT,
    tool_log     TEXT,
    report_json  TEXT,
    model        TEXT,
    session_id   TEXT,
    cost_cents   INTEGER,
    previous_json TEXT
);
"""

# 分析の続きの質問（壁打ち）。前の形の台帳にも足せるよう IF NOT EXISTS にする
_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS analysis_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id  TEXT NOT NULL REFERENCES analysis_runs(analysis_id),
    at           TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    status       TEXT NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
    text         TEXT,
    tool_log     TEXT
);
"""
SCHEMA += _MESSAGES_TABLE

# クーポン：LP で「クーポン」を押したセッションに1つ出す（番号は無作為で、何も表さない）。
# 店で使った時に1回だけ記録する。そのセッションに予約があれば予約番号を結ぶ（無ければ予約なしの来店）。
# 前の形の台帳にも足せるよう IF NOT EXISTS にする
_COUPON_TABLES = """
CREATE TABLE IF NOT EXISTS coupons (
    code       TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE REFERENCES sessions(session_id),
    issued_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coupon_redemptions (
    code        TEXT PRIMARY KEY REFERENCES coupons(code),
    redeemed_at TEXT NOT NULL,
    reserve_no  TEXT REFERENCES reservations(reserve_no),
    handled_by  TEXT
);

-- 間違えて押した「使った」を取り消した記録（取り消した利用の中身と、誰がいつ取り消したか）
CREATE TABLE IF NOT EXISTS coupon_undos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL REFERENCES coupons(code),
    redeemed_at TEXT NOT NULL,
    reserve_no  TEXT,
    handled_by  TEXT,
    undone_at   TEXT NOT NULL,
    undone_by   TEXT NOT NULL
);
"""
SCHEMA += _COUPON_TABLES

# 分析担当の改善（指示文の直しの案・物差しの結果・残したか戻したか・本番に使ったか）。前の形の台帳にも足せるよう IF NOT EXISTS
_IMPROVEMENT_TABLE = """
CREATE TABLE IF NOT EXISTS improvements (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at       TEXT NOT NULL,
    iteration        INTEGER NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
    decision         TEXT CHECK (decision IN ('kept', 'reverted', 'rejected')),
    reason           TEXT,
    base_system      TEXT NOT NULL,
    candidate_system TEXT,
    proposal_json    TEXT,
    eval_base_json   TEXT,
    eval_cand_json   TEXT,
    applied_at       TEXT
);
"""
SCHEMA += _IMPROVEMENT_TABLE

# ナットクに頼むメンテナンス（docs/MAINTENANCE.md 段階 A）：受付のタブの設定の版・頼んだ記録・お知らせの記録。
# 設定は版ごとに丸ごと残す（取り消しは、前の版の中身で新しい版を作る）。お知らせの記録は、タブを外しても消さない
_MAINTENANCE_TABLES = """
CREATE TABLE IF NOT EXISTS settings_versions (
    version           INTEGER PRIMARY KEY,
    created_at        TEXT NOT NULL,
    settings_json     TEXT NOT NULL,
    change_request_id INTEGER,
    note              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_requests (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at         TEXT NOT NULL,
    requested_by       TEXT,
    text               TEXT NOT NULL,
    source_analysis_id TEXT,
    proposal_json      TEXT,
    status             TEXT NOT NULL CHECK (status IN ('proposed', 'applied', 'rejected', 'reverted', 'failed')),
    reason             TEXT,
    applied_version    INTEGER,
    applied_by         TEXT,
    applied_at         TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reserve_no  TEXT NOT NULL REFERENCES reservations(reserve_no),
    at          TEXT NOT NULL,
    result      TEXT NOT NULL CHECK (result IN ('sent', 'replied', 'rescheduled')),
    handled_by  TEXT,
    desk_tab_id TEXT
);

-- 間違えて押したお知らせの記録を取り消した記録（取り消した記録の中身と、誰がいつ取り消したか）
CREATE TABLE IF NOT EXISTS reminder_undos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id INTEGER NOT NULL,
    reserve_no  TEXT NOT NULL,
    at          TEXT NOT NULL,
    result      TEXT NOT NULL,
    handled_by  TEXT,
    desk_tab_id TEXT,
    undone_at   TEXT NOT NULL,
    undone_by   TEXT NOT NULL
);
"""
SCHEMA += _MAINTENANCE_TABLES


class LedgerError(Exception):
    """台帳の決まりに合わない操作（存在しない予約、許されない状態の移り変わり、満席など）。"""


def connect(path: str | Path) -> sqlite3.Connection:
    # 接続はリクエストごとに1つ作って閉じる。FastAPI は作る・閉じるを別のスレッドで行うことがあるので許可する
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def upgrade_schema(conn: sqlite3.Connection) -> None:
    """前の形で作った台帳に、分析のモデル・セッション・前回の分析の列と、分析の続きの質問の表を足す（中身は消さない）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(analysis_runs)")}
    with conn:
        for col, kind in (("model", "TEXT"), ("session_id", "TEXT"), ("cost_cents", "INTEGER"),
                          ("previous_json", "TEXT")):
            if col not in cols:
                conn.execute(f"ALTER TABLE analysis_runs ADD COLUMN {col} {kind}")
        conn.execute(_MESSAGES_TABLE)
        conn.executescript(_COUPON_TABLES)
        conn.executescript(_IMPROVEMENT_TABLE)
        conn.executescript(_MAINTENANCE_TABLES)


# ---- 店と施策 -------------------------------------------------------------

def add_store(conn: sqlite3.Connection, store_id: str, name: str) -> None:
    with conn:
        conn.execute("INSERT INTO stores (store_id, name) VALUES (?, ?)", (store_id, name))
        # 施策不明の予約でも参照が切れないよう、店ごとに unknown の行を置く
        conn.execute(
            "INSERT INTO campaigns (campaign, src, store_id) VALUES (?, ?, ?)",
            (UNKNOWN, UNKNOWN, store_id),
        )


def add_campaign(
    conn: sqlite3.Connection,
    campaign: str,
    src: str,
    store_id: str,
    distributed: int | None,
    started_on: str,
    ended_on: str,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO campaigns (campaign, src, store_id, distributed, started_on, ended_on)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (campaign, src, store_id, distributed, started_on, ended_on),
        )


# ---- 店のマスタ（空き枠と休み） ---------------------------------------------

def get_master(conn: sqlite3.Connection, store_id: str) -> dict:
    slots = _rows(
        conn, "SELECT slot, capacity FROM slot_rules WHERE store_id = ? ORDER BY slot", (store_id,)
    )
    weekdays = [r["weekday"] for r in _rows(
        conn, "SELECT weekday FROM closed_weekdays WHERE store_id = ? ORDER BY weekday", (store_id,)
    )]
    dates = _rows(
        conn, "SELECT day, note FROM closed_dates WHERE store_id = ? ORDER BY day", (store_id,)
    )
    return {"slots": slots, "closed_weekdays": weekdays, "closed_dates": dates}


def set_master(conn: sqlite3.Connection, store_id: str, slots: list[dict],
               closed_weekdays: list[int], closed_dates: list[dict]) -> None:
    """マスタを丸ごと置き換える。すでに入っている予約は動かさない（満席を超えても消さない）。"""
    seen = set()
    for s in slots:
        slot = s["slot"]
        if len(slot) != 5 or slot[2] != ":" or not (slot[:2] + slot[3:]).isdigit():
            raise LedgerError(f"時間帯の形が読めません: {slot}")
        if slot in seen:
            raise LedgerError(f"同じ時間帯が2つあります: {slot}")
        seen.add(slot)
        if int(s["capacity"]) < 0:
            raise LedgerError("台数は0以上にしてください")
    for w in closed_weekdays:
        if not 0 <= int(w) <= 6:
            raise LedgerError(f"曜日が読めません: {w}")
    for d in closed_dates:
        date.fromisoformat(d["day"])
    with conn:
        conn.execute("DELETE FROM slot_rules WHERE store_id = ?", (store_id,))
        conn.execute("DELETE FROM closed_weekdays WHERE store_id = ?", (store_id,))
        conn.execute("DELETE FROM closed_dates WHERE store_id = ?", (store_id,))
        conn.executemany(
            "INSERT INTO slot_rules (store_id, slot, capacity) VALUES (?, ?, ?)",
            [(store_id, s["slot"], int(s["capacity"])) for s in slots],
        )
        conn.executemany(
            "INSERT INTO closed_weekdays (store_id, weekday) VALUES (?, ?)",
            [(store_id, int(w)) for w in sorted(set(closed_weekdays))],
        )
        conn.executemany(
            "INSERT INTO closed_dates (store_id, day, note) VALUES (?, ?, ?)",
            [(store_id, d["day"], d.get("note") or None) for d in closed_dates],
        )


def availability(conn: sqlite3.Connection, store_id: str, day_from: str, day_to: str) -> list[dict]:
    """日ごと・時間帯ごとの空き。休みの日は closed=True で枠を出さない。"""
    master = get_master(conn, store_id)
    closed_days = {d["day"] for d in master["closed_dates"]}
    booked: dict[str, int] = {}
    for r in _rows(
        conn,
        "SELECT substr(confirmed_for, 1, 16) AS at, COUNT(*) AS n FROM reservations"
        f" WHERE store_id = ? AND status IN ({_q(HOLDING)}) AND date(confirmed_for) BETWEEN ? AND ?"
        " GROUP BY substr(confirmed_for, 1, 16)",
        (store_id, *HOLDING, day_from, day_to),
    ):
        booked[r["at"]] = r["n"]
    out = []
    d, end = date.fromisoformat(day_from), date.fromisoformat(day_to)
    while d <= end:
        iso = d.isoformat()
        closed = iso in closed_days or d.weekday() in master["closed_weekdays"]
        slots = [] if closed else [
            {"slot": s["slot"], "capacity": s["capacity"],
             "booked": booked.get(f"{iso}T{s['slot']}", 0),
             "left": max(0, s["capacity"] - booked.get(f"{iso}T{s['slot']}", 0))}
            for s in master["slots"]
        ]
        out.append({"day": iso, "closed": closed, "slots": slots})
        d = date.fromordinal(d.toordinal() + 1)
    return out


def _check_slot(conn: sqlite3.Connection, store_id: str, when: str, exclude: str | None = None) -> None:
    """その日時に、もう1台入れられるか。休み・枠の外・満席なら断る。"""
    day, slot = when[:10], when[11:16]
    master = get_master(conn, store_id)
    if day in {d["day"] for d in master["closed_dates"]} or \
            date.fromisoformat(day).weekday() in master["closed_weekdays"]:
        raise LedgerError(f"{day} は休みです")
    rule = next((s for s in master["slots"] if s["slot"] == slot), None)
    if rule is None:
        raise LedgerError(f"{slot} は受け付けている時間帯ではありません")
    n = conn.execute(
        f"SELECT COUNT(*) FROM reservations WHERE store_id = ? AND status IN ({_q(HOLDING)})"
        " AND substr(confirmed_for, 1, 16) = ? AND reserve_no IS NOT ?",
        (store_id, *HOLDING, f"{day}T{slot}", exclude),
    ).fetchone()[0]
    if n >= rule["capacity"]:
        raise LedgerError(f"{day} {slot} は満席です")


# ---- LP のセッションと出来事 -----------------------------------------------

def create_session(
    conn: sqlite3.Connection,
    session_id: str,
    started_at: str,
    campaign: str | None,
    src: str | None,
    store_id: str,
) -> tuple[str, str]:
    """セッションを作る。台帳に無い施策は unknown に割り当てる。割り当てた (campaign, src) を返す。"""
    known = conn.execute(
        "SELECT 1 FROM campaigns WHERE campaign = ? AND src = ? AND store_id = ?",
        (campaign, src, store_id),
    ).fetchone()
    if not known or campaign == UNKNOWN:
        campaign, src = UNKNOWN, UNKNOWN
    with conn:
        conn.execute(
            "INSERT INTO sessions (session_id, started_at, campaign, src, store_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_id, started_at, campaign, src, store_id),
        )
    return campaign, src


def add_event(conn: sqlite3.Connection, session_id: str, at: str, name: str) -> None:
    if name not in EVENT_NAMES:
        raise LedgerError(f"知らない出来事の名前です: {name}")
    with conn:
        conn.execute(
            "INSERT INTO events (at, session_id, name) VALUES (?, ?, ?)", (at, session_id, name)
        )


# ---- クーポン ---------------------------------------------------------------

def issue_coupon(conn: sqlite3.Connection, session_id: str, code: str, at: str) -> str:
    """セッションにクーポンを出す。同じセッションでもう一度押しても、同じ番号を返す。"""
    with conn:
        if not conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone():
            raise LedgerError("台帳に無いセッションです")
        row = conn.execute("SELECT code FROM coupons WHERE session_id = ?", (session_id,)).fetchone()
        if row:
            return row["code"]
        conn.execute("INSERT INTO coupons (code, session_id, issued_at) VALUES (?, ?, ?)",
                     (code, session_id, at))
    return code


def _coupon_reservation(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    """クーポンのセッションから生まれた予約（取消を除く・新しいもの）。"""
    return conn.execute(
        "SELECT reserve_no FROM reservations WHERE session_id = ? AND status != 'cancelled'"
        " ORDER BY created_at DESC, reserve_no DESC LIMIT 1",
        (session_id,),
    ).fetchone()


def get_coupon(conn: sqlite3.Connection, code: str) -> dict | None:
    """受付の画面用。施策と、使ったかどうか、結ぶ予約（使った時に結んだもの、まだなら今の候補）。"""
    row = conn.execute(
        "SELECT c.code, c.session_id, c.issued_at, s.campaign, s.src, s.store_id,"
        " u.redeemed_at, u.reserve_no AS redeemed_reserve_no, u.handled_by"
        " FROM coupons c JOIN sessions s USING (session_id)"
        " LEFT JOIN coupon_redemptions u USING (code) WHERE c.code = ?",
        (code,),
    ).fetchone()
    if not row:
        return None
    out = dict(row)
    reserve_no = out["redeemed_reserve_no"]
    if not out["redeemed_at"]:
        r = _coupon_reservation(conn, out["session_id"])
        reserve_no = r["reserve_no"] if r else None
    out["reservation"] = get_reservation(conn, reserve_no) if reserve_no else None
    return out


def redeem_coupon(conn: sqlite3.Connection, code: str, at: str, handled_by: str) -> str | None:
    """クーポンを店で使ったと記録する（1つの番号で1回だけ）。結んだ予約番号を返す（無ければ None）。"""
    with conn:
        return _redeem_rows(conn, code, at, handled_by)


def redeem_coupon_with_visit(conn: sqlite3.Connection, code: str, at: str, handled_by: str) -> str:
    """予約のあるお客様の来店とクーポンの利用を、1回で記録する（一緒に成功するか、一緒に失敗する）。"""
    with conn:
        row = conn.execute("SELECT session_id FROM coupons WHERE code = ?", (code,)).fetchone()
        if not row:
            raise LedgerError("台帳に無いクーポンの番号です")
        if conn.execute("SELECT 1 FROM coupon_redemptions WHERE code = ?", (code,)).fetchone():
            raise LedgerError("このクーポンは使用済みです")
        r = _coupon_reservation(conn, row["session_id"])
        if not r or _get(conn, r["reserve_no"])["status"] != "confirmed":
            raise LedgerError("来店を記録できる予約がありません（クーポンだけを記録してください）")
        _visit_rows(conn, r["reserve_no"], at, at, handled_by)
        return _redeem_rows(conn, code, at, handled_by)


def undo_coupon(conn: sqlite3.Connection, code: str, at: str, handled_by: str) -> None:
    """間違えて押した「使った」を取り消す。取り消した記録は coupon_undos に残す（来店の記録はそのまま）。"""
    with conn:
        u = conn.execute("SELECT * FROM coupon_redemptions WHERE code = ?", (code,)).fetchone()
        if not u:
            raise LedgerError("このクーポンは、まだ使った記録がありません")
        conn.execute(
            "INSERT INTO coupon_undos (code, redeemed_at, reserve_no, handled_by, undone_at, undone_by)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (code, u["redeemed_at"], u["reserve_no"], u["handled_by"], at, handled_by),
        )
        conn.execute("DELETE FROM coupon_redemptions WHERE code = ?", (code,))


def _redeem_rows(conn: sqlite3.Connection, code: str, at: str, handled_by: str) -> str | None:
    row = conn.execute("SELECT session_id FROM coupons WHERE code = ?", (code,)).fetchone()
    if not row:
        raise LedgerError("台帳に無いクーポンの番号です")
    if conn.execute("SELECT 1 FROM coupon_redemptions WHERE code = ?", (code,)).fetchone():
        raise LedgerError("このクーポンは使用済みです")
    r = _coupon_reservation(conn, row["session_id"])
    reserve_no = r["reserve_no"] if r else None
    conn.execute(
        "INSERT INTO coupon_redemptions (code, redeemed_at, reserve_no, handled_by) VALUES (?, ?, ?, ?)",
        (code, at, reserve_no, handled_by),
    )
    return reserve_no


# ---- 予約 -----------------------------------------------------------------

def create_reservation(
    conn: sqlite3.Connection,
    *,
    reserve_no: str,
    submit_key: str,
    session_id: str,
    menu: str,
    reserved_for: str,
    created_at: str,
    customer_name: str,
    customer_phone: str,
) -> str:
    """予約を作る（その場で確定）。施策はセッションから写す。同じ送信キーなら既存の予約番号を返す。
    空き枠と休みは、書き込むのと同じトランザクションの中で確かめる（2人が同時に最後の1枠を取らないように）。"""
    existing = conn.execute(
        "SELECT reserve_no FROM reservations WHERE submit_key = ?", (submit_key,)
    ).fetchone()
    if existing:
        return existing["reserve_no"]
    if menu not in MENUS:
        raise LedgerError(f"メニューの表に無い名前です: {menu}")
    session = conn.execute(
        "SELECT campaign, src, store_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not session:
        raise LedgerError(f"セッションがありません: {session_id}")
    if reserved_for[:10] < created_at[:10]:
        raise LedgerError("過ぎた日には予約できません")
    conn.execute("BEGIN IMMEDIATE")
    try:
        _check_slot(conn, session["store_id"], reserved_for)
        conn.execute(
            "INSERT INTO reservations (reserve_no, submit_key, session_id, campaign, src, store_id,"
            " menu, requested_for, confirmed_for, status, handled_by, created_at, updated_at,"
            " customer_name, customer_phone)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', NULL, ?, ?, ?, ?)",
            (
                reserve_no, submit_key, session_id, session["campaign"], session["src"],
                session["store_id"], menu, reserved_for, reserved_for, created_at, created_at,
                customer_name, customer_phone,
            ),
        )
        _log_change(conn, reserve_no, created_at, None, "confirmed", reserved_for, None)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return reserve_no


def reschedule(
    conn: sqlite3.Connection, reserve_no: str, new_for: str, at: str, handled_by: str,
    record_reminder: bool = False, desk_tab_id: str | None = None,
) -> None:
    """日時を変える（お客様から連絡があった時など、店が受付で行う）。新しい日時の空きも確かめる。

    record_reminder が真で、その予約にお知らせの記録があれば、「日時を変えた」の記録も同じ取引で残す
    （受付から変えた時だけ。見本の台帳を作る時は残さない）。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _get(conn, reserve_no)
        store = conn.execute(
            "SELECT store_id FROM reservations WHERE reserve_no = ?", (reserve_no,)
        ).fetchone()["store_id"]
        _check_slot(conn, store, new_for, exclude=reserve_no)
        if row["status"] != "confirmed":
            raise LedgerError(f"{reserve_no}: {row['status']} の予約は日時を変えられません")
        _move(conn, reserve_no, "confirmed", at, handled_by, new_for)
        if record_reminder and conn.execute("SELECT 1 FROM reminders WHERE reserve_no = ? LIMIT 1", (reserve_no,)).fetchone():
            conn.execute("INSERT INTO reminders (reserve_no, at, result, handled_by, desk_tab_id) VALUES (?, ?, 'rescheduled', ?, ?)",
                         (reserve_no, at, handled_by, desk_tab_id))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def cancel(conn: sqlite3.Connection, reserve_no: str, at: str, handled_by: str) -> None:
    with conn:
        _move(conn, reserve_no, "cancelled", at, handled_by)


# ---- 来店 -----------------------------------------------------------------

def record_visit(
    conn: sqlite3.Connection, reserve_no: str, visited_at: str, recorded_at: str, handled_by: str
) -> None:
    """来店を記録する。予約の状態の更新・履歴・来店の行は一緒に成功するか、一緒に失敗する。"""
    with conn:
        _visit_rows(conn, reserve_no, visited_at, recorded_at, handled_by)


def _visit_rows(conn: sqlite3.Connection, reserve_no: str, visited_at: str, recorded_at: str, handled_by: str) -> None:
    _move(conn, reserve_no, "visited", recorded_at, handled_by)
    conn.execute(
        "INSERT INTO visits (reserve_no, visited_at, recorded_at) VALUES (?, ?, ?)",
        (reserve_no, visited_at, recorded_at),
    )


def cancel_visit(conn: sqlite3.Connection, reserve_no: str, at: str, handled_by: str) -> None:
    """間違えて付けた来店を取り消し、確定の状態に戻す。"""
    with conn:
        row = _get(conn, reserve_no)
        if row["status"] != "visited":
            raise LedgerError(f"来店の記録がありません: {reserve_no}")
        conn.execute("DELETE FROM visits WHERE reserve_no = ?", (reserve_no,))
        _move(conn, reserve_no, "confirmed", at, handled_by, row["confirmed_for"], undo_visit=True)


# ---- 内部 -----------------------------------------------------------------

def _q(values: tuple) -> str:
    return ", ".join("?" * len(values))


def _get(conn: sqlite3.Connection, reserve_no: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT status, confirmed_for FROM reservations WHERE reserve_no = ?", (reserve_no,)
    ).fetchone()
    if not row:
        raise LedgerError(f"台帳に無い予約番号です: {reserve_no}")
    return row


def _move(
    conn: sqlite3.Connection,
    reserve_no: str,
    to_status: str,
    at: str,
    handled_by: str,
    confirmed_for: str | None = None,
    *,
    undo_visit: bool = False,
) -> str:
    row = _get(conn, reserve_no)
    current = row["status"]
    if to_status not in TRANSITIONS[current]:
        raise LedgerError(f"{reserve_no}: {current} から {to_status} には移れません")
    if current == "visited" and not undo_visit:
        raise LedgerError("来店済みの予約は、来店の取り消しで戻してください")
    new_confirmed_for = confirmed_for if confirmed_for is not None else row["confirmed_for"]
    conn.execute(
        "UPDATE reservations SET status = ?, confirmed_for = ?, handled_by = ?, updated_at = ?"
        " WHERE reserve_no = ?",
        (to_status, new_confirmed_for, handled_by, at, reserve_no),
    )
    _log_change(conn, reserve_no, at, current, to_status, new_confirmed_for, handled_by)
    return current


def _log_change(
    conn: sqlite3.Connection,
    reserve_no: str,
    at: str,
    from_status: str | None,
    to_status: str,
    confirmed_for: str | None,
    handled_by: str | None,
) -> None:
    conn.execute(
        "INSERT INTO reservation_changes (reserve_no, at, from_status, to_status, confirmed_for,"
        " handled_by) VALUES (?, ?, ?, ?, ?, ?)",
        (reserve_no, at, from_status, to_status, confirmed_for, handled_by),
    )


# ---- 読み出し ---------------------------------------------------------------

def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def snapshot(conn: sqlite3.Connection, store_id: str, period_from: str, period_to: str) -> dict:
    """集計と書き出しに使う台帳の写しを、1回の読み取り（1つのトランザクション）で取る。

    対象は施策期間に始まった LP のセッションと、そこから生まれた予約・来店・履歴。
    period_from / period_to は "YYYY-MM-DD"（両端を含む）。
    """
    session_filter = (
        "SELECT session_id FROM sessions WHERE store_id = ?"
        " AND date(started_at) BETWEEN ? AND ?"
    )
    p = (store_id, period_from, period_to)
    conn.execute("BEGIN")
    try:
        data = {
            "campaigns": _rows(
                conn, "SELECT * FROM campaigns WHERE store_id = ? ORDER BY campaign, src", (store_id,)
            ),
            "sessions": _rows(
                conn,
                "SELECT * FROM sessions WHERE store_id = ? AND date(started_at) BETWEEN ? AND ?"
                " ORDER BY started_at, session_id",
                p,
            ),
            "events": _rows(
                conn,
                f"SELECT * FROM events WHERE session_id IN ({session_filter}) ORDER BY at, id",
                p,
            ),
            "reservations": _rows(
                conn,
                f"SELECT * FROM reservations WHERE session_id IN ({session_filter})"
                " ORDER BY created_at, reserve_no",
                p,
            ),
            "visits": _rows(
                conn,
                "SELECT v.* FROM visits v JOIN reservations r USING (reserve_no)"
                f" WHERE r.session_id IN ({session_filter}) ORDER BY v.visited_at, v.reserve_no",
                p,
            ),
            "reservation_changes": _rows(
                conn,
                "SELECT c.* FROM reservation_changes c JOIN reservations r USING (reserve_no)"
                f" WHERE r.session_id IN ({session_filter}) ORDER BY c.at, c.id",
                p,
            ),
            # 受付のタブの設定の版（いつ・どのタブがあったか。お客様の情報は入らない）
            "settings_versions": _rows(conn, "SELECT version, created_at, settings_json FROM settings_versions ORDER BY version"),
            # 前日のお知らせの記録（送った・返事あり・日時を変えた）。担当は書き出しで落とす
            "reminders": _rows(
                conn,
                "SELECT m.* FROM reminders m JOIN reservations r USING (reserve_no)"
                f" WHERE r.session_id IN ({session_filter}) ORDER BY m.at, m.id",
                p,
            ),
            # クーポン1枚に1行（出した・使った・結んだ予約）。番号そのものは書き出しで落とす
            "coupons": _rows(
                conn,
                "SELECT c.code, c.session_id, c.issued_at, u.redeemed_at, u.reserve_no"
                " FROM coupons c LEFT JOIN coupon_redemptions u USING (code)"
                f" WHERE c.session_id IN ({session_filter}) ORDER BY c.issued_at, c.code",
                p,
            ),
        }
    finally:
        conn.execute("COMMIT")
    return data


def get_store(conn: sqlite3.Connection, store_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM stores WHERE store_id = ?", (store_id,)).fetchone()
    return dict(row) if row else None


def get_session(conn: sqlite3.Connection, session_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def get_reservation(conn: sqlite3.Connection, reserve_no: str) -> dict | None:
    row = conn.execute(
        "SELECT r.*, v.visited_at, v.recorded_at FROM reservations r"
        " LEFT JOIN visits v USING (reserve_no) WHERE r.reserve_no = ?",
        (reserve_no,),
    ).fetchone()
    return dict(row) if row else None


def list_reservations(conn: sqlite3.Connection, store_id: str) -> list[dict]:
    """受付の画面用。名前での絞り込みは画面の側で行う（名前を URL やログに出さないため）。"""
    return _rows(
        conn,
        "SELECT r.reserve_no, r.menu, r.requested_for, r.confirmed_for, r.status, r.handled_by,"
        " r.created_at, r.src, r.customer_name, r.customer_phone, v.visited_at, v.recorded_at"
        " FROM reservations r LEFT JOIN visits v USING (reserve_no)"
        " WHERE r.store_id = ? ORDER BY r.confirmed_for, r.reserve_no",
        (store_id,),
    )


# ---- 分析の記録 -------------------------------------------------------------

ANALYSIS_COLUMNS = ("status", "export_csv", "id_map_json", "funnel_json", "tool_log", "report_json",
                    "model", "session_id", "cost_cents", "previous_json")


def create_analysis_run(conn: sqlite3.Connection, analysis_id: str, as_of: str, **fields: str) -> None:
    unknown = set(fields) - set(ANALYSIS_COLUMNS)
    if unknown:
        raise LedgerError(f"analysis_runs に無い列です: {sorted(unknown)}")
    cols = ["analysis_id", "as_of", *fields]
    with conn:
        conn.execute(
            f"INSERT INTO analysis_runs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            (analysis_id, as_of, *fields.values()),
        )


def update_analysis_run(conn: sqlite3.Connection, analysis_id: str, **fields: str) -> None:
    unknown = set(fields) - set(ANALYSIS_COLUMNS)
    if unknown or not fields:
        raise LedgerError(f"analysis_runs に無い列です: {sorted(unknown)}")
    with conn:
        conn.execute(
            f"UPDATE analysis_runs SET {', '.join(f'{k} = ?' for k in fields)} WHERE analysis_id = ?",
            (*fields.values(), analysis_id),
        )


def list_unfinished_runs(conn: sqlite3.Connection) -> list[dict]:
    """前回のサーバーで終わらなかった分析（受付済み・実行中のまま残ったもの）。"""
    rows = conn.execute(
        "SELECT * FROM analysis_runs WHERE status IN ('queued', 'running') ORDER BY analysis_id"
    ).fetchall()
    return [dict(r) for r in rows]


def fail_pending_messages(conn: sqlite3.Connection) -> None:
    """前回のサーバーで答えの途中だった質問を「失敗」にする（もう一度聞けるように）。"""
    with conn:
        conn.execute(
            "UPDATE analysis_messages SET status = 'failed',"
            " text = 'サーバーが途中で止まったため、答えられませんでした。もう一度聞いてください。'"
            " WHERE status = 'pending'"
        )


IMPROVEMENT_COLUMNS = ("status", "decision", "reason", "candidate_system", "proposal_json",
                       "eval_base_json", "eval_cand_json", "applied_at")


def add_improvement(conn: sqlite3.Connection, created_at: str, iteration: int, base_system: str,
                    eval_base_json: str) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO improvements (created_at, iteration, status, base_system, eval_base_json)"
            " VALUES (?, ?, 'running', ?, ?)",
            (created_at, iteration, base_system, eval_base_json),
        )
    return int(cur.lastrowid)


def update_improvement(conn: sqlite3.Connection, improvement_id: int, **fields: str) -> None:
    unknown = set(fields) - set(IMPROVEMENT_COLUMNS)
    if unknown or not fields:
        raise LedgerError(f"improvements に無い列です: {sorted(unknown)}")
    with conn:
        conn.execute(
            f"UPDATE improvements SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            (*fields.values(), improvement_id),
        )


def list_improvements(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn, "SELECT * FROM improvements ORDER BY id DESC")


def get_improvement(conn: sqlite3.Connection, improvement_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM improvements WHERE id = ?", (improvement_id,)).fetchone()
    return dict(row) if row else None


def latest_reviewable_run(conn: sqlite3.Connection) -> dict | None:
    """振り返りの元にする、いちばん新しい「終わった本物の分析」（見本の報告と失敗は除く）。"""
    for row in conn.execute(
        "SELECT * FROM analysis_runs WHERE status = 'done' AND report_json IS NOT NULL ORDER BY rowid DESC"
    ):
        report = json.loads(row["report_json"])
        if "error" not in report and report.get("mode") != "sample" and "next_action" in report:
            return dict(row)
    return None


def get_analysis_run(conn: sqlite3.Connection, analysis_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM analysis_runs WHERE analysis_id = ?", (analysis_id,)
    ).fetchone()
    return dict(row) if row else None


def analysis_cost_summary(conn: sqlite3.Connection, default_model: str) -> list[dict]:
    """モデルごとの、終わった分析の回数・費用の平均と合計（目安。セント）。続きの質問の分も含む。"""
    rows = conn.execute(
        "SELECT COALESCE(model, ?) AS model, COUNT(*) AS runs, ROUND(AVG(cost_cents)) AS avg_cents, SUM(cost_cents) AS total_cents"
        " FROM analysis_runs WHERE status = 'done' AND cost_cents IS NOT NULL GROUP BY 1 ORDER BY 1",
        (default_model,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_analysis_message(conn: sqlite3.Connection, analysis_id: str, at: str, role: str,
                         status: str, text: str | None = None) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO analysis_messages (analysis_id, at, role, status, text, tool_log)"
            " VALUES (?, ?, ?, ?, ?, '[]')",
            (analysis_id, at, role, status, text),
        )
    return int(cur.lastrowid)


def update_analysis_message(conn: sqlite3.Connection, message_id: int, **fields: str) -> None:
    unknown = set(fields) - {"status", "text", "tool_log"}
    if unknown or not fields:
        raise LedgerError(f"analysis_messages に無い列です: {sorted(unknown)}")
    with conn:
        conn.execute(
            f"UPDATE analysis_messages SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            (*fields.values(), message_id),
        )


def list_analysis_messages(conn: sqlite3.Connection, analysis_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM analysis_messages WHERE analysis_id = ? ORDER BY id", (analysis_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---- ナットクに頼むメンテナンス（受付のタブの設定・お知らせの記録） ---------------------------

EMPTY_SETTINGS = {"desk_tabs": []}
CHANGE_COLUMNS = ("proposal_json", "status", "reason", "applied_version", "applied_by", "applied_at")
REMINDER_RESULTS = ("sent", "replied", "rescheduled")
REMINDER_MANUAL = ("sent", "replied")  # 受付で押す記録。rescheduled は日時を変えた時に reschedule が残す


def current_settings(conn: sqlite3.Connection) -> tuple[int, dict]:
    """いまの設定の版と中身。まだ版が無ければ 0 と空の設定。"""
    row = conn.execute("SELECT version, settings_json FROM settings_versions ORDER BY version DESC LIMIT 1").fetchone()
    return (row["version"], json.loads(row["settings_json"])) if row else (0, json.loads(json.dumps(EMPTY_SETTINGS)))


def settings_version(conn: sqlite3.Connection, version: int) -> dict:
    if version == 0:
        return json.loads(json.dumps(EMPTY_SETTINGS))
    row = conn.execute("SELECT settings_json FROM settings_versions WHERE version = ?", (version,)).fetchone()
    if not row:
        raise LedgerError(f"設定の版がありません: {version}")
    return json.loads(row["settings_json"])


def add_change_request(conn: sqlite3.Connection, at: str, requested_by: str | None, text: str,
                       source_analysis_id: str | None) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO change_requests (created_at, requested_by, text, source_analysis_id, status)"
            " VALUES (?, ?, ?, ?, 'proposed')",
            (at, requested_by, text, source_analysis_id),
        )
    return int(cur.lastrowid)


def update_change_request(conn: sqlite3.Connection, request_id: int, **fields) -> None:
    unknown = set(fields) - set(CHANGE_COLUMNS)
    if unknown or not fields:
        raise LedgerError(f"change_requests に無い列です: {sorted(unknown)}")
    with conn:
        conn.execute(f"UPDATE change_requests SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                     (*fields.values(), request_id))


def get_change_request(conn: sqlite3.Connection, request_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM change_requests WHERE id = ?", (request_id,)).fetchone()
    return dict(row) if row else None


def list_change_requests(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn, "SELECT * FROM change_requests ORDER BY id DESC")


def apply_change(conn: sqlite3.Connection, request_id: int, settings: dict, at: str, applied_by: str) -> int:
    """提案した設定を新しい版として保存し、頼んだ記録を「反映した」にする（一緒に成功するか、一緒に失敗する）。"""
    with conn:
        req = conn.execute("SELECT status FROM change_requests WHERE id = ?", (request_id,)).fetchone()
        if not req or req["status"] != "proposed":
            raise LedgerError("反映できるのは、まだ反映していない提案だけです")
        version = _new_version(conn, settings, at, request_id, f"依頼 {request_id} を反映")
        conn.execute("UPDATE change_requests SET status = 'applied', applied_version = ?, applied_by = ?, applied_at = ?"
                     " WHERE id = ?", (version, applied_by, at, request_id))
    return version


def revert_last_change(conn: sqlite3.Connection, at: str, handled_by: str) -> dict:
    """さっきの変更（いちばん新しい版を作った反映）を取り消す。前の版の中身で新しい版を作る。お知らせの記録は消さない。"""
    with conn:
        last = conn.execute("SELECT version, change_request_id FROM settings_versions ORDER BY version DESC LIMIT 1").fetchone()
        req = conn.execute("SELECT * FROM change_requests WHERE id = ?", (last["change_request_id"],)).fetchone() if last else None
        if not last or not req or req["status"] != "applied" or req["applied_version"] != last["version"]:
            raise LedgerError("取り消せる変更がありません（さっきの変更は、もう取り消してあります）")
        before = settings_version(conn, last["version"] - 1)
        version = _new_version(conn, before, at, None, f"依頼 {req['id']} の反映を取り消し（{handled_by}）")
        conn.execute("UPDATE change_requests SET status = 'reverted' WHERE id = ?", (req["id"],))
    return {"version": version, "request_id": req["id"]}


def _new_version(conn: sqlite3.Connection, settings: dict, at: str, request_id: int | None, note: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM settings_versions").fetchone()
    version = row["v"] + 1
    conn.execute("INSERT INTO settings_versions (version, created_at, settings_json, change_request_id, note)"
                 " VALUES (?, ?, ?, ?, ?)", (version, at, json.dumps(settings, ensure_ascii=False), request_id, note))
    return version


def add_reminder(conn: sqlite3.Connection, reserve_no: str, at: str, result: str, handled_by: str,
                 desk_tab_id: str | None) -> int:
    """前日のお知らせの結果を残す（今回は実際には送らず、記録だけ）。"""
    if result not in REMINDER_MANUAL:
        raise LedgerError(f"受付で押せるお知らせの結果ではありません: {result}（日時を変えた記録は、日時を変えると残ります）")
    with conn:
        _get(conn, reserve_no)
        if result == "replied" and not conn.execute(
                "SELECT 1 FROM reminders WHERE reserve_no = ? AND result = 'sent' LIMIT 1", (reserve_no,)).fetchone():
            raise LedgerError("「送った」の記録が無い予約には「返事あり」を付けられません（先に「送った」を記録してください）")
        cur = conn.execute("INSERT INTO reminders (reserve_no, at, result, handled_by, desk_tab_id) VALUES (?, ?, ?, ?, ?)",
                           (reserve_no, at, result, handled_by, desk_tab_id))
    return int(cur.lastrowid)


def undo_last_reminder(conn: sqlite3.Connection, reserve_no: str, at: str, handled_by: str) -> str:
    """間違えて押した最後の「送った」「返事あり」を取り消す。取り消した記録は reminder_undos に残す。
    （「日時を変えた」は日時の変更と一緒に残るので、ここでは取り消さない。日時は「日時を変える」で直す）"""
    with conn:
        row = conn.execute("SELECT * FROM reminders WHERE reserve_no = ? AND result IN ('sent', 'replied')"
                           " ORDER BY at DESC, id DESC LIMIT 1", (reserve_no,)).fetchone()
        if not row:
            raise LedgerError("取り消せるお知らせの記録がありません")
        conn.execute("INSERT INTO reminder_undos (reminder_id, reserve_no, at, result, handled_by, desk_tab_id, undone_at, undone_by)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (row["id"], reserve_no, row["at"], row["result"], row["handled_by"], row["desk_tab_id"], at, handled_by))
        conn.execute("DELETE FROM reminders WHERE id = ?", (row["id"],))
    return row["result"]


def list_reminders(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn, "SELECT * FROM reminders ORDER BY at, id")

