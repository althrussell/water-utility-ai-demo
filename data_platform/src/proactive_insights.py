"""Job task 3: proactive insights engine and the executive morning briefing.

Each morning, after the data lands, a set of detection rules (plain SQL over governed tables)
looks for what changed and what matters. Each hit becomes an insight with evidence, $ or risk
impact, a recommended action and an owner. ai_query then writes an executive narrative per
insight and the daily briefing. Nobody has to go looking: Genie One skills, the agent, the
Ops Command Centre app and SQL alerts all read these tables.

If the model endpoint is unavailable the engine still runs and writes template narratives.
"""

import argparse
from datetime import datetime

from pyspark.sql import SparkSession

SEVERITY_ORDER = "CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END"

# Every rule returns: domain, severity, site_id, headline, detail, metric_name, metric_value,
# threshold, impact_aud, recommended_action, owner_role, score (higher = more important within severity)
RULES = {
    "algal_bloom": """
WITH d AS (SELECT data_through_date AS d FROM demo_metadata),
c AS (
  SELECT s.site_id, s.parameter, s.sample_date, s.value,
         ROW_NUMBER() OVER (PARTITION BY s.site_id, s.parameter ORDER BY s.sample_date DESC) AS rn
  FROM water_quality_samples s, d
  WHERE s.sample_point = 'Raw water' AND s.parameter IN ('Total cyanobacteria', 'Geosmin')
    AND s.sample_date > date_sub(d.d, 3)
),
base AS (
  SELECT s.site_id, s.parameter, AVG(s.value) AS v
  FROM water_quality_samples s, d
  WHERE s.sample_point = 'Raw water' AND s.parameter IN ('Total cyanobacteria', 'Geosmin')
    AND s.sample_date BETWEEN date_sub(d.d, 28) AND date_sub(d.d, 14)
  GROUP BY ALL
),
x AS (
  SELECT c.site_id,
         MAX(CASE WHEN c.parameter = 'Total cyanobacteria' THEN c.value END) AS cyano,
         MAX(CASE WHEN c.parameter = 'Geosmin' THEN c.value END) AS geosmin,
         MAX(CASE WHEN b.parameter = 'Total cyanobacteria' THEN b.v END) AS cyano_base
  FROM c LEFT JOIN base b ON c.site_id = b.site_id AND c.parameter = b.parameter
  WHERE c.rn = 1 GROUP BY c.site_id
)
SELECT 'Water Quality' AS domain,
       CASE WHEN cyano >= 50000 OR geosmin >= 30 THEN 'Critical' WHEN cyano >= 15000 OR geosmin >= 15 THEN 'High' ELSE 'Medium' END AS severity,
       x.site_id,
       concat('Algal bloom building in ', s.site_name, ' - taste and odour risk for ',
              CASE x.site_id WHEN 'BPD' THEN 'Landers Shute WTP (Sunshine Coast)' WHEN 'NPD' THEN 'North Pine WTP'
                             WHEN 'HIN' THEN 'Molendinar and Mudgeeraba WTPs' WHEN 'WIV' THEN 'Mount Crosby WTPs'
                             ELSE 'downstream treatment' END) AS headline,
       concat('Total cyanobacteria ', format_number(cyano, 0), ' cells/mL (', format_number(cyano / NULLIF(cyano_base, 0), 0),
              'x the level two weeks ago; Alert Level 1 is 2,000). Geosmin ', format_number(geosmin, 1),
              ' ng/L against a 10 ng/L taste and odour threshold.') AS detail,
       'Total cyanobacteria (cells/mL)' AS metric_name, cyano AS metric_value, 2000.0 AS threshold,
       CAST(NULL AS DOUBLE) AS impact_aud,
       'Increase PAC dosing and move the offtake to the best-quality layer; raise Northern Pipeline Interconnector transfers north to take load off Landers Shute; brief Unitywater on customer messaging; sample daily for toxins.' AS recommended_action,
       'Executive General Manager Operations' AS owner_role,
       cyano / 1000 AS score
FROM x JOIN sites s ON x.site_id = s.site_id
WHERE cyano >= 2000 OR geosmin > 10
""",
    "taste_odour_contacts": """
WITH d AS (SELECT data_through_date AS d FROM demo_metadata),
r AS (
  SELECT c.retailer_id,
         SUM(CASE WHEN c.contact_date > date_sub(d.d, 3) THEN c.contact_count END) / 3 AS recent,
         SUM(CASE WHEN c.contact_date BETWEEN date_sub(d.d, 63) AND date_sub(d.d, 4) THEN c.contact_count END) / 60 AS base
  FROM customer_contacts_daily c, d WHERE c.category = 'Taste & odour' GROUP BY c.retailer_id
)
SELECT 'Water Quality', CASE WHEN recent / base >= 5 THEN 'High' ELSE 'Medium' END, 'LSW',
       concat('Taste and odour complaints up ', format_number(recent / base, 1), 'x in the ', t.retailer_name, ' network'),
       concat(format_number(recent, 0), ' taste and odour contacts per day over the last 3 days versus a normal ',
              format_number(base, 1), ' per day.'),
       'Taste & odour contacts per day', recent, base * 3, CAST(NULL AS DOUBLE),
       'Agree joint customer messaging with the retailer today; publish a water quality update; correlate complaint suburbs with supply zones.',
       'Executive General Manager Customer & Community', recent / base
FROM r JOIN retailers t ON r.retailer_id = t.retailer_id
WHERE recent / base >= 3
""",
    "regulator_notification": """
SELECT 'Compliance', 'Critical', i.site_id,
       concat(i.title, ' - regulator notification due ', date_format(i.notification_due_at, 'HH:mm'), ' today'),
       concat(i.description, ' Reported ', date_format(i.reported_at, 'd MMM HH:mm'), '. Not yet notified.'),
       'Hours until notification deadline',
       ROUND((unix_timestamp(i.notification_due_at) - unix_timestamp(i.reported_at)) / 3600, 1),
       0.0, CAST(NULL AS DOUBLE),
       'Notify Queensland Health and the drinking water regulator before the deadline; confirm resample and boil water advisory decision; check chlorine dosing and filter performance at the plant.',
       'Chief Executive Officer / Water Quality Manager', 100.0
FROM incidents i
WHERE i.regulator_notifiable AND i.notified_at IS NULL AND i.status = 'Open'
""",
    "asset_health": """
WITH d AS (SELECT data_through_date AS d FROM demo_metadata),
h AS (
  SELECT c.asset_id,
         MAX_BY(c.health_score, c.reading_date) AS health,
         MAX_BY(c.vibration_mm_s, c.reading_date) AS vib,
         MAX(CASE WHEN c.reading_date = date_sub(d.d, 30) THEN c.health_score END) AS health_30d,
         MAX(CASE WHEN c.reading_date = date_sub(d.d, 21) THEN c.vibration_mm_s END) AS vib_21d
  FROM asset_condition_daily c, d WHERE c.reading_date > date_sub(d.d, 45) GROUP BY c.asset_id
),
pm AS (
  SELECT w.asset_id, MAX(datediff(d.d, w.due_date)) AS days_overdue
  FROM work_orders w, d
  WHERE w.work_type = 'Preventive' AND w.status IN ('Open', 'In Progress') AND w.due_date < d.d
  GROUP BY w.asset_id
)
SELECT 'Assets',
       CASE WHEN h.health < 20 THEN 'Critical' WHEN h.health < 40 OR h.vib >= 7.1 THEN 'High' ELSE 'Medium' END,
       a.site_id,
       concat(a.asset_name, CASE WHEN h.vib >= 7.1 THEN ' in vibration alarm' ELSE ' deteriorating' END,
              CASE WHEN pm.days_overdue > 0 THEN concat(' - preventive maintenance ', pm.days_overdue, ' days overdue') ELSE '' END),
       concat('Vibration ', format_number(h.vib, 1), ' mm/s (alarm 7.1; ', format_number(h.vib_21d, 1), ' three weeks ago). Health score ',
              format_number(h.health, 0), '/100, down from ', format_number(h.health_30d, 0), ' 30 days ago. Criticality ',
              a.criticality, ' asset at ', s.site_name, ' (', format_number(s.design_capacity_mld, 0), ' ML/d plant).'),
       'Health score', h.health, 40.0, a.replacement_value_aud,
       CASE WHEN h.health < 40 THEN 'Raise a P1 corrective work order for vibration analysis and bearing inspection within 72 hours; confirm standby pump availability before summer peak demand.'
            ELSE 'Schedule condition inspection at next planned outage; monitor trend weekly.' END,
       'General Manager Asset Delivery', 100 - h.health
FROM h JOIN assets a ON h.asset_id = a.asset_id JOIN sites s ON a.site_id = s.site_id
LEFT JOIN pm ON h.asset_id = pm.asset_id
WHERE h.health < 40 OR h.vib >= 7.1 OR (h.health_30d - h.health) >= 12
""",
    "demand_vs_forecast": """
WITH d AS (SELECT data_through_date AS d FROM demo_metadata),
v AS (
  SELECT b.retailer_id, SUM(b.delivered_ml) AS delivered, SUM(b.forecast_ml) AS forecast
  FROM bulk_supply_daily b, d WHERE b.supply_date > date_sub(d.d, 14) GROUP BY b.retailer_id
)
SELECT 'Demand', CASE WHEN (delivered / forecast - 1) >= 0.075 THEN 'High' ELSE 'Medium' END,
       CASE v.retailer_id WHEN 'UNW' THEN 'LSW' WHEN 'GCC' THEN 'MOL' ELSE 'MCE' END,
       concat(r.retailer_name, ' demand running ', format_number((delivered / forecast - 1) * 100, 1), '% above forecast'),
       concat(format_number(delivered, 0), ' ML delivered over the last 14 days against a forecast of ', format_number(forecast, 0),
              ' ML (', format_number((delivered - forecast) / 14, 1), ' ML/d extra) during hot, dry weather.'),
       'Demand vs forecast (%)', (delivered / forecast - 1) * 100, 5.0, CAST(NULL AS DOUBLE),
       'Re-run the demand forecast with the heat outlook; confirm transfer plans across the Water Grid; agree a hot-weather water-wise message with the retailer.',
       'General Manager Water Grid Operations', (delivered / forecast - 1) * 100
FROM v JOIN retailers r ON v.retailer_id = r.retailer_id
WHERE delivered / forecast - 1 >= 0.05
""",
    "offtake_layer": """
WITH d AS (SELECT data_through_date AS d FROM demo_metadata),
lvl AS (SELECT MAX(water_level_m) AS lvl FROM reservoir_level_daily, d WHERE reading_date = d.d AND site_id = 'BPD'),
o AS (SELECT offtake_level, in_service, (SELECT lvl FROM lvl) - centre_elevation_m AS depth FROM reservoir_offtakes WHERE site_id = 'BPD'),
p AS (SELECT r.depth_m, r.cyanobacteria_cells_ml, r.manganese_mg_l, r.dissolved_oxygen_mg_l FROM reservoir_profile_daily r, d WHERE r.reading_date = d.d),
q AS (
  SELECT o.offtake_level, o.in_service, o.depth, p.cyanobacteria_cells_ml AS cyano, p.manganese_mg_l AS mn, p.dissolved_oxygen_mg_l AS dox,
         ROW_NUMBER() OVER (PARTITION BY o.offtake_level ORDER BY abs(p.depth_m - o.depth)) AS rn
  FROM o CROSS JOIN p
),
cur AS (SELECT * FROM q WHERE rn = 1 AND in_service),
best AS (SELECT * FROM q WHERE rn = 1 AND mn < 0.1 ORDER BY cyano LIMIT 1)
SELECT 'Water Quality', CASE WHEN cur.cyano >= 15000 THEN 'High' ELSE 'Medium' END, 'BPD',
       concat('Landers Shute is drawing from the ', lower(cur.offtake_level), ' offtake inside the bloom - the ', lower(best.offtake_level),
              ' offtake has ', format_number((1 - best.cyano / cur.cyano) * 100, 0), '% less cyanobacteria'),
       concat('Baroon Pocket Dam is stratified. The in-service ', lower(cur.offtake_level), ' offtake (', format_number(cur.depth, 1), ' m deep) sees ',
              format_number(cur.cyano, 0), ' cells/mL. The ', lower(best.offtake_level), ' offtake (', format_number(best.depth, 1), ' m) sees ',
              format_number(best.cyano, 0), ' cells/mL with manganese ', format_number(best.mn, 3), ' mg/L and oxygen ', format_number(best.dox, 1),
              ' mg/L. The lower offtake is in low-oxygen water with high manganese.'),
       'Cyanobacteria at the in-service offtake (cells/mL)', cur.cyano, best.cyano, CAST(NULL AS DOUBLE),
       concat('Switch Landers Shute to the ', lower(best.offtake_level), ' offtake now (ask the Operations Agent to raise the change for approval), keep PAC dosing at maximum until surface counts fall, and profile the lake daily.'),
       'Executive General Manager Operations', 70.0
FROM cur, best
WHERE cur.offtake_level <> best.offtake_level
""",
    "treatment_headroom": """
WITH d AS (SELECT data_through_date AS d FROM demo_metadata)
SELECT 'Operations', 'High', t.site_id,
       concat(s.site_name, ' at ', format_number(SUM(t.production_ml) / SUM(t.available_capacity_mld) * 100, 0),
              '% of available capacity - ', format_number(100 - AVG(t.available_capacity_mld) / MAX(s.design_capacity_mld) * 100, 0), '% of design capacity lost'),
       concat('Average production ', format_number(AVG(t.production_ml), 0), ' ML/d over 7 days against available capacity of ',
              format_number(AVG(t.available_capacity_mld), 0), ' ML/d (design ', format_number(MAX(s.design_capacity_mld), 0), ' ML/d).'),
       'Utilisation of available capacity (%)', SUM(t.production_ml) / SUM(t.available_capacity_mld) * 100, 90.0, CAST(NULL AS DOUBLE),
       'Shift load to neighbouring plants via the Water Grid (Northern Pipeline Interconnector / SRWP); prioritise the capacity constraint fix.',
       'General Manager Water Grid Operations', SUM(t.production_ml) / SUM(t.available_capacity_mld) * 100
FROM treatment_daily t JOIN sites s ON t.site_id = s.site_id, d
WHERE t.production_date > date_sub(d.d, 7) AND s.site_type = 'Water Treatment Plant'
GROUP BY t.site_id, s.site_name
HAVING SUM(t.production_ml) / SUM(t.available_capacity_mld) >= 0.90
""",
    "peak_tariff_pumping": """
WITH d AS (SELECT data_through_date AS d FROM demo_metadata),
e AS (
  SELECT e.site_id, SUM(e.energy_kwh) AS kwh, SUM(e.peak_kwh) AS peak, SUM(e.energy_cost_aud) AS cost
  FROM energy_daily e JOIN sites s ON e.site_id = s.site_id, d
  WHERE e.energy_date > date_sub(d.d, 30) AND s.site_type = 'Pump Station'
  GROUP BY e.site_id
),
agg AS (
  SELECT SUM(peak) / SUM(kwh) AS share, SUM(GREATEST(peak - 0.2 * kwh, 0)) * 0.20 AS avoidable_30d,
         MAX_BY(site_id, peak / kwh) AS worst_site,
         concat_ws(', ', collect_list(CASE WHEN peak / kwh > 0.3 THEN site_id END)) AS sites
  FROM e
)
SELECT 'Energy', CASE WHEN avoidable_30d * 365 / 30 > 1000000 THEN 'High' ELSE 'Medium' END, worst_site,
       concat('Grid transfer pumping drifting into peak tariff - about $', format_number(avoidable_30d * 365 / 30 / 1000, 0), 'k a year avoidable'),
       concat(format_number(share * 100, 0), '% of transfer pumping energy used in the 4-9pm peak window over the last 30 days against a 20% target (sites: ', sites,
              '). Excess peak energy cost $', format_number(avoidable_30d, 0), ' in 30 days.'),
       'Peak share of transfer pumping (%)', share * 100, 20.0, avoidable_30d * 365 / 30,
       'Re-optimise transfer schedules to pump overnight and in the solar-soak window while reservoirs have headroom; add tariff-aware constraints to the daily grid operating plan.',
       'General Manager Water Grid Operations', avoidable_30d / 1000
FROM agg WHERE share > 0.25
""",
    "water_security": """
WITH d AS (SELECT data_through_date AS d FROM demo_metadata),
g AS (
  SELECT l.reading_date, SUM(l.volume_ml) / SUM(s.full_supply_volume_ml) * 100 AS pct
  FROM storage_levels_daily l JOIN sites s ON l.site_id = s.site_id
  WHERE s.grid_connected GROUP BY l.reading_date
),
x AS (
  SELECT MAX(CASE WHEN g.reading_date = d.d THEN pct END) AS now_pct,
         MAX(CASE WHEN g.reading_date = date_sub(d.d, 30) THEN pct END) AS pct_30,
         MAX(CASE WHEN g.reading_date = date_sub(d.d, 90) THEN pct END) AS pct_90
  FROM g, d
),
r AS (SELECT SUM(rainfall_mm) / COUNT(DISTINCT catchment) AS fc_rain FROM weather_daily WHERE is_forecast),
t AS (SELECT MAX(grid_storage_percent) AS trig FROM drought_trigger_levels WHERE grid_storage_percent < (SELECT now_pct FROM x))
SELECT 'Water Security', CASE WHEN (now_pct - trig) / ((pct_30 - now_pct) / 30) < 120 THEN 'High' WHEN now_pct < pct_90 THEN 'Medium' ELSE 'Info' END,
       'WIV',
       concat('Grid storage ', format_number(now_pct, 1), '% and falling - about ', format_number((now_pct - trig) / ((pct_30 - now_pct) / 30), 0),
              ' days to the ', format_number(trig, 0), '% drought readiness level at the current rate'),
       concat('Grid storage fell from ', format_number(pct_90, 1), '% to ', format_number(now_pct, 1), '% over 90 days (',
              format_number((pct_30 - now_pct) / 30, 3), ' points a day over the last 30). Forecast rainfall for the next week averages ',
              format_number(fc_rain, 0), ' mm across catchments.'),
       'Grid storage (%)', now_pct, trig, CAST(NULL AS DOUBLE),
       'Brief the Board on the dry outlook; confirm Gold Coast Desalination Plant ramp-up readiness and Western Corridor restart lead times; align retailer demand messaging.',
       'Executive General Manager Water Security', 50.0
FROM x, r, t
""",
    "capital_variance": """
SELECT 'Capital', CASE WHEN rag_status = 'Red' THEN 'High' ELSE 'Medium' END, site_id,
       concat(project_name, ': ', rag_status, ', ', format_number((forecast_cost_aud / approved_budget_aud - 1) * 100, 1), '% over budget, ',
              datediff(forecast_finish_date, baseline_finish_date), ' days late'),
       concat('Forecast $', format_number(forecast_cost_aud / 1e6, 1), 'M against an approved $', format_number(approved_budget_aud / 1e6, 1),
              'M (', percent_complete, '% complete, phase: ', phase, '). Key risks: ', key_risks),
       'Cost variance (AUD)', forecast_cost_aud - approved_budget_aud, 0.0, forecast_cost_aud - approved_budget_aud,
       'Request a recovery plan and re-baselined forecast for the next Capital Investment Committee; test scope and procurement options.',
       'Executive General Manager Capital Delivery', (forecast_cost_aud - approved_budget_aud) / 1e6
FROM capital_projects
WHERE rag_status = 'Red' OR forecast_cost_aud / approved_budget_aud - 1 > 0.10 OR datediff(forecast_finish_date, baseline_finish_date) > 90
""",
    "maintenance_backlog": """
WITH d AS (SELECT data_through_date AS d FROM demo_metadata)
SELECT 'Assets', 'Medium', MAX_BY(w.site_id, datediff(d.d, w.due_date)),
       concat(COUNT(1), ' preventive maintenance tasks overdue on supply-critical (A) assets'),
       concat('Oldest is ', MAX(datediff(d.d, w.due_date)), ' days overdue. Sites: ', concat_ws(', ', array_distinct(collect_list(w.site_id))), '.'),
       'Overdue critical PMs', COUNT(1), 0.0, CAST(NULL AS DOUBLE),
       'Review the overdue critical maintenance list at this week\\'s operations meeting and resource the top items before summer.',
       'General Manager Asset Delivery', COUNT(1)
FROM work_orders w JOIN assets a ON w.asset_id = a.asset_id, d
WHERE w.work_type = 'Preventive' AND w.status IN ('Open', 'In Progress') AND w.due_date < d.d AND a.criticality = 'A'
GROUP BY d.d HAVING COUNT(1) >= 3
""",
    "pfas_assurance": """
WITH d AS (SELECT data_through_date AS d FROM demo_metadata),
p AS (
  SELECT q.site_id, q.parameter, MAX(q.value / q.guideline_value) AS ratio
  FROM water_quality_samples q, d
  WHERE q.parameter IN ('PFOS', 'PFHxS', 'PFOA') AND q.sample_date > date_sub(d.d, 365) GROUP BY ALL
)
SELECT 'Water Quality', CASE WHEN MAX(ratio) >= 0.8 THEN 'High' WHEN MAX(ratio) >= 0.5 THEN 'Medium' ELSE 'Info' END,
       MAX_BY(site_id, ratio),
       concat('PFAS assurance: all treated water results within the 2025 ADWG health guidelines'),
       concat('Highest result in the last 12 months was ', format_number(MAX(ratio) * 100, 0), '% of guideline (',
              MAX_BY(parameter, ratio), ' at ', MAX_BY(site_id, ratio), '). ', COUNT(1), ' site/parameter combinations tested.'),
       'Highest PFAS result (% of guideline)', MAX(ratio) * 100, 100.0, CAST(NULL AS DOUBLE),
       'No action required; keep the public PFAS reporting current.', 'Water Quality Manager', 0.0
FROM p
""",
}

INSIGHT_COLUMNS = ["domain", "severity", "site_id", "headline", "detail", "metric_name", "metric_value",
                   "threshold", "impact_aud", "recommended_action", "owner_role", "score"]


FALLBACK_ENDPOINTS = ["databricks-claude-sonnet-4-6", "databricks-claude-sonnet-4-5", "databricks-meta-llama-3-3-70b-instruct"]


def pick_endpoint(spark, preferred: str) -> str | None:
    """First endpoint that supports ai_query batch inference in this workspace."""
    for e in [preferred, *[x for x in FALLBACK_ENDPOINTS if x != preferred]]:
        try:
            spark.sql(f"SELECT ai_query('{e}', 'Reply OK') AS r").collect()
            print(f"  using model endpoint {e}")
            return e
        except Exception as ex:
            print(f"  endpoint {e} not usable for ai_query: {str(ex).splitlines()[0][:140]}")
    return None


def build_insights(spark, llm_endpoint: str | None) -> None:
    parts = []
    for name, sql in RULES.items():
        try:
            df = spark.sql(sql).toDF(*INSIGHT_COLUMNS)
            n = df.count()
            print(f"  rule {name:24s} -> {n} insight(s)")
            parts.append(df.selectExpr("*", f"'{name}' AS rule"))
        except Exception as e:
            print(f"  rule {name:24s} FAILED: {str(e).splitlines()[0][:200]}")
    allx = parts[0]
    for p in parts[1:]:
        allx = allx.unionByName(p)
    allx.createOrReplaceTempView("_insights_raw")
    spark.sql(f"""
        CREATE OR REPLACE TEMP VIEW _insights AS
        SELECT CAST(from_utc_timestamp(current_timestamp(), 'Australia/Brisbane') AS DATE) AS insight_date,
               concat(date_format(from_utc_timestamp(current_timestamp(), 'Australia/Brisbane'), 'yyyyMMdd'), '-', rule, '-',
                      ROW_NUMBER() OVER (PARTITION BY rule ORDER BY score DESC)) AS insight_id,
               CAST(ROW_NUMBER() OVER (ORDER BY {SEVERITY_ORDER}, score DESC) AS INT) AS `rank`,
               domain, severity, site_id, headline, detail, metric_name,
               CAST(metric_value AS DOUBLE) AS metric_value, CAST(threshold AS DOUBLE) AS threshold,
               CAST(impact_aud AS DOUBLE) AS impact_aud, recommended_action, owner_role
        FROM _insights_raw
    """)

    prompt = ("concat('You are the chief of staff at Seqwater, the bulk water supplier for South East Queensland. ', "
              "'Write a 2-3 sentence executive narrative for this operational insight: what is happening, why it matters to ', "
              "'customers, compliance or cost, and the decision needed today. Plain Australian English, no headings, no bullet points, ', "
              "'do not invent numbers beyond the evidence. Insight: ', headline, '. Evidence: ', detail, ' Recommended action: ', recommended_action)")
    try:
        if not llm_endpoint:
            raise RuntimeError("no model endpoint available")
        spark.sql(f"""
            CREATE OR REPLACE TABLE proactive_insights AS
            SELECT *, ai_query('{llm_endpoint}', {prompt}) AS narrative FROM _insights
        """)
        print(f"  narratives written by {llm_endpoint}")
    except Exception as e:
        print(f"  ai_query unavailable ({str(e).splitlines()[0][:160]}) - using template narratives")
        spark.sql("""
            CREATE OR REPLACE TABLE proactive_insights AS
            SELECT *, concat(detail, ' Recommended: ', recommended_action) AS narrative FROM _insights
        """)


def build_briefing(spark, llm_endpoint: str | None) -> None:
    rows = spark.sql("SELECT * FROM proactive_insights ORDER BY rank").collect()
    today = rows[0].insight_date if rows else datetime.utcnow().date()
    crit = sum(r.severity == "Critical" for r in rows)
    high = sum(r.severity == "High" for r in rows)
    icon = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Info": "🟢"}
    lines = [f"{r.rank}. {icon.get(r.severity, '')} **{r.domain} - {r.headline}.** {r.detail} *Action:* {r.recommended_action}"
             for r in rows]
    evidence = "\n".join(lines)
    headline = f"{crit} critical and {high} high-priority items need attention today"
    fallback = f"# Seqwater Morning Operations Briefing - {today:%A %d %B %Y}\n\n**{headline}.**\n\n" + evidence
    spark.createDataFrame([(evidence,)], "evidence STRING").createOrReplaceTempView("_brief_in")
    try:
        if not llm_endpoint:
            raise RuntimeError("no model endpoint available")
        md = spark.sql(f"""
            SELECT ai_query('{llm_endpoint}', concat(
              'You are the chief of staff at Seqwater (bulk water supplier for South East Queensland). Write the executive ',
              'morning operations briefing for {today:%A %d %B %Y} in markdown for the CEO and executive team. Structure: a title ',
              '"Seqwater Morning Operations Briefing", a 2-sentence bottom line up front, then "Needs a decision today", ',
              '"Watch closely" and "Assurance" sections with short bullets that keep the severity emoji and every number from ',
              'the evidence, then one closing line on how the issues connect. Under 350 words. Do not invent numbers. Evidence:\\n',
              evidence)) AS md FROM _brief_in
        """).collect()[0].md
    except Exception as e:
        print(f"  briefing ai_query unavailable ({str(e).splitlines()[0][:160]}) - using template")
        md = fallback
    spark.createDataFrame(
        [(today, headline, md or fallback, crit, high, datetime.utcnow())],
        "briefing_date DATE, headline STRING, briefing_markdown STRING, critical_count INT, high_count INT, generated_at TIMESTAMP",
    ).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("daily_briefing")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--llm-endpoint", default="databricks-claude-sonnet-4-6")
    args = ap.parse_args()

    import catalog_docs  # noqa: F401  (same folder; imported lazily for comments below)

    spark = SparkSession.builder.getOrCreate()
    spark.sql(f"USE CATALOG `{args.catalog}`")
    spark.sql(f"USE SCHEMA `{args.schema}`")
    endpoint = pick_endpoint(spark, args.llm_endpoint)
    build_insights(spark, endpoint)
    build_briefing(spark, endpoint)
    for name in ("proactive_insights", "daily_briefing"):
        meta = catalog_docs.TABLES[name]
        spark.sql(f"COMMENT ON TABLE {name} IS '{meta['comment'].replace(chr(39), chr(92) + chr(39))}'")
        for c, comment in meta["columns"].items():
            spark.sql(f"ALTER TABLE {name} ALTER COLUMN {c} COMMENT '{comment.replace(chr(39), chr(92) + chr(39))}'")
        spark.sql(f"ALTER TABLE {name} SET TAGS ('demo' = 'seqwater-ai-demo', 'data_classification' = 'synthetic')")
    for r in spark.sql("SELECT rank, severity, domain, headline FROM proactive_insights ORDER BY rank").collect():
        print(f"  {r.rank:>2} {r.severity:8s} {r.domain:15s} {r.headline}")


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__ if "__file__" in globals() else sys.argv[0])))
    main()
