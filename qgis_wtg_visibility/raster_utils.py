# -*- coding: utf-8 -*-
"""Utility raster/vector per plugin QGIS."""

from dataclasses import dataclass
import os
from typing import Optional

import numpy as np

try:
    import rasterio
    from rasterio.transform import Affine
except ImportError:  # QGIS runtime può non avere rasterio installato
    rasterio = None

    @dataclass(frozen=True)
    class Affine:  # fallback minimale per calc_core
        a: float
        b: float
        c: float
        d: float
        e: float
        f: float

    from osgeo import gdal

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
    if rasterio is not None:
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

    ds = gdal.Open(path)
    if ds is None:
        raise ValueError(f"Impossibile aprire DEM: {path}")

    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray()
    nodata = band.GetNoDataValue()
    geot = ds.GetGeoTransform()
    transform = Affine(geot[1], geot[2], geot[0], geot[4], geot[5], geot[3])

    profile = {
        "driver": "GTiff",
        "width": ds.RasterXSize,
        "height": ds.RasterYSize,
        "count": 1,
        "dtype": str(arr.dtype),
        "transform": transform,
        "crs_wkt": ds.GetProjectionRef(),
        "nodata": nodata,
    }
    px = abs(float(transform.a))
    py = abs(float(transform.e))
    return DemData(
        array=arr,
        profile=profile,
        transform=transform,
        crs=profile["crs_wkt"],
        nodata=nodata,
        pixel_size_x=px,
        pixel_size_y=py,
    )


def write_geotiff(path: str, profile: dict, values: np.ndarray) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    if rasterio is not None:
        out_profile = profile.copy()
        out_profile.update(dtype=rasterio.float32, count=1, nodata=OUTPUT_NODATA, compress="LZW")
        with rasterio.open(path, "w", **out_profile) as dst:
            dst.write(values.astype(np.float32, copy=False), 1)
        return

    width = int(profile["width"])
    height = int(profile["height"])
    transform = profile["transform"]
    geot = (float(transform.c), float(transform.a), float(transform.b), float(transform.f), float(transform.d), float(transform.e))

    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, width, height, 1, gdal.GDT_Float32, options=["COMPRESS=LZW"])
    ds.SetGeoTransform(geot)
    if profile.get("crs_wkt"):
        ds.SetProjection(profile["crs_wkt"])
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(float(OUTPUT_NODATA))
    band.WriteArray(values.astype(np.float32, copy=False))
    band.FlushCache()
    ds.FlushCache()


def qgis_raster_source_path(raster_layer) -> str:
    source = raster_layer.source()
    if "|" in source:
        return source.split("|", 1)[0]
    return source


def is_metric_projected_crs(qgs_crs) -> bool:
    if not qgs_crs.isValid() or qgs_crs.isGeographic():
        return False
    return "meter" in qgs_crs.mapUnits().name.lower()
