"""Nightly survey ETL (PRD FR-5.2): MongoDB survey_responses -> PostgreSQL indirect_attainment.

For each (offering, CO): respondents and the % rating at or above the favourable_rating of the
offering's rule version. The 0-3 level is not stored: the engine derives it from the % with the
thresholds of each run. Upserts, so re-running is safe.
"""

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

UPSERT = """
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
)
SELECT (SELECT count(*) FROM survey)::int, (SELECT count(*) FROM upserted)::int
"""


def run_survey_etl(pg, mongo: Database) -> dict:
    """`pg` is an owner connection; commits on success. Returns counts for logging: (offering, CO)
    groups found, rows changed, and groups skipped (unknown offering or CO, or no rule version)."""
    rows = list(mongo.survey_responses.aggregate(PIPELINE))
    cols = tuple([r["_id"][k] for r in rows] for k in ("offering_id", "co_id", "rating")) + ([r["n"] for r in rows],)
    groups = len({(r["_id"]["offering_id"], r["_id"]["co_id"]) for r in rows})
    with pg.transaction():
        matched, changed = pg.cursor(row_factory=tuple_row).execute(UPSERT, cols).fetchone()
    return {"groups": groups, "changed": changed, "skipped": groups - matched}
