"""FastAPI application.

  uvicorn api.main:app --reload            API on http://localhost:8000 (docs at /docs)
The built web app (web/dist) is served from the same origin when present.
"""

from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api import config, db
from api.auth import authenticate, current_user, database, issue_token
from api.db import User
from api.errors import database_error
from api.routers import admin, analytics, offerings, student


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    db.close_pools()


app = FastAPI(title="CO-PO Attainment Management System", lifespan=lifespan)
app.add_exception_handler(psycopg.Error, database_error)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"],
                   allow_headers=["*"])


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginIn, dbname=Depends(database)):
    user = authenticate(body.username.strip().lower(), body.password, dbname)
    if not user:
        raise HTTPException(401, "Wrong username or password")
    return {"token": issue_token(user), "user": user.__dict__}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return user.__dict__


for r in (offerings.router, analytics.router, admin.router, student.router):
    app.include_router(r)

DIST = config.ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = DIST / path
        return FileResponse(target if path and target.is_file() else DIST / "index.html")
