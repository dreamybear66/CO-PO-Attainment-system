"""Course-exit surveys as Google Forms (phase 8, FR-5.1, FR-5.3 to FR-5.5).

A form asks for college email, USN, name and phone number, then one 1-5 rating per CO. Reading
responses back, each one goes through the same checks as an in-app survey (services.surveys): the
email must be of the college domain, the USN enrolled, the offering finished, every CO rated once,
one response per student. Accepted responses are stored with a hashed USN only; email, name and
phone number are used for the checks and then dropped. Only counts are kept about the sync.
"""

import json
import re
from collections import Counter
from datetime import datetime, timezone

from psycopg.rows import dict_row
from pymongo.database import Database

from api import config
from api.google.client import Forms
from api.services.surveys import SurveyError, finished_sql, submit_survey

USN = re.compile(r"^\d[A-Z]{2}\d{2}[A-Z]{2}\d{3}$")
FIELDS = [("email", "College email", "Your @{domain} address"),
          ("usn", "USN", "For example 1RV24IS001"),
          ("name", "Name", "Used only to help you fill the form; not stored"),
          ("phone", "Phone number", "Not stored")]

REASONS = {
    "email": "Not a college email",
    "usn": "USN not in the right format",
    "enrolled": "USN not enrolled in this offering",
    "running": "Offering still running (some assessment unlocked)",
    "ratings": "Ratings incomplete or out of range",
    "other": "Other problem",
}


def form_content(code: str, title: str, year: str, section: str, cos: list[dict]) -> tuple[str, list[dict]]:
    """Form title and the batchUpdate requests that add the description and the questions."""
    form_title = f"{code} {title} - course-exit survey ({year}, section {section})"
    domain = config.college_email_domain()
    description = (
        "Rate how well this course helped you reach each course outcome (1 = not at all, 5 = fully). "
        f"Use your @{domain} email and your USN; they are used only to check that you are enrolled "
        "and answer once. Your name and phone number are not stored, and your ratings are stored "
        "without your USN.")
    requests = [{"updateFormInfo": {"info": {"description": description}, "updateMask": "description"}}]
    index = 0
    for _, label, help_text in FIELDS:
        requests.append({"createItem": {"location": {"index": index}, "item": {
            "title": label, "description": help_text.format(domain=domain),
            "questionItem": {"question": {"required": True, "textQuestion": {"paragraph": False}}}}}})
        index += 1
    for co in cos:
        requests.append({"createItem": {"location": {"index": index}, "item": {
            "title": f"CO{co['co_number']}: {co['statement']}",
            "questionItem": {"question": {"required": True, "scaleQuestion": {
                "low": 1, "high": 5, "lowLabel": "Not at all", "highLabel": "Fully"}}}}}})
        index += 1
    return form_title, requests


def create(conn, forms: Forms, offering: dict, cos: list[dict], owner_user_id: int) -> dict:
    """Create and publish the form, then record it. `conn` runs as the teacher (RLS applies)."""
    title, requests = form_content(offering["code"], offering["title"], offering["academic_year"],
                                   offering["section"], cos)
    form = forms.create(title)
    reply = forms.batch_update(form["formId"], requests)
    question_ids = [r["createItem"]["questionId"][0] for r in reply["replies"] if "createItem" in r]
    ids = {key: qid for (key, _, _), qid in zip(FIELDS, question_ids[:len(FIELDS)])}
    ids["cos"] = {str(co["co_id"]): qid for co, qid in zip(cos, question_ids[len(FIELDS):])}
    forms.publish(form["formId"])
    edit_uri = f"https://docs.google.com/forms/d/{form['formId']}/edit"
    conn.execute("""
        INSERT INTO survey_form (offering_id, form_id, responder_uri, edit_uri, owner_user_id, question_ids)
        VALUES (%s, %s, %s, %s, %s, %s)""",
                 (offering["offering_id"], form["formId"], form["responderUri"], edit_uri, owner_user_id,
                  json.dumps(ids)))
    return {"form_id": form["formId"], "responder_uri": form["responderUri"], "edit_uri": edit_uri}


def _text(response: dict, qid: str) -> str:
    answer = response.get("answers", {}).get(qid, {})
    values = answer.get("textAnswers", {}).get("answers", [])
    return values[0].get("value", "").strip() if values else ""


def sync(pg, mongo: Database, form: dict, forms: Forms) -> dict:
    """Read every response of the form and store the new valid ones. Safe to repeat: a response
    already stored is recognised by its student (one per student) and counted, not stored again."""
    ids = form["question_ids"]
    domain = "@" + config.college_email_domain()
    counts = Counter()
    responses = forms.responses(form["form_id"])
    for resp in responses:
        email = _text(resp, ids["email"]).lower()
        usn = _text(resp, ids["usn"]).upper().replace(" ", "")
        if not email.endswith(domain):
            counts["email"] += 1
            continue
        if not USN.match(usn):
            counts["usn"] += 1
            continue
        answers = []
        for co_id, qid in ids["cos"].items():
            value = _text(resp, qid)
            answers.append({"co_id": int(co_id), "rating": int(value) if value.isdigit() else value})
        try:
            submit_survey(pg, mongo, usn=usn, offering_id=form["offering_id"], survey_type="course_exit",
                          answers=answers)
            counts["accepted"] += 1
        except SurveyError as exc:
            msg = str(exc)
            key = ("already" if "already answered" in msg else "enrolled" if "not enrolled" in msg
                   else "running" if "still running" in msg else "ratings" if ("Rat" in msg or "rate" in msg)
                   else "other")
            counts[key] += 1
    summary = {"read": len(responses), "accepted": counts.pop("accepted", 0), "already": counts.pop("already", 0),
               "rejected": {REASONS[k]: n for k, n in counts.items()}}
    pg.execute("UPDATE survey_form SET last_synced_at = %s, last_sync = %s WHERE offering_id = %s",
               (datetime.now(timezone.utc), json.dumps(summary), form["offering_id"]))
    return summary


def dashboard(pg, mongo: Database, offering_id: int) -> dict:
    """Response rate and ratings per CO, from stored responses (anonymous) and the enrolment."""
    cur = pg.cursor(row_factory=dict_row)
    enrolled = cur.execute("SELECT count(*) AS n FROM enrollment WHERE offering_id = %s",
                           (offering_id,)).fetchone()["n"]
    finished = cur.execute(f"SELECT {finished_sql('%s')} AS f", (offering_id, offering_id)).fetchone()["f"]
    cos = cur.execute("""
        SELECT co.co_id, co.co_number, co.statement FROM course_outcome co
        JOIN course_offering o ON o.course_id = co.course_id WHERE o.offering_id = %s ORDER BY co.co_number""",
                      (offering_id,)).fetchall()
    # "Favourable" is the rule version's cut-off (default 4), as in the survey ETL.
    rule = cur.execute("SELECT favourable_rating AS f FROM attainment_config WHERE config_id = fn_result_config(%s)",
                       (offering_id,)).fetchone()
    favourable = rule["f"] if rule else 4
    responses = mongo.survey_responses.count_documents({"offering_id": offering_id, "survey_type": "course_exit"})
    dist = {(r["_id"]["co"], r["_id"]["rating"]): r["n"] for r in mongo.survey_responses.aggregate([
        {"$match": {"offering_id": offering_id, "survey_type": "course_exit"}},
        {"$unwind": "$answers"},
        {"$group": {"_id": {"co": "$answers.co_id", "rating": "$answers.rating"}, "n": {"$sum": 1}}}])}
    rows = []
    for co in cos:
        counts = [dist.get((co["co_id"], r), 0) for r in range(1, 6)]
        total = sum(counts)
        rows.append({**co, "counts": counts,
                     "favourable_pct": round(100 * sum(counts[favourable - 1:]) / total, 1) if total else None})
    return {"enrolled": enrolled, "responses": responses, "yet_to_respond": max(enrolled - responses, 0),
            "response_rate": round(100 * responses / enrolled, 1) if enrolled else None,
            "finished": finished, "favourable_rating": favourable, "cos": rows}
