# -*- coding: utf-8 -*-
"""Core numerico indipendente dalla UI/QGIS.

Mantiene la logica richiesta:
- confronto max_alpha con beta_base/beta_top
- output visibile in [0, H]
- supporto strict nodata
- dominio radiale entro R
"""

from dataclasses import dataclass
import math
from typing import Callable, Optional, Sequence, Tuple

import numpy as np

OUTPUT_NODATA = -9999.0
RAY_QUALITY_PRESETS = (4096, 8192, 12288, 16384)


@dataclass(frozen=True)
class BBox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float


@dataclass(frozen=True)
class RadialConfig:
    radius_m: float = 10000.0
    step_m: float = 24.0
    k_rays: int = 8192
    strict_nodata: bool = True


@dataclass(frozen=True)
class FineConfig:
    enabled: bool = False
    bbox: Optional[BBox] = None
    step_m: float = 12.0
    k_rays: int = 12288
    create_separate_raster: bool = True


def is_nodata(value: float, dem_nodata: Optional[float]) -> bool:
    if np.isnan(value):
        return True
    if dem_nodata is None:
        return False
    return bool(np.isclose(value, dem_nodata))


def suggest_k_from_radius(radius_m: float, pixel_size_m: float) -> int:
    raw_k = int(math.ceil((2.0 * math.pi * radius_m) / pixel_size_m))
    for preset in RAY_QUALITY_PRESETS:
        if preset >= raw_k:
            return preset
    mul = int(math.ceil(raw_k / RAY_QUALITY_PRESETS[-1]))
    return RAY_QUALITY_PRESETS[-1] * mul


def _cell_center_xy(transform, row: int, col: int) -> Tuple[float, float]:
    x = transform.c + (col + 0.5) * transform.a
    y = transform.f + (row + 0.5) * transform.e
    return x, y


def _world_to_rowcol_nearest(transform, x: float, y: float) -> Tuple[int, int]:
    col = int(round((x - (transform.c + 0.5 * transform.a)) / transform.a))
    row = int(round((y - (transform.f + 0.5 * transform.e)) / transform.e))
    return row, col


def _ray_cells(dem, transform, dem_nodata, rt, ct, theta, radius_m, step_m, strict_nodata):
    rows, cols = dem.shape
    x_t, y_t = _cell_center_xy(transform, rt, ct)
    sampled = []
    seen = set()
    d = step_m

    while d <= radius_m + 1e-9:
        x = x_t + d * math.cos(theta)
        y = y_t + d * math.sin(theta)
        r, c = _world_to_rowcol_nearest(transform, x, y)
        if r < 0 or r >= rows or c < 0 or c >= cols:
            break
        if (r, c) in seen or (r == rt and c == ct):
            d += step_m
            continue

        z = float(dem[r, c])
        if is_nodata(z, dem_nodata):
            if strict_nodata:
                break
            d += step_m
            continue

        seen.add((r, c))
        sampled.append((r, c, d))
        d += step_m

    return sampled


def _visible_on_ray(
    dem: np.ndarray,
    dem_nodata: Optional[float],
    ray_cells: Sequence[Tuple[int, int, float]],
    z_base: float,
    turbine_height: float,
    observer_height: float,
    strict_nodata: bool,
):
    z_top = z_base + turbine_height
    out = []

    for j in range(len(ray_cells)):
        rj, cj, dj = ray_cells[j]
        z_cell = float(dem[rj, cj])
        if is_nodata(z_cell, dem_nodata):
            out.append((rj, cj, OUTPUT_NODATA))
            continue

        z_obs = z_cell + observer_height
        max_alpha = -math.inf
        blocked = False

        for i in range(j):
            ri, ci, di = ray_cells[i]
            z_i = float(dem[ri, ci])
            if is_nodata(z_i, dem_nodata):
                if strict_nodata:
                    blocked = True
                    break
                continue

            dist_oi = dj - di
            if dist_oi <= 0.0:
                continue
            alpha_i = (z_i - z_obs) / dist_oi
            if alpha_i > max_alpha:
                max_alpha = alpha_i

        if blocked:
            out.append((rj, cj, OUTPUT_NODATA))
            continue

        beta_base = (z_base - z_obs) / dj
        beta_top = (z_top - z_obs) / dj

        if max_alpha <= beta_base:
            visible = turbine_height
        elif max_alpha >= beta_top:
            visible = 0.0
        else:
            h_block = (z_obs + max_alpha * dj) - z_base
            visible = turbine_height - h_block

        visible = max(0.0, min(turbine_height, visible))
        out.append((rj, cj, visible))

    return out


def compute_visibility_radial(
    dem: np.ndarray,
    transform,
    dem_nodata: Optional[float],
    turbine_x: float,
    turbine_y: float,
    turbine_height: float,
    observer_height: float,
    config: RadialConfig,
    progress_cb: Optional[Callable[[float], None]] = None,
    clip_bbox: Optional[BBox] = None,
) -> np.ndarray:
    rows, cols = dem.shape
    out = np.zeros((rows, cols), dtype=np.float32)

    rt, ct = _world_to_rowcol_nearest(transform, turbine_x, turbine_y)
    if rt < 0 or rt >= rows or ct < 0 or ct >= cols:
        raise ValueError("Coordinate WTG fuori DEM")

    z_base = float(dem[rt, ct])
    if is_nodata(z_base, dem_nodata):
        raise ValueError("WTG su nodata DEM")

    nodata_mask = np.isnan(dem) if dem_nodata is None else (np.isnan(dem) | np.isclose(dem, dem_nodata))
    out[nodata_mask] = OUTPUT_NODATA
    out[rt, ct] = np.float32(turbine_height)

    for k in range(config.k_rays):
        theta = (2.0 * math.pi * k) / config.k_rays
        ray_cells = _ray_cells(
            dem,
            transform,
            dem_nodata,
            rt,
            ct,
            theta,
            config.radius_m,
            config.step_m,
            config.strict_nodata,
        )

        for r, c, visible in _visible_on_ray(
            dem,
            dem_nodata,
            ray_cells,
            z_base,
            turbine_height,
            observer_height,
            config.strict_nodata,
        ):
            if clip_bbox is not None:
                x, y = _cell_center_xy(transform, r, c)
                if x < clip_bbox.min_x or x > clip_bbox.max_x or y < clip_bbox.min_y or y > clip_bbox.max_y:
                    continue
            if visible > out[r, c]:
                out[r, c] = np.float32(visible)

        if progress_cb and (k % max(1, config.k_rays // 100) == 0):
            progress_cb((k + 1) / config.k_rays)

    return out
