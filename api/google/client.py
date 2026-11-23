"""OAuth for one teacher's Google account and the few Forms API calls the surveys need.

Tests replace `transport` with an httpx.MockTransport, so the suite never calls Google.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken

from api import config

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
FORMS_URL = "https://forms.googleapis.com/v1"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
SCOPES = ["openid", "email",
          "https://www.googleapis.com/auth/forms.body",
          "https://www.googleapis.com/auth/forms.responses.readonly",
          "https://www.googleapis.com/auth/drive.file"]          # only to delete a form this app made
STATE_AUDIENCE = "google-connect"          # a state token can never pass as a sign-in token

transport: httpx.BaseTransport | None = None


class GoogleError(RuntimeError):
    """Google refused or could not be reached; the message is safe to show."""


def http() -> httpx.Client:
    return httpx.Client(timeout=30, transport=transport)


def configured() -> bool:
    return bool(config.google_client_id() and config.google_client_secret() and config.google_token_key())


# ---------------------------------------------------------------- tokens at rest

def _fernet() -> Fernet:
    return Fernet(config.google_token_key().encode())


def encrypt(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt(token_enc: str) -> str:
    try:
        return _fernet().decrypt(token_enc.encode()).decode()
    except InvalidToken:
        raise GoogleError("The stored Google connection cannot be read (GOOGLE_TOKEN_KEY changed?); "
                          "connect Google again") from None


# ---------------------------------------------------------------- sign-in

def nonce_hash(nonce: str) -> str:
    import hashlib
    return hashlib.sha256(nonce.encode()).hexdigest()


def state_token(user_id: int, username: str, return_to: str, nonce: str) -> str:
    """Signed state for the Google round trip. It carries the hash of a nonce that is also set as an
    HttpOnly cookie in the browser that started the sign-in, so the callback only accepts that browser."""
    claims = {"aud": STATE_AUDIENCE, "uid": user_id, "un": username, "ret": return_to, "nh": nonce_hash(nonce),
              "exp": datetime.now(timezone.utc) + timedelta(minutes=10)}
    return jwt.encode(claims, config.jwt_secret(), algorithm="HS256")


def read_state(token: str) -> dict:
    try:
        return jwt.decode(token, config.jwt_secret(), algorithms=["HS256"], audience=STATE_AUDIENCE)
    except jwt.PyJWTError:
        raise GoogleError("The Google sign-in link expired; start again from the app") from None


def auth_url(state: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": config.google_client_id(), "redirect_uri": config.google_redirect_uri(),
        "response_type": "code", "scope": " ".join(SCOPES), "access_type": "offline",
        "prompt": "consent", "include_granted_scopes": "true", "state": state})


def _post_token(data: dict) -> dict:
    with http() as c:
        try:
            r = c.post(TOKEN_URL, data={"client_id": config.google_client_id(),
                                        "client_secret": config.google_client_secret(), **data})
        except httpx.HTTPError as exc:
            raise GoogleError("Google could not be reached; try again") from exc
    if r.status_code != 200:
        raise GoogleError(f"Google refused the sign-in ({r.json().get('error', r.status_code)}); connect again")
    return r.json()


def exchange(code: str) -> tuple[str, str]:
    """Authorisation code -> (refresh token, Google email)."""
    tok = _post_token({"code": code, "grant_type": "authorization_code",
                       "redirect_uri": config.google_redirect_uri()})
    if "refresh_token" not in tok:
        raise GoogleError("Google did not grant offline access; remove the app from your Google "
                          "account's third-party access and connect again")
    payload = tok.get("id_token", "").split(".")[1] if tok.get("id_token") else ""
    email = ""
    if payload:   # the id_token came straight from Google over TLS; only the email is read from it
        email = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("email", "")
    return tok["refresh_token"], email


def access_token(refresh_token: str) -> str:
    return _post_token({"refresh_token": refresh_token, "grant_type": "refresh_token"})["access_token"]


def revoke(token: str) -> None:
    with http() as c:
        try:
            c.post(REVOKE_URL, params={"token": token})
        except httpx.HTTPError:
            pass                      # the local copy is deleted either way


# ---------------------------------------------------------------- Forms API

class Forms:
    """The calls the course-exit survey needs, with one access token."""

    def __init__(self, token: str):
        self.client = httpx.Client(base_url=FORMS_URL, timeout=30, transport=transport,
                                   headers={"Authorization": f"Bearer {token}"})

    def _call(self, method: str, path: str, **kw) -> dict:
        try:
            r = self.client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise GoogleError("Google Forms could not be reached; try again") from exc
        if r.status_code >= 400:
            detail = r.json().get("error", {}).get("message", "") if r.headers.get("content-type", "").startswith("application/json") else ""
            raise GoogleError(f"Google Forms refused the request ({r.status_code}{': ' + detail if detail else ''})")
        return r.json() if r.content else {}

    def create(self, title: str) -> dict:
        return self._call("POST", "/forms", json={"info": {"title": title, "documentTitle": title}})

    def delete(self, form_id: str) -> None:
        """Best effort: remove a form this app created (Drive API, drive.file scope)."""
        try:
            r = self.client.delete(f"{DRIVE_FILES_URL}/{form_id}")
        except httpx.HTTPError as exc:
            raise GoogleError("Google Drive could not be reached") from exc
        if r.status_code >= 400:
            raise GoogleError(f"Google Drive refused to delete the form ({r.status_code})")

    def batch_update(self, form_id: str, requests: list[dict]) -> dict:
        return self._call("POST", f"/forms/{form_id}:batchUpdate", json={"requests": requests})

    def publish(self, form_id: str) -> None:
        """Forms made through the API may start unpublished; open this one for responses. Older API
        versions without publish settings answer 400/404, and their forms are already open."""
        try:
            self._call("POST", f"/forms/{form_id}:setPublishSettings", json={
                "publishSettings": {"publishState": {"isPublished": True, "isAcceptingResponses": True}},
                "updateMask": "publishState"})
        except GoogleError as exc:
            if "(400" not in str(exc) and "(404" not in str(exc):
                raise

    def responses(self, form_id: str) -> list[dict]:
        out, page = [], None
        while True:
            body = self._call("GET", f"/forms/{form_id}/responses", params={"pageToken": page} if page else None)
            out += body.get("responses", [])
            page = body.get("nextPageToken")
            if not page:
                return out

    def close(self) -> None:
        self.client.close()
