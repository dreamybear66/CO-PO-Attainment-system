"""Nightly survey ETL (PRD FR-5.2): MongoDB survey_responses -> PostgreSQL indirect_attainment.

For each (offering, CO): respondents, % rating 4 or 5, and a 0-3 level from the same thresholds
as direct attainment (the offering's rule version). Upserts, so re-running is safe.
"""

from pymongo.database import Database

PIPELINE = [
    {"$match": {"survey_type": "course_exit"}},
    {"$unwind": "$answers"},
    {"$group": {
        "_id": {"offering_id": "$offering_id", "co_id": "$answers.co_id"},
        "respondents": {"$sum": 1},
        "favourable": {"$sum": {"$cond": [{"$gte": ["$answers.rating", 4]}, 1, 0]}},
    }},
]

UPSERT = """
INSERT INTO indirect_attainment (offering_id, co_id, respondents, pct_favourable, level, loaded_at)
SELECT s.offering_id, s.co_id, s.respondents,
       round(100.0 * s.favourable / s.respondents, 2),
       fn_level(100.0 * s.favourable / s.respondents, c.l3_pct, c.l2_pct, c.l1_pct),
       now()
FROM unnest(%s::int[], %s::int[], %s::int[], %s::int[]) AS s(offering_id, co_id, respondents, favourable)
JOIN v_offering_config oc ON oc.offering_id = s.offering_id
JOIN attainment_config c  ON c.config_id = oc.config_id
JOIN course_offering o    ON o.offering_id = s.offering_id
JOIN course_outcome co    ON co.co_id = s.co_id AND co.course_id = o.course_id
ON CONFLICT (offering_id, co_id) DO UPDATE
SET respondents = EXCLUDED.respondents, pct_favourable = EXCLUDED.pct_favourable,
    level = EXCLUDED.level, loaded_at = EXCLUDED.loaded_at
"""


def run_survey_etl(pg, mongo: Database) -> dict:
    """`pg` is an owner connection; commits on success. Returns counts for logging."""
    groups = list(mongo.survey_responses.aggregate(PIPELINE))
    cols = ([g["_id"]["offering_id"] for g in groups], [g["_id"]["co_id"] for g in groups],
            [g["respondents"] for g in groups], [g["favourable"] for g in groups])
    with pg.transaction():
        loaded = pg.execute(UPSERT, cols).rowcount
    return {"groups": len(groups), "loaded": loaded, "skipped": len(groups) - loaded}
