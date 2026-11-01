-- 004_dashboards.sql
-- Dashboard read models (PRD FR-6.1, FR-4.5). Materialized views cannot carry row-level
-- security, so they are granted to admin and coordinator only (009_security.sql); faculty
-- dashboards read the base tables, which RLS filters.

-- CO-PO heatmap: one row per mapped (offering, CO, PO) with the CO's final level and the
-- offering's PO value.
CREATE MATERIALIZED VIEW mv_co_po_heatmap AS
SELECT o.offering_id,
       o.academic_year,
       o.term,
       o.section,
       c.course_id,
       c.code       AS course_code,
       co.co_id,
       co.co_number,
       po.po_id,
       po.code      AS po_code,
       m.strength,
       ca.final_level,
       pa.attainment AS po_attainment
FROM co_attainment ca
JOIN course_offering o  ON o.offering_id = ca.offering_id
JOIN course c           ON c.course_id = o.course_id
JOIN course_outcome co  ON co.co_id = ca.co_id
JOIN co_po_map m        ON m.co_id = ca.co_id
JOIN program_outcome po ON po.po_id = m.po_id
LEFT JOIN po_attainment pa ON pa.offering_id = ca.offering_id AND pa.po_id = m.po_id;

CREATE UNIQUE INDEX mv_co_po_heatmap_uq ON mv_co_po_heatmap (offering_id, co_id, po_id);

-- CO trend: final level per course CO and year (sections averaged), with year-on-year change
-- (LAG) and the weakest-CO rank within each year (RANK).
CREATE MATERIALIZED VIEW mv_co_trend AS
WITH yearly AS (
    SELECT c.course_id, c.code AS course_code, co.co_id, co.co_number, o.academic_year,
           round(avg(ca.final_level), 2) AS final_level
    FROM co_attainment ca
    JOIN course_offering o ON o.offering_id = ca.offering_id
    JOIN course c          ON c.course_id = o.course_id
    JOIN course_outcome co ON co.co_id = ca.co_id
    GROUP BY c.course_id, c.code, co.co_id, co.co_number, o.academic_year
)
SELECT y.*,
       y.final_level - lag(y.final_level) OVER (PARTITION BY y.co_id ORDER BY y.academic_year)
           AS change_vs_prev_year,
       rank() OVER (PARTITION BY y.academic_year ORDER BY y.final_level) AS weakest_rank
FROM yearly y;

CREATE UNIQUE INDEX mv_co_trend_uq ON mv_co_trend (co_id, academic_year);

-- Programme-level PO = plain average of offering-level PO values (S10), per academic year.
CREATE VIEW v_program_po_attainment WITH (security_invoker = true) AS
SELECT cr.program_id,
       po.po_id,
       po.code AS po_code,
       o.academic_year,
       count(*)                       AS offerings,
       round(avg(pa.attainment), 2)   AS attainment
FROM po_attainment pa
JOIN course_offering o  ON o.offering_id = pa.offering_id
JOIN course cr          ON cr.course_id = o.course_id
JOIN program_outcome po ON po.po_id = pa.po_id
GROUP BY cr.program_id, po.po_id, po.code, o.academic_year;

-- Refresh runs as the owner so the compute procedures can trigger it for any caller. Directly,
-- only admin may call it: a full refresh is expensive.
CREATE FUNCTION fn_refresh_dashboards() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    REFRESH MATERIALIZED VIEW mv_co_po_heatmap;
    REFRESH MATERIALIZED VIEW mv_co_trend;
END $$;

REVOKE EXECUTE ON FUNCTION fn_refresh_dashboards() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_refresh_dashboards() TO copo_admin;
