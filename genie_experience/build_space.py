"""Render the Seqwater Genie space definition for a target catalog and schema.

The space is authored here as readable Python and rendered to `.build/seqwater_ops.geniespace.json`,
which the bundle in this folder deploys (resources/genie.yml). The repo CLI runs this for you;
to run it by hand:  python3 build_space.py --catalog main --schema seqwater_demo
"""

import argparse
import json
import os

TITLE = "Seqwater Operations Intelligence"
DESCRIPTION = (
    "Ask anything about Seqwater's water grid: storage and water security, water quality and algal risk, "
    "treatment plant performance, retailer demand, energy cost, asset health and maintenance, incidents and "
    "the capital program. Includes the proactive insights raised each morning. SYNTHETIC demo data."
)

TABLES = [
    # governed KPI layer (metric views)
    "mv_asset_health", "mv_bulk_supply", "mv_capital_program", "mv_energy", "mv_treatment",
    "mv_water_quality", "mv_water_security", "mv_work_orders",
    # row-level tables
    "agent_actions", "asset_condition_daily", "assets", "capital_projects", "customer_contacts_daily",
    "daily_briefing", "demo_metadata", "drought_trigger_levels", "incidents", "proactive_insights",
    "retailers", "sites", "storage_levels_daily", "water_quality_guidelines", "water_quality_samples",
    "weather_daily", "work_orders",
    # Baroon Pocket Dam digital twin
    "reservoir_buoy_readings_daily", "reservoir_buoys", "reservoir_level_daily", "reservoir_offtakes", "reservoir_profile_daily",
]

TEXT_INSTRUCTIONS = [
    """## What this space is for
Seqwater is the bulk water authority for South East Queensland: it stores, treats and transfers drinking water for about 3.8 million people and sells it to five retailers (Urban Utilities, Unitywater, City of Gold Coast, Logan City Council, Redland City Council). This space covers the whole operation, end to end. The audience is the executive team: answer like a chief of staff - lead with the number that matters, then the context, then what it means.

All data is SYNTHETIC and generated for a Databricks demo. If asked, say so plainly.

## Data map
- **Proactive insights** - `proactive_insights` (one row per insight raised this morning, ranked; severity Critical/High/Medium/Info) and `daily_briefing` (the AI-written executive morning briefing). For "what should I worry about", "what's changed", "morning briefing", "top issues" start here.
- **Water security** - `mv_water_security` (grid storage %, dam levels, inflows), `storage_levels_daily` (row level), `drought_trigger_levels`, `weather_daily` (rain and temperature incl. 7-day forecast where is_forecast = true).
- **Water quality** - `mv_water_quality`, `water_quality_samples` (raw water in dams and treated water leaving plants), `water_quality_guidelines`, `customer_contacts_daily` (taste & odour complaints are the early signal).
- **Treatment and supply** - `mv_treatment` (production, utilisation of available capacity, chemical and energy intensity), `mv_bulk_supply` (delivered vs forecast by retailer).
- **Energy** - `mv_energy` (cost, peak tariff share, avoidable peak cost).
- **Assets and maintenance** - `mv_asset_health` (pump vibration, health score), `asset_condition_daily`, `assets`, `mv_work_orders`, `work_orders`, `agent_actions` (work orders and notifications raised by the Seqwater Operations Agent).
- **Incidents and compliance** - `incidents` (regulator_notifiable and notified_at show notification status).
- **Baroon Pocket Dam twin (Lake Baroon)** - `reservoir_buoys` and `reservoir_buoy_readings_daily` (surface algae by location, last 30 days), `reservoir_profile_daily` (temperature, oxygen, algae and manganese every 2 m of depth), `reservoir_offtakes` (Upper/Middle/Lower intake levels that feed Landers Shute WTP; depth below surface = today's water level minus centre_elevation_m; today's level is the latest `reservoir_level_daily.water_level_m`).
- **Capital program** - `mv_capital_program`, `capital_projects` (Dam Improvement Program, Water Security Program, Asset Renewals, Digital & Technology).
- `sites` describes every dam, plant and pump station; `retailers` the five customers.
""",
    """## Rules for metric views (mv_ prefix)
- Wrap every measure in `MEASURE()`, e.g. `MEASURE(`Grid Storage Pct`)`. Never `SUM()` or `AVG()` a measure.
- Dimensions are plain columns in backticks and must be grouped: `GROUP BY ALL`.
- Never `SELECT *` from a metric view and never join two metric views together; query each separately or combine in CTEs.
- Measures ending in `Pct` are already 0-100. Do not multiply by 100 again.
- For a single row (one sample, one pump reading, one work order) use the ordinary tables, not metric views.

## Dates
- Data runs to `demo_metadata.data_through_date` (yesterday). Treat that day as "today's latest data" and "yesterday". "This morning" / "today" for insights and incidents means `insight_date` / the current date.
- "Last 30 days" = the 30 days ending data_through_date. Compute relative dates and "days overdue" from `(SELECT data_through_date FROM demo_metadata)`, never current_date().
- "Days until" a grid storage level = (latest Grid Storage Pct - level) / ((Grid Storage Pct 30 days earlier - latest) / 30). This matches the proactive insight.
- Month dimensions are month-start dates; filter with date literals.

## Units and conventions
- Volumes in megalitres (ML); plant capacity in ML per day (ML/d). 1 ML = 1 million litres.
- Money in Australian dollars (AUD). Show $k or $M for large values.
- Grid storage = grid-connected dams only (`Grid Storage Pct`). Wivenhoe Dam alone is about half of grid storage.
- Water quality: cyanobacteria in cells/mL (Alert Level 1 = 2,000); geosmin and 2-MIB in ng/L (taste & odour threshold 10); turbidity in NTU; E. coli any detection in treated water is regulator-notifiable.
- Vibration alarm is 7.1 mm/s; asset health below 40 means intervene now.
""",
    """## Glossary (user term -> data)
- "the grid", "Water Grid", "dam levels" -> `mv_water_security` `Grid Storage Pct`.
- "Mt Crosby" -> Mount Crosby Eastbank WTP (MCE) and Westbank WTP (MCW). "Landers Shute" -> LSW. "the desal" / "desalination" -> Gold Coast Desalination Plant (GCD). "Western Corridor" / "recycled water" / "PRW" -> BUN, LPT, GIB.
- "Baroon", "Lake Baroon" -> Baroon Pocket Dam (BPD), the Sunshine Coast storage feeding Landers Shute.
- "offtake", "intake level", "draw from a different depth" -> `reservoir_offtakes` with `reservoir_profile_daily`. "Stratification" -> temperature and oxygen by depth.
- "NPI" -> Northern Pipeline Interconnector pump stations (NPI-MOR, NPI-LAN); "SRWP" -> Southern Regional Water Pipeline; "EPI" -> Eastern Pipeline Interconnector.
- "T&O" -> taste and odour (geosmin, 2-MIB, Taste & odour contacts). "BGA", "algae", "bloom" -> Total cyanobacteria.
- "Unitywater" / "Sunshine Coast customers" -> retailer UNW. "Urban Utilities" / "Brisbane" -> URU.
- "DIP" -> Dam Improvement Program. "WSP" -> Water Security Program. "overrun", "blowout" -> Cost Variance.
- "backlog", "overdue maintenance" -> `mv_work_orders` `Overdue Work Orders`.

## How to answer
- Lead with the answer and the key number, then 2-3 supporting points, then the implication or next step.
- When a question is about a problem, connect it across domains where the data supports it (e.g. an algal bloom at Baroon Pocket -> Landers Shute capacity -> Sunshine Coast demand -> Northern Pipeline Interconnector transfers -> peak tariff pumping).
- For "morning briefing" or "exec briefing" return `daily_briefing.briefing_markdown` for the latest briefing_date, or summarise `proactive_insights` in rank order with severity.
""",
]

EXAMPLE_SQLS = [
    ("What are today's proactive insights?", """
-- Today's proactive insights in priority order
SELECT `rank`, severity, domain, headline, detail, recommended_action, owner_role, impact_aud
FROM {fq}.proactive_insights
WHERE insight_date = (SELECT MAX(insight_date) FROM {fq}.proactive_insights)
ORDER BY `rank`
"""),
    ("What is grid storage now and how has it changed over the last 90 days?", """
-- Grid storage trend for the last 90 days (grid-connected dams)
SELECT `Reading Date`, MEASURE(`Grid Storage Pct`) AS grid_storage_pct
FROM {fq}.mv_water_security
WHERE `Reading Date` > date_sub((SELECT data_through_date FROM {fq}.demo_metadata), 90)
GROUP BY ALL
ORDER BY `Reading Date`
"""),
    ("Show cyanobacteria and geosmin in Baroon Pocket Dam over the last 30 days", """
-- Algal bloom trend at Baroon Pocket Dam (raw water)
SELECT sample_date, parameter, value, unit, guideline_value
FROM {fq}.water_quality_samples
WHERE site_id = 'BPD' AND parameter IN ('Total cyanobacteria', 'Geosmin')
  AND sample_date > date_sub((SELECT data_through_date FROM {fq}.demo_metadata), 30)
ORDER BY parameter, sample_date
"""),
    ("Which retailers are running above forecast in the last 14 days?", """
-- Demand versus forecast by retailer, last 14 days
SELECT `Retailer`, MEASURE(`Delivered ML`) AS delivered_ml, MEASURE(`Forecast ML`) AS forecast_ml,
       MEASURE(`Variance Pct`) AS variance_pct
FROM {fq}.mv_bulk_supply
WHERE `Supply Date` > date_sub((SELECT data_through_date FROM {fq}.demo_metadata), 14)
GROUP BY ALL
ORDER BY variance_pct DESC
"""),
    ("Which pumps are at highest risk of failure?", """
-- Latest pump condition, worst first
WITH latest AS (SELECT data_through_date AS d FROM {fq}.demo_metadata)
SELECT a.asset_id, a.asset_name, a.criticality, c.health_score, c.vibration_mm_s, c.bearing_temp_c, c.vibration_alarm
FROM {fq}.asset_condition_daily c
JOIN {fq}.assets a ON c.asset_id = a.asset_id
JOIN latest ON c.reading_date = latest.d
ORDER BY c.health_score
LIMIT 10
"""),
    ("Which critical maintenance is overdue?", """
-- Overdue work orders on supply-critical (A) assets
SELECT w.work_order_id, a.asset_name, w.work_type, w.priority, w.status, w.due_date,
       datediff((SELECT data_through_date FROM {fq}.demo_metadata), w.due_date) AS days_overdue, w.description
FROM {fq}.work_orders w
JOIN {fq}.assets a ON w.asset_id = a.asset_id
WHERE w.status IN ('Open', 'In Progress') AND w.due_date < (SELECT data_through_date FROM {fq}.demo_metadata)
  AND a.criticality = 'A'
ORDER BY days_overdue DESC
"""),
    ("How much peak-tariff energy cost could we avoid at the pump stations?", """
-- Peak share and avoidable peak cost by pump station, last 30 days
SELECT `Site`, MEASURE(`Energy Cost AUD`) AS energy_cost_aud, MEASURE(`Peak Share Pct`) AS peak_share_pct,
       MEASURE(`Avoidable Peak Cost AUD`) AS avoidable_peak_cost_aud_30d,
       MEASURE(`Avoidable Peak Cost AUD`) * 365 / 30 AS avoidable_peak_cost_aud_annualised
FROM {fq}.mv_energy
WHERE `Site Type` = 'Pump Station'
  AND `Energy Date` > date_sub((SELECT data_through_date FROM {fq}.demo_metadata), 30)
GROUP BY ALL
ORDER BY avoidable_peak_cost_aud_30d DESC
"""),
    ("Which capital projects are over budget or late?", """
-- Capital projects ranked by cost variance
SELECT project_name, program, phase, rag_status, approved_budget_aud, forecast_cost_aud,
       forecast_cost_aud - approved_budget_aud AS cost_variance_aud,
       round((forecast_cost_aud / approved_budget_aud - 1) * 100, 1) AS cost_variance_pct,
       datediff(forecast_finish_date, baseline_finish_date) AS schedule_slip_days, key_risks
FROM {fq}.capital_projects
ORDER BY cost_variance_aud DESC
"""),
    ("What happened at Mount Crosby during the last major turbidity event?", """
-- Mount Crosby raw turbidity and production, and desalination output, around the largest turbidity event
WITH peak AS (
  SELECT production_date AS d FROM {fq}.treatment_daily WHERE site_id = 'MCE'
  ORDER BY raw_turbidity_ntu DESC LIMIT 1
)
SELECT t.production_date, t.site_id, t.raw_turbidity_ntu, t.production_ml, t.available_capacity_mld, t.utilisation_pct
FROM {fq}.treatment_daily t, peak
WHERE t.site_id IN ('MCE', 'MCW', 'GCD') AND t.production_date BETWEEN date_sub(peak.d, 7) AND date_add(peak.d, 10)
ORDER BY t.production_date, t.site_id
"""),
]

EXAMPLE_SQLS.append(("Which Baroon Pocket offtake has the best water quality right now?", """
-- Water quality at each Baroon Pocket Dam offtake today: offtake depth = water level - offtake elevation
WITH d AS (SELECT MAX(reading_date) AS d FROM {fq}.reservoir_profile_daily),
lvl AS (SELECT water_level_m FROM {fq}.reservoir_level_daily WHERE site_id = 'BPD' ORDER BY reading_date DESC LIMIT 1),
o AS (SELECT offtake_level, in_service, (SELECT water_level_m FROM lvl) - centre_elevation_m AS depth_m FROM {fq}.reservoir_offtakes),
p AS (SELECT r.* FROM {fq}.reservoir_profile_daily r, d WHERE r.reading_date = d.d),
q AS (SELECT o.*, p.cyanobacteria_cells_ml, p.manganese_mg_l, p.dissolved_oxygen_mg_l,
             ROW_NUMBER() OVER (PARTITION BY o.offtake_level ORDER BY abs(p.depth_m - o.depth_m)) AS rn
      FROM o CROSS JOIN p)
SELECT offtake_level, in_service, round(depth_m, 1) AS depth_m, cyanobacteria_cells_ml, manganese_mg_l, dissolved_oxygen_mg_l
FROM q WHERE rn = 1 ORDER BY depth_m
"""))

SAMPLE_QUESTIONS = [
    "Give me this morning's operations briefing",
    "Why is Landers Shute flagged and what is driving it?",
    "What is grid storage now and how many days until the drought readiness level?",
    "Which pumps are at highest risk of failure, and is their maintenance overdue?",
    "How much could we save by moving transfer pumping out of peak tariff?",
    "Which Dam Improvement Program projects are over budget?",
]


def _lines(text: str) -> list[str]:
    text = text.strip("\n")
    return [ln + "\n" for ln in text.split("\n")[:-1]] + [text.split("\n")[-1]]


def _ids(prefix: str):
    i = 0
    while True:
        i += 1
        yield f"01f1{prefix}{i:024x}"


def render(catalog: str, schema: str) -> dict:
    fq = f"{catalog}.{schema}"
    ids = _ids("5e00")
    return {
        "version": 2,
        "config": {"sample_questions": [{"id": next(ids), "question": [q]} for q in SAMPLE_QUESTIONS]},
        "data_sources": {"tables": [{"identifier": f"{fq}.{t}"} for t in sorted(TABLES)]},
        "instructions": {
            # the API accepts a single text instruction block
            "text_instructions": [{"id": next(ids), "content": _lines("\n\n".join(TEXT_INSTRUCTIONS))}],
            "example_question_sqls": [
                {"id": next(ids), "question": [q], "sql": _lines(sql.replace("{fq}", fq))} for q, sql in EXAMPLE_SQLS
            ],
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".build",
                                                  "seqwater_ops.geniespace.json"))
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(render(args.catalog, args.schema), f, indent=2)
    print(args.out)


if __name__ == "__main__":
    main()
