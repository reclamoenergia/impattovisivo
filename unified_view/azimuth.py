"""Azimuth and field-of-view helpers for unified-view sampled points."""

from __future__ import annotations

from math import atan2, degrees
from typing import Iterable


def azimuth_deg(x0: float, y0: float, x1: float, y1: float) -> float:
    """Return cartographic azimuth from (x0,y0) to (x1,y1), in [0, 360)."""
    dx = x1 - x0
    dy = y1 - y0
    return (degrees(atan2(dx, dy)) + 360.0) % 360.0


def minimal_covering_arc(angles: Iterable[float]) -> tuple[float, float, float]:
    """Return (az_min, az_max, fov_az) for the minimal circular arc covering angles.

    az_min and az_max are oriented to the selected arc and may cross the 0/360 boundary.
    """
    normalized = sorted(((a % 360.0) for a in angles))
    if not normalized:
        raise ValueError("angles must contain at least one value")
    if len(normalized) == 1:
        a0 = normalized[0]
        return a0, a0, 0.0

    best_gap = -1.0
    best_idx = -1
    for idx in range(len(normalized) - 1):
        gap = normalized[idx + 1] - normalized[idx]
        if gap > best_gap:
            best_gap = gap
            best_idx = idx
    wrap_gap = (normalized[0] + 360.0) - normalized[-1]
    if wrap_gap > best_gap:
        best_gap = wrap_gap
        best_idx = len(normalized) - 1

    az_min = normalized[(best_idx + 1) % len(normalized)]
    az_max = normalized[best_idx]
    fov_az = 360.0 - best_gap
    if fov_az < 0.0:
        fov_az = 0.0
    return az_min, az_max, fov_az
