"""Build the Baroon Pocket Dam twin assets for the Command Centre (dev-time tool; outputs are committed).

Inputs : a stitched DEM from tools/fetch_terrain.py and the generated forest texture.
Outputs (ops_agent/ui/cc/twin/):
  baroon-terrain.bin  Uint16 elevation in decimetres, row-major, north up (lake bed carved)
  baroon-lake.bin     Uint8 mask of the lake basin at full supply level
  baroon-drape.webp   colour drape for the 3D terrain and the 2D plan
  baroon-meta.json    grid, bbox, full supply level, volume-to-level curve, feature positions

Terrain is public elevation (AWS Terrain Tiles). The lake bed, features and buoy positions are
ILLUSTRATIVE: bathymetry is synthesised so the full supply volume matches 61,000 ML.

Usage: uv run --with numpy --with pillow --with scipy python tools/build_twin_assets.py DEM.npz TEXTURE.png
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

OUT = Path(__file__).resolve().parent.parent / "ops_agent" / "ui" / "cc" / "twin"
N = 512                      # output grid
CENTRE = (600, 560)          # lake centre in the stitched DEM (row, col)
HALF = 380                   # half-size of the square crop in DEM pixels (~8.5 m each)
FSL = 217.0                  # full supply level (m AHD, from the DEM water surface)
FSV_ML = 61000.0             # Baroon Pocket full supply volume
OUTLET_GUESS = (505, 538)    # narrow neck where Obi Obi Creek leaves the lake (DEM row, col)


def main(dem_path, texture_path):
    src = np.load(dem_path)
    dem = src["dem"].astype(np.float64)
    north, west, south, east = src["bbox"]
    bad = (dem < 0) | (dem > 2000)
    dem[bad] = np.nan
    dem = np.where(np.isnan(dem), ndimage.generic_filter(np.nan_to_num(dem, nan=np.nanmedian(dem)), np.median, size=5), dem)
    rows, cols = dem.shape
    lat_per_px, lon_per_px = (south - north) / rows, (east - west) / cols

    r0, c0 = CENTRE[0] - HALF, CENTRE[1] - HALF
    crop = dem[r0:r0 + 2 * HALF, c0:c0 + 2 * HALF]
    zoom = N / crop.shape[0]
    grid = ndimage.zoom(crop, zoom, order=1)[:N, :N]
    cell_m = 8.5 / zoom * 2 * HALF / (2 * HALF)  # metres per output cell
    cell_m = (2 * HALF * 8.5) / N
    bbox = {"north": north + r0 * lat_per_px, "west": west + c0 * lon_per_px,
            "south": north + (r0 + 2 * HALF) * lat_per_px, "east": west + (c0 + 2 * HALF) * lon_per_px}

    # lake basin at full supply: connected cells at or below FSL + 0.6 m, seeded at the centre
    seed = (N // 2, N // 2)
    low = grid <= FSL + 0.6
    lab, _ = ndimage.label(low)
    lake = lab == lab[seed]
    lake = ndimage.binary_closing(lake, iterations=2) & low | lake
    lake = ndimage.binary_fill_holes(lake)

    # outlet / dam wall: lake cell nearest the downstream neck
    og = ((OUTLET_GUESS[0] - r0) * zoom, (OUTLET_GUESS[1] - c0) * zoom)
    ly, lx = np.nonzero(lake)
    k = np.argmin((ly - og[0]) ** 2 + (lx - og[1]) ** 2)
    dam = (int(ly[k]), int(lx[k]))

    # synthetic bathymetry: deeper away from the shore and toward the dam (old creek bed)
    dist = ndimage.distance_transform_edt(lake) * cell_m
    to_dam = np.hypot(ly - dam[0], lx - dam[1]).astype(float)
    damw = np.zeros_like(grid)
    damw[ly, lx] = 1 - np.clip(to_dam / to_dam.max(), 0, 1)
    shape = (1 - np.exp(-dist / 140.0)) * (0.55 + 0.75 * damw)
    area_cell = cell_m ** 2
    scale = FSV_ML * 1000 / (shape[lake].sum() * area_cell)   # metres of depth per unit shape
    depth = shape * scale
    bed = grid.copy()
    bed[lake] = FSL - depth[lake]
    print(f"lake area {lake.sum() * area_cell / 1e6:.2f} km2, max depth {depth.max():.1f} m, cell {cell_m:.1f} m")

    # volume-to-level curve
    curve = []
    for lvl in np.arange(FSL - depth.max(), FSL + 0.001, 0.25):
        d = np.clip(lvl - bed[lake], 0, None)
        curve.append([round(float(lvl), 2), round(float(d.sum() * area_cell / 1000), 1), round(float((d > 0).sum() * area_cell / 1e6), 3)])

    # features (grid row, col)
    def toward(p, q, metres):
        v = np.array(q, float) - np.array(p, float)
        v /= np.linalg.norm(v)
        return (int(round(p[0] + v[0] * metres / cell_m)), int(round(p[1] + v[1] * metres / cell_m)))

    deep = np.unravel_index(np.argmax(np.where(lake, depth, -1)), lake.shape)
    intake = toward(dam, deep, 160)
    # dam wall axis: perpendicular to the dam -> deepest point direction; spillway on the right abutment
    axis = np.array(deep, float) - np.array(dam, float)
    axis /= np.linalg.norm(axis)
    perp = np.array([-axis[1], axis[0]])
    spill = (int(round(dam[0] + perp[0] * 9 - axis[0] * 1)), int(round(dam[1] + perp[1] * 9 - axis[1] * 1)))

    def extreme(direction, min_dist=70):
        ok = lake & (dist >= min_dist)
        yy, xx = np.nonzero(ok)
        score = yy * direction[0] + xx * direction[1]
        i = np.argmax(score)
        return int(yy[i]), int(xx[i])

    buoys = {
        "BPD-B1": ("Intake and dam wall", toward(intake, deep, 190)),
        "BPD-B2": ("Central basin", tuple(int(v) for v in deep)),
        "BPD-B3": ("Western bay", extreme((0.1, -1))),
        "BPD-B4": ("Eastern arm", extreme((-0.25, 1))),
        "BPD-B5": ("Obi Obi Creek inflow (south-east arm)", extreme((1, 0.6))),
        "BPD-B6": ("Southern shore", extreme((1, -0.35))),
    }

    def latlon(p):
        return [round(bbox["north"] + (p[0] + 0.5) / N * (bbox["south"] - bbox["north"]), 6),
                round(bbox["west"] + (p[1] + 0.5) / N * (bbox["east"] - bbox["west"]), 6)]

    meta = {
        "name": "Baroon Pocket Dam (Lake Baroon)",
        "grid": {"width": N, "height": N, "cell_m": round(cell_m, 3), "elevation_scale": 0.1},
        "bbox": {k: round(float(v), 6) for k, v in bbox.items()},
        "full_supply_level_m": FSL, "full_supply_volume_ml": FSV_ML,
        "max_depth_m": round(float(depth.max()), 1),
        "volume_curve": curve,
        "features": {
            "dam_wall": {"label": "Baroon Pocket Dam wall", "rc": dam, "latlon": latlon(dam),
                         "axis": [round(float(axis[0]), 4), round(float(axis[1]), 4)], "crest_length_m": 260, "crest_m": FSL + 4},
            "intake": {"label": "Intake tower (3 offtake levels)", "rc": intake, "latlon": latlon(intake)},
            "spillway": {"label": "Spillway", "rc": spill, "latlon": latlon(spill)},
        },
        "pipeline": {"label": "To Landers Shute WTP", "from": intake, "bearing_deg": 55},
        "buoys": {k: {"label": v[0], "rc": v[1], "latlon": latlon(v[1])} for k, v in buoys.items()},
        "attribution": "Terrain: AWS Terrain Tiles (Mapzen, SRTM and other open sources). Lake bed, structures and buoy positions are illustrative.",
    }

    # the data job uses the same buoy positions and volume curve (data_platform/src/baroon_twin.json)
    job = {
        "full_supply_level_m": FSL, "full_supply_volume_ml": FSV_ML, "volume_curve": curve,
        "buoys": {k: {"label": v[0], "latitude": latlon(v[1])[0], "longitude": latlon(v[1])[1],
                      "depth_at_fsl_m": round(float(depth[v[1]]), 1)} for k, v in buoys.items()},
        "offtakes": {"Upper": 207.5, "Middle": 199.5, "Lower": 186.0},
    }
    (Path(__file__).resolve().parent.parent / "data_platform" / "src" / "baroon_twin.json").write_text(json.dumps(job, indent=1))
    meta["offtakes"] = job["offtakes"]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "baroon-terrain.bin").write_bytes(np.clip(np.round(bed * 10), 0, 65535).astype("<u2").tobytes())
    (OUT / "baroon-lake.bin").write_bytes(lake.astype(np.uint8).tobytes())
    (OUT / "baroon-meta.json").write_text(json.dumps(meta, indent=1))

    # colour drape (2048): tiled forest texture x hillshade, with a dry-mud tint on the exposed lake bed
    D = 2048
    up = ndimage.zoom(bed, D / N, order=1)
    lake_up = ndimage.zoom(lake.astype(float), D / N, order=1) > 0.5
    gy, gx = np.gradient(up, cell_m * N / D)  # noqa: used for shading and slope tint
    az = np.radians(315)
    nx, ny, nz = -gx * 1.6, -gy * 1.6, np.ones_like(up)
    norm = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2)
    light = np.array([np.cos(az) * 0.6, -np.sin(az) * 0.6, 0.8])
    hs = np.clip((nx * light[0] + ny * light[1] + nz * light[2]) / norm, 0.15, 1.0)
    tex = Image.open(texture_path).convert("RGB").resize((512, 512), Image.LANCZOS)
    tile = np.asarray(tex, dtype=np.float64) / 255
    reps = D // 512
    rng = np.random.default_rng(7)
    forest = np.zeros((D, D, 3))
    for ty in range(reps):
        for tx in range(reps):
            t = np.rot90(tile, int(rng.integers(0, 4)))
            if rng.random() < 0.5:
                t = t[:, ::-1]
            forest[ty * 512:(ty + 1) * 512, tx * 512:(tx + 1) * 512] = t
    # low-frequency variation: valleys greener and darker, ridges paler; steep slopes darker
    elev_t = np.clip((up - up.min()) / (np.ptp(up) + 1e-9), 0, 1)[..., None]
    slope = np.clip(np.hypot(gx, gy) / 0.6, 0, 1)[..., None]
    forest = forest * (0.85 + 0.25 * elev_t) * (1 - 0.25 * slope)
    # warm, slightly desaturated toward the Databricks oat palette
    oat = np.array([0.976, 0.969, 0.957])
    forest = forest * 0.82 + oat * 0.18 * forest.mean(axis=2, keepdims=True)
    mud = np.array([0.62, 0.55, 0.43])
    shore_t = np.clip((FSL - up) / 6.0, 0, 1)[..., None]
    rgb = np.where(lake_up[..., None], mud * (1 - 0.35 * shore_t) + 0.0, forest)
    rgb = rgb * (0.45 + 0.65 * hs[..., None])
    Image.fromarray(np.clip(rgb * 255, 0, 255).astype(np.uint8)).save(OUT / "baroon-drape.webp", quality=82)
    print(json.dumps({k: meta[k] for k in ("grid", "bbox", "max_depth_m")}, indent=1))
    print("buoys:", {k: v["latlon"] for k, v in meta["buoys"].items()})
    print("features:", {k: v["rc"] for k, v in meta["features"].items()})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
