"""The planted demo stories must survive any change to the generator.

Run: uv run --with pandas --with numpy --with pytest pytest tests/
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data_platform" / "src"))

import seqwater_synth  # noqa: E402
from catalog_docs import TABLES  # noqa: E402


@pytest.fixture(scope="module", params=[date(2026, 10, 11), date(2027, 2, 1)])
def gen(request):
    g = seqwater_synth.SeqwaterSynth(as_of=request.param)
    g.build()
    return g


def test_every_table_is_documented(gen):
    for name, df in gen.tables.items():
        assert name in TABLES, f"{name} has no Unity Catalog documentation"
        missing = set(df.columns) - set(TABLES[name]["columns"])
        assert not missing, f"{name}: undocumented columns {missing}"


def test_data_runs_to_yesterday(gen):
    assert gen.tables["storage_levels_daily"].reading_date.max() == gen.as_of - timedelta(days=1)


def test_grid_storage_story(gen):
    st = gen.tables["storage_levels_daily"].merge(gen.tables["sites"], on="site_id")
    g = st[st.grid_connected].groupby("reading_date").apply(
        lambda x: x.volume_ml.sum() / x.full_supply_volume_ml.sum() * 100, include_groups=False)
    assert 74 < g.iloc[-1] < 81, "grid storage should sit in the high 70s"
    assert g.iloc[-1] < g.iloc[-31], "grid storage should be falling over the last 30 days"


def test_algal_bloom_story(gen):
    wq = gen.tables["water_quality_samples"]
    bpd = wq[(wq.site_id == "BPD") & (wq.parameter == "Total cyanobacteria")].sort_values("sample_date")
    assert bpd.value.iloc[-1] > 50000
    geo = wq[(wq.site_id == "BPD") & (wq.parameter == "Geosmin")].sort_values("sample_date")
    assert geo.value.iloc[-1] > 30


def test_pump_story(gen):
    c = gen.tables["asset_condition_daily"]
    hlp = c[c.asset_id == "MCE-HLP-03"].sort_values("reading_date")
    assert hlp.vibration_mm_s.iloc[-1] > 7.1 and hlp.health_score.iloc[-1] < 40
    wo = gen.tables["work_orders"]
    pm = wo[(wo.asset_id == "MCE-HLP-03") & (wo.work_type == "Preventive") & (wo.status == "Open")]
    assert len(pm) == 1
    assert (gen.data_through - pm.due_date.iloc[0]).days == 46


def test_demand_and_incident_stories(gen):
    b = gen.tables["bulk_supply_daily"]
    last = b[pd.to_datetime(b.supply_date) > pd.Timestamp(gen.data_through - timedelta(days=14))]
    unw = last[last.retailer_id == "UNW"]
    assert unw.delivered_ml.sum() / unw.forecast_ml.sum() - 1 > 0.07
    inc = gen.tables["incidents"]
    ecoli = inc[(inc.site_id == "CAN") & inc.regulator_notifiable & inc.notified_at.isna()]
    assert len(ecoli) == 1


def test_work_order_ids_unique(gen):
    assert not gen.tables["work_orders"].work_order_id.duplicated().any()


def test_twin_story(gen):
    buoys = gen.tables["reservoir_buoy_readings_daily"]
    last = buoys[buoys.reading_date == buoys.reading_date.max()].set_index("buoy_id").cyanobacteria_cells_ml
    assert last["BPD-B5"] > last["BPD-B1"], "the bloom should be strongest in the inflow arm"
    prof = gen.tables["reservoir_profile_daily"]
    p = prof[prof.reading_date == prof.reading_date.max()].set_index("depth_m")
    level = gen.tables["reservoir_level_daily"].water_level_m.iloc[-1]
    offt = gen.tables["reservoir_offtakes"].set_index("offtake_level").centre_elevation_m
    depth = {k: level - v for k, v in offt.items()}
    near = lambda d: p.iloc[(p.index.to_series() - d).abs().argmin()]
    assert depth["Upper"] > 0.5, "upper offtake must stay below the water surface"
    assert near(depth["Middle"]).cyanobacteria_cells_ml < near(depth["Upper"]).cyanobacteria_cells_ml * 0.2
    assert near(depth["Lower"]).manganese_mg_l > 0.1 > near(depth["Middle"]).manganese_mg_l
