# Seqwater: business challenges and demo ideas

*Public-source research summary, October 2026. Figures are approximate and from public material; verify them before quoting.*

## Context

- **Seqwater** is the bulk water authority for South East Queensland. It serves about 3.8 million people through five retailers (Urban Utilities, Unitywater, City of Gold Coast, Logan, Redland) and manages around $10B of assets. Those assets include 25-plus dams and about 47 weirs, more than 30 water treatment plants, the Gold Coast Desalination Plant (133 ML/d), the Western Corridor Recycled Water Scheme and more than 600 km of SEQ Water Grid pipeline.
- **Strategic agenda:**
  - Water Security Program 2023 (a 30-year plan: desal expansion, the Logan River / Wyaralong connection, recycled water)
  - Dam Improvement Program (Somerset, Lake Macdonald, North Pine)
  - Drought Response Plan triggers
  - Growth toward Brisbane 2032
  - Water quality (algae and taste & odour, turbidity after floods, PFAS reporting)
  - Bulk water price scrutiny from the Queensland Competition Authority (QCA)
  - Critical-infrastructure cyber obligations under the SOCI Act
- **Digital and AI.** There is little public detail on Seqwater's data and AI strategy. That gives a new CTO and Innovation Executive room to set the agenda.

## Ranked demo ideas (for a CTO and an Innovation Executive)

| # | Business challenge | What the demo shows | Databricks capability |
|---|---|---|---|
| 1 | **Algal bloom and taste & odour risk** (Baroon Pocket → Landers Shute) | The warning lands before complaints spike; a sitrep in seconds | Proactive insights, Genie One, Skill |
| 2 | **Critical asset failure risk** (Mount Crosby high lift pump) | The agent investigates and raises a work order with approval | Agent Bricks, Apps, human in the loop |
| 3 | **Water security and drought readiness** | Days to trigger, what-ifs on demand and desal | Genie One, metric views, agent tool |
| 4 | **Energy cost in grid transfers** | A "$0.6M a year avoidable" insight from peak-tariff drift | Proactive insights, metric views |
| 5 | **Regulatory incident response** (E. coli at a regional plant) | Deadline-aware alert; drafted notification, approved and logged | Agent, Skill, SQL alert |
| 6 | **Capital program assurance** (Dam Improvement Program) | A board-ready variance view in house style | Skill |
| 7 | Flood event decision support | *Not recommended as a lead: politically sensitive* | (Genie / agent scenario) |

## Chosen storyline

**"From reactive to proactive water operations."** One connected story instead of seven separate use cases. It links ideas 1–6, and is scripted in [RUNBOOK.md](RUNBOOK.md).

## Pilot options for the close

1. **Water quality early warning.** Lab and online quality data, plus complaints, feeding insights and sitreps.
2. **Asset risk agent.** Condition data and Maximo, with approval-gated work orders.
3. **Executive morning briefing.** Genie One and skills over the KPIs already reported to the Board.
