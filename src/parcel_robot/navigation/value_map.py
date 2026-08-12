"""Pure, rolling 2D semantic value map for value-directed visual search.

The map uses the same cell convention as ``RollingOccupancyGrid``: cells are
global ``(x, y)`` integer indices, array storage is ``[y, x]``, and world cell
centres are ``((x + 0.5) * resolution, (y + 0.5) * resolution)``.

No detector or runtime is invoked here.  A caller supplies one scalar semantic
similarity and optical-axis confidence for each camera look.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

GridCell = tuple[int, int]
WorldPoint = tuple[float, float]


@dataclass(frozen=True)
class ViewCone:
    """Horizontal camera cone to paint into the co-registered grid."""

    origin_world_xy: WorldPoint
    heading_rad: float
    fov_rad: float
    max_range_m: float
    min_range_m: float = 0.0

    def __post_init__(self) -> None:
        numbers = (
            *self.origin_world_xy,
            self.heading_rad,
            self.fov_rad,
            self.max_range_m,
            self.min_range_m,
        )
        if not all(math.isfinite(number) for number in numbers):
            raise ValueError("cone fields must be finite")
        if not 0.0 < self.fov_rad <= 2.0 * math.pi:
            raise ValueError("fov_rad must be in (0, 2*pi]")
        if self.min_range_m < 0.0:
            raise ValueError("min_range_m must be non-negative")
        if self.max_range_m <= self.min_range_m:
            raise ValueError("max_range_m must be greater than min_range_m")


@dataclass(frozen=True)
class CellRegion:
    """Half-open rectangular region in global grid-cell coordinates."""

    min_cell: GridCell
    max_cell_exclusive: GridCell

    def __post_init__(self) -> None:
        if (
            self.max_cell_exclusive[0] <= self.min_cell[0]
            or self.max_cell_exclusive[1] <= self.min_cell[1]
        ):
            raise ValueError("region must have positive width and height")

    def __iter__(self):
        for y in range(self.min_cell[1], self.max_cell_exclusive[1]):
            for x in range(self.min_cell[0], self.max_cell_exclusive[0]):
                yield (x, y)


class SemanticValueMap2D:
    """Confidence-fused semantic values in a rolling metric grid.

    ``write(cone, value, conf)`` applies the VLFM angular confidence

    ``conf * cos²((theta / (fov / 2)) * (pi / 2))``

    to each cell centre in the cone.  Overlapping observations are fused as

    ``(c_new * v_new + c_old * v_old) / (c_new + c_old)``.

    The confidence returned by :meth:`read` is accumulated observation weight,
    not a probability, and can therefore exceed one after repeated looks.

    **Evidence surface (card VS-5).** ``write(..., is_evidence=True)`` records
    that the painted look carried QUERY-RELEVANT evidence, as decided upstream
    by :mod:`parcel_robot.navigation.value_evidence` (VS-3's frozen contract:
    ``is_evidence`` is true iff at least one observation in the cone matched the
    query at or above ``SIGLIP2_MATCH_THRESHOLD``).  :attr:`evidence_count` is
    the number of such looks that actually landed at least one cell, and it is
    the number the empty-map delegation keys on: ``evidence_count == 0`` means
    no cell in this map holds anything that could move a decision, which is what
    makes "flag-on with no evidence is EXACTLY the baseline" provable rather
    than accidental (``FOLLOWUP_DESIGNS.md`` §2.2(d)).  MISS paints — a scanned
    cone with nothing query-relevant in it — deliberately do NOT increment it:
    a miss lowers value, it is not evidence that the target is anywhere.
    """

    def __init__(
        self,
        *,
        shape: tuple[int, int],
        resolution_m: float,
        origin_global_cell: GridCell = (0, 0),
    ) -> None:
        if (
            len(shape) != 2
            or isinstance(shape[0], bool)
            or isinstance(shape[1], bool)
            or not isinstance(shape[0], int)
            or not isinstance(shape[1], int)
            or shape[0] <= 0
            or shape[1] <= 0
        ):
            raise ValueError("shape must be a pair of positive integers")
        if not math.isfinite(resolution_m) or resolution_m <= 0.0:
            raise ValueError("resolution_m must be finite and positive")
        self._shape = shape
        self._resolution_m = float(resolution_m)
        self._origin_global_cell = _cell(origin_global_cell)
        self._values = np.zeros(shape, dtype=np.float64)
        self._confidence = np.zeros(shape, dtype=np.float64)
        self._evidence_count = 0

    @property
    def shape(self) -> tuple[int, int]:
        return self._shape

    @property
    def evidence_count(self) -> int:
        """Number of query-relevant evidence looks painted into this map.

        Zero means the map is evidence-free — the delegation predicate card
        VS-5 keys on.  Misses and background looks leave it at zero for any
        number of looks.
        """

        return self._evidence_count

    def reset(self) -> None:
        """Mission scope: forget every look, including the evidence count.

        A new search starts with an empty map (VS-3's ``ValueEvidencePolicy``
        has the same clause).  Without this, evidence from a previous mission
        would make ``evidence_count > 0`` before the new mission has looked at
        anything, and the empty-map delegation would silently not fire.
        """

        self._values = np.zeros(self._shape, dtype=np.float64)
        self._confidence = np.zeros(self._shape, dtype=np.float64)
        self._evidence_count = 0

    @property
    def resolution_m(self) -> float:
        return self._resolution_m

    @property
    def origin_global_cell(self) -> GridCell:
        return self._origin_global_cell

    def write(
        self,
        cone: ViewCone,
        value: float,
        conf: float,
        *,
        is_evidence: bool = False,
    ) -> int:
        """Paint one look and return the number of cells with positive weight.

        ``is_evidence`` is VS-3's paint-tuple third field.  It is keyword-only
        and defaults to ``False`` so every pre-existing caller is unchanged, and
        it increments :attr:`evidence_count` only when the look also LANDED
        (``painted > 0``) — a cone that fell entirely outside the rolling window
        put no evidence in the map and must not claim to have.
        """

        semantic_value = _unit_interval(value, "value")
        axis_confidence = _unit_interval(conf, "conf")
        if axis_confidence == 0.0:
            return 0

        half_fov = cone.fov_rad / 2.0
        painted = 0
        for local_y in range(self._shape[0]):
            for local_x in range(self._shape[1]):
                global_cell = (
                    self._origin_global_cell[0] + local_x,
                    self._origin_global_cell[1] + local_y,
                )
                centre_x, centre_y = self._cell_center(global_cell)
                dx = centre_x - cone.origin_world_xy[0]
                dy = centre_y - cone.origin_world_xy[1]
                distance = math.hypot(dx, dy)
                if distance < cone.min_range_m or distance > cone.max_range_m:
                    continue

                # The camera-origin cell has no geometric bearing. Treat its
                # centre as optical-axis evidence when min_range_m includes it.
                theta = (
                    0.0
                    if distance == 0.0
                    else abs(_wrap_angle(math.atan2(dy, dx) - cone.heading_rad))
                )
                if theta > half_fov:
                    continue
                if theta == half_fov:
                    angular_confidence = 0.0
                else:
                    angular_confidence = math.cos(theta / half_fov * math.pi / 2.0) ** 2
                new_confidence = axis_confidence * angular_confidence
                if new_confidence <= 0.0:
                    continue

                previous_confidence = self._confidence[local_y, local_x]
                total_confidence = previous_confidence + new_confidence
                if previous_confidence == 0.0:
                    self._values[local_y, local_x] = semantic_value
                else:
                    self._values[local_y, local_x] = (
                        previous_confidence * self._values[local_y, local_x]
                        + new_confidence * semantic_value
                    ) / total_confidence
                self._confidence[local_y, local_x] = total_confidence
                painted += 1
        if is_evidence and painted > 0:
            self._evidence_count += 1
        return painted

    def read(self, cell: GridCell) -> tuple[float, float]:
        """Return ``(value, accumulated_confidence)``; out-of-window is unknown."""

        local = self._to_local(_cell(cell))
        if local is None:
            return (0.0, 0.0)
        local_x, local_y = local
        return (float(self._values[local_y, local_x]), float(self._confidence[local_y, local_x]))

    def unknown_fraction(self, region: Iterable[GridCell]) -> float:
        """Return the fraction of unique region cells with zero confidence.

        Cells outside the current rolling window are unknown.  An empty region
        is rejected because its fraction is undefined.
        """

        cells = {_cell(cell) for cell in region}
        if not cells:
            raise ValueError("region must contain at least one cell")
        unknown = sum(self.read(cell)[1] == 0.0 for cell in cells)
        return unknown / len(cells)

    def recenter(self, origin_global_cell: GridCell) -> GridCell:
        """Move the rolling window, preserving evidence in the overlap.

        Returns the integer shift ``new_origin - old_origin``.
        """

        new_origin = _cell(origin_global_cell)
        shift_x = new_origin[0] - self._origin_global_cell[0]
        shift_y = new_origin[1] - self._origin_global_cell[1]
        if shift_x == 0 and shift_y == 0:
            return (0, 0)

        new_values = np.zeros_like(self._values)
        new_confidence = np.zeros_like(self._confidence)
        height, width = self._shape
        for new_y in range(height):
            old_y = new_y + shift_y
            if not 0 <= old_y < height:
                continue
            for new_x in range(width):
                old_x = new_x + shift_x
                if 0 <= old_x < width:
                    new_values[new_y, new_x] = self._values[old_y, old_x]
                    new_confidence[new_y, new_x] = self._confidence[old_y, old_x]
        self._values = new_values
        self._confidence = new_confidence
        self._origin_global_cell = new_origin
        return (shift_x, shift_y)

    def _cell_center(self, cell: GridCell) -> WorldPoint:
        return (
            (cell[0] + 0.5) * self._resolution_m,
            (cell[1] + 0.5) * self._resolution_m,
        )

    def _to_local(self, cell: GridCell) -> GridCell | None:
        local_x = cell[0] - self._origin_global_cell[0]
        local_y = cell[1] - self._origin_global_cell[1]
        if 0 <= local_x < self._shape[1] and 0 <= local_y < self._shape[0]:
            return (local_x, local_y)
        return None


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _unit_interval(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be finite and in [0, 1]")
    return result


def _cell(value: GridCell) -> GridCell:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or isinstance(value[0], bool)
        or isinstance(value[1], bool)
        or not isinstance(value[0], int)
        or not isinstance(value[1], int)
    ):
        raise TypeError("cell must be an (x, y) integer tuple")
    return value
