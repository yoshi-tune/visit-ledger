"""台帳の保存の層。SQL と状態の移り変わりの決まりは、このファイルにだけ書く（docs/DESIGN.md §3・§5）。

日時はすべて呼び出し側から渡す（この層では「今」を読まない）。形式は "YYYY-MM-DDTHH:MM:SS"（店の現地時刻）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MENUS = ("オイル交換", "タイヤ交換", "秋の点検")
EVENT_NAMES = ("lp_view", "reserve_tap")
# 電話の結果（つながって日時が決まったら confirm で記録する。ここは「決まらなかった」電話）
CONTACT_RESULTS = ("no_answer", "callback")
UNKNOWN = "unknown"

# 状態ごとに、次に移れる状態（DESIGN §3）
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "requested": ("confirmed", "declined", "cancelled"),
    "confirmed": ("confirmed", "visited", "cancelled"),
    "visited": ("confirmed",),
    "declined": (),
    "cancelled": (),
}

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
    confirmed_for  TEXT,
    status         TEXT NOT NULL
                   CHECK (status IN ('requested', 'confirmed', 'visited', 'declined', 'cancelled')),
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

CREATE TABLE contact_attempts (
    id          INTEGER PRIMARY KEY,
    reserve_no  TEXT NOT NULL REFERENCES reservations(reserve_no),
    at          TEXT NOT NULL,
    result      TEXT NOT NULL CHECK (result IN ('no_answer', 'callback')),
    handled_by  TEXT NOT NULL
);

CREATE TABLE analysis_runs (
    analysis_id  TEXT PRIMARY KEY,
    as_of        TEXT NOT NULL,
    status       TEXT NOT NULL,
    export_csv   TEXT,
    id_map_json  TEXT,
    funnel_json  TEXT,
    tool_log     TEXT,
    report_json  TEXT
);
"""


class LedgerError(Exception):
    """台帳の決まりに合わない操作（存在しない予約、許されない状態の移り変わりなど）。"""


def connect(path: str | Path) -> sqlite3.Connection:
    # 接続はリクエストごとに1つ作って閉じる。FastAPI は作る・閉じるを別のスレッドで行うことがあるので許可する
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


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


# ---- 予約 -----------------------------------------------------------------

def create_reservation(
    conn: sqlite3.Connection,
    *,
    reserve_no: str,
    submit_key: str,
    session_id: str,
    menu: str,
    requested_for: str,
    created_at: str,
    customer_name: str,
    customer_phone: str,
) -> str:
    """予約の希望を保存する。施策はセッションから写す。同じ送信キーなら既存の予約番号を返す。"""
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
    with conn:
        conn.execute(
            "INSERT INTO reservations (reserve_no, submit_key, session_id, campaign, src, store_id,"
            " menu, requested_for, confirmed_for, status, handled_by, created_at, updated_at,"
            " customer_name, customer_phone)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'requested', NULL, ?, ?, ?, ?)",
            (
                reserve_no, submit_key, session_id, session["campaign"], session["src"],
                session["store_id"], menu, requested_for, created_at, created_at,
                customer_name, customer_phone,
            ),
        )
        _log_change(conn, reserve_no, created_at, None, "requested", None, None)
    return reserve_no


def confirm(
    conn: sqlite3.Connection, reserve_no: str, confirmed_for: str, at: str, handled_by: str
) -> None:
    """店が確定日時を入れる。確定済みの予約に対しては日時の変更になる。"""
    with conn:
        _move(conn, reserve_no, "confirmed", at, handled_by, confirmed_for)


def decline(conn: sqlite3.Connection, reserve_no: str, at: str, handled_by: str) -> None:
    with conn:
        _move(conn, reserve_no, "declined", at, handled_by)


def cancel(conn: sqlite3.Connection, reserve_no: str, at: str, handled_by: str) -> None:
    with conn:
        _move(conn, reserve_no, "cancelled", at, handled_by)


# ---- 来店 -----------------------------------------------------------------

def record_visit(
    conn: sqlite3.Connection, reserve_no: str, visited_at: str, recorded_at: str, handled_by: str
) -> None:
    """来店を記録する。予約の状態の更新・履歴・来店の行は一緒に成功するか、一緒に失敗する。"""
    with conn:
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
    """受付の画面用。名前での絞り込みは画面の側で行う（名前を URL やログに出さないため）。
    最後に「決まらなかった電話」の記録と、その回数も付ける（交代した人が二度電話しないように）。"""
    return _rows(
        conn,
        "SELECT r.reserve_no, r.menu, r.requested_for, r.confirmed_for, r.status, r.handled_by,"
        " r.created_at, r.src, r.customer_name, r.customer_phone, v.visited_at, v.recorded_at,"
        " c.at AS last_contact_at, c.result AS last_contact_result, c.handled_by AS last_contact_by,"
        " (SELECT COUNT(*) FROM contact_attempts x WHERE x.reserve_no = r.reserve_no) AS contact_count"
        " FROM reservations r LEFT JOIN visits v USING (reserve_no)"
        " LEFT JOIN contact_attempts c ON c.id = ("
        "   SELECT id FROM contact_attempts y WHERE y.reserve_no = r.reserve_no ORDER BY at DESC, id DESC LIMIT 1)"
        " WHERE r.store_id = ? ORDER BY COALESCE(r.confirmed_for, r.requested_for), r.reserve_no",
        (store_id,),
    )


def record_contact(
    conn: sqlite3.Connection, reserve_no: str, at: str, result: str, handled_by: str
) -> None:
    """日時が決まらなかった電話（不在・折り返し待ち）を記録する。予約の状態は変えない。"""
    if result not in CONTACT_RESULTS:
        raise LedgerError(f"知らない電話の結果です: {result}")
    row = _get(conn, reserve_no)
    if row["status"] not in ("requested", "confirmed"):
        raise LedgerError(f"{reserve_no}: {row['status']} の予約には電話の記録を付けません")
    with conn:
        conn.execute(
            "INSERT INTO contact_attempts (reserve_no, at, result, handled_by) VALUES (?, ?, ?, ?)",
            (reserve_no, at, result, handled_by),
        )


# ---- 分析の記録 -------------------------------------------------------------

ANALYSIS_COLUMNS = ("status", "export_csv", "id_map_json", "funnel_json", "tool_log", "report_json")


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


def fail_unfinished_runs(conn: sqlite3.Connection, message: str) -> int:
    """起動した時に、前回のサーバーで終わらなかった分析を「失敗」にする（実行中のまま残さない）。"""
    with conn:
        cur = conn.execute(
            "UPDATE analysis_runs SET status = 'failed', report_json = ?"
            " WHERE status IN ('queued', 'running')",
            (message,),
        )
    return cur.rowcount


def get_analysis_run(conn: sqlite3.Connection, analysis_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM analysis_runs WHERE analysis_id = ?", (analysis_id,)
    ).fetchone()
    return dict(row) if row else None
