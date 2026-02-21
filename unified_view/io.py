"""I/O helpers for unified view raster sampling workflow."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform


@dataclass(frozen=True)
class Turbine:
    turbine_id: str
    x: float
    y: float
    name: str | None = None


def _parse_csv_delimiter(sample: str) -> str:
    return ";" if sample.count(";") >= sample.count(",") else ","


def _normalize_csv_row(row: dict[str, str]) -> dict[str, str]:
    normalized = {}
    for key, value in row.items():
        if key is None:
            continue
        norm_key = key.strip().lower().lstrip("\ufeff")
        normalized[norm_key] = value.strip() if isinstance(value, str) else value
    return normalized


def _load_turbines_csv(path: Path) -> list[Turbine]:
    raw = path.read_text(encoding="utf-8").lstrip("\ufeff")
    lines = raw.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)

    delimiter = _parse_csv_delimiter("\n".join(lines)[:4096])
    rows = list(csv.DictReader(lines, delimiter=delimiter))
    if not rows:
        raise ValueError(f"No rows found in turbine metadata CSV: {path}")

    turbines = []
    for row in rows:
        parsed = _normalize_csv_row(row)
        turbine_id = (parsed.get("turbine_id") or parsed.get("id") or "").strip()
        if not turbine_id:
            raise ValueError("Missing turbine_id in CSV row")
        try:
            x = float(parsed["x"])
            y = float(parsed["y"])
        except KeyError as exc:
            raise ValueError("Missing x/y columns in CSV row") from exc
        name = parsed.get("name")
        turbines.append(Turbine(turbine_id=turbine_id, x=x, y=y, name=name))
    return turbines


def _load_turbines_geojson(path: Path) -> tuple[list[Turbine], CRS | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    turbines = []
    for feat in features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or [None, None]
        turbine_id = (props.get("turbine_id") or props.get("id") or "").strip()
        if not turbine_id:
            raise ValueError("Missing turbine_id in GeoJSON feature")
        turbines.append(
            Turbine(
                turbine_id=turbine_id,
                x=float(coords[0]),
                y=float(coords[1]),
                name=props.get("name"),
            )
        )

    crs_value = (payload.get("crs") or {}).get("properties", {}).get("name")
    crs = CRS.from_string(crs_value) if crs_value else None
    return turbines, crs


def load_turbines(path: str) -> tuple[list[Turbine], CRS | None]:
    src = Path(path)
    suffix = src.suffix.lower()
    if suffix == ".csv":
        return _load_turbines_csv(src), None
    if suffix in {".geojson", ".json"}:
        return _load_turbines_geojson(src)
    raise ValueError("Supported turbine metadata formats: CSV, GeoJSON")


def reproject_turbines(
    turbines: Iterable[Turbine], src_crs: CRS, dst_crs: CRS
) -> list[Turbine]:
    turbines = list(turbines)
    if src_crs == dst_crs:
        return turbines
    xs = [t.x for t in turbines]
    ys = [t.y for t in turbines]
    tx, ty = transform(src_crs, dst_crs, xs, ys)
    return [
        Turbine(turbine_id=t.turbine_id, x=x, y=y, name=t.name)
        for t, x, y in zip(turbines, tx, ty)
    ]


def validate_rasters(raster_paths: list[str]) -> list[rasterio.io.DatasetReader]:
    if not raster_paths:
        raise ValueError("At least one raster is required")
    datasets = [rasterio.open(path) for path in raster_paths]

    first = datasets[0]
    for idx, ds in enumerate(datasets[1:], start=2):
        if ds.crs != first.crs:
            raise ValueError(f"Raster #{idx} CRS mismatch: {ds.crs} != {first.crs}")
        if ds.transform != first.transform:
            raise ValueError(
                f"Raster #{idx} transform mismatch. Unified View rasters must be aligned."
            )
        if ds.width != first.width or ds.height != first.height:
            raise ValueError(f"Raster #{idx} shape mismatch: {(ds.width, ds.height)}")
    return datasets
