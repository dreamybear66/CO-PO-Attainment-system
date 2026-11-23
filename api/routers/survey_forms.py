"""Google sign-in for teachers and course-exit surveys as Google Forms (phase 8).

GET    /api/google/status                      is Google set up, and is my account connected
GET    /api/google/connect?return_to=/path     the Google sign-in address
GET    /api/google/callback                    Google returns here (browser redirect, no bearer token)
POST   /api/google/disconnect                  revoke and forget my Google connection
GET    /api/offerings/{id}/survey-form         the form, its last fetch and the response dashboard
POST   /api/offerings/{id}/survey-form         create the form in my Google account
POST   /api/offerings/{id}/survey-form/sync    fetch new responses now (the form's owner)
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from psycopg.rows import dict_row

from api import db
from api.auth import database, require
from api.db import User
from api.google import client as google
from api.mongo import get_db
from api.services import survey_forms

router = APIRouter(prefix="/api")
editors = require("admin", "faculty")
staff = require("admin", "faculty", "coordinator")


def _mongo(request: Request):
    return get_db(getattr(request.app.state, "mongo_name", None))


def _safe_path(path: str | None) -> str:
    """Only paths inside this app (no //host, no scheme), so the redirect cannot leave the site."""
    return path if path and path.startswith("/") and not path.startswith("//") and "\\" not in path else "/"


def _account(conn) -> dict | None:
    return conn.execute(
        "SELECT google_email, refresh_token_enc FROM google_account WHERE user_id = fn_my_user_id()").fetchone()


def _forms_for(token_enc: str) -> google.Forms:
    return google.Forms(google.access_token(google.decrypt(token_enc)))


# ---------------------------------------------------------------- connecting a Google account

@router.get("/google/status")
def status(user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        acc = _account(conn)
    return {"configured": google.configured(), "connected": acc is not None,
            "email": acc["google_email"] if acc else None}


@router.get("/google/connect")
def connect(return_to: str = "/", user: User = Depends(editors)):
    if not google.configured():
        raise HTTPException(409, "Google is not set up on this server yet (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET "
                                 "and GOOGLE_TOKEN_KEY in .env)")
    return {"url": google.auth_url(google.state_token(user.user_id, user.username, _safe_path(return_to)))}


@router.get("/google/callback", include_in_schema=False)
def callback(state: str, code: str | None = None, error: str | None = None, dbname=Depends(database)):
    try:
        st = google.read_state(state)
    except google.GoogleError as exc:
        return RedirectResponse(f"/?google_error={quote(str(exc))}", status_code=303)
    back = _safe_path(st.get("ret"))
    sep = "&" if "?" in back else "?"
    if error or not code:
        return RedirectResponse(f"{back}{sep}google_error={quote('Google sign-in was cancelled')}", status_code=303)
    try:
        refresh, email = google.exchange(code)
    except google.GoogleError as exc:
        return RedirectResponse(f"{back}{sep}google_error={quote(str(exc))}", status_code=303)
    with db.anonymous(dbname) as conn:
        row = conn.execute("SELECT * FROM fn_login_lookup(%s)", (st["un"],)).fetchone()
    if not row or row["user_id"] != st["uid"] or row["role"] not in ("admin", "faculty"):
        return RedirectResponse(f"{back}{sep}google_error={quote('Unknown user; sign in again')}", status_code=303)
    user = User(row["user_id"], st["un"], row["role"], row["faculty_id"], row["usn"])
    with db.session(user, dbname) as conn:
        conn.execute("""
            INSERT INTO google_account (user_id, google_email, refresh_token_enc) VALUES (fn_my_user_id(), %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET google_email = EXCLUDED.google_email,
                refresh_token_enc = EXCLUDED.refresh_token_enc, connected_at = now()""",
                     (email or "unknown", google.encrypt(refresh)))
    return RedirectResponse(f"{back}{sep}google=connected", status_code=303)


@router.post("/google/disconnect")
def disconnect(user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        acc = _account(conn)
        if acc:
            conn.execute("DELETE FROM google_account WHERE user_id = fn_my_user_id()")
    if acc and google.configured():
        try:
            google.revoke(google.decrypt(acc["refresh_token_enc"]))
        except google.GoogleError:
            pass                      # the stored copy is gone either way
    return {"connected": False}


# ---------------------------------------------------------------- the survey form of an offering

def _offering(conn, offering_id: int) -> dict:
    row = conn.execute("""
        SELECT o.offering_id, o.academic_year, o.section, c.code, c.title
        FROM course_offering o JOIN course c USING (course_id)
        WHERE o.offering_id = %s AND fn_can_view_offering(o.offering_id)""", (offering_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Offering not found")
    return row


def _form(conn, offering_id: int) -> dict | None:
    return conn.execute("SELECT * FROM survey_form WHERE offering_id = %s", (offering_id,)).fetchone()


def _public(form: dict | None, user: User) -> dict | None:
    if not form:
        return None
    keep = ("form_id", "responder_uri", "edit_uri", "created_at", "last_synced_at", "last_sync")
    return {k: form[k] for k in keep} | {"mine": form["owner_user_id"] == user.user_id}


@router.get("/offerings/{offering_id}/survey-form")
def get_form(offering_id: int, request: Request, user: User = Depends(staff), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        _offering(conn, offering_id)
        form = _form(conn, offering_id)
        dash = survey_forms.dashboard(conn, _mongo(request), offering_id)
    return {"form": _public(form, user), "dashboard": dash, "google_configured": google.configured()}


@router.post("/offerings/{offering_id}/survey-form", status_code=201)
def create_form(offering_id: int, user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        offering = _offering(conn, offering_id)
        if _form(conn, offering_id):
            raise HTTPException(409, "This offering already has a survey form")
        acc = _account(conn)
        if not acc:
            raise HTTPException(409, "Connect your Google account first")
        cos = conn.execute("""
            SELECT co.co_id, co.co_number, co.statement FROM course_outcome co
            JOIN course_offering o ON o.course_id = co.course_id WHERE o.offering_id = %s ORDER BY co.co_number""",
                           (offering_id,)).fetchall()
        if not cos:
            raise HTTPException(409, "The course has no COs to ask about")
        try:
            forms = _forms_for(acc["refresh_token_enc"])
            try:
                made = survey_forms.create(conn, forms, offering, cos, user.user_id)
            finally:
                forms.close()
        except google.GoogleError as exc:
            raise HTTPException(502, str(exc)) from None
    return made


@router.post("/offerings/{offering_id}/survey-form/sync")
def sync_form(offering_id: int, request: Request, user: User = Depends(editors), dbname=Depends(database)):
    with db.session(user, dbname) as conn:
        _offering(conn, offering_id)
        form = _form(conn, offering_id)
        if not form:
            raise HTTPException(404, "This offering has no survey form yet")
        if form["owner_user_id"] != user.user_id:
            raise HTTPException(403, "Only the teacher who created the form can fetch its responses now; "
                                     "the nightly job fetches them for everyone")
        acc = _account(conn)
        if not acc:
            raise HTTPException(409, "Connect your Google account again to fetch responses")
        try:
            forms = _forms_for(acc["refresh_token_enc"])
            try:
                summary = survey_forms.sync(conn, _mongo(request), form, forms)
            finally:
                forms.close()
        except google.GoogleError as exc:
            raise HTTPException(502, str(exc)) from None
    return summary


def sync_all(pg, mongo) -> dict:
    """Nightly: fetch every form's responses with its owner's Google connection (owner connection,
    so row-level security does not apply). A form whose owner disconnected is skipped and reported."""
    pg.row_factory = dict_row
    out = {"forms": 0, "accepted": 0, "skipped": []}
    rows = pg.execute("""
        SELECT f.*, g.refresh_token_enc FROM survey_form f
        LEFT JOIN google_account g ON g.user_id = f.owner_user_id ORDER BY f.offering_id""").fetchall()
    for form in rows:
        if not form["refresh_token_enc"]:
            out["skipped"].append({"offering_id": form["offering_id"], "reason": "owner not connected to Google"})
            continue
        try:
            forms = _forms_for(form["refresh_token_enc"])
            try:
                summary = survey_forms.sync(pg, mongo, form, forms)
            finally:
                forms.close()
        except google.GoogleError as exc:
            out["skipped"].append({"offering_id": form["offering_id"], "reason": str(exc)})
            continue
        out["forms"] += 1
        out["accepted"] += summary["accepted"]
    return out
