"""Early warning (phase 9, FR-6.5): who is likely to miss each CO, while the term is still running.

Once some CIE assessments of an offering are locked (its "stage", e.g. CIE Test 1 and Quiz 1), a
logistic regression is trained on earlier, finished offerings of the same course, looking only at
the same assessments there (same type, same order), and labelled with whether each student then
missed the CO's target at the end of that term. Features, for one student and one CO:

  co_so_far      marks so far on questions that test this CO (%); when no stage question tests the
                 CO, the marks on the whole stage stand in (co_tested = 0)
  prereq         the student's final score on the COs this CO builds on (co_dependency), from
                 earlier offerings (%), the same links root-cause analysis uses (prereq_known = 0
                 when there is none; the training mean stands in)

The whole-stage score is not a separate feature: it overlaps the CO score so much that its weight
came out with the wrong sign, which would make the reasons shown to teachers contradictory.

A student is flagged when the predicted chance of missing the CO reaches the rule version's
ew_flag_prob (default 0.5). The reasons shown are the features that pushed the chance up most.
Advisory only: nothing is written to the official result tables.

Training reads other teachers' finished offerings, so it runs on an owner connection; only the
fitted model leaves it. Saving the predictions goes through the teacher's own session (RLS).
"""

import json
from collections import defaultdict

import numpy as np
from psycopg.rows import dict_row

STAGE_TYPES = ("CIE_THEORY", "CIE_QUIZ", "EL")
FEATURES = ["co_so_far", "co_tested", "prereq", "prereq_known"]
SHOWN = {"co_so_far": "CO{co} marks so far", "prereq": "Prerequisite CO scores"}
MIN_EFFECT = 0.05                       # smaller pushes are not worth showing as a reason
MIN_TRAINING_ROWS = 100


class EarlyWarningError(ValueError):
    """Early warning cannot run for this offering; the message says why."""


def _cur(pg):
    return pg.cursor(row_factory=dict_row)


def _stage_keys(assessments: list[dict]) -> dict[tuple[str, int], dict]:
    """(type, rank within type) -> assessment, rank by creation order."""
    out, seen = {}, defaultdict(int)
    for a in sorted(assessments, key=lambda a: a["assessment_id"]):
        seen[a["type"]] += 1
        out[(a["type"], seen[a["type"]])] = a
    return out


def stage(pg, offering_id: int) -> list[dict]:
    rows = _cur(pg).execute("SELECT assessment_id, type::text AS type, name, locked FROM assessment "
                            "WHERE offering_id = %s", (offering_id,)).fetchall()
    keys = _stage_keys(rows)
    if rows and all(r["locked"] for r in rows) and any(r["type"] == "SEE" for r in rows):
        raise EarlyWarningError("Every assessment is locked: the term's results are in, so there is nothing left to warn about")
    picked = [{"type": t, "rank": r, "name": a["name"], "assessment_id": a["assessment_id"]}
              for (t, r), a in sorted(keys.items()) if a["locked"] and t in STAGE_TYPES]
    if not picked:
        raise EarlyWarningError("Lock a CIE test, quiz or EL assessment first; the warning starts from locked marks")
    return picked


def _marks(pg, assessment_ids: list[int]) -> dict:
    """(offering, usn) -> {"co": {co_id: [got, max]}, "all": [got, max]} over the given assessments."""
    out: dict = defaultdict(lambda: {"co": defaultdict(lambda: [0.0, 0.0]), "all": [0.0, 0.0]})
    for r in _cur(pg).execute("""
            SELECT e.offering_id, e.usn, qcm.co_id,
                   sum(coalesce(m.marks_obtained, 0) * qcm.weight)::float AS got,
                   sum(aq.max_marks * qcm.weight)::float AS mx
            FROM student_question_mark m
            JOIN enrollment e USING (enrollment_id)
            JOIN assessment_question aq USING (question_id)
            JOIN question_co_map qcm USING (question_id)
            WHERE aq.assessment_id = ANY(%s)
            GROUP BY e.offering_id, e.usn, qcm.co_id""", (assessment_ids,)):
        d = out[(r["offering_id"], r["usn"])]
        d["co"][r["co_id"]][0] += r["got"]
        d["co"][r["co_id"]][1] += r["mx"]
        d["all"][0] += r["got"]           # CO weights of a question add up to 1, so this sums questions
        d["all"][1] += r["mx"]
    return out


def _prereq_scores(pg, course_id: int, usns: list[str]) -> dict:
    """(usn, co_id) -> [(term start, % on a prerequisite CO), ...] for the course's COs.
    Reads the score view filtered to the prerequisite courses' offerings, which the planner pushes
    down (a fraction of a second, against seconds for every mark or a call per offering)."""
    cur = _cur(pg)
    pre = cur.execute("""
        SELECT d.co_id, d.prereq_co_id, p.course_id AS pre_course
        FROM co_dependency d
        JOIN course_outcome co ON co.co_id = d.co_id AND co.course_id = %s
        JOIN course_outcome p  ON p.co_id = d.prereq_co_id""", (course_id,)).fetchall()
    if not pre:
        return {}
    offerings = [r["offering_id"] for r in cur.execute(
        "SELECT offering_id FROM course_offering WHERE course_id = ANY(%s)",
        (sorted({r["pre_course"] for r in pre}),))]
    builds_on = defaultdict(list)
    for r in pre:
        builds_on[r["prereq_co_id"]].append(r["co_id"])
    out = defaultdict(list)
    for r in cur.execute("""
            SELECT s.usn, s.co_id, fn_term_start(o.academic_year, o.term) AS start, s.pct::float AS pct
            FROM student_co_score s JOIN course_offering o USING (offering_id)
            WHERE s.offering_id = ANY(%s) AND s.co_id = ANY(%s) AND s.usn = ANY(%s)""",
                         (offerings, list(builds_on), usns)):
        for co in builds_on[r["co_id"]]:
            out[(r["usn"], co)].append((r["start"], r["pct"]))
    return out


def _rows(marks: dict, offering_id: int, usns: list[str], cos: list[int], prereq: dict, before) -> list[dict]:
    rows = []
    for usn in usns:
        d = marks.get((offering_id, usn))
        overall = 100 * d["all"][0] / d["all"][1] if d and d["all"][1] else 0.0
        for co in cos:
            got, mx = d["co"].get(co, (0, 0)) if d else (0, 0)
            earlier = [p for start, p in prereq.get((usn, co), []) if start < before]
            rows.append({"usn": usn, "co_id": co,
                         "co_so_far": 100 * got / mx if mx else None, "overall": overall,
                         "prereq": float(np.mean(earlier)) if earlier else None})
    return rows


def _matrix(rows: list[dict], fill: dict | None = None) -> tuple[np.ndarray, dict]:
    """Features with missing values filled (CO marks by overall marks, prerequisites by the training
    mean) and a 0/1 column saying whether the value was there."""
    prereqs = [r["prereq"] for r in rows if r["prereq"] is not None]
    fill = fill or {"prereq": float(np.mean(prereqs)) if prereqs else 0.0}
    x = np.array([[r["co_so_far"] if r["co_so_far"] is not None else r["overall"],
                   1.0 if r["co_so_far"] is not None else 0.0,
                   r["prereq"] if r["prereq"] is not None else fill["prereq"],
                   1.0 if r["prereq"] is not None else 0.0] for r in rows], dtype=float)
    return x, fill


def predict(owner_pg, offering_id: int, keys: list[tuple[str, int]] | None = None) -> dict:
    """Train on earlier finished offerings of the course and predict for this one. `keys` replays a
    stage, e.g. [("CIE_THEORY", 1)], whatever is locked (scripts/evaluate_early_warning.py)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    cur = _cur(owner_pg)
    off = cur.execute("""
        SELECT o.offering_id, o.course_id, fn_term_start(o.academic_year, o.term) AS start, oc.config_id,
               ac.target_pct::float AS target_pct, ac.ew_flag_prob::float AS flag_prob
        FROM course_offering o JOIN v_offering_config oc USING (offering_id)
        JOIN attainment_config ac USING (config_id) WHERE o.offering_id = %s""", (offering_id,)).fetchone()
    if not off:
        raise EarlyWarningError("Offering not found or no rule version for its term")
    if keys is None:
        st = stage(owner_pg, offering_id)
    else:
        mine = _stage_keys(cur.execute("SELECT assessment_id, type::text AS type, name FROM assessment "
                                       "WHERE offering_id = %s", (offering_id,)).fetchall())
        st = [{"type": t, "rank": r, "name": mine[(t, r)]["name"], "assessment_id": mine[(t, r)]["assessment_id"]}
              for t, r in keys if (t, r) in mine]
        if len(st) != len(keys):
            raise EarlyWarningError("The offering does not have every assessment of that stage")
    keys = [(s["type"], s["rank"]) for s in st]

    # Earlier finished offerings of the same course that have the same assessments.
    earlier = cur.execute("""
        SELECT o.offering_id FROM course_offering o
        WHERE o.course_id = %s AND fn_term_start(o.academic_year, o.term) < %s
          AND EXISTS (SELECT 1 FROM assessment a WHERE a.offering_id = o.offering_id)
          AND NOT EXISTS (SELECT 1 FROM assessment a WHERE a.offering_id = o.offering_id AND NOT a.locked)""",
                          (off["course_id"], off["start"])).fetchall()
    train_assessments, train_offerings = [], []
    for e in earlier:
        ks = _stage_keys(cur.execute("SELECT assessment_id, type::text AS type FROM assessment WHERE offering_id = %s",
                                     (e["offering_id"],)).fetchall())
        if all(k in ks for k in keys):
            train_offerings.append(e["offering_id"])
            train_assessments += [ks[k]["assessment_id"] for k in keys]
    if not train_offerings:
        raise EarlyWarningError("No earlier finished offering of this course has the same assessments to learn from")

    cos = [r["co_id"] for r in cur.execute("SELECT co_id FROM course_outcome WHERE course_id = %s ORDER BY co_number",
                                           (off["course_id"],))]
    co_number = {r["co_id"]: r["co_number"] for r in cur.execute(
        "SELECT co_id, co_number FROM course_outcome WHERE course_id = %s", (off["course_id"],))}
    enrolled = cur.execute("SELECT e.offering_id, e.usn, fn_term_start(o.academic_year, o.term) AS start "
                           "FROM enrollment e JOIN course_offering o USING (offering_id) "
                           "WHERE e.offering_id = ANY(%s)", (train_offerings + [offering_id],)).fetchall()
    prereq = _prereq_scores(owner_pg, off["course_id"], sorted({r["usn"] for r in enrolled}))
    labels = {(r["offering_id"], r["usn"], r["co_id"]): r["missed"] for r in cur.execute("""
        SELECT s.offering_id, s.usn, s.co_id, (s.pct < ac.target_pct) AS missed
        FROM student_co_score s JOIN v_offering_config oc USING (offering_id) JOIN attainment_config ac USING (config_id)
        WHERE s.offering_id = ANY(%s)""", (train_offerings,))}

    marks = _marks(owner_pg, train_assessments + [s["assessment_id"] for s in st])
    by_offering = defaultdict(list)
    for r in enrolled:
        by_offering[(r["offering_id"], r["start"])].append(r["usn"])
    train_rows, y = [], []
    for (oid, start), usns in by_offering.items():
        if oid == offering_id:
            continue
        for row in _rows(marks, oid, usns, cos, prereq, start):
            label = labels.get((oid, row["usn"], row["co_id"]))
            if label is not None:
                train_rows.append(row)
                y.append(1 if label else 0)
    y = np.array(y)
    if len(y) < MIN_TRAINING_ROWS or y.min() == y.max():
        raise EarlyWarningError("Earlier offerings do not give enough examples (both students who met and who "
                                "missed a CO) to learn from")

    x, fill = _matrix(train_rows)
    mean, sd = x.mean(axis=0), x.std(axis=0)
    use = sd > 1e-9                                   # a feature that never varies cannot inform
    z = (x[:, use] - mean[use]) / sd[use]
    model = LogisticRegression(max_iter=1000).fit(z, y)
    auc = float(roc_auc_score(y, model.predict_proba(z)[:, 1]))

    usns = [r["usn"] for r in enrolled if r["offering_id"] == offering_id]
    rows = _rows(marks, offering_id, usns, cos, prereq, off["start"])
    xt, _ = _matrix(rows, fill)
    zt = (xt[:, use] - mean[use]) / sd[use]
    proba = model.predict_proba(zt)[:, 1]
    names = [f for f, u in zip(FEATURES, use) if u]
    coef = dict(zip(names, model.coef_[0]))
    typical = {f: float(np.median(x[:, i])) for i, f in enumerate(FEATURES)}
    out = []
    for row, p, zrow in zip(rows, proba, zt):
        effects = dict(zip(names, model.coef_[0] * zrow))
        shown = {"co_so_far": row["co_so_far"] if row["co_so_far"] is not None else row["overall"], "prereq": row["prereq"]}
        labels = dict(SHOWN, co_so_far="CO{co} marks so far" if row["co_so_far"] is not None
                      else "All marks so far (CO{co} not tested yet)")
        reasons = [{"feature": f, "label": labels[f].format(co=co_number[row["co_id"]]),
                    "value": round(shown[f], 1), "typical": round(typical[f], 1), "effect": round(float(e), 3)}
                   for f, e in sorted(effects.items(), key=lambda kv: -kv[1])
                   if f in SHOWN and e > MIN_EFFECT and shown[f] is not None]
        out.append({"usn": row["usn"], "co_id": row["co_id"], "probability": round(float(p), 3),
                    "flagged": bool(p >= off["flag_prob"]), "reasons": reasons[:3]})
    return {
        "config_id": off["config_id"], "flag_prob": off["flag_prob"],
        "stage": [{k: s[k] for k in ("type", "rank", "name")} for s in st],
        "model": {"kind": "logistic regression", "features": names,
                  "coefficients": {f: round(float(c), 4) for f, c in coef.items()},
                  "training_offerings": len(train_offerings), "training_rows": int(len(y)),
                  "missed_share": round(float(y.mean()), 3), "training_auc": round(auc, 3)},
        "predictions": out,
    }


def save(pg, offering_id: int, result: dict) -> None:
    """Replace the offering's run with `result`. `pg` runs as the teacher, so RLS checks ownership.
    Runs of one offering are saved one at a time (advisory lock), so a lock-triggered run and a
    Run button pressed at the same moment queue instead of colliding on the primary key."""
    pg.execute("SELECT pg_advisory_xact_lock(hashtext('early_warning'), %s)", (offering_id,))
    pg.execute("DELETE FROM early_warning_run WHERE offering_id = %s", (offering_id,))
    pg.execute("INSERT INTO early_warning_run (offering_id, config_id, stage, model, flag_prob) "
               "VALUES (%s, %s, %s, %s, %s)",
               (offering_id, result["config_id"], json.dumps(result["stage"]), json.dumps(result["model"]),
                result["flag_prob"]))
    p = result["predictions"]
    with pg.cursor() as cur:
        cur.executemany("INSERT INTO early_warning (offering_id, usn, co_id, probability, flagged, reasons) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        [(offering_id, r["usn"], r["co_id"], r["probability"], r["flagged"], json.dumps(r["reasons"]))
                         for r in p])
