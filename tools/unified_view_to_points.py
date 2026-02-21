#!/usr/bin/env python3
"""Sample Unified View per-turbine rasters on a regular grid and export points."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform

from unified_view.azimuth import azimuth_deg, minimal_covering_arc
from unified_view.io import Turbine, load_turbines, reproject_turbines, validate_rasters

try:
    import fiona
    from fiona.crs import CRS as FionaCRS
except ImportError:  # pragma: no cover
    fiona = None
    FionaCRS = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rasters", nargs="+", required=True)
    parser.add_argument("--turbines", required=True)
    parser.add_argument("--spacing", type=float, default=25.0, dest="spacing_m")
    parser.add_argument("--visibility-threshold", type=float, default=0.0)
    parser.add_argument(
        "--extent-mode", choices=["from_rasters", "custom_bbox"], default="from_rasters"
    )
    parser.add_argument("--extent-op", choices=["union", "intersection"], default="union")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("xmin", "ymin", "xmax", "ymax"))
    parser.add_argument("--mask-mode", choices=["valid_pixels", "any_valid"], default="valid_pixels")
    parser.add_argument("--out", required=True, dest="output_path")
    parser.add_argument("--output-format", choices=["gpkg", "shp"], default="gpkg")
    parser.add_argument("--layer-name", default="unified_view_points")
    parser.add_argument("--crs-epsg", type=int)
    parser.add_argument("--chunk-size", type=int, default=5000)
    parser.add_argument("--no-nulls", action="store_true", help="Use -9999 instead of NULL for azimuth fields")
    return parser.parse_args()


def get_extent(datasets: list[rasterio.io.DatasetReader], mode: str, op: str, bbox: list[float] | None):
    if mode == "custom_bbox":
        if not bbox:
            raise ValueError("--bbox is required when extent-mode=custom_bbox")
        return tuple(bbox)
    bounds = [ds.bounds for ds in datasets]
    if op == "intersection":
        xmin = max(b.left for b in bounds)
        ymin = max(b.bottom for b in bounds)
        xmax = min(b.right for b in bounds)
        ymax = min(b.top for b in bounds)
    else:
        xmin = min(b.left for b in bounds)
        ymin = min(b.bottom for b in bounds)
        xmax = max(b.right for b in bounds)
        ymax = max(b.top for b in bounds)
    if xmin >= xmax or ymin >= ymax:
        raise ValueError("Invalid extent: empty area")
    return xmin, ymin, xmax, ymax


def build_field_names(turbines: list[Turbine], output_format: str) -> tuple[list[str], dict[str, str]]:
    mapping = {}
    fields = []
    for idx, turbine in enumerate(turbines, start=1):
        if output_format == "shp":
            field = f"h_{idx:03d}"
        else:
            tid = "".join(ch if ch.isalnum() else "_" for ch in turbine.turbine_id)
            field = f"h_{tid}"[:30]
            if field in fields:
                field = f"h_{idx:03d}"
        fields.append(field)
        mapping[field] = turbine.turbine_id
    return fields, mapping


def iter_grid_points(xmin: float, ymin: float, xmax: float, ymax: float, spacing_m: float):
    xs = np.arange(xmin, xmax + 1e-9, spacing_m)
    ys = np.arange(ymin, ymax + 1e-9, spacing_m)
    for y in ys:
        for x in xs:
            yield float(x), float(y)


def _fiona_driver(fmt: str) -> str:
    return "GPKG" if fmt == "gpkg" else "ESRI Shapefile"


def main() -> None:
    args = parse_args()
    if fiona is None:
        raise RuntimeError("fiona is required to write Shapefile/GeoPackage outputs")

    datasets = validate_rasters(args.rasters)
    raster_crs = datasets[0].crs
    working_crs = raster_crs

    turbines, turbines_crs = load_turbines(args.turbines)
    if len(turbines) != len(datasets):
        raise ValueError(
            f"Number of turbines ({len(turbines)}) must equal number of rasters ({len(datasets)})"
        )

    if turbines_crs is not None and turbines_crs != working_crs:
        turbines = reproject_turbines(turbines, turbines_crs, working_crs)

    out_crs = CRS.from_epsg(args.crs_epsg) if args.crs_epsg else working_crs

    xmin, ymin, xmax, ymax = get_extent(datasets, args.extent_mode, args.extent_op, args.bbox)
    total_points = (math.floor((xmax - xmin) / args.spacing_m) + 1) * (
        math.floor((ymax - ymin) / args.spacing_m) + 1
    )

    print(f"[INFO] Processing extent {xmin:.2f},{ymin:.2f},{xmax:.2f},{ymax:.2f} | grid points ~{total_points}")

    h_fields, h_field_map = build_field_names(turbines, args.output_format)

    schema = {
        "geometry": "Point",
        "properties": {
            "pt_id": "int",
            "x": "float",
            "y": "float",
            "n_vis": "int",
            "az_ctr": "float",
            "az_min": "float",
            "az_max": "float",
            "fov_az": "float",
            **{field: "float" for field in h_fields},
        },
    }

    output = Path(args.output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    dropped_nodata = 0
    written = 0
    point_id = 1

    with fiona.open(
        output,
        mode="w",
        driver=_fiona_driver(args.output_format),
        schema=schema,
        crs=FionaCRS.from_wkt(out_crs.to_wkt()),
        layer=args.layer_name if args.output_format == "gpkg" else None,
    ) as sink:
        points_iter = iter_grid_points(xmin, ymin, xmax, ymax, args.spacing_m)
        while True:
            batch = list()
            for _ in range(args.chunk_size):
                try:
                    batch.append(next(points_iter))
                except StopIteration:
                    break
            if not batch:
                break

            sampled = [list(ds.sample(batch, indexes=1, masked=True)) for ds in datasets]

            for p_idx, (x, y) in enumerate(batch):
                vals = []
                valid_flags = []
                for ridx in range(len(datasets)):
                    scalar = sampled[ridx][p_idx]
                    if np.ma.is_masked(scalar) and bool(np.ma.getmaskarray(scalar).any()):
                        valid_flags.append(False)
                        vals.append(0.0)
                    else:
                        valid_flags.append(True)
                        vals.append(float(np.asarray(scalar).item()))

                if args.mask_mode == "valid_pixels" and not all(valid_flags):
                    dropped_nodata += 1
                    continue
                if args.mask_mode == "any_valid" and not any(valid_flags):
                    dropped_nodata += 1
                    continue

                visible_idx = [i for i, v in enumerate(vals) if v > args.visibility_threshold]
                n_vis = len(visible_idx)
                az_null = -9999.0 if args.no_nulls else None

                if n_vis == 0:
                    az_ctr = az_min = az_max = fov_az = az_null
                else:
                    az_values = [
                        azimuth_deg(x, y, turbines[i].x, turbines[i].y)
                        for i in visible_idx
                    ]
                    az_min, az_max, fov_az = minimal_covering_arc(az_values)
                    cx = float(np.mean([turbines[i].x for i in visible_idx]))
                    cy = float(np.mean([turbines[i].y for i in visible_idx]))
                    az_ctr = azimuth_deg(x, y, cx, cy)

                if out_crs != working_crs:
                    tx, ty = transform(working_crs, out_crs, [x], [y])
                    out_x, out_y = tx[0], ty[0]
                else:
                    out_x, out_y = x, y

                props = {
                    "pt_id": point_id,
                    "x": out_x,
                    "y": out_y,
                    "n_vis": n_vis,
                    "az_ctr": az_ctr,
                    "az_min": az_min,
                    "az_max": az_max,
                    "fov_az": fov_az,
                }
                for i, field in enumerate(h_fields):
                    props[field] = vals[i] if i in visible_idx else 0.0

                sink.write(
                    {
                        "geometry": {"type": "Point", "coordinates": (out_x, out_y)},
                        "properties": props,
                    }
                )
                point_id += 1
                written += 1

            progress = min(100.0, (written + dropped_nodata) * 100.0 / max(total_points, 1))
            print(f"[INFO] progress: {progress:6.2f}% | written={written} dropped={dropped_nodata}")

    mapping_path = output.with_suffix(output.suffix + ".field_map.csv")
    with mapping_path.open("w", encoding="utf-8", newline="") as fp:
        fp.write("field_name;turbine_id\n")
        for field, tid in h_field_map.items():
            fp.write(f"{field};{tid}\n")

    print("[INFO] Completed")
    print(f"[INFO] points_written={written}")
    print(f"[INFO] points_dropped_nodata={dropped_nodata}")
    print(f"[INFO] output_path={output}")
    print(
        "[INFO] params="
        f"spacing_m={args.spacing_m}, threshold={args.visibility_threshold}, "
        f"mask_mode={args.mask_mode}, extent_mode={args.extent_mode}, output_format={args.output_format}"
    )

    for ds in datasets:
        ds.close()


if __name__ == "__main__":
    main()
