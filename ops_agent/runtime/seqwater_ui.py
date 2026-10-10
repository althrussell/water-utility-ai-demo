"""Seqwater Ops Command Centre: the executive front end served by the agent app.

`/` is the Command Centre (briefing, KPIs, proactive insights, agent chat with approvals, action log).
The Agent Bricks developer workbench stays available at `/workbench`.
Data comes from governed Unity Catalog tables through the demo SQL warehouse (app service principal).
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent.seqwater_tools import _sql

_UI = Path(__file__).resolve().parent.parent / "ui"
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 60


QUERIES = {
    "meta": "SELECT as_of_date, data_through_date, generated_at_utc FROM {fq}.demo_metadata",
    "brief": """SELECT briefing_date, headline, briefing_markdown, critical_count, high_count, generated_at
                FROM {fq}.daily_briefing ORDER BY briefing_date DESC LIMIT 1""",
    "insights": """SELECT p.`rank`, p.severity, p.domain, p.site_id, s.site_name, s.site_type, p.headline, p.detail,
                          p.recommended_action, p.owner_role, p.impact_aud, p.narrative
                   FROM {fq}.proactive_insights p LEFT JOIN {fq}.sites s ON p.site_id = s.site_id
                   WHERE p.insight_date = (SELECT MAX(insight_date) FROM {fq}.proactive_insights) ORDER BY p.`rank`""",
    "grid": """SELECT `Reading Date` AS d, MEASURE(`Grid Storage Pct`) AS pct FROM {fq}.mv_water_security
               WHERE `Reading Date` IN ((SELECT data_through_date FROM {fq}.demo_metadata),
                                        (SELECT date_sub(data_through_date, 30) FROM {fq}.demo_metadata))
               GROUP BY ALL ORDER BY d""",
    "prod": """SELECT MEASURE(`Production ML`) AS ml FROM {fq}.mv_treatment
               WHERE `Production Date` = (SELECT data_through_date FROM {fq}.demo_metadata)""",
    "demand": """SELECT MEASURE(`Variance Pct`) AS v FROM {fq}.mv_bulk_supply
                 WHERE `Supply Date` > (SELECT date_sub(data_through_date, 14) FROM {fq}.demo_metadata)""",
    "backlog": "SELECT MEASURE(`Overdue Critical Work Orders`) AS n FROM {fq}.mv_work_orders",
    "notif": """SELECT COUNT(*) AS n FROM {fq}.incidents i
                WHERE regulator_notifiable AND notified_at IS NULL AND status = 'Open'
                  AND NOT EXISTS (SELECT 1 FROM {fq}.agent_actions a WHERE a.incident_id = i.incident_id
                                  AND a.action_type = 'REGULATOR_NOTIFICATION')""",
    "actions": """SELECT created_at, action_type, status, site_id, asset_id, incident_id, priority, title,
                         requested_by, reference_id
                  FROM {fq}.agent_actions ORDER BY created_at DESC LIMIT 12""",
}


def _overview() -> dict:
    with ThreadPoolExecutor(len(QUERIES)) as pool:
        futures = {k: pool.submit(_sql, q) for k, q in QUERIES.items()}
        r = {k: f.result() for k, f in futures.items()}
    meta, brief, insights, grid = r["meta"], r["brief"], r["insights"], r["grid"]
    prod, demand, backlog, notif, actions = r["prod"], r["demand"], r["backlog"], r["notif"], r["actions"]

    def f(rows, key):
        try:
            return float(rows[0][key])
        except (IndexError, KeyError, TypeError, ValueError):
            return None

    energy = next((i for i in insights if i["domain"] == "Energy"), None)
    return {
        "meta": meta[0] if meta else {},
        "briefing": brief[0] if brief else None,
        "kpis": {
            "grid_storage_pct": f(grid[-1:], "pct") if grid else None,
            "grid_storage_change_30d": (f(grid[-1:], "pct") - f(grid[:1], "pct")) if len(grid) == 2 else None,
            "produced_yesterday_ml": f(prod, "ml"),
            "demand_vs_forecast_pct": f(demand, "v"),
            "critical": sum(i["severity"] == "Critical" for i in insights),
            "high": sum(i["severity"] == "High" for i in insights),
            "notifications_pending": f(notif, "n"),
            "overdue_critical_pms": f(backlog, "n"),
            "avoidable_energy_aud": float(energy["impact_aud"]) if energy and energy.get("impact_aud") else None,
        },
        "insights": insights,
        "actions": actions,
    }


TWIN_QUERIES = {
    "level": """SELECT reading_date, percent_full, volume_ml, water_level_m FROM {fq}.reservoir_level_daily
                WHERE site_id = 'BPD' ORDER BY reading_date DESC LIMIT 30""",
    "buoys": "SELECT buoy_id, buoy_name, latitude, longitude, depth_at_full_supply_m FROM {fq}.reservoir_buoys ORDER BY buoy_id",
    "readings": """SELECT reading_date, buoy_id, cyanobacteria_cells_ml, geosmin_ng_l, surface_temp_c, chlorophyll_a_ug_l
                   FROM {fq}.reservoir_buoy_readings_daily ORDER BY reading_date, buoy_id""",
    "profile": """SELECT reading_date, depth_m, water_temp_c, dissolved_oxygen_mg_l, cyanobacteria_cells_ml, manganese_mg_l
                  FROM {fq}.reservoir_profile_daily ORDER BY reading_date, depth_m""",
    "offtakes": "SELECT offtake_level, centre_elevation_m, in_service FROM {fq}.reservoir_offtakes WHERE site_id = 'BPD'",
    "change": """SELECT replace(asset_id, 'BPD-OFFTAKE-', '') AS level, reference_id, requested_by, created_at
                 FROM {fq}.agent_actions WHERE action_type = 'OFFTAKE_CHANGE' ORDER BY created_at DESC LIMIT 1""",
}


def _twin() -> dict:
    with ThreadPoolExecutor(len(TWIN_QUERIES)) as pool:
        futures = {k: pool.submit(_sql, q) for k, q in TWIN_QUERIES.items()}
        r = {k: f.result() for k, f in futures.items()}
    change = r["change"][0] if r["change"] else None
    for o in r["offtakes"]:
        o["in_service"] = (o["offtake_level"] == change["level"]) if change else str(o["in_service"]).lower() == "true"
    return {"level": list(reversed(r["level"])), "buoys": r["buoys"], "readings": r["readings"],
            "profile": r["profile"], "offtakes": r["offtakes"], "offtake_change": change}


def install_seqwater_ui(app: FastAPI) -> None:
    """Register before the template's install_ui so `/` serves the Command Centre."""
    app.mount("/cc-assets", StaticFiles(directory=_UI / "cc"), name="seqwater-cc-assets")

    @app.get("/", include_in_schema=False)
    async def command_centre() -> FileResponse:
        return FileResponse(_UI / "cc" / "index.html")

    @app.get("/workbench", include_in_schema=False)
    async def workbench() -> FileResponse:
        return FileResponse(_UI / "index.html")

    @app.get("/api/seqwater/overview", include_in_schema=False)
    async def overview(fresh: bool = False):
        hit = _CACHE.get("overview")
        if hit and not fresh and time.time() - hit[0] < _TTL:
            return hit[1]
        try:
            data = await asyncio.to_thread(_overview)
        except Exception as e:  # surface a readable error in the UI instead of a blank page
            return JSONResponse({"error": str(e)[:500]}, status_code=500)
        _CACHE["overview"] = (time.time(), data)
        return data

    @app.get("/api/seqwater/twin", include_in_schema=False)
    async def twin(fresh: bool = False):
        hit = _CACHE.get("twin")
        if hit and not fresh and time.time() - hit[0] < _TTL:
            return hit[1]
        try:
            data = await asyncio.to_thread(_twin)
        except Exception as e:
            return JSONResponse({"error": str(e)[:500]}, status_code=500)
        _CACHE["twin"] = (time.time(), data)
        return data
