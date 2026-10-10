"""Synthetic Seqwater operating data for the Databricks executive demo.

Everything here is SYNTHETIC. Asset names and approximate magnitudes come from public
Seqwater material so the demo feels familiar, but every number is generated.

The generator is pure pandas/numpy so it runs locally (tests) and on serverless (job).
Dates are generated relative to ``as_of`` (today in Brisbane), so the demo always shows
"yesterday" as the latest complete day and the planted stories are always current:

  S1  Algal bloom building in Baroon Pocket Dam -> Landers Shute WTP taste & odour risk
  S2  Mount Crosby Eastbank High Lift Pump No.3 vibration trending to alarm, PM overdue
  S3  Grid transfer pumping drifting into peak tariff windows (avoidable energy cost)
  S4  Sunshine Coast (Unitywater) demand running well above forecast in a hot, dry spell
  S5  Grid storage drawing down through a dry spring, heading for the drought readiness level
  S6  A historical summer rain event (turbidity spike at Mount Crosby, desal ramp-up)
  S7  Dam Improvement Program cost and schedule pressure (Somerset, Mt Crosby filters)
  S8  E. coli detection at a regional plant this morning, regulator notification pending
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

HISTORY_DAYS = 730
FORECAST_DAYS = 7

# --------------------------------------------------------------------------- reference data

REGIONS = {
    "BNE": "Brisbane",
    "IPS": "Ipswich & Somerset",
    "MBR": "Moreton Bay",
    "SCO": "Sunshine Coast",
    "NOO": "Noosa",
    "GCO": "Gold Coast",
    "LSR": "Logan & Scenic Rim",
    "RED": "Redlands",
}

CATCHMENTS = {
    "Upper Brisbane River": dict(annual_mm=950, wet=1.0),
    "Pine Rivers": dict(annual_mm=1250, wet=1.1),
    "Gold Coast Hinterland": dict(annual_mm=1550, wet=1.25),
    "Sunshine Coast Hinterland": dict(annual_mm=1800, wet=1.35),
    "Redlands": dict(annual_mm=1300, wet=1.1),
    "Logan & Scenic Rim": dict(annual_mm=900, wet=0.95),
    "Mary Valley": dict(annual_mm=1150, wet=1.05),
}

# site_id, name, type, region, catchment, lat, lon, grid, full_supply_ml, capacity_mld, description
_SITES = [
    # --- dams (grid connected)
    ("WIV", "Wivenhoe Dam", "Dam", "IPS", "Upper Brisbane River", -27.394, 152.608, True, 1165238, None,
     "Largest storage in the SEQ Water Grid (Lake Wivenhoe). Dual purpose: water supply and flood mitigation. Releases feed Mount Crosby WTPs via the Brisbane River."),
    ("SOM", "Somerset Dam", "Dam", "IPS", "Upper Brisbane River", -27.120, 152.551, True, 379849, None,
     "Lake Somerset on the Stanley River, upstream of Wivenhoe. Water supply and flood mitigation. Subject of the Somerset Dam Improvement Project."),
    ("NPD", "North Pine Dam", "Dam", "MBR", "Pine Rivers", -27.270, 152.940, True, 214302, None,
     "Lake Samsonvale. Supplies North Pine WTP. Gated dam with flood operations."),
    ("HIN", "Hinze Dam", "Dam", "GCO", "Gold Coast Hinterland", -28.051, 153.287, True, 310730, None,
     "Advancetown Lake. Main Gold Coast storage supplying Molendinar and Mudgeeraba WTPs."),
    ("LND", "Little Nerang Dam", "Dam", "GCO", "Gold Coast Hinterland", -28.148, 153.283, True, 6705, None,
     "Small storage upstream of Hinze Dam supplying Molendinar WTP."),
    ("BPD", "Baroon Pocket Dam", "Dam", "SCO", "Sunshine Coast Hinterland", -26.715, 152.866, True, 61000, None,
     "Lake Baroon. Main Sunshine Coast storage supplying Landers Shute WTP. Prone to spring/summer cyanobacteria and taste & odour events."),
    ("LMD", "Lake Macdonald", "Dam", "NOO", "Sunshine Coast Hinterland", -26.383, 152.933, True, 8018, None,
     "Six Mile Creek Dam supplying Noosa WTP. Storage held lower during the Lake Macdonald Dam Improvement Project."),
    ("EMD", "Ewen Maddock Dam", "Dam", "SCO", "Sunshine Coast Hinterland", -26.783, 152.983, True, 16587, None,
     "Supplies Ewen Maddock WTP on the southern Sunshine Coast."),
    ("CLB", "Cooloolabin Dam", "Dam", "SCO", "Sunshine Coast Hinterland", -26.550, 152.900, True, 8183, None,
     "Small Sunshine Coast hinterland storage."),
    ("LHD", "Leslie Harrison Dam", "Dam", "RED", "Redlands", -27.533, 153.183, True, 13206, None,
     "Tingalpa Reservoir supplying Capalaba WTP for the Redlands."),
    ("LKB", "Lake Kurwongbah", "Dam", "MBR", "Pine Rivers", -27.250, 152.950, True, 14370, None,
     "Sideling Creek Dam in Moreton Bay."),
    ("LMN", "Lake Manchester", "Dam", "BNE", "Upper Brisbane River", -27.483, 152.767, True, 26217, None,
     "Cabbage Tree Creek storage west of Brisbane, feeds Mount Crosby."),
    # --- dams (not grid connected)
    ("WYA", "Wyaralong Dam", "Dam", "LSR", "Logan & Scenic Rim", -27.930, 152.837, False, 102883, None,
     "Teviot Brook storage. Not yet connected to the Water Grid; the Water Security Program plans a Logan River connection and new treatment plant."),
    ("MOO", "Moogerah Dam", "Dam", "LSR", "Logan & Scenic Rim", -28.033, 152.550, False, 83765, None,
     "Irrigation and town supply storage for the Warrill Valley scheme."),
    ("MAR", "Maroon Dam", "Dam", "LSR", "Logan & Scenic Rim", -28.180, 152.650, False, 44319, None,
     "Logan River irrigation scheme storage."),
    ("BOR", "Lake Borumba", "Dam", "NOO", "Mary Valley", -26.510, 152.580, False, 45950, None,
     "Mary Valley irrigation storage and recreation lake."),
    # --- water treatment plants
    ("MCE", "Mount Crosby Eastbank WTP", "Water Treatment Plant", "BNE", "Upper Brisbane River", -27.535, 152.800, True, None, 550,
     "Largest WTP in SEQ, treating Brisbane River water released from Wivenhoe/Somerset. High lift pumps lift treated water to the Brisbane network. Highly sensitive to raw water turbidity after rain."),
    ("MCW", "Mount Crosby Westbank WTP", "Water Treatment Plant", "BNE", "Upper Brisbane River", -27.537, 152.797, True, None, 200,
     "Second Mount Crosby plant on the Brisbane River."),
    ("NPW", "North Pine WTP", "Water Treatment Plant", "MBR", "Pine Rivers", -27.272, 152.945, True, None, 250,
     "Treats North Pine Dam water for Moreton Bay and north Brisbane; can push water north via the Northern Pipeline Interconnector."),
    ("MOL", "Molendinar WTP", "Water Treatment Plant", "GCO", "Gold Coast Hinterland", -27.975, 153.370, True, None, 220,
     "Main Gold Coast WTP fed from Hinze and Little Nerang dams."),
    ("MUD", "Mudgeeraba WTP", "Water Treatment Plant", "GCO", "Gold Coast Hinterland", -28.080, 153.360, True, None, 140,
     "Southern Gold Coast WTP fed from Hinze Dam."),
    ("LSW", "Landers Shute WTP", "Water Treatment Plant", "SCO", "Sunshine Coast Hinterland", -26.705, 152.880, True, None, 130,
     "Main Sunshine Coast WTP treating Baroon Pocket Dam water. Uses powdered activated carbon (PAC) dosing for taste & odour control; PAC dosing capacity limits throughput during algal events."),
    ("NOW", "Noosa WTP", "Water Treatment Plant", "NOO", "Sunshine Coast Hinterland", -26.390, 152.960, True, None, 45,
     "Treats Lake Macdonald water for Noosa."),
    ("EMW", "Ewen Maddock WTP", "Water Treatment Plant", "SCO", "Sunshine Coast Hinterland", -26.785, 152.990, True, None, 18,
     "Small Sunshine Coast WTP."),
    ("CAP", "Capalaba WTP", "Water Treatment Plant", "RED", "Redlands", -27.535, 153.190, True, None, 22,
     "Treats Leslie Harrison Dam water for the Redlands."),
    ("ESK", "Esk WTP", "Water Treatment Plant", "IPS", "Upper Brisbane River", -27.240, 152.420, False, None, 3,
     "Off-grid regional plant supplying the Esk community."),
    ("KIL", "Kilcoy WTP", "Water Treatment Plant", "IPS", "Upper Brisbane River", -26.940, 152.565, False, None, 4,
     "Off-grid regional plant supplying Kilcoy."),
    ("BEA", "Beaudesert WTP", "Water Treatment Plant", "LSR", "Logan & Scenic Rim", -27.985, 152.995, False, None, 6,
     "Off-grid regional plant supplying Beaudesert; growth area served by the planned South West Pipeline."),
    ("BOO", "Boonah-Kalbar WTP", "Water Treatment Plant", "LSR", "Logan & Scenic Rim", -27.995, 152.680, False, None, 4,
     "Off-grid regional plant supplying Boonah and Kalbar."),
    ("CAN", "Canungra WTP", "Water Treatment Plant", "LSR", "Gold Coast Hinterland", -28.015, 153.165, False, None, 1.5,
     "Small off-grid plant supplying Canungra."),
    ("GCD", "Gold Coast Desalination Plant", "Desalination Plant", "GCO", None, -28.157, 153.494, True, None, 133,
     "Reverse osmosis plant at Tugun. Climate-independent supply, normally run in hot standby and ramped up during drought or when Mount Crosby is impacted by flood turbidity."),
    ("BUN", "Bundamba AWTP", "Advanced Water Treatment Plant", "IPS", None, -27.610, 152.810, True, None, 66,
     "Western Corridor Recycled Water Scheme advanced water treatment plant. Supplies purified recycled water to industry; scheme held in care and maintenance readiness."),
    ("LPT", "Luggage Point AWTP", "Advanced Water Treatment Plant", "BNE", None, -27.380, 153.150, True, None, 66,
     "Western Corridor Recycled Water Scheme advanced water treatment plant (care and maintenance)."),
    ("GIB", "Gibson Island AWTP", "Advanced Water Treatment Plant", "BNE", None, -27.440, 153.110, True, None, 50,
     "Western Corridor Recycled Water Scheme advanced water treatment plant (care and maintenance)."),
    # --- bulk transfer pump stations
    ("NPI-MOR", "Northern Pipeline Interconnector - Morayfield PS", "Pump Station", "MBR", None, -27.105, 152.950, True, None, 65,
     "Bi-directional transfer between Brisbane and the Sunshine Coast. Pumps north when Sunshine Coast demand exceeds local treatment capacity."),
    ("NPI-LAN", "Northern Pipeline Interconnector - Landsborough PS", "Pump Station", "SCO", None, -26.805, 152.965, True, None, 65,
     "Northern end of the NPI transfer into the Sunshine Coast network."),
    ("SRWP-CHF", "Southern Regional Water Pipeline - Chambers Flat PS", "Pump Station", "LSR", None, -27.745, 153.080, True, None, 120,
     "Transfers water between Brisbane and the Gold Coast via Logan."),
    ("SRWP-MOL", "Southern Regional Water Pipeline - Molendinar PS", "Pump Station", "GCO", None, -27.970, 153.365, True, None, 120,
     "Gold Coast end of the SRWP; pushes Gold Coast and desal water north when required."),
    ("EPI-CAP", "Eastern Pipeline Interconnector - Capalaba PS", "Pump Station", "RED", None, -27.530, 153.200, True, None, 40,
     "Connects the Redlands to the Brisbane network."),
]

SITE_COLUMNS = ["site_id", "site_name", "site_type", "region_code", "catchment", "latitude", "longitude",
                "grid_connected", "full_supply_volume_ml", "design_capacity_mld", "description"]

RETAILERS = [
    # id, name, service area, population, base share of grid demand
    ("URU", "Urban Utilities", "Brisbane, Ipswich, Lockyer Valley, Scenic Rim, Somerset", 1_650_000, 0.455),
    ("UNW", "Unitywater", "Moreton Bay, Sunshine Coast, Noosa", 900_000, 0.240),
    ("GCC", "City of Gold Coast", "Gold Coast", 660_000, 0.185),
    ("LCC", "Logan City Council", "Logan", 360_000, 0.080),
    ("RCC", "Redland City Council", "Redlands", 165_000, 0.040),
]

GUIDELINES = {
    # parameter: (unit, guideline value, guideline basis, sample point)
    "Total cyanobacteria": ("cells/mL", 2000.0, "Operational alert (Alert Level 1)", "Raw water"),
    "Geosmin": ("ng/L", 10.0, "Aesthetic (taste & odour)", "Raw water"),
    "2-MIB": ("ng/L", 10.0, "Aesthetic (taste & odour)", "Raw water"),
    "Raw turbidity": ("NTU", 300.0, "Operational (treatment derate threshold)", "Raw water"),
    "Water temperature": ("degC", None, "Monitoring only", "Raw water"),
    "Manganese": ("mg/L", 0.1, "Aesthetic (ADWG)", "Raw water"),
    "Treated turbidity": ("NTU", 1.0, "Operational compliance (disinfection)", "Treated water"),
    "Free chlorine": ("mg/L", 0.2, "Minimum residual (operational)", "Treated water"),
    "E. coli": ("MPN/100mL", 0.0, "Health (ADWG) - any detection is notifiable", "Treated water"),
    "pH": ("pH units", 8.5, "Aesthetic upper limit (ADWG 6.5-8.5)", "Treated water"),
    "PFOS": ("ng/L", 8.0, "Health (ADWG 2025)", "Treated water"),
    "PFHxS": ("ng/L", 30.0, "Health (ADWG 2025)", "Treated water"),
    "PFOA": ("ng/L", 200.0, "Health (ADWG 2025)", "Treated water"),
}

DROUGHT_TRIGGERS = [
    (80.0, "Business as usual", "Normal operations; desalination in hot standby."),
    (70.0, "Drought readiness", "Heightened monitoring, prepare community messaging, review desalination and recycled water readiness."),
    (60.0, "Drought response", "Desalination to full output, voluntary demand reduction targets, Western Corridor scheme restart preparation."),
    (50.0, "Severe drought response", "Mandatory restrictions with retailers, purified recycled water readiness."),
]

TARIFF_AUD_PER_KWH = {"peak": 0.31, "shoulder": 0.19, "offpeak": 0.11}
EMISSIONS_T_PER_KWH = 0.00071  # QLD grid, scope 2 (approx)


def _rng(seed: int, *keys: int) -> np.random.Generator:
    return np.random.default_rng([seed, *keys])


def brisbane_today() -> date:
    return (datetime.utcnow() + timedelta(hours=10)).date()  # AEST, no daylight saving in QLD


# --------------------------------------------------------------------------- generator

class SeqwaterSynth:
    def __init__(self, as_of: date | None = None, seed: int = 20261010):
        self.as_of = as_of or brisbane_today()
        self.seed = seed
        self.data_through = self.as_of - timedelta(days=1)
        self.start = self.data_through - timedelta(days=HISTORY_DAYS - 1)
        self.dates = pd.date_range(self.start, self.data_through, freq="D")
        self.n = len(self.dates)
        self.t = np.arange(self.n)
        self.days_ago = (self.n - 1) - self.t  # 0 == yesterday
        self.doy = self.dates.dayofyear.to_numpy()
        self.sites = pd.DataFrame(_SITES, columns=SITE_COLUMNS)
        self.sites["region"] = self.sites["region_code"].map(REGIONS)
        self.event_day = self.n - 1 - 240  # S6: historical summer rain event
        self.tables: dict[str, pd.DataFrame] = {}

    # ---------------------------------------------------------------- helpers
    def _story_ramp(self, start_days_ago: int, power: float = 2.0) -> np.ndarray:
        """0 before the story starts, rising to 1 at yesterday."""
        x = np.clip((start_days_ago - self.days_ago) / max(start_days_ago, 1), 0, 1)
        return x ** power

    def _seasonal(self, amplitude: float, peak_doy: int = 15) -> np.ndarray:
        return 1 + amplitude * np.cos(2 * np.pi * (self.doy - peak_doy) / 365.25)

    # ---------------------------------------------------------------- weather
    def weather(self) -> pd.DataFrame:
        rows = []
        for k, (catch, cfg) in enumerate(CATCHMENTS.items()):
            r = _rng(self.seed, 1, k)
            wet_season = self._seasonal(0.65, peak_doy=40)  # Feb peak
            p_rain = np.clip(0.28 * wet_season * cfg["wet"], 0.05, 0.8)
            mean_rain_day = cfg["annual_mm"] / 365.25 / 0.30
            rain = np.where(r.random(self.n) < p_rain, r.gamma(0.75, mean_rain_day / 0.75, self.n), 0.0)
            # S6: historical summer rain event (multi-day, heaviest on the Brisbane River)
            ev = self.event_day
            scale = {"Upper Brisbane River": 1.0, "Pine Rivers": 0.8, "Logan & Scenic Rim": 0.7}.get(catch, 0.5)
            for d, mm in enumerate([45, 120, 210, 160, 60, 25]):
                rain[ev + d] = mm * scale + r.normal(0, 5)
            # S5: dry spring - last 90 days well below average, nothing in the last 3 weeks
            rain = np.where(self.days_ago < 90, rain * 0.35, rain)
            rain = np.where(self.days_ago < 21, rain * 0.05, rain)
            rain = np.clip(rain, 0, None).round(1)
            tmax = 25.5 + 4.5 * np.cos(2 * np.pi * (self.doy - 20) / 365.25) + r.normal(0, 1.8, self.n)
            tmax = tmax - 0.08 * np.clip(rain, 0, 40)
            # S1/S4: spring heat over the last fortnight
            tmax = tmax + 4.0 * self._story_ramp(14, 1.0)
            tmax = tmax + (1.5 if "Hinterland" not in catch else 0.0)
            for i in range(self.n):
                rows.append((self.dates[i].date(), catch, float(rain[i]), round(float(tmax[i]), 1), False))
            # forecast: hot and dry
            for f in range(FORECAST_DAYS + 1):
                d = self.as_of + timedelta(days=f)
                fr = float(max(0.0, r.normal(0.6, 1.2))) if f not in (5, 6) else float(max(0.0, r.normal(3, 2)))
                ft = 32.5 + 1.2 * np.sin(f / 2) + r.normal(0, 0.6) + (1.5 if "Hinterland" not in catch else 0)
                rows.append((d, catch, round(fr, 1), round(float(ft), 1), True))
        df = pd.DataFrame(rows, columns=["weather_date", "catchment", "rainfall_mm", "max_temp_c", "is_forecast"])
        self.tables["weather_daily"] = df
        return df

    # ---------------------------------------------------------------- demand
    def demand(self) -> pd.DataFrame:
        w = self.tables["weather_daily"]
        bne_t = w[(w.catchment == "Upper Brisbane River") & (~w.is_forecast)]["max_temp_c"].to_numpy()
        bne_r = w[(w.catchment == "Upper Brisbane River") & (~w.is_forecast)]["rainfall_mm"].to_numpy()
        r = _rng(self.seed, 2)
        growth = (1 + 0.021) ** (self.t / 365.25)
        weekly = 1 + 0.025 * np.isin(self.dates.dayofweek, [5, 6])
        heat = 1 + 0.016 * np.clip(bne_t - 28, 0, None)
        rain_supp = 1 - 0.05 * (np.convolve(bne_r, np.ones(5) / 5, mode="same") > 8)
        base_total = 935 * self._seasonal(0.09, peak_doy=20) * growth * weekly
        expected_total = 935 * self._seasonal(0.09, peak_doy=20) * growth * weekly  # retailer forecast basis
        rows = []
        self.retail_demand = {}
        for k, (rid, name, area, pop, share) in enumerate(RETAILERS):
            rr = _rng(self.seed, 2, k)
            noise = 1 + rr.normal(0, 0.022, self.n)
            delivered = base_total * share * heat * rain_supp * noise
            forecast = expected_total * share * (1 + 0.008 * np.clip(bne_t - 28, 0, None))
            if rid == "UNW":  # S4: Sunshine Coast running hot above forecast
                delivered = delivered * (1 + 0.115 * self._story_ramp(16, 0.6))
            if rid == "GCC":
                delivered = delivered * (1 + 0.03 * self._story_ramp(10, 1.0))
            self.retail_demand[rid] = delivered
            for i in range(self.n):
                rows.append((self.dates[i].date(), rid, round(float(delivered[i]), 2), round(float(forecast[i]), 2),
                             round(float(bne_t[i]), 1)))
        df = pd.DataFrame(rows, columns=["supply_date", "retailer_id", "delivered_ml", "forecast_ml", "max_temp_c"])
        self.tables["bulk_supply_daily"] = df
        return df

    # ---------------------------------------------------------------- treatment + transfers
    def treatment(self) -> pd.DataFrame:
        d = self.retail_demand
        n = self.n
        r = _rng(self.seed, 3)
        ev = self.event_day
        # Raw turbidity at Brisbane River plants driven by the S6 event
        w = self.tables["weather_daily"]
        bne_r = w[(w.catchment == "Upper Brisbane River") & (~w.is_forecast)]["rainfall_mm"].to_numpy()
        runoff = np.convolve(np.clip(bne_r - 15, 0, None) ** 1.35, np.exp(-np.arange(20) / 3.5), mode="full")[:n]
        turb_bne = 8 + 2.8 * runoff + r.gamma(2, 2.5, n)
        turb_bne = np.clip(turb_bne, 3, 1850)

        # Mount Crosby derate when raw turbidity is extreme
        mc_avail = np.where(turb_bne > 300, np.clip(1 - (turb_bne - 300) / 1900, 0.38, 1), 1.0)

        # S1: Landers Shute capacity constrained by PAC dosing during the bloom
        bloom = self._story_ramp(12, 1.6)
        lsw_cap = 130 * (1 - 0.30 * bloom)

        uru, unw, gcc, lcc, rcc = (d[k] for k in ["URU", "UNW", "GCC", "LCC", "RCC"])
        regional = uru * 0.025
        # Sunshine Coast: local plants first, NPI transfer covers the gap
        lsw = np.minimum(unw * 0.47, lsw_cap * 0.97)
        now = unw * 0.11
        emw = unw * 0.045
        npw_unw = unw * 0.31
        npi = np.clip(unw - (lsw + now + emw + npw_unw), 0, None)
        # Gold Coast and desal
        gcd = 26 + r.normal(0, 2.5, n)
        mc_need = uru * 0.92 + lcc * 0.6 + rcc * 0.6 + npi
        mc_cap = 750 * mc_avail
        shortfall = np.clip(mc_need - mc_cap * 0.97, 0, None)
        gcd = np.clip(gcd + shortfall * 0.55, 0, 128)  # desal ramps when Mt Crosby is derated
        npw_extra = shortfall * 0.30
        mol_extra = shortfall * 0.15
        mc_total = np.minimum(mc_need, mc_cap * 0.97)
        mce = mc_total * 0.735
        mcw = mc_total * 0.265
        npw = npw_unw + uru * 0.055 + npw_extra
        mol = gcc * 0.55 + lcc * 0.4 + mol_extra
        mud = np.clip(gcc - gcc * 0.55 - (gcd - 6), gcc * 0.12, None)
        cap = rcc * 0.4
        bun = np.clip(6 + r.normal(0, 1.2, n), 2, None)

        production = {"MCE": mce, "MCW": mcw, "NPW": npw, "MOL": mol, "MUD": mud, "LSW": lsw, "NOW": now,
                      "EMW": emw, "CAP": cap, "GCD": gcd, "BUN": bun, "LPT": np.zeros(n), "GIB": np.zeros(n)}
        reg_share = {"ESK": 0.17, "KIL": 0.2, "BEA": 0.33, "BOO": 0.2, "CAN": 0.10}
        for k, s in reg_share.items():
            production[k] = regional * s

        capacity = self.sites.set_index("site_id")["design_capacity_mld"].to_dict()
        intensity = {"GCD": 3800.0, "BUN": 1150.0, "LPT": 0.0, "GIB": 0.0, "MCE": 420.0, "MCW": 380.0}
        rows = []
        self.plant_production = production
        for k, (sid, prod) in enumerate(production.items()):
            rr = _rng(self.seed, 3, k)
            cap_avail = np.full(n, float(capacity[sid]))
            if sid in ("MCE", "MCW"):
                cap_avail = cap_avail * mc_avail
                raw_turb = turb_bne * (1.0 if sid == "MCE" else 0.96)
            elif sid == "LSW":
                cap_avail = lsw_cap
                raw_turb = 6 + rr.gamma(2, 1.5, n)
            else:
                raw_turb = 4 + rr.gamma(2, 1.6, n) + (np.where(np.abs(self.t - ev - 2) < 4, 60, 0) if capacity[sid] < 300 else 0)
            if sid in ("GCD", "BUN", "LPT", "GIB"):
                raw_turb = np.full(n, np.nan)
            treated = np.clip(0.08 + rr.gamma(2, 0.025, n) + np.where(np.nan_to_num(raw_turb) > 300, 0.12, 0), 0.03, None)
            if sid == "CAN":  # S8 precursor: small plant filter performance drifting in the last week
                treated = treated + 0.55 * self._story_ramp(7, 1.5)
            alum = np.nan_to_num(raw_turb) * 0.9 + 18
            pac = np.where(sid == "LSW", 4 + 46 * bloom, 0.0)
            chem_cost = prod * (alum * 0.55 + pac * 3.1) / 1.0  # AUD
            if sid in ("GCD",):
                chem_cost = prod * 38.0 + 2500
            energy = prod * intensity.get(sid, 230.0) * (1 + rr.normal(0, 0.03, n))
            if sid == "GCD":
                energy = energy + 24000  # hot standby base load
            util = np.where(cap_avail > 0, prod / np.maximum(cap_avail, 1e-6) * 100, 0)
            ok = treated <= 1.0
            for i in range(n):
                rows.append((self.dates[i].date(), sid, round(float(prod[i]), 2), round(float(cap_avail[i]), 1),
                             round(float(util[i]), 1),
                             None if np.isnan(raw_turb[i]) else round(float(raw_turb[i]), 1),
                             round(float(treated[i]), 3), round(float(chem_cost[i]), 0),
                             round(float(energy[i]), 0), bool(ok[i])))
        df = pd.DataFrame(rows, columns=["production_date", "site_id", "production_ml", "available_capacity_mld",
                                         "utilisation_pct", "raw_turbidity_ntu", "treated_turbidity_ntu",
                                         "chemical_cost_aud", "energy_kwh", "treated_water_compliant"])
        self.tables["treatment_daily"] = df
        self.turb_bne = turb_bne
        self.transfers = {"NPI-MOR": npi, "NPI-LAN": npi * 0.98, "SRWP-CHF": lcc * 0.6 + mol_extra + 18,
                          "SRWP-MOL": mol_extra + gcd * 0.25 + 6, "EPI-CAP": rcc * 0.6}
        return df

    # ---------------------------------------------------------------- storages
    def storages(self) -> pd.DataFrame:
        w = self.tables["weather_daily"]
        dams = self.sites[self.sites.site_type == "Dam"]
        n = self.n
        draw_map = {
            "WIV": lambda: (self.plant_production["MCE"] + self.plant_production["MCW"]) * 0.80,
            "SOM": lambda: (self.plant_production["MCE"] + self.plant_production["MCW"]) * 0.12,
            "LMN": lambda: (self.plant_production["MCE"] + self.plant_production["MCW"]) * 0.02,
            "NPD": lambda: self.plant_production["NPW"],
            "HIN": lambda: self.plant_production["MUD"] + self.plant_production["MOL"] * 0.85,
            "LND": lambda: self.plant_production["MOL"] * 0.15,
            "BPD": lambda: self.plant_production["LSW"],
            "LMD": lambda: self.plant_production["NOW"],
            "EMD": lambda: self.plant_production["EMW"],
            "CLB": lambda: np.full(n, 0.6),
            "LHD": lambda: self.plant_production["CAP"],
            "LKB": lambda: np.full(n, 1.5),
        }
        # start and end-of-history levels (% of full supply volume). End levels reflect a dry spring;
        # the catchment yield is calibrated per dam so the simulated water balance lands on them.
        start_pct = {"WIV": 0.79, "SOM": 0.80, "NPD": 0.72, "HIN": 0.88, "LND": 0.95, "BPD": 0.90, "LMD": 0.55,
                     "EMD": 0.86, "CLB": 0.92, "LHD": 0.80, "LKB": 0.84, "LMN": 0.90, "WYA": 0.78, "MOO": 0.62,
                     "MAR": 0.70, "BOR": 0.71}
        end_pct = {"WIV": 0.765, "SOM": 0.80, "NPD": 0.705, "HIN": 0.835, "LND": 0.92, "BPD": 0.745, "LMD": 0.46,
                   "EMD": 0.815, "CLB": 0.88, "LHD": 0.785, "LKB": 0.81, "LMN": 0.86, "WYA": 0.83, "MOO": 0.58,
                   "MAR": 0.66, "BOR": 0.62}
        target_cap = {"LMD": 0.70}  # Lake Macdonald held low for dam works
        rows = []
        self.storage_pct = {}
        for k, dam in enumerate(dams.itertuples()):
            rr = _rng(self.seed, 4, k)
            rain = w[(w.catchment == dam.catchment) & (~w.is_forecast)]["rainfall_mm"].to_numpy()
            fsv = float(dam.full_supply_volume_ml)
            # unit hydrograph: big rain days generate most runoff, recession over ~2 weeks
            eff = np.convolve(np.clip(rain - 8, 0, None), np.exp(-np.arange(30) / 6.0), mode="full")[:n]
            eff = eff / max(eff.sum(), 1e-9)
            base = np.clip(self._seasonal(0.85, 45), 0.05, None) * (1 + rr.normal(0, 0.05, n))
            base = np.where(self.days_ago < 90, base * 0.35, base)
            base = base / base.sum()
            draw = draw_map.get(dam.site_id, lambda: np.full(n, fsv * 0.00045))()
            cap_frac = target_cap.get(dam.site_id, 1.0)
            evap_rate = 0.00020 * self._seasonal(0.45, 15)
            flood_cap = 1.25 if dam.site_id in ("WIV", "SOM", "NPD") else 1.0

            def simulate(total_inflow: float):
                inflow = total_inflow * (0.6 * eff + 0.4 * base)
                vol, release = np.zeros(n), np.zeros(n)
                v = start_pct[dam.site_id] * fsv
                for i in range(n):
                    v = v + inflow[i] - draw[i] - v * evap_rate[i]
                    rel = draw[i]
                    if v > fsv * cap_frac:
                        excess = v - fsv * cap_frac
                        out = excess * 0.2 if (flood_cap > 1.0 and v <= fsv * flood_cap) else excess
                        v -= out
                        rel += out
                    v = max(v, fsv * 0.05)
                    vol[i], release[i] = v, rel
                return inflow, vol, release

            lo, hi = 0.0, fsv * 6
            for _ in range(32):
                mid = (lo + hi) / 2
                if simulate(mid)[1][-1] / fsv < end_pct[dam.site_id]:
                    lo = mid
                else:
                    hi = mid
            inflow, vol, release = simulate((lo + hi) / 2)
            pct = vol / fsv * 100
            self.storage_pct[dam.site_id] = pct
            for i in range(n):
                rows.append((self.dates[i].date(), dam.site_id, round(float(vol[i]), 0), round(float(pct[i]), 2),
                             round(float(inflow[i]), 0), round(float(release[i]), 0), round(float(rain[i]), 1)))
        df = pd.DataFrame(rows, columns=["reading_date", "site_id", "volume_ml", "percent_full", "inflow_ml",
                                         "release_ml", "catchment_rainfall_mm"])
        self.tables["storage_levels_daily"] = df
        return df

    # ---------------------------------------------------------------- energy
    def energy(self) -> pd.DataFrame:
        n = self.n
        rows = []
        drift = self._story_ramp(35, 0.8)  # S3: transfers creeping into peak windows
        for k, site in enumerate(self.sites.itertuples()):
            rr = _rng(self.seed, 5, k)
            if site.site_id in self.transfers:
                flow = self.transfers[site.site_id]
                kwh = flow * {"NPI-MOR": 520, "NPI-LAN": 380, "SRWP-CHF": 450, "SRWP-MOL": 410, "EPI-CAP": 300}[site.site_id]
                kwh = kwh * (1 + rr.normal(0, 0.04, n)) + 900
                peak_share = 0.20 + rr.normal(0, 0.02, n)
                if site.site_id in ("NPI-MOR", "NPI-LAN", "SRWP-CHF"):
                    peak_share = peak_share + 0.24 * drift
            else:
                tr = self.tables["treatment_daily"]
                sub = tr[tr.site_id == site.site_id]
                if sub.empty:
                    continue
                kwh = sub["energy_kwh"].to_numpy()
                peak_share = 0.24 + rr.normal(0, 0.015, n)
            peak_share = np.clip(peak_share, 0.08, 0.6)
            shoulder_share = np.clip(0.30 + rr.normal(0, 0.02, n), 0.15, 0.45)
            off_share = 1 - peak_share - shoulder_share
            peak, shoulder, off = kwh * peak_share, kwh * shoulder_share, kwh * off_share
            cost = (peak * TARIFF_AUD_PER_KWH["peak"] + shoulder * TARIFF_AUD_PER_KWH["shoulder"]
                    + off * TARIFF_AUD_PER_KWH["offpeak"])
            for i in range(n):
                rows.append((self.dates[i].date(), site.site_id, round(float(kwh[i]), 0), round(float(peak[i]), 0),
                             round(float(shoulder[i]), 0), round(float(off[i]), 0),
                             round(float(peak[i] * TARIFF_AUD_PER_KWH["peak"]), 2), round(float(cost[i]), 2),
                             round(float(kwh[i] * EMISSIONS_T_PER_KWH), 3)))
        df = pd.DataFrame(rows, columns=["energy_date", "site_id", "energy_kwh", "peak_kwh", "shoulder_kwh",
                                         "offpeak_kwh", "peak_cost_aud", "energy_cost_aud", "emissions_tco2e"])
        self.tables["energy_daily"] = df
        return df

    # ---------------------------------------------------------------- assets + condition
    def assets(self) -> pd.DataFrame:
        r = _rng(self.seed, 6)
        rows = []
        spec = {
            "MCE": [("High Lift Pump No.{}", "Pump", 4, "A", 2_400_000), ("Raw Water Pump No.{}", "Pump", 3, "A", 1_600_000),
                    ("Filter Bed {}", "Filter", 4, "B", 900_000), ("Alum Dosing System", "Dosing System", 1, "A", 650_000),
                    ("Chlorination System", "Dosing System", 1, "A", 800_000), ("Main Switchboard", "Electrical", 1, "A", 1_900_000)],
            "MCW": [("High Lift Pump No.{}", "Pump", 3, "A", 1_900_000), ("Filter Bed {}", "Filter", 3, "B", 800_000),
                    ("Chlorination System", "Dosing System", 1, "A", 650_000)],
            "NPW": [("Treated Water Pump No.{}", "Pump", 3, "A", 1_300_000), ("Filter Bed {}", "Filter", 3, "B", 750_000),
                    ("Ozone Generator", "Treatment", 1, "B", 2_100_000)],
            "MOL": [("Treated Water Pump No.{}", "Pump", 3, "A", 1_200_000), ("Filter Bed {}", "Filter", 3, "B", 700_000),
                    ("Chlorination System", "Dosing System", 1, "A", 600_000)],
            "MUD": [("Treated Water Pump No.{}", "Pump", 2, "B", 900_000), ("Filter Bed {}", "Filter", 2, "B", 600_000)],
            "LSW": [("Treated Water Pump No.{}", "Pump", 3, "A", 950_000), ("PAC Dosing Pump No.{}", "Pump", 2, "A", 240_000),
                    ("Filter Bed {}", "Filter", 3, "B", 600_000)],
            "GCD": [("RO Train {}", "Membrane Train", 4, "A", 6_500_000), ("High Pressure Pump No.{}", "Pump", 4, "A", 2_800_000),
                    ("Seawater Intake Pump No.{}", "Pump", 3, "A", 1_700_000)],
            "BUN": [("Reverse Osmosis Train {}", "Membrane Train", 2, "B", 4_000_000), ("Product Water Pump No.{}", "Pump", 2, "B", 900_000)],
            "NPI-MOR": [("Transfer Pump No.{}", "Pump", 3, "A", 1_400_000), ("Variable Speed Drive {}", "Electrical", 3, "B", 320_000)],
            "NPI-LAN": [("Transfer Pump No.{}", "Pump", 2, "A", 1_200_000)],
            "SRWP-CHF": [("Transfer Pump No.{}", "Pump", 3, "A", 1_500_000), ("Variable Speed Drive {}", "Electrical", 3, "B", 340_000)],
            "SRWP-MOL": [("Transfer Pump No.{}", "Pump", 2, "A", 1_300_000)],
            "EPI-CAP": [("Transfer Pump No.{}", "Pump", 2, "B", 800_000)],
            "WIV": [("Radial Spillway Gate {}", "Gate", 5, "A", 5_500_000), ("Regulator Outlet Valve", "Valve", 1, "A", 1_200_000)],
            "SOM": [("Sluice Gate {}", "Gate", 4, "A", 3_200_000)],
            "NPD": [("Radial Gate {}", "Gate", 5, "A", 2_800_000)],
            "CAP": [("Treated Water Pump No.{}", "Pump", 2, "B", 420_000)],
            "CAN": [("Filter Unit {}", "Filter", 2, "B", 180_000), ("UV Disinfection Unit", "Treatment", 1, "A", 150_000)],
            "BEA": [("Filter Unit {}", "Filter", 2, "B", 210_000)],
        }
        for site_id, items in spec.items():
            site_name = self.sites.set_index("site_id").loc[site_id, "site_name"]
            for name_tpl, cls, count, crit, rv in items:
                for j in range(1, count + 1):
                    nm = name_tpl.format(j) if "{}" in name_tpl else name_tpl
                    asset_id = f"{site_id}-{''.join(w[0] for w in nm.replace('No.', '').split() if w[0].isalpha()).upper()}-{j:02d}"
                    install = int(r.integers(1984, 2021))
                    if site_id == "GCD":
                        install = int(r.integers(2009, 2016))
                    rows.append((asset_id, f"{site_name} - {nm}", cls, site_id, crit, install,
                                 float(rv * (0.85 + 0.3 * r.random())),
                                 "Condition-based" if cls in ("Pump", "Electrical") else "Time-based"))
        df = pd.DataFrame(rows, columns=["asset_id", "asset_name", "asset_class", "site_id", "criticality",
                                         "install_year", "replacement_value_aud", "maintenance_strategy"])
        df = df.drop_duplicates("asset_id")
        self.tables["assets"] = df
        return df

    def asset_condition(self) -> pd.DataFrame:
        a = self.tables["assets"]
        rot = a[a.asset_class == "Pump"].reset_index(drop=True)
        rows = []
        self.story_assets = {}
        for k, asset in enumerate(rot.itertuples()):
            rr = _rng(self.seed, 7, k)
            age = self.as_of.year - asset.install_year
            vib = 1.6 + 0.035 * age + rr.normal(0, 0.18, self.n) + 0.25 * np.sin(self.t / 47 + k)
            temp = 54 + 0.25 * age + rr.normal(0, 1.4, self.n) + 3 * np.cos(2 * np.pi * (self.doy - 20) / 365.25)
            hours = np.clip(rr.normal(15, 4, self.n), 0, 24)
            if asset.asset_name.endswith("High Lift Pump No.3") and asset.site_id == "MCE":  # S2
                ramp = self._story_ramp(21, 2.2)
                vib = vib + 5.6 * ramp
                temp = temp + 17 * ramp
                hours = np.clip(hours + 4, 0, 24)
                self.story_assets["S2"] = asset.asset_id
            elif asset.site_id == "NPI-MOR" and asset.asset_name.endswith("No.2"):
                vib = vib + 2.4 * self._story_ramp(40, 1.2)
                temp = temp + 6 * self._story_ramp(40, 1.2)
                hours = np.clip(hours + 3 * self._story_ramp(35, 0.8), 0, 24)
                self.story_assets["NPI"] = asset.asset_id
            elif asset.site_id == "LSW" and "PAC" in asset.asset_name:
                hours = np.where(self.days_ago < 12, 24.0, hours * 0.4)
                vib = vib + 1.1 * self._story_ramp(12, 1.0)
            vib = np.clip(vib, 0.6, None)
            health = 100 - np.clip((vib - 2.5) * 8, 0, 60) - np.clip((temp - 65) * 1.2, 0, 20) - 0.2 * age
            health = np.clip(health + rr.normal(0, 1.2, self.n), 5, 100)
            for i in range(self.n):
                rows.append((self.dates[i].date(), asset.asset_id, round(float(vib[i]), 2), round(float(temp[i]), 1),
                             round(float(hours[i]), 1), round(float(health[i]), 1), bool(vib[i] >= 7.1)))
        df = pd.DataFrame(rows, columns=["reading_date", "asset_id", "vibration_mm_s", "bearing_temp_c",
                                         "run_hours", "health_score", "vibration_alarm"])
        self.tables["asset_condition_daily"] = df
        return df

    # ---------------------------------------------------------------- work orders
    def work_orders(self) -> pd.DataFrame:
        a = self.tables["assets"]
        r = _rng(self.seed, 8)
        rows = []
        wo = 400000
        d_end = self.data_through
        corrective_text = {
            "Pump": ["Investigate high vibration", "Replace mechanical seal", "Bearing noise - inspect and lubricate",
                     "Motor overcurrent trip - investigate"],
            "Filter": ["Backwash valve not sealing", "Media loss - top up and inspect underdrain", "Turbidity meter fault"],
            "Dosing System": ["Dosing pump stroke failure", "Chemical leak at bund", "Analyser drift - recalibrate"],
            "Electrical": ["VSD fault code - investigate", "Thermal imaging hotspot on busbar"],
            "Membrane Train": ["Membrane CIP required", "Differential pressure high"],
            "Gate": ["Hydraulic power unit leak", "Gate position sensor fault"],
            "Valve": ["Actuator fault"], "Treatment": ["Lamp replacement", "Ozone generator trip"],
        }
        for asset in a.itertuples():
            interval = 90 if asset.criticality == "A" else 180
            offset = int(r.integers(0, interval))
            due = self.start + timedelta(days=offset)
            while due <= d_end + timedelta(days=30):
                wo += 1
                is_story = asset.asset_id == self.story_assets.get("S2")
                if due > d_end:
                    status, completed, raised = "Scheduled", None, due - timedelta(days=21)
                else:
                    late = int(r.gamma(1.1, 9))
                    comp = due + timedelta(days=late)
                    if is_story and (d_end - due).days < 60:
                        status, completed = "Open", None
                    elif comp > d_end:
                        status, completed = ("In Progress" if r.random() < 0.6 else "Open"), None
                    else:
                        status, completed = "Completed", comp
                    raised = due - timedelta(days=21)
                hrs = float(round(r.gamma(3, 2.2 if asset.criticality == "A" else 1.5), 1))
                cost = round(hrs * 145 + (r.gamma(2, 900) if r.random() < 0.3 else 0), 0)
                rows.append((f"WO-{wo}", asset.asset_id, asset.site_id, "Preventive",
                             "P2" if asset.criticality == "A" else "P3", status, raised, due, completed,
                             hrs if completed else None, cost if completed else None,
                             f"Scheduled {interval}-day preventive maintenance - {asset.asset_class.lower()}", "Maximo"))
                if is_story:
                    # the overdue PM is ~46 days late; skip generating any later PM for the story asset
                    pass
                due = due + timedelta(days=interval)
            # corrective work
            n_corr = int(r.poisson(HISTORY_DAYS / 365 * (3.5 if asset.criticality == "A" else 2)))
            for _ in range(n_corr):
                wo += 1
                raised = self.start + timedelta(days=int(r.integers(0, HISTORY_DAYS)))
                prio = r.choice(["P1", "P2", "P3", "P4"], p=[0.08, 0.3, 0.42, 0.2])
                due = raised + timedelta(days={"P1": 1, "P2": 7, "P3": 28, "P4": 60}[prio])
                comp = raised + timedelta(days=int(max(0, r.gamma(2, {"P1": 0.5, "P2": 3, "P3": 9, "P4": 20}[prio]))))
                status = "Completed" if comp <= d_end else "Open"
                hrs = float(round(r.gamma(2.5, 3.0), 1))
                cost = round(hrs * 145 + r.gamma(2, 1600), 0)
                rows.append((f"WO-{wo}", asset.asset_id, asset.site_id, "Corrective", prio, status, raised, due,
                             comp if status == "Completed" else None, hrs if status == "Completed" else None,
                             cost if status == "Completed" else None,
                             str(r.choice(corrective_text.get(asset.asset_class, ["General repair"]))), "Maximo"))
        df = pd.DataFrame(rows, columns=["work_order_id", "asset_id", "site_id", "work_type", "priority", "status",
                                         "raised_date", "due_date", "completed_date", "labour_hours", "cost_aud",
                                         "description", "source_system"])
        # S2: the story pump's last preventive maintenance is 46 days overdue and nothing is scheduled after it
        sid = self.story_assets.get("S2")
        if sid:
            pm = df[(df.asset_id == sid) & (df.work_type == "Preventive")]
            df = df.drop(pm[pd.to_datetime(pm.due_date) > pd.Timestamp(d_end - timedelta(days=46 + 85))].index)
            last = df[(df.asset_id == sid) & (df.work_type == "Preventive")].index.max()
            df.loc[last + 0.5] = (f"WO-{wo + 1}", sid, "MCE", "Preventive", "P2", "Open",
                                  d_end - timedelta(days=67), d_end - timedelta(days=46), None, None, None,
                                  "Scheduled 90-day preventive maintenance - pump (bearing and alignment check)",
                                  "Maximo")
            df = df.sort_index()
        for c in ("raised_date", "due_date", "completed_date"):
            df[c] = pd.to_datetime(df[c]).dt.date
        self.tables["work_orders"] = df.reset_index(drop=True)
        return df

    # ---------------------------------------------------------------- water quality
    def water_quality(self) -> pd.DataFrame:
        r = _rng(self.seed, 9)
        rows = []
        sid = 0
        bloom = self._story_ramp(12, 2.4)
        raw_sites = ["WIV", "SOM", "NPD", "HIN", "BPD", "LMD", "EMD", "LHD", "LKB", "LMN"]
        temp_base = 21 + 5 * np.cos(2 * np.pi * (self.doy - 30) / 365.25)
        temp_heat = temp_base + 3.2 * self._story_ramp(14, 1.0)

        def add(i, site, point, param, value):
            nonlocal sid
            sid += 1
            unit, gv, basis, _ = GUIDELINES[param]
            exceed = bool(gv is not None and ((param == "Free chlorine" and value < gv) or (param != "Free chlorine" and value > gv)))
            rows.append((f"S{sid:07d}", self.dates[i].date(), site, point, param, float(value), unit, gv, basis, exceed))

        for k, site in enumerate(raw_sites):
            rr = _rng(self.seed, 9, k)
            cyano_base = 300 + 1500 * np.clip(np.cos(2 * np.pi * (self.doy - 25) / 365.25), 0, None)
            for i in range(self.n):
                da = self.days_ago[i]
                story = site == "BPD"
                freq = 7
                if story and da < 14:
                    freq = 1
                elif story and da < 30:
                    freq = 3
                if (i + k) % freq != 0 and da != 0:
                    continue
                c = cyano_base[i] * rr.lognormal(0, 0.45)
                g = 2 + rr.gamma(2, 0.9)
                m = 1 + rr.gamma(1.5, 0.8)
                if story:
                    c = c + 66000 * bloom[i]
                    g = g + 34 * bloom[i] ** 1.2
                    m = m + 7 * bloom[i]
                if site == "NPD":
                    c = c * 1.8  # North Pine runs warmer and greener
                add(i, site, "Raw water", "Total cyanobacteria", round(c, 0))
                add(i, site, "Raw water", "Geosmin", round(g, 1))
                add(i, site, "Raw water", "2-MIB", round(m, 1))
                add(i, site, "Raw water", "Water temperature", round(temp_heat[i] + rr.normal(0, 0.6), 1))
                if i % 14 == 0:
                    add(i, site, "Raw water", "Manganese", round(0.02 + rr.gamma(2, 0.012) + (0.06 if site == "NPD" and self.doy[i] < 120 else 0), 3))

        tr = self.tables["treatment_daily"]
        plants = ["MCE", "MCW", "NPW", "MOL", "MUD", "LSW", "NOW", "EMW", "CAP", "ESK", "KIL", "BEA", "BOO", "CAN", "GCD"]
        for k, site in enumerate(plants):
            rr = _rng(self.seed, 10, k)
            tt = tr[tr.site_id == site]["treated_turbidity_ntu"].to_numpy()
            for i in range(self.n):
                da = self.days_ago[i]
                if i % 2 == 0 or da < 14:
                    add(i, site, "Treated water", "Treated turbidity", round(float(tt[i]) + rr.normal(0, 0.01), 3))
                if i % 7 == (k % 7):
                    add(i, site, "Treated water", "Free chlorine", round(max(0.05, rr.normal(0.9, 0.18)), 2))
                    add(i, site, "Treated water", "E. coli", 0.0)
                    add(i, site, "Treated water", "pH", round(rr.normal(7.6, 0.18), 2))
                if i % 91 == (k * 5) % 91:
                    pfos_base = {"NPW": 2.9, "LKB": 3.5, "MCE": 1.6, "MCW": 1.5, "MOL": 0.9, "LSW": 0.7}.get(site, 0.5)
                    add(i, site, "Treated water", "PFOS", round(max(0.0, rr.normal(pfos_base, 0.4)), 2))
                    add(i, site, "Treated water", "PFHxS", round(max(0.0, rr.normal(pfos_base * 1.6, 0.6)), 2))
                    add(i, site, "Treated water", "PFOA", round(max(0.0, rr.normal(pfos_base * 0.8, 0.3)), 2))
        # S8: this morning's E. coli detection at Canungra (recorded against yesterday's sample run)
        add(self.n - 1, "CAN", "Treated water", "E. coli", 2.0)
        add(self.n - 1, "CAN", "Treated water", "Free chlorine", 0.14)
        df = pd.DataFrame(rows, columns=["sample_id", "sample_date", "site_id", "sample_point", "parameter", "value",
                                         "unit", "guideline_value", "guideline_basis", "exceeds_guideline"])
        self.tables["water_quality_samples"] = df
        return df

    # ---------------------------------------------------------------- customer contacts
    def customer_contacts(self) -> pd.DataFrame:
        rows = []
        cats = {"Taste & odour": 0.9, "Discoloured water": 1.6, "Pressure or supply": 2.2, "Water quality - other": 0.7}
        for k, (rid, name, area, pop, share) in enumerate(RETAILERS):
            rr = _rng(self.seed, 11, k)
            for c, base in cats.items():
                lam = base * pop / 500_000 * np.ones(self.n)
                if c == "Taste & odour" and rid == "UNW":
                    lam = lam + 46 * self._story_ramp(7, 1.8)
                if c == "Discoloured water":
                    lam = lam + 25 * np.exp(-np.abs(self.t - self.event_day - 4) / 3) * (1 if rid in ("URU", "LCC") else 0.3)
                v = rr.poisson(lam)
                for i in range(self.n):
                    rows.append((self.dates[i].date(), rid, c, int(v[i])))
        df = pd.DataFrame(rows, columns=["contact_date", "retailer_id", "category", "contact_count"])
        self.tables["customer_contacts_daily"] = df
        return df

    # ---------------------------------------------------------------- incidents
    def incidents(self) -> pd.DataFrame:
        r = _rng(self.seed, 12)
        rows = []
        n_id = 2400
        sites = self.sites.site_id.tolist()
        cats = [("Asset failure", 0.34), ("Water quality", 0.22), ("Environmental", 0.14), ("Safety", 0.16),
                ("Security", 0.06), ("Recreation", 0.08)]
        titles = {
            "Asset failure": ["Pump trip and auto-restart failure", "Valve actuator failure", "Power supply interruption",
                              "Telemetry outage at site", "Chemical dosing pump failure"],
            "Water quality": ["Treated water turbidity excursion", "Low chlorine residual at reservoir",
                              "Taste and odour complaint cluster", "Manganese above aesthetic guideline"],
            "Environmental": ["Minor chemical spill contained in bund", "Fish kill reported in storage",
                              "Sediment discharge after rain"],
            "Safety": ["Near miss - working at heights", "Contractor minor injury", "Snake encounter at site"],
            "Security": ["Unauthorised access to site perimeter", "Phishing email reported by staff"],
            "Recreation": ["Visitor rescue at recreation area", "Illegal camping and rubbish dumping"],
        }
        for day in range(self.n):
            for _ in range(int(r.poisson(0.55))):
                n_id += 1
                cat = r.choice([c for c, _ in cats], p=[p for _, p in cats])
                sev = int(r.choice([1, 2, 3, 4], p=[0.01, 0.07, 0.32, 0.60]))
                ts = datetime.combine(self.dates[day].date(), time(int(r.integers(0, 24)), int(r.integers(0, 60))))
                closed = ts + timedelta(days=float(r.gamma(2, 2)))
                status = "Closed" if closed.date() <= self.data_through else "Open"
                rows.append((f"INC-{n_id}", ts, str(r.choice(sites)), cat, sev, str(r.choice(titles[cat])),
                             "Logged from operations control room.", status, False, None, None))
        # S6 historical event
        ev = self.dates[self.event_day + 3].date()
        rows.append((f"INC-{n_id + 1}", datetime.combine(ev, time(5, 10)), "MCE", "Water quality", 2,
                     "Extreme raw water turbidity - Mount Crosby production derated",
                     "Raw water turbidity exceeded 1,500 NTU after heavy rain in the Brisbane River catchment. Mount Crosby output reduced to ~40%; Gold Coast Desalination Plant ramped to near full output and SRWP/NPI transfers reconfigured.",
                     "Closed", True, datetime.combine(ev, time(7, 0)), datetime.combine(ev, time(6, 40))))
        # S1 open incident
        rows.append((f"INC-{n_id + 2}", datetime.combine(self.data_through - timedelta(days=2), time(8, 15)), "LSW",
                     "Water quality", 3, "Rising cyanobacteria and geosmin in Baroon Pocket Dam",
                     "Total cyanobacteria above Alert Level 1 and rising; geosmin above the 10 ng/L taste and odour threshold. PAC dosing at maximum; taste and odour complaints rising in the Unitywater network.",
                     "Open", False, None, None))
        # S8: E. coli detection this morning at Canungra - notification pending
        det = datetime.combine(self.as_of, time(4, 40))
        rows.append((f"INC-{n_id + 3}", det, "CAN", "Water quality", 2,
                     "E. coli detected in treated water sample - Canungra WTP",
                     "Routine treated water sample from the Canungra WTP clear water storage returned E. coli 2 MPN/100mL with low free chlorine (0.14 mg/L). Filter turbidity has drifted up over the past week. Resample collected; boil water advisory decision pending with Queensland Health.",
                     "Open", True, det + timedelta(hours=6), None))
        df = pd.DataFrame(rows, columns=["incident_id", "reported_at", "site_id", "category", "severity", "title",
                                         "description", "status", "regulator_notifiable", "notification_due_at",
                                         "notified_at"])
        self.tables["incidents"] = df
        return df

    # ---------------------------------------------------------------- capital program
    def capital(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        D = self.data_through
        projects = [
            # id, name, program, site, phase, budget, forecast, pct, baseline_finish_offset_days, slip_days, rag, risk
            ("CP-101", "Somerset Dam Improvement Project", "Dam Improvement Program", "SOM", "Detailed design & early works",
             880e6, 986e6, 18, 1460, 94, "Amber", "Concrete and steel escalation; early works access constraints; flood season construction windows."),
            ("CP-102", "Lake Macdonald Dam Improvement Project", "Dam Improvement Program", "LMD", "Construction",
             142e6, 151e6, 64, 420, 35, "Amber", "Wet weather delays on spillway works; storage held at reduced level until completion."),
            ("CP-103", "North Pine Dam Improvement Project", "Dam Improvement Program", "NPD", "Options analysis",
             310e6, 310e6, 6, 2200, 0, "Green", "Option selection pending hydrology review."),
            ("CP-104", "Lake Manchester Dam Improvement Project", "Dam Improvement Program", "LMN", "Construction",
             61e6, 63e6, 72, 240, 10, "Green", "Minor scope growth in outlet works."),
            ("CP-105", "Leslie Harrison Dam Upgrade - Closeout", "Dam Improvement Program", "LHD", "Closeout",
             48e6, 47.2e6, 99, 30, 0, "Green", "Final defects period."),
            ("CP-201", "Logan River Connection & Wyaralong WTP", "Water Security Program", "WYA", "Business case",
             820e6, 865e6, 4, 2600, 60, "Amber", "Land acquisition and pipeline corridor approvals."),
            ("CP-202", "Gold Coast Desalination Plant Expansion", "Water Security Program", "GCD", "Business case",
             1.95e9, 1.95e9, 3, 2900, 0, "Green", "Energy supply and marine approvals under assessment."),
            ("CP-203", "Western Corridor Scheme Restart Readiness", "Water Security Program", "BUN", "Planning",
             96e6, 104e6, 12, 900, 45, "Amber", "Membrane replacement lead times; operator capability."),
            ("CP-204", "South West Pipeline (Beaudesert)", "Water Security Program", "BEA", "Design",
             215e6, 228e6, 15, 1300, 30, "Green", "Growth area demand ramp; easement negotiations."),
            ("CP-301", "Mount Crosby Eastbank Filter Renewal", "Asset Renewals", "MCE", "Construction",
             46e6, 53.5e6, 58, 180, 122, "Red", "Contractor resourcing and filter media supply delays; outages constrained by summer demand."),
            ("CP-302", "Landers Shute WTP PAC & Advanced Treatment Upgrade", "Asset Renewals", "LSW", "Design",
             27e6, 29.5e6, 22, 520, 75, "Amber", "Delay leaves the plant reliant on existing PAC dosing capacity through this summer's algal season."),
            ("CP-303", "SRWP Pump Station Renewal", "Asset Renewals", "SRWP-CHF", "Construction",
             38e6, 37.1e6, 81, 120, 0, "Green", "On track."),
            ("CP-401", "SCADA & OT Cyber Security Uplift", "Digital & Technology", "MCE", "Delivery",
             32e6, 35.8e6, 47, 365, 60, "Amber", "OT network segmentation cutovers constrained by operational windows (SOCI Act obligations)."),
            ("CP-402", "Enterprise Asset Management Modernisation", "Digital & Technology", "MCE", "Delivery",
             19e6, 21.4e6, 38, 400, 90, "Amber", "Data migration quality of asset hierarchy and work history."),
        ]
        prow, srow = [], []
        r = _rng(self.seed, 13)
        months = pd.date_range((D - timedelta(days=HISTORY_DAYS)).replace(day=1), D.replace(day=1), freq="MS")
        for p in projects:
            pid, name, prog, site, phase, bud, fc, pct, fin_off, slip, rag, risk = p
            spend_to_date = fc * pct / 100 * (0.97 + 0.06 * r.random())
            start = D - timedelta(days=int(fin_off * pct / max(100 - pct, 1)) + 200)
            baseline_finish = D + timedelta(days=fin_off)
            prow.append((pid, name, prog, site, phase, bud, fc, round(spend_to_date, 0), pct, start,
                         baseline_finish, baseline_finish + timedelta(days=slip), rag, risk))
            # monthly planned vs actual spend for the last 24 months
            per_month = spend_to_date / max(len(months), 1)
            for m in months:
                planned = per_month * (bud / fc) * (0.85 + 0.3 * r.random())
                actual = per_month * (0.8 + 0.4 * r.random())
                srow.append((m.date(), pid, round(planned, 0), round(actual, 0)))
        proj = pd.DataFrame(prow, columns=["project_id", "project_name", "program", "site_id", "phase",
                                           "approved_budget_aud", "forecast_cost_aud", "spend_to_date_aud",
                                           "percent_complete", "start_date", "baseline_finish_date",
                                           "forecast_finish_date", "rag_status", "key_risks"])
        spend = pd.DataFrame(srow, columns=["spend_month", "project_id", "planned_spend_aud", "actual_spend_aud"])
        self.tables["capital_projects"] = proj
        self.tables["capital_spend_monthly"] = spend
        return proj, spend

    # ---------------------------------------------------------------- Baroon Pocket twin (S1 in space and depth)
    def reservoir_twin(self) -> None:
        """Buoys, depth profile, offtakes and water level for the Lake Baroon digital twin.

        The bloom starts in the warm, nutrient-rich Obi Obi Creek inflow arm and drifts toward the intake.
        The lake stratifies in the heat: algae concentrate at the surface, and the deep water loses oxygen
        and gains manganese, so the middle offtake is the best-quality layer while the plant draws from the upper one.
        """
        cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "baroon_twin.json")))
        r = _rng(self.seed, 14)
        last = 30
        idx = np.arange(self.n - last, self.n)
        dates = [self.dates[i].date() for i in idx]
        da = self.days_ago[idx]
        onset = {"BPD-B5": 14, "BPD-B4": 12, "BPD-B6": 11, "BPD-B2": 9, "BPD-B3": 8, "BPD-B1": 7}
        peak = {"BPD-B5": 1.9, "BPD-B4": 1.45, "BPD-B6": 1.2, "BPD-B2": 1.05, "BPD-B3": 0.65, "BPD-B1": 0.95}
        shallow = {"BPD-B5": 0.9, "BPD-B4": 0.6, "BPD-B6": 0.5, "BPD-B3": 0.4}
        heat = np.clip((14 - da) / 14, 0, 1)
        self.tables["reservoir_buoys"] = pd.DataFrame(
            [(k, v["label"], "BPD", v["latitude"], v["longitude"], v["depth_at_fsl_m"]) for k, v in cfg["buoys"].items()],
            columns=["buoy_id", "buoy_name", "site_id", "latitude", "longitude", "depth_at_full_supply_m"])
        rows = []
        surface_b2 = None
        for k in cfg["buoys"]:
            ramp = np.clip((onset[k] - da) / onset[k], 0, 1)
            bg = 300 + 900 * np.clip(np.cos(2 * np.pi * (self.doy[idx] - 25) / 365.25), 0, None)
            cyano = (bg + 66000 * peak[k] * ramp ** 2.0) * r.lognormal(0, 0.10, last)
            geo = (2 + 34 * peak[k] * ramp ** 1.3) * r.lognormal(0, 0.08, last)
            temp = 21.8 + 3.3 * heat + shallow.get(k, 0) + r.normal(0, 0.25, last)
            if k == "BPD-B2":
                surface_b2 = cyano
            for i in range(last):
                rows.append((dates[i], k, round(float(cyano[i]), 0), round(float(geo[i]), 1), round(float(temp[i]), 1),
                             round(float(cyano[i] / 2200 + 1.5), 1)))
        self.tables["reservoir_buoy_readings_daily"] = pd.DataFrame(
            rows, columns=["reading_date", "buoy_id", "cyanobacteria_cells_ml", "geosmin_ng_l", "surface_temp_c",
                           "chlorophyll_a_ug_l"])

        # water level from storage percent and the volume curve
        curve = np.array(cfg["volume_curve"])
        pct = self.storage_pct["BPD"]
        vol = pct / 100 * cfg["full_supply_volume_ml"]
        level = np.interp(vol, curve[:, 1], curve[:, 0])
        self.tables["reservoir_level_daily"] = pd.DataFrame({
            "reading_date": [d.date() for d in self.dates], "site_id": "BPD",
            "percent_full": np.round(pct, 2), "volume_ml": np.round(vol, 0), "water_level_m": np.round(level, 2)})

        # depth profile at the central basin
        prow = []
        for i in range(last):
            s = 0.45 + 0.55 * heat[i]
            lvl = level[idx[i]]
            max_depth = int(min(44, lvl - (cfg["full_supply_level_m"] - 46.9)))
            t0, tb, zt = 22.0 + 3.5 * heat[i], 17.4, 7.5 - 1.5 * heat[i]
            for z in range(0, max_depth + 1, 2):
                temp = tb + (t0 - tb) / (1 + np.exp((z - zt) / 1.3))
                do = 8.6 - 8.0 * s * (1 / (1 + np.exp(-(z - 15) / 2.8)))
                mn = 0.02 + 0.48 * s * (1 / (1 + np.exp(-(z - 21) / 2.5)))
                cy = float(surface_b2[i]) * np.exp(-z / 2.6) + 250
                prow.append((dates[i], "BPD-B2", z, round(float(temp + r.normal(0, 0.08)), 2), round(float(max(do + r.normal(0, 0.1), 0.2)), 2),
                             round(cy, 0), round(float(mn), 3)))
        self.tables["reservoir_profile_daily"] = pd.DataFrame(
            prow, columns=["reading_date", "buoy_id", "depth_m", "water_temp_c", "dissolved_oxygen_mg_l",
                           "cyanobacteria_cells_ml", "manganese_mg_l"])
        self.tables["reservoir_offtakes"] = pd.DataFrame(
            [(lv, "BPD", "LSW", el, lv == "Upper") for lv, el in cfg["offtakes"].items()],
            columns=["offtake_level", "site_id", "supplies_site_id", "centre_elevation_m", "in_service"])

    # ---------------------------------------------------------------- reference tables
    def reference(self) -> None:
        self.tables["sites"] = self.sites[["site_id", "site_name", "site_type", "region", "catchment", "latitude",
                                           "longitude", "grid_connected", "full_supply_volume_ml",
                                           "design_capacity_mld", "description"]].copy()
        self.tables["retailers"] = pd.DataFrame(
            [(a, b, c, d) for a, b, c, d, _ in RETAILERS],
            columns=["retailer_id", "retailer_name", "service_area", "population_served"])
        self.tables["drought_trigger_levels"] = pd.DataFrame(
            DROUGHT_TRIGGERS, columns=["grid_storage_percent", "stage", "actions"])
        self.tables["water_quality_guidelines"] = pd.DataFrame(
            [(k, v[0], v[1], v[2], v[3]) for k, v in GUIDELINES.items()],
            columns=["parameter", "unit", "guideline_value", "guideline_basis", "sample_point"])
        self.tables["demo_metadata"] = pd.DataFrame(
            [(self.as_of, self.data_through, self.start, self.seed, datetime.utcnow())],
            columns=["as_of_date", "data_through_date", "history_start_date", "seed", "generated_at_utc"])

    def build(self) -> dict[str, pd.DataFrame]:
        self.weather()
        self.demand()
        self.treatment()
        self.storages()
        self.energy()
        self.assets()
        self.asset_condition()
        self.work_orders()
        self.water_quality()
        self.customer_contacts()
        self.incidents()
        self.capital()
        self.reservoir_twin()
        self.reference()
        return self.tables


def build(as_of: date | None = None, seed: int = 20261010) -> dict[str, pd.DataFrame]:
    return SeqwaterSynth(as_of=as_of, seed=seed).build()
