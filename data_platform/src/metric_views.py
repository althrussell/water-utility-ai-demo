"""Job task 2: governed KPI layer - Unity Catalog metric views over the demo tables.

Every KPI the executives see (grid storage %, demand variance, peak energy share, overdue
maintenance, capital variance...) is defined once here and reused by Genie, Genie One skills,
the proactive insights engine and the agent.
"""

import argparse
import re

from pyspark.sql import SparkSession

TODAY = "CAST(from_utc_timestamp(current_timestamp(), 'Australia/Brisbane') AS DATE)"

METRIC_VIEWS = {
    "mv_water_security": """
version: 1.1
comment: "Water security KPIs from daily dam storage levels. Grid Storage Pct is the headline SEQ Water Grid number (grid-connected dams only). Percent measures are already 0-100 and safe to use at any grain."
source: {fq}.storage_levels_daily
joins:
  - name: dim_site
    source: {fq}.sites
    on: source.site_id = dim_site.site_id
dimensions:
  - name: Reading Date
    expr: reading_date
    comment: "Day of the storage reading"
  - name: Reading Month
    expr: DATE_TRUNC('MONTH', reading_date)
    comment: "Month (first day of month)"
  - name: Dam
    expr: dim_site.site_name
    synonyms: ["storage", "lake", "reservoir"]
  - name: Region
    expr: dim_site.region
  - name: Catchment
    expr: dim_site.catchment
  - name: Grid Connected
    expr: dim_site.grid_connected
measures:
  - name: Grid Storage Pct
    expr: SUM(CASE WHEN dim_site.grid_connected THEN volume_ml END) / SUM(CASE WHEN dim_site.grid_connected THEN dim_site.full_supply_volume_ml END) * 100
    comment: "SEQ Water Grid storage as % of full supply volume (grid-connected dams). Use for 'grid storage', 'dam levels overall', 'how full are our dams'."
    synonyms: ["grid storage", "combined dam level", "water grid level"]
  - name: Storage Pct
    expr: SUM(volume_ml) / SUM(dim_site.full_supply_volume_ml) * 100
    comment: "Storage as % of full supply volume for whatever dams are in the group"
    synonyms: ["percent full", "dam level"]
  - name: Avg Volume ML
    expr: SUM(volume_ml) / COUNT(DISTINCT reading_date)
    comment: "Average volume held (ML) over the selected days"
  - name: Inflow ML
    expr: SUM(inflow_ml)
    comment: "Total inflow (ML)"
  - name: Release ML
    expr: SUM(release_ml)
    comment: "Total released or drawn for supply (ML)"
  - name: Avg Daily Rainfall mm
    expr: AVG(catchment_rainfall_mm)
    comment: "Average daily catchment rainfall (mm)"
""",
    "mv_water_quality": """
version: 1.1
comment: "Water quality KPIs from raw and treated water samples. Use Max Value / Latest Value for trends of a single parameter; never average different parameters together."
source: {fq}.water_quality_samples
joins:
  - name: dim_site
    source: {fq}.sites
    on: source.site_id = dim_site.site_id
dimensions:
  - name: Sample Date
    expr: sample_date
  - name: Sample Week
    expr: DATE_TRUNC('WEEK', sample_date)
  - name: Sample Month
    expr: DATE_TRUNC('MONTH', sample_date)
  - name: Site
    expr: dim_site.site_name
  - name: Site Type
    expr: dim_site.site_type
  - name: Region
    expr: dim_site.region
  - name: Sample Point
    expr: sample_point
    comment: "Raw water or Treated water"
  - name: Parameter
    expr: parameter
    synonyms: ["analyte", "water quality measure"]
  - name: Unit
    expr: unit
measures:
  - name: Sample Count
    expr: COUNT(1)
  - name: Exceedance Count
    expr: COUNT_IF(exceeds_guideline)
    comment: "Results beyond the guideline"
    synonyms: ["breaches", "exceedances"]
  - name: Exceedance Rate Pct
    expr: COUNT_IF(exceeds_guideline) / COUNT(1) * 100
  - name: Max Value
    expr: MAX(value)
  - name: Avg Value
    expr: AVG(value)
  - name: Latest Value
    expr: MAX_BY(value, sample_date)
    comment: "Most recent result in the group"
  - name: Pct Of Guideline
    expr: MAX(value) / MAX(guideline_value) * 100
    comment: "Highest result as % of its guideline (single parameter only)"
""",
    "mv_treatment": """
version: 1.1
comment: "Treatment plant production and performance KPIs. Utilisation Pct = production / available capacity."
source: {fq}.treatment_daily
joins:
  - name: dim_site
    source: {fq}.sites
    on: source.site_id = dim_site.site_id
dimensions:
  - name: Production Date
    expr: production_date
  - name: Production Month
    expr: DATE_TRUNC('MONTH', production_date)
  - name: Plant
    expr: dim_site.site_name
    synonyms: ["WTP", "treatment plant"]
  - name: Plant Type
    expr: dim_site.site_type
  - name: Region
    expr: dim_site.region
  - name: Grid Connected
    expr: dim_site.grid_connected
measures:
  - name: Production ML
    expr: SUM(production_ml)
  - name: Avg Daily Production ML
    expr: SUM(production_ml) / COUNT(DISTINCT production_date)
  - name: Utilisation Pct
    expr: SUM(production_ml) / NULLIF(SUM(available_capacity_mld), 0) * 100
    comment: "Production as % of available capacity. Above 90 = little headroom."
    synonyms: ["headroom", "capacity used"]
  - name: Chemical Cost AUD
    expr: SUM(chemical_cost_aud)
  - name: Chemical Cost per ML
    expr: SUM(chemical_cost_aud) / NULLIF(SUM(production_ml), 0)
  - name: Energy kWh
    expr: SUM(energy_kwh)
  - name: Energy Intensity kWh per ML
    expr: SUM(energy_kwh) / NULLIF(SUM(production_ml), 0)
  - name: Max Raw Turbidity NTU
    expr: MAX(raw_turbidity_ntu)
  - name: Non Compliant Days
    expr: COUNT_IF(NOT treated_water_compliant)
""",
    "mv_bulk_supply": """
version: 1.1
comment: "Bulk water delivered to retailers versus forecast."
source: {fq}.bulk_supply_daily
joins:
  - name: dim_retailer
    source: {fq}.retailers
    on: source.retailer_id = dim_retailer.retailer_id
dimensions:
  - name: Supply Date
    expr: supply_date
  - name: Supply Week
    expr: DATE_TRUNC('WEEK', supply_date)
  - name: Supply Month
    expr: DATE_TRUNC('MONTH', supply_date)
  - name: Retailer
    expr: dim_retailer.retailer_name
    synonyms: ["customer", "council", "water retailer"]
measures:
  - name: Delivered ML
    expr: SUM(delivered_ml)
  - name: Forecast ML
    expr: SUM(forecast_ml)
  - name: Variance ML
    expr: SUM(delivered_ml) - SUM(forecast_ml)
  - name: Variance Pct
    expr: (SUM(delivered_ml) - SUM(forecast_ml)) / NULLIF(SUM(forecast_ml), 0) * 100
    comment: "Delivered vs forecast, % (positive = demand above forecast)"
    synonyms: ["forecast error", "demand above forecast"]
  - name: Avg Daily Delivered ML
    expr: SUM(delivered_ml) / COUNT(DISTINCT supply_date)
  - name: Avg Max Temp C
    expr: AVG(max_temp_c)
""",
    "mv_energy": """
version: 1.1
comment: "Electricity use, cost and peak-tariff exposure. Target peak share for transfer pumping is 20%; Avoidable Peak Cost AUD prices the excess at the peak/off-peak difference ($0.20/kWh)."
source: {fq}.energy_daily
joins:
  - name: dim_site
    source: {fq}.sites
    on: source.site_id = dim_site.site_id
dimensions:
  - name: Energy Date
    expr: energy_date
  - name: Energy Month
    expr: DATE_TRUNC('MONTH', energy_date)
  - name: Site
    expr: dim_site.site_name
  - name: Site Type
    expr: dim_site.site_type
  - name: Region
    expr: dim_site.region
measures:
  - name: Energy MWh
    expr: SUM(energy_kwh) / 1000
  - name: Energy Cost AUD
    expr: SUM(energy_cost_aud)
    synonyms: ["electricity cost", "power bill"]
  - name: Peak Share Pct
    expr: SUM(peak_kwh) / NULLIF(SUM(energy_kwh), 0) * 100
    comment: "Share of energy used in the peak tariff window"
  - name: Peak Cost AUD
    expr: SUM(peak_cost_aud)
  - name: Avoidable Peak Cost AUD
    expr: GREATEST(SUM(peak_kwh) - 0.20 * SUM(energy_kwh), 0) * 0.20
    comment: "Cost that would be avoided by bringing peak share down to the 20% target"
  - name: Cost per MWh AUD
    expr: SUM(energy_cost_aud) / NULLIF(SUM(energy_kwh) / 1000, 0)
  - name: Emissions tCO2e
    expr: SUM(emissions_tco2e)
""",
    "mv_asset_health": """
version: 1.1
comment: "Pump condition KPIs from daily condition monitoring. Health below 40 = intervene now; vibration alarm at 7.1 mm/s."
source: {fq}.asset_condition_daily
joins:
  - name: dim_asset
    source: {fq}.assets
    on: source.asset_id = dim_asset.asset_id
    joins:
      - name: dim_site
        source: {fq}.sites
        on: dim_asset.site_id = dim_site.site_id
dimensions:
  - name: Reading Date
    expr: reading_date
  - name: Reading Week
    expr: DATE_TRUNC('WEEK', reading_date)
  - name: Asset
    expr: dim_asset.asset_name
  - name: Asset Id
    expr: dim_asset.asset_id
  - name: Criticality
    expr: dim_asset.criticality
  - name: Site
    expr: dim_asset.dim_site.site_name
  - name: Region
    expr: dim_asset.dim_site.region
measures:
  - name: Avg Health Score
    expr: AVG(health_score)
  - name: Min Health Score
    expr: MIN(health_score)
  - name: Latest Health Score
    expr: MAX_BY(health_score, reading_date)
  - name: Avg Vibration mm s
    expr: AVG(vibration_mm_s)
  - name: Max Vibration mm s
    expr: MAX(vibration_mm_s)
  - name: Max Bearing Temp C
    expr: MAX(bearing_temp_c)
  - name: Alarm Days
    expr: COUNT_IF(vibration_alarm)
  - name: Assets Monitored
    expr: COUNT(DISTINCT source.asset_id)
""",
    "mv_work_orders": """
version: 1.1
comment: "Maintenance work order KPIs. Overdue = not Completed or Scheduled and past due date (Brisbane today)."
source: {fq}.work_orders
joins:
  - name: dim_asset
    source: {fq}.assets
    on: source.asset_id = dim_asset.asset_id
  - name: dim_site
    source: {fq}.sites
    on: source.site_id = dim_site.site_id
dimensions:
  - name: Raised Month
    expr: DATE_TRUNC('MONTH', raised_date)
  - name: Due Date
    expr: due_date
  - name: Work Type
    expr: work_type
  - name: Priority
    expr: priority
  - name: Status
    expr: status
  - name: Criticality
    expr: dim_asset.criticality
  - name: Asset Class
    expr: dim_asset.asset_class
  - name: Asset
    expr: dim_asset.asset_name
  - name: Site
    expr: dim_site.site_name
  - name: Source System
    expr: source_system
  - name: Is Overdue
    expr: status NOT IN ('Completed', 'Scheduled') AND due_date < {today}
measures:
  - name: Work Orders
    expr: COUNT(1)
  - name: Open Work Orders
    expr: COUNT_IF(status IN ('Open', 'In Progress'))
  - name: Overdue Work Orders
    expr: COUNT_IF(status NOT IN ('Completed', 'Scheduled') AND due_date < {today})
    synonyms: ["backlog overdue", "late work orders"]
  - name: Overdue Critical Work Orders
    expr: COUNT_IF(status NOT IN ('Completed', 'Scheduled') AND due_date < {today} AND dim_asset.criticality = 'A')
  - name: Max Days Overdue
    expr: MAX(CASE WHEN status NOT IN ('Completed', 'Scheduled') AND due_date < {today} THEN DATEDIFF({today}, due_date) END)
  - name: Maintenance Cost AUD
    expr: SUM(cost_aud)
  - name: PM On Time Pct
    expr: COUNT_IF(work_type = 'Preventive' AND status = 'Completed' AND completed_date <= due_date) / NULLIF(COUNT_IF(work_type = 'Preventive' AND status = 'Completed'), 0) * 100
    comment: "Preventive maintenance completed on or before the due date, %"
""",
    "mv_capital_program": """
version: 1.1
comment: "Capital program cost and schedule KPIs across the Dam Improvement Program, Water Security Program, Asset Renewals and Digital & Technology."
source: {fq}.capital_projects
dimensions:
  - name: Program
    expr: program
  - name: Project
    expr: project_name
  - name: Phase
    expr: phase
  - name: RAG Status
    expr: rag_status
    synonyms: ["status", "health"]
measures:
  - name: Projects
    expr: COUNT(1)
  - name: Approved Budget AUD
    expr: SUM(approved_budget_aud)
  - name: Forecast Cost AUD
    expr: SUM(forecast_cost_aud)
  - name: Cost Variance AUD
    expr: SUM(forecast_cost_aud) - SUM(approved_budget_aud)
    synonyms: ["overrun", "cost blowout"]
  - name: Cost Variance Pct
    expr: (SUM(forecast_cost_aud) - SUM(approved_budget_aud)) / NULLIF(SUM(approved_budget_aud), 0) * 100
  - name: Spend To Date AUD
    expr: SUM(spend_to_date_aud)
  - name: Avg Schedule Slip Days
    expr: AVG(DATEDIFF(forecast_finish_date, baseline_finish_date))
  - name: Max Schedule Slip Days
    expr: MAX(DATEDIFF(forecast_finish_date, baseline_finish_date))
""",
}


def create_all(spark, catalog: str, schema: str) -> None:
    fq = f"`{catalog}`.`{schema}`"
    for name, yaml in METRIC_VIEWS.items():
        body = yaml.replace("{fq}", f"{catalog}.{schema}").replace("{today}", TODAY)
        stmt = f"CREATE OR REPLACE VIEW {fq}.{name} WITH METRICS LANGUAGE YAML AS $$\n{body}\n$$"
        try:
            spark.sql(stmt)
        except Exception as e:  # older runtimes do not support semantic metadata
            print(f"  {name}: retrying without synonyms ({str(e).splitlines()[0][:160]})")
            spark.sql(re.sub(r"\n\s*synonyms: \[.*?\]", "", stmt))
        try:  # tags are best-effort: workspaces with governed tag policies may reject these keys or values
            spark.sql(f"ALTER VIEW {fq}.{name} SET TAGS ('demo' = 'seqwater-ai-demo', 'certified' = 'true')")
        except Exception as e:
            print(f"  {name}: tags skipped ({str(e).splitlines()[0][:120]})")
        print(f"  created metric view {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    args = ap.parse_args()
    create_all(SparkSession.builder.getOrCreate(), args.catalog, args.schema)


if __name__ == "__main__":
    main()
