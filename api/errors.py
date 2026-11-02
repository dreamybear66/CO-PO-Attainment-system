"""Map database errors to HTTP responses with the database's own message."""

import psycopg
from fastapi import Request
from fastapi.responses import JSONResponse

# SQLSTATE -> HTTP status
STATUS = {
    "CP001": 409,   # locked assessment
    "CP002": 422,   # marks out of range
    "CP003": 422,   # cross-offering / cross-course reference
    "CP004": 422,   # weights do not sum
    "CP005": 422,   # dependency outside graph or cycle
    "CP006": 409,   # cannot lock yet
    "CP007": 409,   # unlock not approved
    "CP010": 404,
    "CP011": 409,
    "CP012": 409,   # assessments missing or unlocked
    "CP013": 409,   # CO not assessed
    "CP014": 422,
    "42501": 403,   # insufficient privilege / not allowed
    "23505": 409,   # unique violation
    "23503": 422,   # foreign key violation
    "23514": 422,   # check violation
    "23P01": 409,   # exclusion violation (overlapping rule versions)
    "55P03": 409,   # lock not available (concurrent compute)
}


def message(exc: psycopg.Error) -> str:
    diag = exc.diag.message_primary if exc.diag else None
    return diag or str(exc).splitlines()[0]


async def database_error(request: Request, exc: psycopg.Error) -> JSONResponse:
    code = exc.sqlstate or ""
    return JSONResponse({"detail": message(exc), "code": code}, status_code=STATUS.get(code, 500))
