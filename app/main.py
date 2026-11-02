"""visit-ledger の入口。画面（app/static）と API をつなぐ。SQL は書かない（保存の層 app/ledger.py を通す）。

    uv run python scripts/make_sample.py   # 見本の台帳を作る（最初に1回）
    uv run uvicorn app.main:app --reload    # http://127.0.0.1:8000/
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterator
from datetime import date, datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import analysis, config, funnel, ledger

if not config.DB_PATH.exists():
    raise SystemExit(
        f"台帳がありません: {config.DB_PATH}\n"
        "先に `uv run python scripts/make_sample.py` で見本の台帳を作ってください。"
    )

# 前回のサーバーで終わらなかった分析は、実行中のまま残さず「失敗」にする（もう一度頼めるように）
with ledger.connect(config.DB_PATH) as _conn:
    ledger.fail_unfinished_runs(_conn, json.dumps(
        {"error": "サーバーが途中で止まったため、分析が終わりませんでした。もう一度頼んでください。"},
        ensure_ascii=False))

STATIC = config.ROOT / "app" / "static"
app = FastAPI(title="visit-ledger")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = ledger.connect(config.DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def normalize(value: str) -> str:
    """画面から来た日時（"YYYY-MM-DDTHH:MM" など）を台帳の形にそろえる。"""
    try:
        return fmt(datetime.fromisoformat(value))
    except ValueError as e:
        raise HTTPException(400, f"日時の形が読めません: {value}") from e


def guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ledger.LedgerError as e:
        raise HTTPException(400, str(e)) from e


# ---- 画面 -------------------------------------------------------------------

def page(name: str) -> FileResponse:
    return FileResponse(STATIC / name)


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/dashboard")


@app.get("/lp/{store_id}", include_in_schema=False)
def lp_page(store_id: str) -> FileResponse:
    return page("lp.html")


@app.get("/reserve", include_in_schema=False)
def reserve_page() -> FileResponse:
    return page("reserve.html")


@app.get("/reserve/done/{reserve_no}", include_in_schema=False)
def done_page(reserve_no: str) -> FileResponse:
    return page("done.html")


@app.get("/desk", include_in_schema=False)
def desk_page() -> FileResponse:
    return page("desk.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page() -> FileResponse:
    return page("dashboard.html")


# ---- API：設定 ----------------------------------------------------------------

@app.get("/api/config")
def get_config(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    store = ledger.get_store(conn, config.STORE_ID)
    return {
        "today": config.TODAY.isoformat(),
        "store": store,
        "menus": list(ledger.MENUS),
        # 予約の希望で選べる時間帯と日数（空き枠の管理はしない。確定は店から電話）
        "slots": ["10:00", "11:00", "13:00", "14:00", "15:00", "16:00"],
        "days_ahead": 14,
        "staff": ["A", "B"],
        "period": {"from": config.PERIOD_FROM.isoformat(), "to": config.PERIOD_TO.isoformat()},
    }


# ---- API：LP とセッション -------------------------------------------------------

class SessionIn(BaseModel):
    store: str
    campaign: str | None = None
    src: str | None = None


@app.post("/api/sessions")
def create_session(body: SessionIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if not ledger.get_store(conn, body.store):
        raise HTTPException(404, "店がありません")
    session_id = secrets.token_hex(6)
    at = fmt(config.now())
    campaign, src = ledger.create_session(conn, session_id, at, body.campaign, body.src, body.store)
    ledger.add_event(conn, session_id, at, "lp_view")
    return {"session_id": session_id, "campaign": campaign, "src": src}


class EventIn(BaseModel):
    session_id: str
    name: str


@app.post("/api/events")
def add_event(body: EventIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if not ledger.get_session(conn, body.session_id):
        raise HTTPException(404, "セッションがありません")
    guard(ledger.add_event, conn, body.session_id, fmt(config.now()), body.name)
    return {"ok": True}


# ---- API：予約 -----------------------------------------------------------------

class ReservationIn(BaseModel):
    session_id: str
    submit_key: str = Field(min_length=8)
    menu: str
    requested_for: str
    customer_name: str = Field(min_length=1)
    customer_phone: str = Field(min_length=1)


@app.post("/api/reservations")
def create_reservation(body: ReservationIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    no = f"R{secrets.randbelow(900000) + 100000}"
    while ledger.get_reservation(conn, no):
        no = f"R{secrets.randbelow(900000) + 100000}"
    reserve_no = guard(
        ledger.create_reservation, conn,
        reserve_no=no, submit_key=body.submit_key, session_id=body.session_id, menu=body.menu,
        requested_for=normalize(body.requested_for), created_at=fmt(config.now()),
        customer_name=body.customer_name, customer_phone=body.customer_phone,
    )
    return {"reserve_no": reserve_no}


@app.get("/api/reservations")
def list_reservations(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    # 名前での絞り込みは画面の側で行う（名前を URL・ログに出さない）
    return {"today": config.TODAY.isoformat(),
            "reservations": ledger.list_reservations(conn, config.STORE_ID)}


@app.get("/api/reservations/{reserve_no}/public")
def reservation_public(reserve_no: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """受付の完了画面用。名前・電話は返さない。"""
    r = ledger.get_reservation(conn, reserve_no)
    if not r:
        raise HTTPException(404, "予約がありません")
    return {k: r[k] for k in ("reserve_no", "menu", "requested_for", "status")}


class StaffIn(BaseModel):
    staff: str


class ConfirmIn(StaffIn):
    confirmed_for: str


@app.post("/api/reservations/{reserve_no}/confirm")
def confirm(reserve_no: str, body: ConfirmIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    guard(ledger.confirm, conn, reserve_no, normalize(body.confirmed_for), fmt(config.now()), body.staff)
    return {"ok": True}


class ContactIn(StaffIn):
    result: str  # no_answer（不在）/ callback（折り返し待ち）


@app.post("/api/reservations/{reserve_no}/contact")
def contact(reserve_no: str, body: ContactIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    guard(ledger.record_contact, conn, reserve_no, fmt(config.now()), body.result, body.staff)
    return {"ok": True}


@app.post("/api/reservations/{reserve_no}/decline")
def decline(reserve_no: str, body: StaffIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    guard(ledger.decline, conn, reserve_no, fmt(config.now()), body.staff)
    return {"ok": True}


@app.post("/api/reservations/{reserve_no}/cancel")
def cancel(reserve_no: str, body: StaffIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    guard(ledger.cancel, conn, reserve_no, fmt(config.now()), body.staff)
    return {"ok": True}


# ---- API：来店 -----------------------------------------------------------------

class VisitIn(StaffIn):
    reserve_no: str
    visited_on: str | None = None  # 押し忘れを後から記録する日（"YYYY-MM-DD"）。無ければ今


@app.post("/api/visits")
def record_visit(body: VisitIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    recorded = config.now()
    if body.visited_on:
        day = date.fromisoformat(body.visited_on)
        if day > config.TODAY:
            raise HTTPException(400, "先の日付の来店は記録できません")
        r = ledger.get_reservation(conn, body.reserve_no)
        if not r:
            raise HTTPException(400, f"台帳に無い予約番号です: {body.reserve_no}")
        slot = (r["confirmed_for"] or "")[11:19] or "10:00:00"
        visited = datetime.fromisoformat(f"{day.isoformat()}T{slot}")
    else:
        visited = recorded
    guard(ledger.record_visit, conn, body.reserve_no, fmt(visited), fmt(recorded), body.staff)
    return {"ok": True}


@app.delete("/api/visits/{reserve_no}")
def cancel_visit(reserve_no: str, body: StaffIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    guard(ledger.cancel_visit, conn, reserve_no, fmt(config.now()), body.staff)
    return {"ok": True}


# ---- API：効果と分析 ------------------------------------------------------------

def current_funnel(conn: sqlite3.Connection) -> tuple[dict, dict]:
    snap = ledger.snapshot(conn, config.STORE_ID, config.PERIOD_FROM.isoformat(),
                           config.cohort_to().isoformat())
    return snap, funnel.compute(snap, config.TODAY, config.PERIOD_FROM, config.cohort_to())


@app.get("/api/funnel")
def get_funnel(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return current_funnel(conn)[1]


@app.post("/api/analysis")
def start_analysis(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    snap, fun = current_funnel(conn)
    return analysis.start(conn, snap, fun)


@app.get("/api/analysis/{analysis_id}")
def get_analysis(analysis_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    run = analysis.get(conn, analysis_id)
    if not run:
        raise HTTPException(404, "分析がありません")
    return run
