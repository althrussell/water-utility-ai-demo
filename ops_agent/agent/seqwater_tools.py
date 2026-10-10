"""Seqwater operations tools for the agent.

Read tools query governed Unity Catalog data through a SQL warehouse. Action tools write to
`agent_actions` (and so into work_orders on the next refresh) and are gated by human approval
in agent.py (REQUIRE_APPROVAL). All SQL runs as the app's service principal, which the installer
grants least-privilege access to the demo schema.

Configuration (app.yaml env / .env): SEQWATER_CATALOG, SEQWATER_SCHEMA, SEQWATER_WAREHOUSE_ID.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from databricks.sdk.service.sql import StatementParameterListItem, StatementState
from langchain_core.tools import BaseTool, tool

from databricks_agentkit import workspace_client

ALIASES = {
    "wivenhoe": "WIV", "somerset": "SOM", "north pine dam": "NPD", "samsonvale": "NPD", "hinze": "HIN",
    "baroon": "BPD", "lake baroon": "BPD", "macdonald": "LMD", "leslie harrison": "LHD", "kurwongbah": "LKB",
    "manchester": "LMN", "wyaralong": "WYA", "mt crosby": "MCE", "mount crosby": "MCE", "eastbank": "MCE",
    "westbank": "MCW", "north pine wtp": "NPW", "molendinar": "MOL", "mudgeeraba": "MUD", "landers": "LSW",
    "landers shute": "LSW", "noosa": "NOW", "capalaba": "CAP", "canungra": "CAN", "beaudesert": "BEA",
    "desal": "GCD", "desalination": "GCD", "tugun": "GCD", "bundamba": "BUN", "npi": "NPI-MOR",
    "northern pipeline": "NPI-MOR", "srwp": "SRWP-CHF", "southern regional": "SRWP-CHF",
}


def _fq() -> str:
    return f"`{os.environ['SEQWATER_CATALOG']}`.`{os.environ['SEQWATER_SCHEMA']}`"


def _sql(statement: str, **params: Any) -> list[dict]:
    """Run a statement on the demo warehouse and return rows as dicts."""
    w = workspace_client()
    resp = w.statement_execution.execute_statement(
        warehouse_id=os.environ["SEQWATER_WAREHOUSE_ID"],
        statement=statement.replace("{fq}", _fq()),
        parameters=[StatementParameterListItem(name=k, value=None if v is None else str(v)) for k, v in params.items()],
        wait_timeout="30s",
    )
    while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status and resp.status.state != StatementState.SUCCEEDED:
        msg = resp.status.error.message if resp.status.error else str(resp.status.state)
        raise RuntimeError(f"SQL failed: {msg}")
    if not resp.manifest or not resp.result:
        return []
    cols = [c.name for c in resp.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (resp.result.data_array or [])]


def _out(data: Any) -> str:
    return json.dumps(data, default=str)[:12000]


def _resolve_site(site: str) -> str:
    s = (site or "").strip()
    if not s:
        raise ValueError("site is required")
    key = s.lower()
    for alias, sid in ALIASES.items():
        if alias in key:
            return sid
    rows = _sql("SELECT site_id FROM {fq}.sites WHERE upper(site_id) = upper(:s) OR lower(site_name) LIKE lower(concat('%', :s, '%')) "
                "ORDER BY length(site_name) LIMIT 1", s=s)
    if not rows:
        raise ValueError(f"No site matches '{site}'. Try a name like 'Landers Shute', 'Mount Crosby' or 'Baroon Pocket'.")
    return rows[0]["site_id"]


def build_seqwater_tools(actor: str) -> list[BaseTool]:
    """Build the Seqwater tools. ``actor`` is the signed-in user, recorded on approved actions."""

    @tool
    def get_morning_briefing() -> str:
        """Get today's AI-written Seqwater Morning Operations Briefing and the ranked proactive insights behind it.
        Use first for 'what do I need to know today', 'morning briefing', 'top issues', 'what changed'."""
        brief = _sql("SELECT briefing_date, headline, briefing_markdown FROM {fq}.daily_briefing ORDER BY briefing_date DESC LIMIT 1")
        insights = _sql("SELECT `rank`, severity, domain, site_id, headline, recommended_action, owner_role, impact_aud "
                        "FROM {fq}.proactive_insights WHERE insight_date = (SELECT MAX(insight_date) FROM {fq}.proactive_insights) ORDER BY `rank`")
        return _out({"briefing": brief[0] if brief else None, "insights": insights})

    @tool
    def list_proactive_insights(domain: str = "", min_severity: str = "Medium") -> str:
        """List today's proactive insights, optionally filtered by domain (Water Quality, Compliance, Assets,
        Demand, Energy, Water Security, Capital, Operations) and minimum severity (Critical, High, Medium, Info).
        Returns evidence, recommended action, owner and AI narrative."""
        order = {"critical": 1, "high": 2, "medium": 3, "info": 4}.get(min_severity.lower(), 3)
        rows = _sql("""
            SELECT `rank`, severity, domain, site_id, headline, detail, recommended_action, owner_role, impact_aud, narrative
            FROM {fq}.proactive_insights
            WHERE insight_date = (SELECT MAX(insight_date) FROM {fq}.proactive_insights)
              AND (:domain = '' OR lower(domain) = lower(:domain))
              AND CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END <= CAST(:ord AS INT)
            ORDER BY `rank`""", domain=domain or "", ord=order)
        return _out(rows)

    @tool
    def investigate_site(site: str) -> str:
        """360-degree view of one site (dam, treatment plant, desalination plant or pump station) by name or code:
        description, latest storage or production and utilisation, latest raw and treated water quality, open
        incidents, at-risk assets, overdue maintenance and today's related insights. Use to investigate a flag."""
        sid = _resolve_site(site)
        result: dict[str, Any] = {"site": _sql("SELECT * FROM {fq}.sites WHERE site_id = :s", s=sid)}
        result["storage_last_7d"] = _sql("""
            SELECT reading_date, round(percent_full, 1) AS percent_full, inflow_ml, release_ml FROM {fq}.storage_levels_daily
            WHERE site_id = :s ORDER BY reading_date DESC LIMIT 7""", s=sid)
        result["production_last_7d"] = _sql("""
            SELECT production_date, production_ml, available_capacity_mld, utilisation_pct, raw_turbidity_ntu,
                   treated_turbidity_ntu, chemical_cost_aud FROM {fq}.treatment_daily
            WHERE site_id = :s ORDER BY production_date DESC LIMIT 7""", s=sid)
        result["water_quality_latest"] = _sql("""
            SELECT parameter, sample_point, MAX_BY(value, sample_date) AS latest_value, MAX(sample_date) AS latest_date,
                   ANY_VALUE(unit) AS unit, ANY_VALUE(guideline_value) AS guideline, COUNT_IF(exceeds_guideline) AS exceedances_30d
            FROM {fq}.water_quality_samples
            WHERE site_id = :s AND sample_date > (SELECT date_sub(data_through_date, 30) FROM {fq}.demo_metadata)
            GROUP BY parameter, sample_point ORDER BY exceedances_30d DESC, parameter""", s=sid)
        result["open_incidents"] = _sql("""
            SELECT incident_id, reported_at, category, severity, title, regulator_notifiable, notification_due_at, notified_at
            FROM {fq}.incidents WHERE site_id = :s AND status = 'Open' ORDER BY severity""", s=sid)
        result["assets_at_risk"] = _sql("""
            SELECT a.asset_id, a.asset_name, a.criticality, MAX_BY(c.health_score, c.reading_date) AS health,
                   MAX_BY(c.vibration_mm_s, c.reading_date) AS vibration_mm_s
            FROM {fq}.asset_condition_daily c JOIN {fq}.assets a ON c.asset_id = a.asset_id
            WHERE a.site_id = :s AND c.reading_date > (SELECT date_sub(data_through_date, 3) FROM {fq}.demo_metadata)
            GROUP BY ALL HAVING health < 70 ORDER BY health""", s=sid)
        result["overdue_work_orders"] = _sql("""
            SELECT work_order_id, asset_id, work_type, priority, status, due_date, description
            FROM {fq}.work_orders WHERE site_id = :s AND status IN ('Open', 'In Progress')
              AND due_date < (SELECT data_through_date FROM {fq}.demo_metadata) ORDER BY due_date""", s=sid)
        result["related_insights"] = _sql("""
            SELECT `rank`, severity, headline, recommended_action FROM {fq}.proactive_insights
            WHERE insight_date = (SELECT MAX(insight_date) FROM {fq}.proactive_insights) AND site_id = :s ORDER BY `rank`""", s=sid)
        return _out(result)

    @tool
    def water_quality_trend(site: str, parameter: str, days: int = 30) -> str:
        """Daily trend of one water quality parameter at a site, e.g. site='Baroon Pocket Dam',
        parameter='Total cyanobacteria' or 'Geosmin', 'Treated turbidity', 'Free chlorine', 'E. coli', 'Manganese'."""
        sid = _resolve_site(site)
        rows = _sql("""
            SELECT sample_date, parameter, value, unit, guideline_value, exceeds_guideline
            FROM {fq}.water_quality_samples
            WHERE site_id = :s AND lower(parameter) LIKE lower(concat('%', :p, '%'))
              AND sample_date > (SELECT date_sub(data_through_date, CAST(:d AS INT)) FROM {fq}.demo_metadata)
            ORDER BY parameter, sample_date""", s=sid, p=parameter, d=int(days))
        return _out({"site_id": sid, "samples": rows})

    @tool
    def asset_health(asset_or_site: str) -> str:
        """Condition and maintenance status for an asset id (e.g. MCE-HLP-03) or all monitored pumps at a site:
        latest health score and vibration vs 7, 21 and 30 days ago, alarm status, criticality, replacement value,
        and open or overdue work orders. Use for failure risk and maintenance questions."""
        key = asset_or_site.strip()
        if "-" in key and key.upper() == key:
            asset_filter, value = "a.asset_id = :k", key
        else:
            asset_filter, value = "a.site_id = :k", _resolve_site(key)
        rows = _sql(f"""
            WITH d AS (SELECT data_through_date AS d FROM {{fq}}.demo_metadata)
            SELECT a.asset_id, a.asset_name, a.criticality, a.install_year, a.replacement_value_aud,
                   MAX(CASE WHEN c.reading_date = d.d THEN c.health_score END) AS health_now,
                   MAX(CASE WHEN c.reading_date = date_sub(d.d, 7) THEN c.health_score END) AS health_7d_ago,
                   MAX(CASE WHEN c.reading_date = date_sub(d.d, 30) THEN c.health_score END) AS health_30d_ago,
                   MAX(CASE WHEN c.reading_date = d.d THEN c.vibration_mm_s END) AS vibration_now,
                   MAX(CASE WHEN c.reading_date = date_sub(d.d, 21) THEN c.vibration_mm_s END) AS vibration_21d_ago,
                   MAX(CASE WHEN c.reading_date = d.d THEN c.bearing_temp_c END) AS bearing_temp_now,
                   MAX(CASE WHEN c.reading_date = d.d THEN c.vibration_alarm END) AS in_alarm
            FROM {{fq}}.assets a JOIN {{fq}}.asset_condition_daily c ON a.asset_id = c.asset_id, d
            WHERE {asset_filter} AND c.reading_date >= date_sub(d.d, 30)
            GROUP BY ALL ORDER BY health_now LIMIT 12""", k=value)
        ids = [r["asset_id"] for r in rows] or [value]
        wos = _sql("""
            SELECT work_order_id, asset_id, work_type, priority, status, due_date, source_system, description,
                   datediff((SELECT data_through_date FROM {fq}.demo_metadata), due_date) AS days_overdue
            FROM {fq}.work_orders WHERE array_contains(split(:ids, ','), asset_id) AND status IN ('Open', 'In Progress', 'Scheduled')
            ORDER BY due_date""", ids=",".join(ids))
        return _out({"assets": rows, "open_work_orders": wos,
                     "notes": "Vibration alarm 7.1 mm/s; health below 40 = intervene now."})

    @tool
    def water_security_outlook(extra_demand_pct: float = 0.0, retailer: str = "", extra_desal_mld: float = 0.0) -> str:
        """Grid storage position and a what-if: days until each drought trigger level at the current drawdown, and
        under a scenario where demand runs `extra_demand_pct` % higher - for one `retailer` (e.g. 'Unitywater') or all
        retailers if blank - and/or the Gold Coast Desalination Plant adds `extra_desal_mld` ML/d (max ~105 above
        hot standby). Example: extra_demand_pct=9, retailer='Unitywater' for 'if Unitywater stays 9% high'."""
        g = _sql("""
            WITH d AS (SELECT data_through_date AS d FROM {fq}.demo_metadata),
            g AS (SELECT l.reading_date, SUM(l.volume_ml) AS v, SUM(s.full_supply_volume_ml) AS fsv
                  FROM {fq}.storage_levels_daily l JOIN {fq}.sites s ON l.site_id = s.site_id WHERE s.grid_connected GROUP BY 1)
            SELECT MAX(CASE WHEN reading_date = d.d THEN v / fsv * 100 END) AS pct_now,
                   MAX(CASE WHEN reading_date = date_sub(d.d, 30) THEN v / fsv * 100 END) AS pct_30d_ago,
                   MAX(fsv) AS grid_fsv_ml
            FROM g, d""")[0]
        demand = _sql("""SELECT SUM(b.delivered_ml) / 30 AS avg_daily_ml FROM {fq}.bulk_supply_daily b
                         JOIN {fq}.retailers r ON b.retailer_id = r.retailer_id
                         WHERE b.supply_date > (SELECT date_sub(data_through_date, 30) FROM {fq}.demo_metadata)
                           AND (:r = '' OR lower(r.retailer_name) LIKE lower(concat('%', :r, '%')) OR r.retailer_id = upper(:r))""",
                      r=retailer or "")[0]
        triggers = _sql("SELECT grid_storage_percent, stage, actions FROM {fq}.drought_trigger_levels ORDER BY grid_storage_percent DESC")
        pct_now, pct_30, fsv = float(g["pct_now"]), float(g["pct_30d_ago"]), float(g["grid_fsv_ml"])
        base_ml_day = (pct_30 - pct_now) / 30 * fsv / 100
        scen_ml_day = base_ml_day + float(extra_demand_pct) / 100 * float(demand["avg_daily_ml"]) - float(extra_desal_mld)
        out = []
        for t in triggers:
            lvl = float(t["grid_storage_percent"])
            if lvl >= pct_now:
                continue
            gap_ml = (pct_now - lvl) / 100 * fsv
            out.append({"level_pct": lvl, "stage": t["stage"], "actions": t["actions"],
                        "days_at_current_rate": round(gap_ml / base_ml_day) if base_ml_day > 0 else None,
                        "days_in_scenario": round(gap_ml / scen_ml_day) if scen_ml_day > 0 else None})
        return _out({"grid_storage_pct_now": round(pct_now, 2), "grid_storage_pct_30d_ago": round(pct_30, 2),
                     "net_drawdown_ml_per_day_now": round(base_ml_day, 0),
                     "net_drawdown_ml_per_day_scenario": round(scen_ml_day, 0),
                     "scenario": {"extra_demand_pct": extra_demand_pct, "applies_to": retailer or "all retailers",
                                  "baseline_daily_demand_ml": round(float(demand["avg_daily_ml"] or 0)),
                                  "extra_desal_mld": extra_desal_mld},
                     "triggers": out, "note": "Linear projection, no rain assumed. Trigger levels are demo assumptions."})

    @tool
    def energy_shift_savings(target_peak_share_pct: float = 20.0) -> str:
        """For each bulk transfer pump station, the last 30 days of energy, peak-tariff share and the cost avoided by
        shifting pumping down to `target_peak_share_pct` (peak $0.31 vs off-peak $0.11 per kWh), 30-day and annualised."""
        rows = _sql("""
            SELECT s.site_name, SUM(e.energy_kwh) AS kwh, SUM(e.peak_kwh) / SUM(e.energy_kwh) * 100 AS peak_share_pct,
                   SUM(e.energy_cost_aud) AS cost_30d_aud,
                   GREATEST(SUM(e.peak_kwh) - CAST(:t AS DOUBLE) / 100 * SUM(e.energy_kwh), 0) * 0.20 AS avoidable_30d_aud
            FROM {fq}.energy_daily e JOIN {fq}.sites s ON e.site_id = s.site_id
            WHERE s.site_type = 'Pump Station' AND e.energy_date > (SELECT date_sub(data_through_date, 30) FROM {fq}.demo_metadata)
            GROUP BY s.site_name ORDER BY avoidable_30d_aud DESC""", t=float(target_peak_share_pct))
        total = sum(float(r["avoidable_30d_aud"] or 0) for r in rows)
        return _out({"target_peak_share_pct": target_peak_share_pct, "pump_stations": rows,
                     "total_avoidable_30d_aud": round(total), "total_avoidable_annualised_aud": round(total * 365 / 30)})

    @tool
    def get_reservoir_profile() -> str:
        """Baroon Pocket Dam (Lake Baroon) digital twin data: today's water level, the three intake offtake levels
        (Upper/Middle/Lower) with their depth and the water quality at each depth (cyanobacteria, manganese, oxygen),
        which offtake is in service, and the latest surface readings from the six lake buoys with 7-day change.
        Use for the algal bloom, taste and odour, Landers Shute raw water quality and 'which offtake should we use'."""
        lvl = _sql("""SELECT reading_date, percent_full, water_level_m FROM {fq}.reservoir_level_daily
                      WHERE site_id = 'BPD' ORDER BY reading_date DESC LIMIT 1""")
        offt = _sql("""
            WITH d AS (SELECT MAX(reading_date) AS d FROM {fq}.reservoir_profile_daily),
            lvl AS (SELECT water_level_m FROM {fq}.reservoir_level_daily WHERE site_id = 'BPD' ORDER BY reading_date DESC LIMIT 1),
            act AS (SELECT replace(asset_id, 'BPD-OFFTAKE-', '') AS level FROM {fq}.agent_actions
                    WHERE action_type = 'OFFTAKE_CHANGE' ORDER BY created_at DESC LIMIT 1),
            o AS (SELECT o.offtake_level, o.centre_elevation_m, (SELECT water_level_m FROM lvl) - o.centre_elevation_m AS depth_m,
                         COALESCE(o.offtake_level = (SELECT level FROM act), o.in_service) AS in_service
                  FROM {fq}.reservoir_offtakes o),
            q AS (SELECT o.*, p.cyanobacteria_cells_ml, p.manganese_mg_l, p.dissolved_oxygen_mg_l, p.water_temp_c,
                         ROW_NUMBER() OVER (PARTITION BY o.offtake_level ORDER BY abs(p.depth_m - o.depth_m)) AS rn
                  FROM o CROSS JOIN {fq}.reservoir_profile_daily p, d WHERE p.reading_date = d.d)
            SELECT offtake_level, round(centre_elevation_m, 1) AS elevation_m, round(depth_m, 1) AS depth_m, in_service,
                   cyanobacteria_cells_ml, manganese_mg_l, dissolved_oxygen_mg_l, water_temp_c
            FROM q WHERE rn = 1 ORDER BY depth_m""")
        buoys = _sql("""
            WITH d AS (SELECT MAX(reading_date) AS d FROM {fq}.reservoir_buoy_readings_daily)
            SELECT b.buoy_id, b.buoy_name,
                   MAX(CASE WHEN r.reading_date = d.d THEN r.cyanobacteria_cells_ml END) AS cyano_today,
                   MAX(CASE WHEN r.reading_date = date_sub(d.d, 7) THEN r.cyanobacteria_cells_ml END) AS cyano_7d_ago,
                   MAX(CASE WHEN r.reading_date = d.d THEN r.geosmin_ng_l END) AS geosmin_today,
                   MAX(CASE WHEN r.reading_date = d.d THEN r.surface_temp_c END) AS surface_temp_today
            FROM {fq}.reservoir_buoys b JOIN {fq}.reservoir_buoy_readings_daily r ON b.buoy_id = r.buoy_id, d
            GROUP BY ALL ORDER BY cyano_today DESC""")
        return _out({"water_level": lvl[0] if lvl else None, "offtakes": offt, "buoys": buoys,
                     "notes": "Alert Level 1 = 2,000 cells/mL; manganese aesthetic guideline 0.1 mg/L; oxygen < 2 mg/L releases manganese."})

    @tool
    def list_open_incidents() -> str:
        """Open incidents with regulator notification status (notifiable, deadline, whether notified)."""
        return _out(_sql("""
            SELECT i.incident_id, i.reported_at, i.site_id, s.site_name, i.category, i.severity, i.title, i.description,
                   i.regulator_notifiable, i.notification_due_at, i.notified_at,
                   (SELECT COUNT(*) FROM {fq}.agent_actions a WHERE a.incident_id = i.incident_id
                      AND a.action_type = 'REGULATOR_NOTIFICATION') AS notifications_recorded
            FROM {fq}.incidents i JOIN {fq}.sites s ON i.site_id = s.site_id
            WHERE i.status = 'Open' ORDER BY i.severity, i.reported_at DESC LIMIT 20"""))

    @tool
    def recent_agent_actions(limit: int = 10) -> str:
        """Actions the agent has taken after human approval (work orders, regulator notifications, briefings)."""
        return _out(_sql("SELECT * FROM {fq}.agent_actions ORDER BY created_at DESC LIMIT " + str(int(min(max(limit, 1), 50)))))

    def _record(action_type: str, status: str, title: str, details: str, *, site_id=None, asset_id=None,
                incident_id=None, priority=None, reference_id=None) -> dict:
        action_id = str(uuid.uuid4())
        _sql("""
            INSERT INTO {fq}.agent_actions (action_id, created_at, action_type, status, site_id, asset_id, incident_id,
                                            priority, title, details, requested_by, reference_id)
            VALUES (:action_id, current_timestamp(), :action_type, :status, :site_id, :asset_id, :incident_id,
                    :priority, :title, :details, :requested_by, :reference_id)""",
             action_id=action_id, action_type=action_type, status=status, site_id=site_id, asset_id=asset_id,
             incident_id=incident_id, priority=priority, title=title, details=details, requested_by=actor,
             reference_id=reference_id)
        return {"action_id": action_id, "reference_id": reference_id, "status": status,
                "recorded_at": datetime.now(timezone.utc).isoformat(), "approved_by": actor}

    @tool
    def raise_work_order(asset_id: str, priority: str, description: str, justification: str) -> str:
        """Raise a corrective maintenance work order in the asset management system (requires human approval).
        priority: P1 (24h), P2 (7 days), P3 (28 days). description: the work to do. justification: the evidence."""
        a = _sql("SELECT asset_id, site_id, asset_name FROM {fq}.assets WHERE asset_id = :a", a=asset_id.strip().upper())
        if not a:
            return _out({"error": f"Unknown asset {asset_id}"})
        wo = f"WO-AG{datetime.now(timezone.utc):%y%m%d%H%M%S}"
        res = _record("WORK_ORDER", "Submitted", f"{a[0]['asset_name']}: {description}"[:250],
                      f"{description}\n\nJustification: {justification}", site_id=a[0]["site_id"],
                      asset_id=a[0]["asset_id"], priority=priority.upper()[:2], reference_id=wo)
        res["work_order_id"] = wo
        res["note"] = "Recorded in agent_actions; appears in work_orders (source 'Seqwater Operations Agent') after the next refresh."
        return _out(res)

    @tool
    def submit_regulator_notification(incident_id: str, recipient: str, notification_text: str) -> str:
        """Record a drinking water incident notification to the regulator / Queensland Health (requires human
        approval). Draft the full notification text first from the incident facts. Demo: recorded, not emailed."""
        inc = _sql("SELECT incident_id, site_id, title FROM {fq}.incidents WHERE incident_id = :i", i=incident_id.strip())
        if not inc:
            return _out({"error": f"Unknown incident {incident_id}"})
        ref = f"NTF-{datetime.now(timezone.utc):%y%m%d%H%M%S}"
        return _out(_record("REGULATOR_NOTIFICATION", "Submitted", f"Notification to {recipient}: {inc[0]['title']}"[:250],
                            notification_text, site_id=inc[0]["site_id"], incident_id=inc[0]["incident_id"],
                            reference_id=ref))

    @tool
    def request_offtake_change(offtake_level: str, justification: str) -> str:
        """Switch the Baroon Pocket Dam intake that supplies Landers Shute WTP to another offtake level (requires
        human approval). offtake_level: Upper, Middle or Lower. justification: the water quality evidence by depth.
        Demo: recorded in agent_actions; the digital twin and tomorrow's data show the new offtake in service."""
        level = offtake_level.strip().capitalize()
        if level not in ("Upper", "Middle", "Lower"):
            return _out({"error": "offtake_level must be Upper, Middle or Lower"})
        return _out(_record("OFFTAKE_CHANGE", "Approved", f"Switch Landers Shute WTP supply to the {level} offtake at Baroon Pocket Dam",
                            justification, site_id="BPD", asset_id=f"BPD-OFFTAKE-{level}",
                            reference_id=f"OFT-{datetime.now(timezone.utc):%y%m%d%H%M%S}"))

    @tool
    def send_stakeholder_briefing(recipient: str, subject: str, body: str) -> str:
        """Send a short briefing to a stakeholder, e.g. a retailer or the executive team (requires human approval).
        Demo: recorded in agent_actions, not emailed."""
        return _out(_record("BRIEFING", "Sent", f"{subject} -> {recipient}"[:250], body,
                            reference_id=f"BRF-{datetime.now(timezone.utc):%y%m%d%H%M%S}"))

    return [get_morning_briefing, list_proactive_insights, investigate_site, water_quality_trend, asset_health,
            water_security_outlook, energy_shift_savings, get_reservoir_profile, list_open_incidents,
            recent_agent_actions, raise_work_order, submit_regulator_notification, request_offtake_change,
            send_stakeholder_briefing]


APPROVAL_TOOLS = ("raise_work_order", "submit_regulator_notification", "request_offtake_change", "send_stakeholder_briefing")
