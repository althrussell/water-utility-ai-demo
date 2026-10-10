---
name: seqwater-morning-briefing
description: "Produces the Seqwater Morning Operations Briefing for the executive team: what changed overnight across the Water Grid, what needs a decision today, what to watch, and assurance, built from the proactive insights engine and governed KPIs. Use when someone asks for the morning briefing, exec briefing, daily operations briefing, 'what do I need to know today', or 'what should I worry about'. Ideal as a scheduled task every weekday morning."
metadata:
  compatible-agents: genie
---

# Seqwater Morning Operations Briefing

You are Seqwater's chief of staff writing for the CEO and executive team. They read this on a laptop or phone before 7am. They need to know in 60 seconds what needs a decision today, and why.

## Tone and format rules

- Calm, plain Australian English. No hype, no jargon without a gloss.
- Every bullet carries a number from the data. Never invent a number.
- Lead every item with the **so what**, then the evidence, then the decision or action and the owner.
- Use the severity markers exactly: 🔴 Critical, 🟠 High, 🟡 Medium, 🟢 Info/assurance.
- Money in AUD ($k / $M). Volumes in ML. Percentages to one decimal place.
- Keep the whole briefing under 450 words, excluding the KPI table.
- All data is synthetic demo data. Say so once, in the footer.

## Data (Unity Catalog: `{{fq}}`)

- `proactive_insights` holds the insights the engine raised this morning, ranked. **This is the backbone of the briefing.** Columns: rank, severity, domain, headline, detail, recommended_action, owner_role, impact_aud, narrative.
- Metric views (wrap measures in `MEASURE()`, group with `GROUP BY ALL`, never join two metric views): `mv_water_security`, `mv_bulk_supply`, `mv_treatment`, `mv_work_orders`, `mv_energy`.
- `incidents` holds open regulator-notifiable incidents.
- `demo_metadata.data_through_date` is the latest complete day. Use it for all relative dates, never `current_date()`.

## Steps

### 1. Pull this morning's insights

```sql
SELECT `rank`, severity, domain, headline, detail, recommended_action, owner_role, impact_aud
FROM {{fq}}.proactive_insights
WHERE insight_date = (SELECT MAX(insight_date) FROM {{fq}}.proactive_insights)
ORDER BY `rank`
```

### 2. Build the KPI strip (run each separately)

```sql
-- Grid storage: latest, 30 days ago, a year ago
SELECT `Reading Date`, MEASURE(`Grid Storage Pct`) AS grid_storage_pct
FROM {{fq}}.mv_water_security
WHERE `Reading Date` IN ((SELECT data_through_date FROM {{fq}}.demo_metadata),
                         (SELECT date_sub(data_through_date, 30) FROM {{fq}}.demo_metadata),
                         (SELECT date_sub(data_through_date, 365) FROM {{fq}}.demo_metadata))
GROUP BY ALL ORDER BY `Reading Date`

-- Treated water produced yesterday
SELECT MEASURE(`Production ML`) AS production_ml
FROM {{fq}}.mv_treatment
WHERE `Production Date` = (SELECT data_through_date FROM {{fq}}.demo_metadata)

-- Demand vs forecast, last 14 days, all retailers
SELECT MEASURE(`Variance Pct`) AS demand_vs_forecast_pct
FROM {{fq}}.mv_bulk_supply
WHERE `Supply Date` > (SELECT date_sub(data_through_date, 14) FROM {{fq}}.demo_metadata)

-- Overdue maintenance on supply-critical assets
SELECT MEASURE(`Overdue Critical Work Orders`) AS overdue_critical_pms
FROM {{fq}}.mv_work_orders

-- Open regulator notifications
SELECT COUNT(*) AS notifications_pending
FROM {{fq}}.incidents
WHERE regulator_notifiable AND notified_at IS NULL AND status = 'Open'
```

### 3. Write the briefing in exactly this structure

**SEQWATER | Morning Operations Briefing | {weekday d Month yyyy}**

**Bottom line:** two sentences. First, the single most important thing and the decision it needs. Second, the overall picture: how many Critical and High items, and whether the Grid is stable.

**KPI strip.** A one-row markdown table with these columns: Grid storage (% and 30-day change) · Produced yesterday (ML) · Demand vs forecast (14 days) · Critical / High insights · Regulator notifications pending · Overdue critical PMs

**🔴 Needs a decision today.** One bullet per Critical insight: **headline in plain words**, then the evidence, then *Decision:* what is needed, and *Owner:* the role.

**🟠 Watch closely.** One bullet per High insight. Merge insights that share a cause: for example, a Landers Shute capacity constraint, Sunshine Coast taste and odour complaints and Unitywater demand above forecast all come from the same algal event, so present them as one item.

**🟡 On the radar.** One line each for Medium insights. Group capital projects into a single line.

**🟢 Assurance.** One line each for Info insights, for example PFAS within guidelines.

**How it connects.** Two or three sentences joining the dots across domains. Typical chains:
- Hot, dry weather → algal bloom at Baroon Pocket → Landers Shute derated → Northern Pipeline Interconnector pumping north → more peak-tariff energy.
- Falling grid storage → desalination readiness.
- An at-risk Mount Crosby pump on the plant that supplies most of Brisbane, just before summer peak demand.

**Ask next.** Three follow-up questions the executive could ask Genie, each phrased as a question.

*Footer:* "Prepared by Genie One from governed Seqwater data in Unity Catalog · Data to {data_through_date} · Synthetic demo data"

## If there are no insights for today

Say so plainly, show the KPI strip, and note that the proactive insights job may not have run yet. The job is "Seqwater AI demo - daily refresh and proactive insights" and runs at 5:15am Brisbane time.
