import math

import pytest

from parcel_robot.navigation.value_map import (
    CellRegion,
    SemanticValueMap2D,
    ViewCone,
)


def _map(*, shape: tuple[int, int] = (7, 7)) -> SemanticValueMap2D:
    return SemanticValueMap2D(
        shape=shape,
        resolution_m=1.0,
        origin_global_cell=(-3, -3),
    )


def test_cone_paints_only_cell_centres_inside_range_and_fov() -> None:
    value_map = _map()
    cone = ViewCone(
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        fov_rad=math.pi / 2.0,
        min_range_m=0.5,
        max_range_m=2.1,
    )

    painted = value_map.write(cone, value=0.7, conf=1.0)

    assert painted == 2
    assert value_map.read((1, 0)) == (0.7, 1.0)
    assert value_map.read((2, 0)) == (0.7, 1.0)
    assert value_map.read((1, 1)) == (0.0, 0.0)  # exact FOV edge has zero weight
    assert value_map.read((0, 0)) == (0.0, 0.0)  # below minimum range
    assert value_map.read((-1, 0)) == (0.0, 0.0)  # behind camera
    assert value_map.read((3, 0)) == (0.0, 0.0)  # beyond maximum range


def test_vlfm_confidence_falloff_is_cosine_squared() -> None:
    value_map = _map()
    cone = ViewCone(
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        fov_rad=math.pi,
        min_range_m=0.5,
        max_range_m=2.0,
    )

    value_map.write(cone, value=0.9, conf=0.8)

    axis_value, axis_confidence = value_map.read((1, 0))
    diagonal_value, diagonal_confidence = value_map.read((1, 1))
    edge_value, edge_confidence = value_map.read((0, 1))
    expected_diagonal = 0.8 * math.cos(
        (math.pi / 4.0) / (math.pi / 2.0) * math.pi / 2.0
    ) ** 2

    assert axis_value == 0.9
    assert axis_confidence == 0.8
    assert diagonal_value == 0.9
    assert diagonal_confidence == pytest.approx(expected_diagonal, rel=0.0, abs=1e-15)
    assert edge_value == 0.0
    assert edge_confidence == 0.0


def test_overlapping_looks_use_confidence_weighted_average_exactly() -> None:
    value_map = _map()
    cone = ViewCone(
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        fov_rad=math.pi / 3.0,
        min_range_m=0.5,
        max_range_m=1.1,
    )

    value_map.write(cone, value=0.2, conf=0.25)
    value_map.write(cone, value=0.8, conf=0.75)

    value, confidence = value_map.read((1, 0))
    assert value == pytest.approx((0.25 * 0.2 + 0.75 * 0.8) / (0.25 + 0.75))
    assert confidence == 1.0


def test_zero_confidence_look_does_not_make_cells_known() -> None:
    value_map = _map()
    cone = ViewCone(
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        fov_rad=math.pi / 2.0,
        max_range_m=2.0,
    )

    assert value_map.write(cone, value=1.0, conf=0.0) == 0
    assert value_map.read((1, 0)) == (0.0, 0.0)


def test_unknown_fraction_counts_unseen_and_out_of_window_cells() -> None:
    value_map = _map(shape=(3, 3))
    cone = ViewCone(
        origin_world_xy=(-1.5, -1.5),
        heading_rad=0.0,
        fov_rad=math.pi / 2.0,
        min_range_m=0.5,
        max_range_m=1.1,
    )
    value_map.write(cone, value=0.4, conf=1.0)

    assert value_map.unknown_fraction([(-1, -2), (-1, -1)]) == 0.5
    assert value_map.unknown_fraction([(-1, -2), (-1, -2)]) == 0.0
    assert value_map.unknown_fraction([(-1, -2), (50, 50)]) == 0.5
    assert value_map.unknown_fraction(CellRegion((-1, -2), (0, 0))) == 0.5
    with pytest.raises(ValueError, match="at least one"):
        value_map.unknown_fraction([])


def test_recenter_preserves_global_overlap_and_drops_departed_cells() -> None:
    value_map = SemanticValueMap2D(shape=(2, 3), resolution_m=1.0)
    cone = ViewCone(
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        fov_rad=math.pi / 2.0,
        min_range_m=0.5,
        max_range_m=1.1,
    )
    value_map.write(cone, value=0.6, conf=1.0)
    assert value_map.read((1, 0)) == (0.6, 1.0)

    assert value_map.recenter((1, 0)) == (1, 0)
    assert value_map.read((1, 0)) == (0.6, 1.0)
    assert value_map.read((0, 0)) == (0.0, 0.0)

    assert value_map.recenter((2, 0)) == (1, 0)
    assert value_map.read((1, 0)) == (0.0, 0.0)


@pytest.mark.parametrize("name,value", [("value", -0.01), ("value", 1.01), ("conf", math.nan)])
def test_write_rejects_values_outside_frozen_contract(name: str, value: float) -> None:
    value_map = _map()
    cone = ViewCone(
        origin_world_xy=(0.5, 0.5),
        heading_rad=0.0,
        fov_rad=math.pi / 2.0,
        max_range_m=1.0,
    )
    kwargs = {"value": 0.5, "conf": 0.5}
    kwargs[name] = value

    with pytest.raises(ValueError):
        value_map.write(cone, **kwargs)
