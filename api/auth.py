"""Password login and bearer tokens (PRD FR-7.1)."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api import config, db
from api.db import User

TOKEN_HOURS = 8
_bearer = HTTPBearer(auto_error=False)


def authenticate(username: str, password: str, dbname: str | None = None) -> User | None:
    with db.anonymous(dbname) as conn:
        row = conn.execute("SELECT * FROM fn_login_lookup(%s)", (username,)).fetchone()
    if not row or not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return None
    return User(row["user_id"], username, row["role"], row["faculty_id"], row["usn"])


def issue_token(user: User) -> str:
    claims = {"sub": str(user.user_id), "username": user.username, "role": user.role,
              "faculty_id": user.faculty_id, "usn": user.usn,
              "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)}
    return jwt.encode(claims, config.jwt_secret(), algorithm="HS256")


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first")
    try:
        c = jwt.decode(creds.credentials, config.jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired; sign in again") from None
    return User(int(c["sub"]), c["username"], c["role"], c.get("faculty_id"), c.get("usn"))


def require(*roles: str):
    """Dependency: the caller must hold one of `roles`."""
    def check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot do this")
        return user
    return check


def database(request: Request) -> str | None:
    """Tests point the app at another database through app.state."""
    return getattr(request.app.state, "dbname", None)
