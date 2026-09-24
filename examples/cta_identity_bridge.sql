-- Real analysis query from feature-builder's cta-testing project (2026-09-23/24):
-- checks whether a "new visitor" (by cookie) is actually linked to a pre-existing customer
-- account via an identity-resolution bridge, and whether that linked account's real first
-- order predates the visit or falls inside/after the 30-day window being measured.
--
-- Spans three separate systems joined only through CTEs:
--   datalake_agg.sdl_site_session        (web analytics, visitor_id grain)
--   data_science.ss_global_user_id_*     (identity-resolution bridge, global-id grain)
--   datalake_agg.sdl_orders              (orders, uid grain)
--
-- Good wayfinder demo case: three schemas, five joins, and the exact kind of "is this
-- relationship safe to build on" question wayfinder exists to answer before trusting it.

WITH home_sessions AS (
    SELECT
        visitor_id, date,
        lower(trim(visitor_type)) AS visitor_type,
        non_bounce_flag, qw_start, bms_view, shop_packages_view
    FROM datalake_agg.sdl_site_session
    WHERE is_reporting_eligible = 1
      AND date >= DATE '2026-06-24'
      AND date < DATE '2026-09-22'
      AND lower(trim(landing_page)) = '/'
),
first_touch AS (
    SELECT visitor_id, min(date) AS anchor_date FROM home_sessions GROUP BY visitor_id
),
anchored AS (
    SELECT
        ft.visitor_id, ft.anchor_date,
        max(hs.visitor_type) AS visitor_type,
        max(hs.non_bounce_flag) AS non_bounce_flag
    FROM first_touch ft
    JOIN home_sessions hs ON ft.visitor_id = hs.visitor_id AND ft.anchor_date = hs.date
    GROUP BY ft.visitor_id, ft.anchor_date
),
engaged_new AS (
    SELECT * FROM anchored
    WHERE non_bounce_flag = 1 AND visitor_type = 'new visitor'
      AND anchor_date <= DATE '2026-08-23'
),
vid_map AS (
    SELECT id AS visitor_id, ss_global_user_id
    FROM data_science.ss_global_user_id_mappings
    WHERE id_type = 'visitor_id'
      AND NOT coalesce(is_bot, false) AND NOT coalesce(is_test_user, false)
      AND NOT coalesce(is_deleted_user, false)
),
cluster_uids AS (
    SELECT ss_global_user_id, id AS uid
    FROM data_science.ss_global_user_id_mappings
    WHERE id_type = 'uid'
),
has_uid_cohort AS (
    SELECT en.visitor_id, en.anchor_date, vm.ss_global_user_id, cu.uid
    FROM engaged_new en
    JOIN vid_map vm ON vm.visitor_id = en.visitor_id
    JOIN cluster_uids cu ON cu.ss_global_user_id = vm.ss_global_user_id
),
first_order_per_uid AS (
    SELECT CAST(uid AS VARCHAR) AS uid, min(order_created_date_est) AS first_order_date
    FROM datalake_agg.sdl_orders
    WHERE lower(order_status) not in ('canceled', 'fbi', 'quote', 'in_checkout')
    GROUP BY uid
),
joined AS (
    SELECT
        h.visitor_id, h.anchor_date,
        min(fo.first_order_date) AS earliest_first_order_date
    FROM has_uid_cohort h
    LEFT JOIN first_order_per_uid fo ON fo.uid = h.uid
    GROUP BY h.visitor_id, h.anchor_date
),
conversion_raw AS (
    SELECT s.visitor_id, max(coalesce(s.system_purchase_session,0)) AS system_purchase_session
    FROM datalake_agg.sdl_site_session s
    INNER JOIN engaged_new er ON s.visitor_id = er.visitor_id
    WHERE s.is_reporting_eligible = 1
      AND s.date >= er.anchor_date
      AND s.date < DATE_ADD('day', 30, er.anchor_date)
    GROUP BY s.visitor_id
)
SELECT
    j.visitor_id, j.anchor_date, j.earliest_first_order_date,
    coalesce(c.system_purchase_session, 0) AS system_purchase_session,
    CASE
        WHEN j.earliest_first_order_date IS NULL THEN 'no_order_found'
        WHEN j.earliest_first_order_date < j.anchor_date THEN 'genuinely_pre_existing'
        WHEN j.earliest_first_order_date < DATE_ADD('day', 30, j.anchor_date)
            THEN 'same_event_circularity'
        ELSE 'later_leakage'
    END AS bucket
FROM joined j
LEFT JOIN conversion_raw c ON j.visitor_id = c.visitor_id;
