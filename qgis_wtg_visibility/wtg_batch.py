# -*- coding: utf-8 -*-
"""Batch multi-WTG e naming output."""

from dataclasses import dataclass
import csv
import os
import re
from typing import Callable, Dict, List, Optional

from qgis.core import QgsCoordinateTransform, QgsProject

from .calc_core import RadialConfig, compute_visibility_radial
from .raster_utils import write_geotiff


@dataclass
class WtgItem:
    idx: int
    x: float
    y: float
    height: float
    wtg_id: str


@dataclass
class BatchResult:
    success: int
    failed: int
    outputs: List[str]
    errors: List[str]


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value)).strip("_")
    return cleaned or "wtg"


def build_output_path(output_dir: str, wtg_id: str, idx: int) -> str:
    name = sanitize_name(wtg_id) if wtg_id else str(idx)
    return os.path.join(output_dir, f"visible_height_{name}.tif")


def vector_features_to_items(vector_layer, h_field: str, id_field: Optional[str], target_crs=None) -> List[WtgItem]:
    items: List[WtgItem] = []
    xform = None
    if target_crs is not None and vector_layer.crs() != target_crs:
        xform = QgsCoordinateTransform(vector_layer.crs(), target_crs, QgsProject.instance())

    for i, feat in enumerate(vector_layer.getFeatures()):
        geom = feat.geometry()
        if geom is None or geom.isEmpty() or geom.type() != 0:
            continue
        pt = geom.asPoint()
        if xform is not None:
            pt = xform.transform(pt)
        h = float(feat[h_field])
        wtg_id = str(feat[id_field]) if id_field else str(i)
        items.append(WtgItem(idx=i, x=pt.x(), y=pt.y(), height=h, wtg_id=wtg_id))
    return items


def run_batch(
    dem_data,
    items: List[WtgItem],
    observer_height: float,
    radial_cfg: RadialConfig,
    output_dir: str,
    log_cb: Callable[[str], None],
    progress_cb: Callable[[float], None],
    csv_path: Optional[str] = None,
) -> BatchResult:
    os.makedirs(output_dir, exist_ok=True)
    rows: List[Dict[str, str]] = []
    outputs: List[str] = []
    errors: List[str] = []
    success = 0

    for i, item in enumerate(items):
        out_path = build_output_path(output_dir, item.wtg_id, item.idx)
        try:
            arr = compute_visibility_radial(
                dem=dem_data.array,
                transform=dem_data.transform,
                dem_nodata=dem_data.nodata,
                turbine_x=item.x,
                turbine_y=item.y,
                turbine_height=item.height,
                observer_height=observer_height,
                config=radial_cfg,
            )
            write_geotiff(out_path, dem_data.profile, arr)
            outputs.append(out_path)
            success += 1
            msg = "ok"
            err = ""
        except Exception as exc:  # pylint: disable=broad-except
            msg = "error"
            err = str(exc)
            errors.append(f"WTG {item.wtg_id}: {err}")

        rows.append(
            {
                "wtg_id": item.wtg_id,
                "x": str(item.x),
                "y": str(item.y),
                "h": str(item.height),
                "file_output": out_path,
                "esito": msg,
                "errore": err,
            }
        )
        log_cb(f"[{i + 1}/{len(items)}] WTG {item.wtg_id}: {msg}")
        progress_cb((i + 1) / max(1, len(items)))

    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=["wtg_id", "x", "y", "h", "file_output", "esito", "errore"])
            writer.writeheader()
            writer.writerows(rows)

    return BatchResult(success=success, failed=len(items) - success, outputs=outputs, errors=errors)
