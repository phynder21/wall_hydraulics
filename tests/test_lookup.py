"""Tests for the precomputed lookup table (lookup_build.py) and its query layer
(lookup.py). Small grid resolutions keep these fast; correctness — not the exact
optimum — is what's checked."""
import numpy as np
import pytest

import lookup_build
import lookup
from optimize import MIN_MOMENT_ARM, CONTAINER_PRESETS

STANDARD_W, STANDARD_H = CONTAINER_PRESETS["standard"]
HIGHCUBE_W, HIGHCUBE_H = CONTAINER_PRESETS["highcube"]


@pytest.fixture(scope="module")
def table():
    return lookup_build.build_table(res=16)[0]


def test_table_structure_and_pruning(table):
    keys = {"a", "b", "d", "f", "stroke_ratio", "L_min", "L_max", "moment_arm",
            "max_ceiling", "G", "store_theta"}
    assert keys <= set(table)
    n = table["a"].size
    assert n > 0
    assert table["G"].shape == (n, lookup_build.STORE_THETA)
    # Build-time pruning: no over-center/thin-margin, no over-limit stroke.
    assert np.all(table["moment_arm"] >= MIN_MOMENT_ARM)
    assert np.all(table["stroke_ratio"] <= lookup_build.STROKE_RATIO_CAP)
    assert np.all(np.isfinite(table["stroke_ratio"]))


def test_stored_gain_matches_exact_physics(table):
    """Peak force from the stored float16 gain curve matches an independent
    recompute at fine theta to well under a percent."""
    theta = np.linspace(0.0, np.pi / 2, 721)
    step = max(1, table["a"].size // 500)
    i = np.arange(0, table["a"].size, step)
    pk_stored = lookup._peak_from_gain(table["G"][i], table["store_theta"], 1.3, 0.7)
    pk_exact = lookup._peak_recompute(table["a"][i], table["b"][i], table["d"][i],
                                      table["f"][i], 1.3, 0.7, theta)
    rel = np.abs(pk_stored - pk_exact) / np.maximum(pk_exact, 1.0)
    assert rel.max() < 0.01


def test_search_respects_mounting_limits_and_constraints(table):
    res = lookup.search(table, STANDARD_H, 1.2, 0.55, stroke_max=1.8,
                        roof_clearance=0.0, bounds={"f": (0.0, 0.8)})
    assert res["peak_force"].size > 0
    assert np.all(res["f"] <= 0.8 + 1e-6)
    assert np.all(res["stroke_ratio"] <= 1.8 + 1e-6)
    assert np.all(res["moment_arm"] >= MIN_MOMENT_ARM - 1e-6)
    # default sort is ascending peak force
    assert np.all(np.diff(res["peak_force"]) >= -1e-6)


def test_container_height_filters_tall_geometries(table):
    res = lookup.search(table, STANDARD_H, 1.2, 0.55)
    assert np.all(res["b"] <= STANDARD_H + 1e-6)
    assert np.all(res["f"] <= STANDARD_H + 1e-6)
    # High-Cube admits taller geometries than Standard.
    hc = lookup.search(table, HIGHCUBE_H, 1.2, 0.55, limit=100000)
    std = lookup.search(table, STANDARD_H, 1.2, 0.55, limit=100000)
    assert hc["peak_force"].size >= std["peak_force"].size


def test_roof_clearance_shrinks_the_feasible_set(table):
    loose = lookup.search(table, STANDARD_H, 1.2, 0.55, roof_clearance=0.0,
                          limit=100000)
    tight = lookup.search(table, STANDARD_H, 1.2, 0.55, roof_clearance=0.4,
                          limit=100000)
    assert tight["peak_force"].size <= loose["peak_force"].size


def test_sort_by_attribute(table):
    res = lookup.search(table, STANDARD_H, 1.2, 0.55, sort_by="f", ascending=True)
    assert np.all(np.diff(res["f"]) >= -1e-6)


def test_extra_filter_caps_attribute(table):
    res = lookup.search(table, STANDARD_H, 1.2, 0.55, filters={"f": (None, 0.5)})
    assert res["peak_force"].size > 0
    assert np.all(res["f"] <= 0.5 + 1e-6)


def test_empty_result_is_handled_cleanly(table):
    # A mounting window outside every geometry yields no rows, no error.
    res = lookup.search(table, STANDARD_H, 1.2, 0.55, bounds={"f": (2.95, 2.96)})
    assert res["peak_force"].size == 0
    assert lookup.best(table, STANDARD_H, 1.2, 0.55, bounds={"f": (2.95, 2.96)}) is None


def test_grid_best_is_a_valid_upper_bound():
    """The grid's best feasible peak is a sane upper bound on the continuous
    optimum (~12.94): it can't be far below it, and shouldn't be wildly above."""
    tbl = lookup_build.build_table(res=20)[0]
    b = lookup.best(tbl, STANDARD_H, 1.2, 0.55, stroke_max=1.8)
    assert b is not None
    assert 12.5 <= b["peak_force"] <= 15.0


@pytest.mark.slow
def test_grid_best_not_below_exact_optimum():
    """The exact optimizer must do at least as well as the best grid point."""
    from optimize import optimize_actuator
    tbl = lookup_build.build_table(res=24)[0]
    grid = lookup.best(tbl, STANDARD_H, 1.2, 0.55, stroke_max=1.8)
    exact = optimize_actuator(STANDARD_W, STANDARD_H, 1.2, 0.55)
    assert exact["peak_force"] <= grid["peak_force"] + 1e-6
