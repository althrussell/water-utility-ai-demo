---
name: seqwater-board-water-security
description: "Drafts the monthly Seqwater Board paper on water security: SEQ Water Grid storage position and trend, dam-by-dam levels, inflows, demand versus forecast by retailer, climate-independent supply readiness (Gold Coast Desalination Plant, Western Corridor Recycled Water Scheme), drought trigger outlook and capital program items relevant to water security. Use when someone asks for a board paper, board update, water security report or brief, or drought outlook."
metadata:
  compatible-agents: genie
---

# Seqwater Board Paper: Water Security Position

You are drafting the standing water security paper for the Seqwater Board. The Board is non-executive. Its members want the position, the trend, the risk and the recommendation in plain language, and they will hold management to the numbers.

## Rules

- Write in Board paper style: numbered paragraphs, a formal but plain tone, and no operational jargon without a gloss.
- Every claim is backed by a number from the data.
- Drought trigger levels in `drought_trigger_levels` are demo assumptions. Call them "demo trigger levels".
- Money in $M. Volumes in GL (gigalitres) for grid totals (1 GL = 1,000 ML) and ML for individual dams.
- Under 700 words, plus tables.
- Synthetic demo data. Note it in the footer.

## Data (Unity Catalog: `{{fq}}`)

Metric views take the rules: `MEASURE()`, `GROUP BY ALL`, never join two metric views.

- `mv_water_security`: Grid Storage Pct, Storage Pct, Avg Volume ML, Inflow ML, Avg Daily Rainfall mm. Dimensions: Reading Date, Reading Month, Dam, Region, Catchment, Grid Connected.
- `mv_bulk_supply`: Delivered ML, Forecast ML, Variance Pct. Dimensions: Supply Month, Retailer.
- `mv_treatment`: Production ML, Utilisation Pct. Dimensions: Plant, Plant Type, Production Month.
- `drought_trigger_levels`, `weather_daily` (is_forecast = true for the next 7 days), `capital_projects` (program = 'Water Security Program' or 'Dam Improvement Program').
- `demo_metadata.data_through_date`: the latest complete day.

## Queries

```sql
-- Grid storage: latest vs 30, 90, 365 days ago
SELECT `Reading Date`, MEASURE(`Grid Storage Pct`) AS grid_storage_pct
FROM {{fq}}.mv_water_security
WHERE `Reading Date` IN ((SELECT data_through_date FROM {{fq}}.demo_metadata),
                         (SELECT date_sub(data_through_date, 30) FROM {{fq}}.demo_metadata),
                         (SELECT date_sub(data_through_date, 90) FROM {{fq}}.demo_metadata),
                         (SELECT date_sub(data_through_date, 365) FROM {{fq}}.demo_metadata))
GROUP BY ALL ORDER BY `Reading Date`

-- Dam by dam (grid connected), latest day
SELECT `Dam`, `Region`, MEASURE(`Storage Pct`) AS pct_full, MEASURE(`Avg Volume ML`) AS volume_ml
FROM {{fq}}.mv_water_security
WHERE `Reading Date` = (SELECT data_through_date FROM {{fq}}.demo_metadata) AND `Grid Connected`
GROUP BY ALL ORDER BY volume_ml DESC

-- Monthly inflows, last 12 months
SELECT `Reading Month`, MEASURE(`Inflow ML`) AS inflow_ml, MEASURE(`Avg Daily Rainfall mm`) AS rain_mm
FROM {{fq}}.mv_water_security
WHERE `Grid Connected` AND `Reading Month` >= (SELECT add_months(trunc(data_through_date, 'MM'), -11) FROM {{fq}}.demo_metadata)
GROUP BY ALL ORDER BY `Reading Month`

-- Demand vs forecast by retailer, last full month and month to date
SELECT `Supply Month`, `Retailer`, MEASURE(`Delivered ML`) AS delivered_ml, MEASURE(`Variance Pct`) AS variance_pct
FROM {{fq}}.mv_bulk_supply
WHERE `Supply Month` >= (SELECT add_months(trunc(data_through_date, 'MM'), -1) FROM {{fq}}.demo_metadata)
GROUP BY ALL ORDER BY `Supply Month`, `Retailer`

-- Climate-independent supply: desalination and recycled water output, last 30 days
SELECT `Plant`, MEASURE(`Avg Daily Production ML`) AS avg_ml_d, MEASURE(`Utilisation Pct`) AS utilisation_pct
FROM {{fq}}.mv_treatment
WHERE `Plant Type` IN ('Desalination Plant', 'Advanced Water Treatment Plant')
  AND `Production Date` > (SELECT date_sub(data_through_date, 30) FROM {{fq}}.demo_metadata)
GROUP BY ALL
```

Days to each demo trigger level = (latest Grid Storage Pct − trigger) ÷ ((Grid Storage Pct 30 days ago − latest) ÷ 30). Only compute this if storage is falling.

## Paper structure

**SEQWATER BOARD PAPER · Water Security Position · {Month yyyy}**
*For noting · Prepared by: Executive General Manager Water Security*

1. **Purpose.** One sentence.
2. **Recommendation.** "That the Board note…", followed by one or two specific items to note or endorse.
3. **Key points.** Four bullets: position, trend, demand, readiness.
4. **Grid storage position.** A table of latest vs 30, 90 and 365 days ago, with a short commentary. Add a dam-by-dam table for the grid-connected dams, flagging any under 50%. Lake Macdonald is held low for dam improvement works; say so.
5. **Inflows and outlook.** Monthly inflows for the last 12 months and the 7-day forecast rainfall.
6. **Demand.** Delivered vs forecast by retailer. Call out any retailer more than 5% above forecast and the likely driver (heat, growth).
7. **Climate-independent supply readiness.** Gold Coast Desalination Plant utilisation (hot standby versus capacity of 133 ML/d) and the Western Corridor Recycled Water Scheme status.
8. **Drought trigger outlook.** A table of each demo trigger level with the days to reach it at the current rate, and what each stage would mean.
9. **Related capital program.** Water Security Program and Dam Improvement Program projects with their RAG status and cost variance.
10. **Risks and mitigations.** Three to five rows.
11. **Next steps.**

*Footer:* "Draft prepared by Genie One from governed Seqwater data in Unity Catalog · Data to {data_through_date} · Synthetic demo data · Trigger levels are demo assumptions"
