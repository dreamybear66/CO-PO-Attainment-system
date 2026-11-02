"""Nightly survey ETL (PRD FR-5.2): MongoDB survey_responses -> PostgreSQL indirect_attainment.

For each (offering, CO): respondents and the % rating at or above the favourable_rating of the
offering's rule version. The 0-3 level is not stored: the engine derives it from the % with the
thresholds of each run. MongoDB is the source: groups that no longer have responses are removed.

Survey input feeds the official results, so every offering whose input changed and that already
has official results is recomputed in the same transaction, and the dashboards refreshed once.
An offering that cannot be computed now (an assessment was unlocked again) is reported and keeps
its results until it is locked and computed. Re-running is safe: unchanged rows are not written.
"""

import psycopg
from psycopg.rows import tuple_row
from pymongo.database import Database

# Counts per (offering, CO, rating), so the favourable cut-off can come from each offering's rule
# version. Only well-formed answers are counted.
PIPELINE = [
    {"$match": {"survey_type": "course_exit", "offering_id": {"$type": ["int", "long"]}}},
    {"$unwind": "$answers"},
    {"$match": {"answers.co_id": {"$type": ["int", "long"]},
                "answers.rating": {"$type": ["int", "long"], "$gte": 1, "$lte": 5}}},
    {"$group": {
        "_id": {"offering_id": "$offering_id", "co_id": "$answers.co_id", "rating": "$answers.rating"},
        "n": {"$sum": 1},
    }},
]

SYNC = """
WITH counts AS (
    SELECT * FROM unnest(%s::int[], %s::int[], %s::int[], %s::int[]) AS s(offering_id, co_id, rating, n)
),
survey AS (
    SELECT s.offering_id, s.co_id, sum(s.n)::int AS respondents,
           round(100.0 * coalesce(sum(s.n) FILTER (WHERE s.rating >= c.favourable_rating), 0) / sum(s.n), 2)
               AS pct_favourable
    FROM counts s
    JOIN v_offering_config oc ON oc.offering_id = s.offering_id
    JOIN attainment_config c  ON c.config_id = oc.config_id
    JOIN course_offering o    ON o.offering_id = s.offering_id
    JOIN course_outcome co    ON co.co_id = s.co_id AND co.course_id = o.course_id
    GROUP BY s.offering_id, s.co_id
),
upserted AS (
    INSERT INTO indirect_attainment (offering_id, co_id, respondents, pct_favourable, loaded_at)
    SELECT offering_id, co_id, respondents, pct_favourable, now() FROM survey
    ON CONFLICT (offering_id, co_id) DO UPDATE
    SET respondents = EXCLUDED.respondents, pct_favourable = EXCLUDED.pct_favourable, loaded_at = EXCLUDED.loaded_at
    WHERE (indirect_attainment.respondents, indirect_attainment.pct_favourable)       -- no no-op writes
          IS DISTINCT FROM (EXCLUDED.respondents, EXCLUDED.pct_favourable)
    RETURNING offering_id
),
removed AS (
    DELETE FROM indirect_attainment ia
    WHERE NOT EXISTS (SELECT 1 FROM survey s WHERE s.offering_id = ia.offering_id AND s.co_id = ia.co_id)
    RETURNING offering_id
),
touched AS (
    SELECT offering_id FROM upserted UNION SELECT offering_id FROM removed
)
SELECT (SELECT count(*) FROM survey)::int, (SELECT count(*) FROM upserted)::int, (SELECT count(*) FROM removed)::int,
       ARRAY(SELECT t.offering_id FROM touched t
             WHERE EXISTS (SELECT 1 FROM co_attainment ca WHERE ca.offering_id = t.offering_id)
             ORDER BY t.offering_id)
"""


def run_survey_etl(pg, mongo: Database) -> dict:
    """`pg` is an owner connection; commits on success. Returns, for logging: (offering, CO) groups
    found, rows changed and removed, groups skipped (unknown offering or CO, or no rule version),
    offerings recomputed, and offerings that could not be recomputed with the SQLSTATE."""
    rows = list(mongo.survey_responses.aggregate(PIPELINE))
    cols = tuple([r["_id"][k] for r in rows] for k in ("offering_id", "co_id", "rating")) + ([r["n"] for r in rows],)
    groups = len({(r["_id"]["offering_id"], r["_id"]["co_id"]) for r in rows})
    cur = pg.cursor(row_factory=tuple_row)
    recomputed, not_recomputed = [], {}
    with pg.transaction():
        matched, changed, removed, stale = cur.execute(SYNC, cols).fetchone()
        for offering_id in stale:
            try:
                with pg.transaction():
                    cur.execute("CALL sp_compute_attainment(%s, p_refresh => false)", (offering_id,))
                recomputed.append(offering_id)
            except psycopg.Error as exc:
                not_recomputed[offering_id] = exc.sqlstate
        if recomputed:
            cur.execute("SELECT fn_refresh_dashboards()")
    return {"groups": groups, "changed": changed, "removed": removed, "skipped": groups - matched,
            "recomputed": recomputed, "not_recomputed": not_recomputed}
