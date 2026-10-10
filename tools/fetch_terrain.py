"""Fetch public elevation for the Lake Baroon area and save a stitched DEM (dev-time tool).

Source: AWS Terrain Tiles (Mapzen terrarium encoding), https://registry.opendata.aws/terrain-tiles/
(SRTM, GMTED2010 and other open datasets; see the registry page for attribution).
Usage: uv run --with numpy --with pillow python tools/fetch_terrain.py /tmp/baroon_dem.npz
"""
import io
import math
import sys
import urllib.request

import numpy as np
from PIL import Image

Z = 14
BBOX = (-26.660, 152.820, -26.760, 152.930)  # north, west, south, east


def tile_xy(lat, lon, z):
    n = 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def main(out):
    x0, y0 = tile_xy(BBOX[0], BBOX[1], Z)
    x1, y1 = tile_xy(BBOX[2], BBOX[3], Z)
    tx = range(int(x0), int(x1) + 1)
    ty = range(int(y0), int(y1) + 1)
    mosaic = np.zeros((len(ty) * 256, len(tx) * 256), dtype=np.float32)
    for j, y in enumerate(ty):
        for i, x in enumerate(tx):
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png"
            rgb = np.asarray(Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=30).read())).convert("RGB"), dtype=np.float32)
            mosaic[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
    # crop to the bbox in pixel space
    px0, py0 = int((x0 - tx[0]) * 256), int((y0 - ty[0]) * 256)
    px1, py1 = int((x1 - tx[0]) * 256), int((y1 - ty[0]) * 256)
    dem = mosaic[py0:py1, px0:px1]
    np.savez_compressed(out, dem=dem, bbox=np.array(BBOX), zoom=Z)
    print(out, dem.shape, float(dem.min()), float(dem.max()))


if __name__ == "__main__":
    main(sys.argv[1])
