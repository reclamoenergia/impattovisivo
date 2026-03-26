# -*- coding: utf-8 -*-
"""Utility raster/vector per plugin QGIS."""

from dataclasses import dataclass
import os
from typing import Optional

import numpy as np
import rasterio
from rasterio.transform import Affine
from qgis.core import QgsUnitTypes

from .calc_core import OUTPUT_NODATA


@dataclass
class DemData:
    array: np.ndarray
    profile: dict
    transform: Affine
    crs: object
    nodata: Optional[float]
    pixel_size_x: float
    pixel_size_y: float


def read_dem_from_path(path: str) -> DemData:
    with rasterio.open(path) as src:
        arr = src.read(1)
        profile = src.profile.copy()
        transform = src.transform
        px = abs(float(transform.a))
        py = abs(float(transform.e))
        return DemData(
            array=arr,
            profile=profile,
            transform=transform,
            crs=src.crs,
            nodata=src.nodata,
            pixel_size_x=px,
            pixel_size_y=py,
        )


def write_geotiff(path: str, profile: dict, values: np.ndarray) -> None:
    out_profile = profile.copy()
    out_profile.update(dtype=rasterio.float32, count=1, nodata=OUTPUT_NODATA, compress="LZW")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with rasterio.open(path, "w", **out_profile) as dst:
        dst.write(values.astype(np.float32, copy=False), 1)


def qgis_raster_source_path(raster_layer) -> str:
    source = raster_layer.source()
    if "|" in source:
        return source.split("|", 1)[0]
    return source


def is_metric_projected_crs(qgs_crs) -> bool:
    if not qgs_crs.isValid() or qgs_crs.isGeographic():
        return False
    return qgs_crs.mapUnits() == QgsUnitTypes.DistanceMeters
