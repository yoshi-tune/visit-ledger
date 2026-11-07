"""visit-ledger の入口。画面（app/static）と API をつなぐ。SQL は書かない（保存の層 app/ledger.py を通す）。

    uv run uvicorn app.main:app --reload    # http://127.0.0.1:8000/（台帳が無ければ見本を作る）
    uv run python scripts/make_sample.py   # 見本の台帳を作り直す時
"""

from __future__ import annotations

import io
import json
import secrets
import sqlite3
from collections.abc import Iterator
from datetime import date, datetime
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import analysis, config, funnel, ledger, maintenance, public

if not config.DB_PATH.exists():
    # 初めての起動：見本の台帳を作る（scripts/make_sample.py と同じ中身。作り直す時はそちらを回す）
    import importlib.util

    _spec = importlib.util.spec_from_file_location("make_sample", config.ROOT / "scripts" / "make_sample.py")
    _sample = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_sample)
    _sample.build(config.DB_PATH, plant=True)
    print(f"見本の台帳を作りました: {config.DB_PATH}")

with ledger.connect(config.DB_PATH) as _conn:
    ledger.upgrade_schema(_conn)
    # 前回のサーバーで終わらなかった分析は、エージェントのセッションがあれば引き継ぐ（無ければ「失敗」にして頼み直せるように）
    analysis.resume_unfinished(_conn)

STATIC = config.ROOT / "app" / "static"
# 公開版では API の説明の画面（/docs など）を出さない
app = FastAPI(title="visit-ledger", **({"docs_url": None, "redoc_url": None, "openapi_url": None} if public.PUBLIC else {}))
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def login_gate(request, call_next):
    # 公開版だけ：ログインしていない人は、LP・予約・お客様のクーポンと、それらが使う API だけを開ける
    if public.PUBLIC and not public.is_open(request.method, request.url.path)             and not public.valid_token(request.cookies.get(public.COOKIE)):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "ログインしてください"}, status_code=401)
        return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)
    return await call_next(request)


@app.exception_handler(Exception)
async def hide_errors(request, exc):
    # 思わぬ失敗は、中身を出さずに決まった文だけを返す（中身はサーバーのログにだけ残る）
    return JSONResponse({"detail": "うまくいきませんでした。少し待ってからもう一度試してください。"}, status_code=500)


@app.middleware("http")
async def no_stale_pages(request, call_next):
    # 画面と JS・CSS は毎回確かめてから使わせる（古い画面と新しい JS が混ざらないように）
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


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


STAFF = ("A", "B")  # 見本の担当（権限と暗証番号は、まだ作っていない）


class StaffIn(BaseModel):
    staff: str


def guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ledger.LedgerError as e:
        raise HTTPException(400, str(e)) from e


# ---- ログイン（公開版だけ） ------------------------------------------------------

class LoginIn(BaseModel):
    user: str = Field(max_length=100)
    password: str = Field(max_length=200)


@app.get("/login", include_in_schema=False)
def login_page() -> Response:
    if not public.PUBLIC:
        return RedirectResponse("/dashboard")
    return page("login.html")


@app.post("/api/login")
def login(body: LoginIn) -> Response:
    if not public.PUBLIC:
        raise HTTPException(404, "手元の起動にはログインはありません")
    if not public.check_password(body.user, body.password):
        import time

        time.sleep(1)  # 総当たりを遅らせる
        raise HTTPException(401, "ID かパスワードが違います")
    res = JSONResponse({"ok": True})
    res.set_cookie(public.COOKIE, public.make_token(body.user), max_age=public.LOGIN_DAYS * 86400,
                   httponly=True, secure=True, samesite="lax")
    return res


@app.get("/logout", include_in_schema=False)
def logout() -> Response:
    res = RedirectResponse("/login", status_code=303)
    res.delete_cookie(public.COOKIE)
    return res


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


@app.get("/analysis/{analysis_id}", include_in_schema=False)
def analysis_page(analysis_id: str) -> FileResponse:
    return page("analysis.html")


@app.get("/coupon/{code}", include_in_schema=False)
def coupon_page(code: str) -> FileResponse:
    return page("coupon.html")


@app.get("/desk/coupon", include_in_schema=False)
@app.get("/desk/coupon/{code}", include_in_schema=False)
def desk_coupon_page(code: str | None = None) -> FileResponse:
    return page("desk_coupon.html")


@app.get("/about", include_in_schema=False)
def about_page() -> FileResponse:
    return page("about.html")


@app.get("/improve", include_in_schema=False)
def improve_page() -> FileResponse:
    return page("improve.html")


@app.get("/maintenance", include_in_schema=False)
def maintenance_page() -> FileResponse:
    return page("maintenance.html")


@app.get("/settings", include_in_schema=False)
def settings_page() -> FileResponse:
    return page("settings.html")


# ---- API：設定と店のマスタ ---------------------------------------------------------

@app.get("/api/config")
def get_config(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    store = ledger.get_store(conn, config.STORE_ID)
    return {
        "today": config.TODAY.isoformat(),
        "store": store,
        "menus": list(ledger.MENUS),
        "days_ahead": 14,  # お客様が予約できるのは「今日」から何日先まで
        "staff": list(STAFF),
        "weekdays": list(ledger.WEEKDAYS),
        "period": {"from": config.PERIOD_FROM.isoformat(), "to": config.PERIOD_TO.isoformat()},
        "models": [{"id": k, **v} for k, v in config.MODELS.items()],
        "default_model": config.DEFAULT_MODEL,
        "public": public.PUBLIC,  # 公開版（審査用の URL）か。予約の画面で「本名・本当の電話番号は入れない」を出す
    }


@app.get("/api/availability")
def get_availability(days: int = 14, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """「今日」から days 日分の、日ごと・時間帯ごとの空き（お客様の画面用。名前などは返さない）。"""
    days = max(1, min(days, 60))
    start = config.TODAY.isoformat()
    end = date.fromordinal(config.TODAY.toordinal() + days - 1).isoformat()
    return {"today": start, "days": ledger.availability(conn, config.STORE_ID, start, end)}


@app.get("/api/master")
def get_master(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return ledger.get_master(conn, config.STORE_ID)


class SlotIn(BaseModel):
    slot: str
    capacity: int


class ClosedDateIn(BaseModel):
    day: str
    note: str | None = None


class MasterIn(BaseModel):
    staff: str
    slots: list[SlotIn]
    closed_weekdays: list[int]
    closed_dates: list[ClosedDateIn]


@app.put("/api/master")
def put_master(body: MasterIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """店の設定（時間帯ごとの台数・休み）を変える。すでに入っている予約は動かさない。"""
    guard(ledger.set_master, conn, config.STORE_ID,
          [s.model_dump() for s in body.slots], body.closed_weekdays,
          [d.model_dump() for d in body.closed_dates])
    return ledger.get_master(conn, config.STORE_ID)


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


# ---- API：クーポン --------------------------------------------------------------

COUPON_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 見分けにくい字（0/O・1/I/L）を除く


class CouponIn(BaseModel):
    session_id: str


@app.post("/api/coupons")
def issue_coupon(body: CouponIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """LP の「クーポン」：このセッションのクーポンを出す（もう一度押しても同じ番号）。"""
    for _ in range(5):
        code = "".join(secrets.choice(COUPON_CHARS) for _ in range(6))
        try:
            return {"code": guard(ledger.issue_coupon, conn, body.session_id, code, fmt(config.now()))}
        except sqlite3.IntegrityError:  # 番号がたまたま重なった時は引き直す
            continue
    raise HTTPException(500, "クーポンの番号を作れませんでした")


def _coupon_or_404(conn: sqlite3.Connection, code: str) -> dict:
    c = ledger.get_coupon(conn, code.strip().upper())
    if not c:
        raise HTTPException(404, "台帳に無いクーポンの番号です")
    return c


@app.get("/api/coupons/{code}/public")
def coupon_public(code: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """お客様の画面用：番号と、使ったかどうかだけ。"""
    c = _coupon_or_404(conn, code)
    return {"code": c["code"], "used": bool(c["redeemed_at"])}


@app.get("/api/coupons/{code}/qr.svg", include_in_schema=False)
def coupon_qr(code: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """QR の中身は受付の画面の URL だけ（番号のほか、個人情報は入れない）。"""
    import segno

    c = _coupon_or_404(conn, code)
    url = str(request.base_url).rstrip("/") + f"/desk/coupon/{c['code']}"
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=8, border=2, dark="#1f1a17", light="#ffffff")
    return Response(buf.getvalue(), media_type="image/svg+xml")


@app.get("/api/coupons/{code}")
def get_coupon(code: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """受付の画面用：施策・使ったかどうか・結ぶ予約。"""
    c = _coupon_or_404(conn, code)
    r = c["reservation"]
    return {
        "code": c["code"], "campaign": c["campaign"], "src": c["src"], "issued_at": c["issued_at"],
        "redeemed_at": c["redeemed_at"], "handled_by": c["handled_by"],
        "reservation": None if not r else {
            "reserve_no": r["reserve_no"], "menu": r["menu"], "confirmed_for": r["confirmed_for"],
            "status": r["status"], "customer_name": r["customer_name"], "visited_at": r["visited_at"],
        },
    }


class RedeemIn(StaffIn):
    with_visit: bool = False  # 予約のあるお客様なら、来店も一緒に記録する


@app.post("/api/coupons/{code}/redeem")
def redeem_coupon(code: str, body: RedeemIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """店でクーポンを使った（受付が「使った」を押した時だけ。画面を開いただけでは記録しない）。"""
    c = _coupon_or_404(conn, code)
    fn = ledger.redeem_coupon_with_visit if body.with_visit else ledger.redeem_coupon
    reserve_no = guard(fn, conn, c["code"], fmt(config.now()), body.staff)
    return {"ok": True, "reserve_no": reserve_no}


@app.post("/api/coupons/{code}/undo")
def undo_coupon(code: str, body: StaffIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """間違えて押した「使った」を取り消す（来店の記録は受付の画面で取り消す）。"""
    c = _coupon_or_404(conn, code)
    guard(ledger.undo_coupon, conn, c["code"], fmt(config.now()), body.staff)
    return {"ok": True}


# ---- API：ナットクに頼むメンテナンス（受付のタブ・前日のお知らせ） ----------------------------

class ChangeIn(BaseModel):
    staff: str
    text: str = Field(min_length=1, max_length=600)
    source_analysis_id: str | None = None


def _change_view(conn: sqlite3.Connection, row: dict) -> dict:
    """画面に出す形。見本（件数と一覧）は、出すたびにアプリが今の台帳で数える。"""
    p = json.loads(row["proposal_json"]) if row["proposal_json"] else {}
    tab = p.get("tab_checked")
    out = {k: row[k] for k in ("id", "created_at", "requested_by", "text", "source_analysis_id", "status",
                               "reason", "applied_version", "applied_by", "applied_at")}
    out.update(reply=p.get("reply"), mode=p.get("mode"), sample_text=p.get("sample_text"), tab=tab,
               conditions_text=maintenance.describe(tab["conditions"]) if tab else [])
    if tab:
        out["preview"] = maintenance.preview(ledger.list_reservations(conn, config.STORE_ID), tab["conditions"], config.TODAY)
    return out


@app.get("/api/change-requests")
def list_change_requests(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    version, settings = ledger.current_settings(conn)
    items = [_change_view(conn, r) for r in ledger.list_change_requests(conn)]
    last = next((i for i in items if i["status"] == "applied" and i["applied_version"] == version), None)
    return {"version": version, "tabs": [{"id": t["id"], "title": t["title"], "conditions_text": maintenance.describe(t["conditions"])}
                                         for t in settings["desk_tabs"]],
            "can_revert": bool(last), "items": items}


@app.get("/api/change-requests/draft")
def draft_change(from_analysis: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """分析の「次の一手」から、依頼の文の下書きを作る。"""
    run = analysis.get(conn, from_analysis)
    if not run or not run.get("report"):
        raise HTTPException(404, "その分析の報告がありません")
    return {"text": maintenance.draft_text(run["report"].get("next_action")), "source_analysis_id": from_analysis}


@app.post("/api/change-requests")
def create_change(body: ChangeIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """依頼を受けて、ナットク（Claude）に条件を提案させる。部品から外れた案は捨てる（記録は「捨てた」で残す）。"""
    if body.staff not in STAFF:
        raise HTTPException(400, "担当を選んでください")
    _, settings = ledger.current_settings(conn)
    rid = ledger.add_change_request(conn, fmt(config.now()), body.staff, body.text.strip(), body.source_analysis_id)
    try:
        proposal, mode = maintenance.propose(body.text.strip(), settings, force_sample=public.refuse_proposal(conn))
        tab = maintenance.check_proposal(proposal, settings)
    except maintenance.ProposalError as e:
        ledger.update_change_request(conn, rid, status="failed", reason=f"提案を捨てました：{e}",
                                     proposal_json=json.dumps({"mode": locals().get("mode")}, ensure_ascii=False))
        return _change_view(conn, ledger.get_change_request(conn, rid))
    except Exception as e:  # 呼び出しの失敗（通信・鍵など）
        ledger.update_change_request(conn, rid, status="failed", reason=f"提案を作れませんでした：{type(e).__name__}")
        raise HTTPException(502, "提案を作れませんでした。少し待ってからもう一度頼んでください") from e
    record = {"mode": mode, "reply": proposal.get("reply"), "raw": proposal, "tab_checked": tab,
              **({"sample_text": maintenance.sample_text()} if mode == "sample" else {})}
    ledger.update_change_request(conn, rid, proposal_json=json.dumps(record, ensure_ascii=False),
                                 **({} if tab else {"status": "rejected", "reason": "決まった部品では表せない依頼でした"}))
    return _change_view(conn, ledger.get_change_request(conn, rid))


@app.post("/api/change-requests/{request_id}/apply")
def apply_change(request_id: int, body: StaffIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """人が「反映する」を押した時だけ、設定の新しい版として保存する（add_desk_tab）。"""
    row = ledger.get_change_request(conn, request_id)
    if not row:
        raise HTTPException(404, "その依頼はありません")
    tab = (json.loads(row["proposal_json"] or "{}")).get("tab_checked")
    if not tab:
        raise HTTPException(400, "反映できる提案がありません")
    _, settings = ledger.current_settings(conn)
    try:
        tab = maintenance.validate_tab(tab)  # 保存の前にもう一度確かめる
        maintenance.check_proposal({"possible": True, "reply": "", "tab": tab}, settings)
    except maintenance.ProposalError as e:
        raise HTTPException(400, str(e)) from e
    new = maintenance.with_tab(settings, tab, f"tab{request_id}")
    version = guard(ledger.apply_change, conn, request_id, new, fmt(config.now()), body.staff)
    return {"ok": True, "version": version}


@app.post("/api/change-requests/{request_id}/reject")
def reject_change(request_id: int, body: StaffIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    row = ledger.get_change_request(conn, request_id)
    if not row or row["status"] != "proposed":
        raise HTTPException(400, "やめられるのは、まだ反映していない提案だけです")
    ledger.update_change_request(conn, request_id, status="rejected", reason=f"{body.staff} がやめた")
    return {"ok": True}


@app.post("/api/change-requests/revert-last")
def revert_last_change(body: StaffIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """さっきの変更を取り消す（設定だけ。お知らせの記録は消さない）。"""
    return {"ok": True, **guard(ledger.revert_last_change, conn, fmt(config.now()), body.staff)}


@app.get("/api/desk-tabs")
def desk_tabs(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """受付に足したタブと、それぞれに当てはまる予約番号（当てはめはアプリの側の1つの関数）・お知らせの記録。"""
    version, settings = ledger.current_settings(conn)
    rows = ledger.list_reservations(conn, config.STORE_ID)
    tabs = [{"id": t["id"], "title": t["title"], "conditions_text": maintenance.describe(t["conditions"]),
             "reserve_nos": [r["reserve_no"] for r in maintenance.match(rows, t["conditions"], config.TODAY)]}
            for t in settings["desk_tabs"]]
    reminders: dict[str, list] = {}
    for m in ledger.list_reminders(conn):
        reminders.setdefault(m["reserve_no"], []).append({k: m[k] for k in ("at", "result", "handled_by", "desk_tab_id")})
    return {"version": version, "tabs": tabs, "reminders": reminders}


class ReminderIn(BaseModel):
    staff: str
    reserve_no: str
    result: str
    desk_tab_id: str | None = None


@app.post("/api/reminders")
def add_reminder(body: ReminderIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """前日のお知らせの結果を残す（実際には送らず、記録だけの見本）。"""
    if body.staff not in STAFF:
        raise HTTPException(400, "担当を選んでください")
    rid = guard(ledger.add_reminder, conn, body.reserve_no, fmt(config.now()), body.result, body.staff, body.desk_tab_id)
    return {"ok": True, "id": rid}


@app.post("/api/reminders/{reserve_no}/undo")
def undo_reminder(reserve_no: str, body: StaffIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """間違えて押した最後の「送った」「返事あり」を取り消す（取り消した記録は reminder_undos に残る）。"""
    if body.staff not in STAFF:
        raise HTTPException(400, "担当を選んでください")
    result = guard(ledger.undo_last_reminder, conn, reserve_no, fmt(config.now()), body.staff)
    return {"ok": True, "undone": result}


# ---- API：分析担当の改善 ----------------------------------------------------------

def _improvement_view(row: dict) -> dict:
    """画面に出す形。報告の全文と指示文の全文は返さない（図・説明・本当の差分・物差しの数字だけ）。"""
    def ev(raw: str | None) -> dict | None:
        if not raw:
            return None
        e = json.loads(raw)
        one = lambda r: {k: r.get(k) for k in ("schema_ok", "matches", "rounds", "cost_cents", "tool_calls", "judge", "reused", "error")}
        return {"plant": one(e["plant"]), "noplant": one(e["noplant"]), "total_rounds": e["total_rounds"],
                "total_cost_cents": e["total_cost_cents"], "all_judge_ok": e["all_judge_ok"], "all_schema_ok": e["all_schema_ok"]}
    proposal = json.loads(row["proposal_json"]) if row["proposal_json"] else {}
    return {
        "id": row["id"], "created_at": row["created_at"], "iteration": row["iteration"], "status": row["status"],
        "decision": row["decision"], "reason": row["reason"], "applied_at": row["applied_at"],
        "explain": proposal.get("explain"), "eli5": proposal.get("eli5"), "plain": proposal.get("plain"),
        "eval_base": ev(row["eval_base_json"]), "eval_cand": ev(row["eval_cand_json"]),
    }


@app.get("/api/improvements")
def list_improvements(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    from app.analysis.agent_runner import MAX_GRADES

    items = [_improvement_view(r) for r in ledger.list_improvements(conn)]
    if items:
        return {"items": items, "max_grades": MAX_GRADES, "sample": False}
    # 台帳に見直しの記録が無い時（鍵が無い手元の起動など）は、作者が本物で回した記録を「見本の記録」として出す
    sample = config.ROOT / "agent" / "sample_improvements.json"
    data = json.loads(sample.read_text(encoding="utf-8")) if sample.exists() else {"items": []}
    return {"items": data["items"], "max_grades": MAX_GRADES, "sample": bool(data["items"])}


@app.post("/api/improvements/{improvement_id}/apply")
def apply_improvement(improvement_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """残した版を本番に使う（人が押した時だけ）。指示文のファイルを書き換え、エージェントの版を上げる。鍵が要る。"""
    from app import improve

    row = ledger.get_improvement(conn, improvement_id)
    if not row or row["decision"] != "kept":
        raise HTTPException(400, "物差しで残した版だけ本番に使えます")
    if row["applied_at"]:
        raise HTTPException(400, "この版はもう本番に使っています")
    current = improve.SYSTEM_PATH.read_text(encoding="utf-8")
    if current.replace("\r\n", "\n").strip() != row["base_system"].replace("\r\n", "\n").strip():
        raise HTTPException(409, "今の指示文が、この案を作った時と違います（別の直しが入った後です）。もう一度改善を回してください")
    improve.SYSTEM_PATH.write_text(row["candidate_system"], encoding="utf-8")
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("setup_agent", config.ROOT / "scripts" / "setup_agent.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
    except Exception as e:  # エージェントを更新できなければ、指示文も元に戻す
        improve.SYSTEM_PATH.write_text(current, encoding="utf-8")
        raise HTTPException(500, f"エージェントを更新できませんでした（指示文は元に戻しました）: {e}") from e
    ledger.update_improvement(conn, improvement_id, applied_at=fmt(config.now()))
    return {"ok": True}


# ---- API：予約 -----------------------------------------------------------------

class ReservationIn(BaseModel):
    session_id: str
    submit_key: str = Field(min_length=8)
    menu: str
    reserved_for: str
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
        reserved_for=normalize(body.reserved_for), created_at=fmt(config.now()),
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
    """予約の完了画面用。名前・電話は返さない。"""
    r = ledger.get_reservation(conn, reserve_no)
    if not r:
        raise HTTPException(404, "予約がありません")
    return {k: r[k] for k in ("reserve_no", "menu", "confirmed_for", "status")}


class RescheduleIn(StaffIn):
    confirmed_for: str
    desk_tab_id: str | None = None  # 開いていた足したタブ（お知らせの「日時を変えた」の記録に付ける）


@app.post("/api/reservations/{reserve_no}/reschedule")
def reschedule(reserve_no: str, body: RescheduleIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """日時を変える（お客様から連絡があった時に店が行う）。新しい日時の空きもここで確かめる。"""
    guard(ledger.reschedule, conn, reserve_no, normalize(body.confirmed_for), fmt(config.now()), body.staff,
          True, body.desk_tab_id)
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


class AnalysisIn(BaseModel):
    model: str = config.DEFAULT_MODEL


class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@app.post("/api/analysis")
def start_analysis(body: AnalysisIn | None = None,
                   conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    model = (body or AnalysisIn()).model
    if model not in config.MODELS:
        raise HTTPException(400, f"選べないモデルです: {model}")
    snap, fun = current_funnel(conn)
    notice = public.refuse_analysis(conn)  # 公開版の全体の上限・一度に1つまで。断る時は見本の報告を出す
    return {**analysis.start(conn, snap, fun, model, force_sample=bool(notice)), "notice": notice}


@app.get("/api/analysis-costs")
def analysis_costs(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """モデルごとの分析の費用の目安（定価で数えた額。正しい額は Claude Console で見る）。"""
    return analysis.costs(conn)


@app.post("/api/analysis/{analysis_id}/messages")
def ask_analysis(analysis_id: str, body: QuestionIn,
                 conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """分析の続きの質問（壁打ち）。同じエージェントのセッションに送り、答えは裏の処理で書く。"""
    if refused := public.refuse_question(conn):
        raise HTTPException(400, refused)
    try:
        return analysis.ask(conn, analysis_id, body.text)
    except analysis.RunError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/analysis/{analysis_id}")
def get_analysis(analysis_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    run = analysis.get(conn, analysis_id)
    if not run:
        raise HTTPException(404, "分析がありません")
    return run
