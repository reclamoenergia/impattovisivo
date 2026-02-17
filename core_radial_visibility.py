import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.windows import Window

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
    radius_m: float
    step_m: float = 24.0
    k_rays: int = 8192
    strict_nodata: bool = True


@dataclass(frozen=True)
class FineConfig:
    bbox: BBox
    step_m: float
    k_rays: int
    full_extent: bool = False


def is_nodata(value: float, dem_nodata: Optional[float]) -> bool:
    if np.isnan(value):
        return True
    if dem_nodata is None:
        return False
    return bool(np.isclose(value, dem_nodata))


def suggest_k_from_radius(radius_m: float, pixel_size_m: float) -> int:
    """Suggest K using K ~= 2*pi*R/s and snap up to quality presets."""
    if radius_m <= 0 or pixel_size_m <= 0:
        raise ValueError("radius_m e pixel_size_m devono essere > 0")
    raw_k = int(math.ceil((2.0 * math.pi * radius_m) / pixel_size_m))
    for preset in RAY_QUALITY_PRESETS:
        if preset >= raw_k:
            return preset
    mul = int(math.ceil(raw_k / RAY_QUALITY_PRESETS[-1]))
    return RAY_QUALITY_PRESETS[-1] * mul


def default_step_from_pixel(pixel_size_m: float) -> float:
    """Suggested default step for DTM 8 m -> 24 m (3 pixels)."""
    if pixel_size_m <= 0:
        raise ValueError("pixel_size_m deve essere > 0")
    return float(max(pixel_size_m, 3.0 * pixel_size_m))


def _cell_center_xy(transform: Affine, row: int, col: int) -> Tuple[float, float]:
    x = transform.c + (col + 0.5) * transform.a
    y = transform.f + (row + 0.5) * transform.e
    return x, y


def _world_to_rowcol_nearest(transform: Affine, x: float, y: float) -> Tuple[int, int]:
    col = int(round((x - (transform.c + 0.5 * transform.a)) / transform.a))
    row = int(round((y - (transform.f + 0.5 * transform.e)) / transform.e))
    return row, col


def _ray_cells(
    dem: np.ndarray,
    transform: Affine,
    dem_nodata: Optional[float],
    rt: int,
    ct: int,
    theta: float,
    radius_m: float,
    step_m: float,
    strict_nodata: bool,
):
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
    transform: Affine,
    dem_nodata: Optional[float],
    turbine_x: float,
    turbine_y: float,
    turbine_height: float,
    observer_height: float,
    config: RadialConfig,
    theta_mask: Optional[np.ndarray] = None,
    clip_bbox: Optional[BBox] = None,
) -> np.ndarray:
    rows, cols = dem.shape
    out = np.zeros((rows, cols), dtype=np.float32)

    rt, ct = _world_to_rowcol_nearest(transform, turbine_x, turbine_y)
    if rt < 0 or rt >= rows or ct < 0 or ct >= cols:
        raise ValueError("Coordinate turbina fuori DEM")

    z_base = float(dem[rt, ct])
    if is_nodata(z_base, dem_nodata):
        raise ValueError("Se turbina su nodata: errore")

    # nodata DEM stays nodata in output.
    nodata_mask = np.isnan(dem) if dem_nodata is None else (np.isnan(dem) | np.isclose(dem, dem_nodata))
    out[nodata_mask] = OUTPUT_NODATA
    out[rt, ct] = np.float32(turbine_height)

    for k in range(config.k_rays):
        if theta_mask is not None and not bool(theta_mask[k]):
            continue
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

    return out


def build_theta_mask_for_bbox(
    transform: Affine,
    turbine_x: float,
    turbine_y: float,
    bbox: BBox,
    k_rays: int,
) -> np.ndarray:
    corners = np.array(
        [
            [bbox.min_x, bbox.min_y],
            [bbox.min_x, bbox.max_y],
            [bbox.max_x, bbox.min_y],
            [bbox.max_x, bbox.max_y],
        ],
        dtype=np.float64,
    )

    ang = np.mod(np.arctan2(corners[:, 1] - turbine_y, corners[:, 0] - turbine_x), 2.0 * np.pi)
    a_min = float(np.min(ang))
    a_max = float(np.max(ang))

    wrap_span = (a_min + 2.0 * np.pi) - a_max
    direct_span = a_max - a_min
    use_wrap = wrap_span < direct_span

    mask = np.zeros(k_rays, dtype=np.bool_)
    for k in range(k_rays):
        theta = (2.0 * math.pi * k) / k_rays
        if not use_wrap:
            mask[k] = a_min <= theta <= a_max
        else:
            mask[k] = theta >= a_max or theta <= a_min
    return mask


def aligned_bbox_window(transform: Affine, width: int, height: int, bbox: BBox) -> Window:
    c0 = int(math.floor((bbox.min_x - transform.c) / transform.a))
    c1 = int(math.ceil((bbox.max_x - transform.c) / transform.a))
    r0 = int(math.floor((bbox.min_y - transform.f) / transform.e))
    r1 = int(math.ceil((bbox.max_y - transform.f) / transform.e))

    col_off = max(0, min(c0, width))
    col_end = max(0, min(c1, width))
    row_off = max(0, min(r0, height))
    row_end = max(0, min(r1, height))

    return Window(col_off=col_off, row_off=row_off, width=max(0, col_end - col_off), height=max(0, row_end - row_off))


def write_main_output(path: str, dem_profile: dict, values: np.ndarray) -> None:
    profile = dem_profile.copy()
    profile.update(dtype=rasterio.float32, count=1, nodata=OUTPUT_NODATA, compress="LZW")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(values.astype(np.float32, copy=False), 1)


def write_fine_output(path: str, dem_profile: dict, values: np.ndarray, full_extent: bool, window: Optional[Window] = None) -> None:
    profile = dem_profile.copy()
    profile.update(dtype=rasterio.float32, count=1, nodata=OUTPUT_NODATA, compress="LZW")

    if not full_extent:
        if window is None:
            raise ValueError("window obbligatoria quando full_extent=False")
        profile.update(
            width=int(window.width),
            height=int(window.height),
            transform=rasterio.windows.transform(window, dem_profile["transform"]),
        )

    with rasterio.open(path, "w", **profile) as dst:
        dst.write(values.astype(np.float32, copy=False), 1)
