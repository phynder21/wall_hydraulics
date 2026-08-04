"""Optimizer validation for optimize.py.

These tests assert *invariants* of ``optimize_actuator`` — the properties that
must hold for every result regardless of inputs — rather than exact optimal
values (which depend on the search and would make brittle tests). They therefore
run with small search budgets: a handful of starts and iterations is plenty to
check structure, feasibility bookkeeping, locks, and bounds.

The exhaustive input sweep is marked ``slow`` and skipped by default; run it
with ``pytest -m slow`` before a release or after touching the optimizer.
"""
import numpy as np
import pytest

from optimize import optimize_actuator, CONTAINER_PRESETS, VAR_NAMES

STANDARD = CONTAINER_PRESETS["standard"]

# Every key downstream code (app.py, the CLI) reads off a result.
REQUIRED_KEYS = {
    "a", "b", "d", "f", "locked", "peak_force", "stroke_ratio", "L_min", "L_max",
    "ceiling_violation", "roof_clearance", "moment_arm", "over_center", "feasible",
    "alternatives", "alt_rel_tol", "n_starts", "stroke_ratio_max", "x_cg", "z_cg",
    "container_width", "container_height", "success",
}

# Small budget: enough to exercise structure and constraints, fast to run.
FAST = dict(n_starts=3, maxiter=60)


def assert_result_invariants(res, ctx=""):
    """Every property that must hold for any optimizer result."""
    assert REQUIRED_KEYS <= set(res), f"{ctx}: missing {REQUIRED_KEYS - set(res)}"

    for key in ("a", "b", "d", "f", "peak_force", "stroke_ratio", "L_min", "L_max"):
        assert np.isfinite(res[key]), f"{ctx}: {key} is not finite ({res[key]})"

    # The first alternative is, by contract, the optimum shown in the sliders,
    # with zero force penalty; every alternative stays inside the tolerance band.
    alts = res["alternatives"]
    if alts:
        first = alts[0]
        for key in ("a", "b", "d", "f"):
            assert abs(round(first[key], 2) - round(res[key], 2)) <= 0.02, (
                f"{ctx}: alternatives[0].{key} disagrees with result.{key}")
        assert first["penalty_pct"] == pytest.approx(0.0, abs=1e-6), (
            f"{ctx}: alternatives[0] should be the optimum (0% penalty)")
        band = res["peak_force"] * (1 + res["alt_rel_tol"]) + 1e-6
        for alt in alts:
            assert "penalty_pct" in alt
            assert alt["peak_force"] <= band, (
                f"{ctx}: alternative peak {alt['peak_force']:.3f} exceeds band "
                f"{band:.3f}")

    # The over-center flag is exactly the sign of the worst moment arm.
    assert res["over_center"] == (res["moment_arm"] < 0.0), f"{ctx}: flag/sign disagree"

    # "Feasible" must not contradict the constraints it claims to satisfy.
    if res["feasible"]:
        assert res["stroke_ratio"] <= res["stroke_ratio_max"] + 1e-2, f"{ctx}: stroke"
        assert res["ceiling_violation"] <= 1e-2, f"{ctx}: ceiling"
        assert res["moment_arm"] >= 0.0, f"{ctx}: over-centers yet feasible"


def test_baseline_result_is_well_formed():
    res = optimize_actuator(*STANDARD, x_cg=1.20, z_cg=0.55, **FAST)
    assert_result_invariants(res, "baseline")


@pytest.mark.parametrize("x_cg,z_cg", [(0.0, 0.0), (1.2, 0.55), (2.0, 1.5), (2.591, 0.0)])
def test_varied_center_of_gravity(x_cg, z_cg):
    res = optimize_actuator(*STANDARD, x_cg=x_cg, z_cg=z_cg, **FAST)
    assert_result_invariants(res, f"cg=({x_cg},{z_cg})")


@pytest.mark.parametrize("stroke_ratio_max", [1.0, 1.5, 1.8, 2.5, 3.0])
def test_varied_stroke_ratio(stroke_ratio_max):
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55,
                            stroke_ratio_max=stroke_ratio_max, **FAST)
    assert_result_invariants(res, f"stroke={stroke_ratio_max}")


@pytest.mark.parametrize("roof_clearance", [0.0, 0.05, 0.20, 2.0])
def test_varied_roof_clearance(roof_clearance):
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55,
                            roof_clearance=roof_clearance, **FAST)
    assert_result_invariants(res, f"clearance={roof_clearance}")


@pytest.mark.parametrize("locked", [
    {"a": 0.5}, {"b": 1.8}, {"d": 0.1}, {"f": 0.4}, {"a": 0.5, "f": 0.4},
])
def test_locked_variables_are_held(locked):
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55, locked=dict(locked), **FAST)
    assert_result_invariants(res, f"locked={locked}")
    for key, value in locked.items():
        assert abs(res[key] - value) < 1e-6, f"lock {key}={value} not held ({res[key]})"


def test_all_locked_is_pure_evaluation():
    """With all four variables locked there is nothing to search: the geometry is
    just evaluated, and no starts are reported."""
    locked = {"a": 0.5, "b": 1.8, "d": 0.1, "f": 0.4}
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55, locked=locked, **FAST)
    assert_result_invariants(res, "all-locked")
    assert res["n_starts"] == 0
    for key, value in locked.items():
        assert abs(res[key] - value) < 1e-6


@pytest.mark.parametrize("var_bounds", [
    {"f": (0.0, 1.0)},
    {"a": (0.2, 0.4), "f": (0.3, 0.8)},
    {"d": (0.0, 0.2)},
    {"b": (2.0, 2.0)},  # zero-width range must be treated as a lock at 2.0
])
def test_var_bounds_are_respected(var_bounds):
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55, var_bounds=var_bounds, **FAST)
    assert_result_invariants(res, f"var_bounds={var_bounds}")
    for key, (lo, hi) in var_bounds.items():
        assert lo - 1e-6 <= res[key] <= hi + 1e-6, (
            f"{key}={res[key]:.4f} outside mounting limit [{lo}, {hi}]")


def test_forced_over_centering_geometry_is_flagged_not_crashed():
    """Locking all four variables to an impossible (over-centering) geometry must
    return a flagged result, never raise."""
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55,
                            locked={"a": 0.5, "b": 0.5, "d": 0.0, "f": 0.5}, **FAST)
    assert_result_invariants(res, "forced-geometry")
    # An over-centering geometry cannot be feasible.
    if res["over_center"]:
        assert not res["feasible"]


def test_result_is_deterministic():
    """Fixed seeds make identical inputs produce identical output (so shared URLs
    and repeated runs are stable)."""
    kwargs = dict(x_cg=1.2, z_cg=0.55, **FAST)
    first = optimize_actuator(*STANDARD, **kwargs)
    second = optimize_actuator(*STANDARD, **kwargs)
    assert abs(first["peak_force"] - second["peak_force"]) < 1e-9
    for key in VAR_NAMES:
        assert abs(first[key] - second[key]) < 1e-9


@pytest.mark.parametrize("alt_tol", [0.0, 0.05, 0.15, 0.30])
def test_alternatives_respect_tolerance(alt_tol):
    """Whatever the tolerance, alternatives[0] is the optimum and every listed
    design stays within the requested force band."""
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55, alt_rel_tol=alt_tol, **FAST)
    assert res["alt_rel_tol"] == alt_tol
    assert_result_invariants(res, f"alt_tol={alt_tol}")
    # Zero tolerance -> nothing worse than the optimum is listed (only the
    # optimum and any exact ties, all at ~0% penalty).
    if alt_tol == 0.0:
        assert all(alt["penalty_pct"] <= 0.5 for alt in res["alternatives"])


def test_alternatives_are_geometrically_distinct():
    """Any two listed alternatives differ by a real amount in geometry (they are
    fallbacks, not near-duplicates)."""
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55, alt_rel_tol=0.15)
    alts = res["alternatives"]
    for i in range(len(alts)):
        for j in range(i + 1, len(alts)):
            gi, gj = alts[i], alts[j]
            spread = max(abs(gi[k] - gj[k]) for k in ("a", "b", "d", "f"))
            assert spread > 0.02, f"alternatives {i},{j} are near-duplicates"


@pytest.mark.slow
def test_diverse_alternatives_surface_for_standard_container():
    """On the standard container the sharp optimum (~12.94, base at the ceiling)
    has a genuinely different near-optimal basin ~10% worse (base near the
    floor); a 15% band must surface at least one such fallback."""
    res = optimize_actuator(*STANDARD, x_cg=1.20, z_cg=0.55, alt_rel_tol=0.15)
    assert len(res["alternatives"]) > 1, "expected diverse fallbacks within 15%"
    fallback = res["alternatives"][1]
    assert fallback["penalty_pct"] > 0.0
    # The optimum mounts the base high; the fallback should differ in geometry.
    optimum = res["alternatives"][0]
    spread = max(abs(fallback[k] - optimum[k]) for k in ("a", "b", "d", "f"))
    assert spread > 0.1, "fallback is not geometrically distinct from the optimum"


def test_finds_known_standard_optimum():
    """The full multi-start search on the standard container reaches its global
    optimum (~13.90 N/kg for the internal clear dimensions), below the ~14.3+ local
    basin a single start tends to find. Guards against a regression that breaks
    multi-start. (The old ~12.94 target was for the larger external dimensions and a
    wider `a` range, both since tightened.)"""
    res = optimize_actuator(*STANDARD, x_cg=1.20, z_cg=0.55)  # full default budget
    assert res["feasible"]
    assert res["peak_force"] < 14.2, f"peak {res['peak_force']:.2f} — multi-start regressed?"


def test_fast_mode_reaches_the_optimum():
    """fast=True (grid-seed + polish) still lands on the known global optimum,
    quickly, with valid result invariants."""
    res = optimize_actuator(*STANDARD, x_cg=1.20, z_cg=0.55, fast=True)
    assert_result_invariants(res, "fast")
    assert res["feasible"]
    assert res["peak_force"] < 14.2          # the ~13.90 internal-dimensions optimum


@pytest.mark.slow
@pytest.mark.parametrize("kw", [
    {"x_cg": 1.2, "z_cg": 0.55},
    {"x_cg": 1.2, "z_cg": 1.0},
    {"x_cg": 1.2, "z_cg": 0.55, "stroke_ratio_max": 2.0},
    {"x_cg": 1.2, "z_cg": 0.55, "var_bounds": {"f": (0.0, 0.5)}},
])
def test_fast_matches_default_within_tolerance(kw):
    """The fast optimizer never lands meaningfully ABOVE the full 20-start search.
    It may occasionally beat it (the vectorized grid sweep can find a basin the
    random starts miss), so the bound is one-sided: fast must not be worse by more
    than a fraction of a N/kg -- the speedup doesn't cost accuracy."""
    slow = optimize_actuator(*STANDARD, **kw)
    fast = optimize_actuator(*STANDARD, **kw, fast=True)
    assert fast["peak_force"] <= slow["peak_force"] + 0.2


@pytest.mark.slow
@pytest.mark.parametrize("container", list(CONTAINER_PRESETS))
def test_exhaustive_input_sweep(container):
    """Exhaustive invariant sweep over containers, cg, stroke ratios, and
    clearances. Opt in with ``pytest -m slow``."""
    width, height = CONTAINER_PRESETS[container]
    checked = 0
    for x_cg in (0.0, 0.6, 1.2, 2.0, height):
        for z_cg in (0.0, 0.3, 0.55, 1.0, 1.5):
            for stroke in (1.5, 1.8, 2.5):
                for clearance in (0.0, 0.05, 0.2):
                    res = optimize_actuator(
                        width, height, x_cg, z_cg, stroke_ratio_max=stroke,
                        roof_clearance=clearance, alt_rel_tol=0.0, **FAST)
                    assert_result_invariants(
                        res, f"{container} cg=({x_cg},{z_cg}) sr={stroke} clr={clearance}")
                    checked += 1
    assert checked == 5 * 5 * 3 * 3


def test_length_window_is_respected():
    """With a cylinder length window, the optimum's cylinder length stays inside
    it (the reverse optimizer's core constraint)."""
    from optimize import LENGTH_TOL
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55, length_window=(0.9, 1.7),
                            stroke_ratio_max=3.0, n_starts=4, maxiter=80)
    assert res["feasible"]
    assert res["L_min"] >= 0.9 - LENGTH_TOL - 1e-6
    assert res["L_max"] <= 1.7 + LENGTH_TOL + 1e-6


@pytest.mark.parametrize("window", [(0.9, 1.7), (0.7, 1.5), (1.0, 2.0)])
def test_length_window_variants(window):
    """Across several cylinder windows, a feasible reverse optimum keeps its
    cylinder length inside the window."""
    from optimize import LENGTH_TOL
    lo, hi = window
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55, length_window=window,
                            stroke_ratio_max=3.0, n_starts=4, maxiter=80)
    if res["feasible"]:
        assert res["L_min"] >= lo - LENGTH_TOL - 1e-6
        assert res["L_max"] <= hi + LENGTH_TOL + 1e-6


def test_length_mode_minimizes_cylinder_length():
    """Length mode returns a shorter cylinder than force mode and keeps peak
    force at or below the cap; a tighter cap yields a LONGER cylinder (the
    force-vs-length tradeoff)."""
    from optimize import FORCE_CAP_TOL
    force = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55, alt_rel_tol=0.0, **FAST)
    lengths = {}
    for cap in (40.0, 25.0):
        res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55,
                                objective_mode="length", force_cap=cap,
                                alt_rel_tol=0.0, n_starts=4, maxiter=80)
        assert res["feasible"], f"cap={cap} should be reachable"
        assert res["peak_force"] <= cap + FORCE_CAP_TOL + 1e-6
        assert res["L_max"] < force["L_max"]     # shorter than the min-force design
        lengths[cap] = res["L_max"]
    assert lengths[25.0] > lengths[40.0]         # tighter cap -> longer cylinder


def test_length_mode_infeasible_when_cap_too_low():
    """An unreachably low force cap is flagged infeasible."""
    res = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55,
                            objective_mode="length", force_cap=3.0,
                            n_starts=4, maxiter=80)
    assert not res["feasible"]


def test_fast_length_matches_slow_optimizer():
    """The fast grid solver for the length objective lands on the same optimum as
    the thorough differential-evolution path — no accuracy compromise. Its
    extended length matches the DE result within 1%, and it respects the cap."""
    for cap in (45.0, 20.0):
        fast = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55,
                                 objective_mode="length", force_cap=cap,
                                 fast=True, alt_rel_tol=0.0)
        slow = optimize_actuator(*STANDARD, x_cg=1.2, z_cg=0.55,
                                 objective_mode="length", force_cap=cap,
                                 fast=False, n_starts=6, maxiter=150, alt_rel_tol=0.0)
        assert fast["feasible"] and slow["feasible"]
        assert fast["peak_force"] <= cap + 0.5
        assert abs(fast["L_max"] - slow["L_max"]) / slow["L_max"] < 0.01


def test_minimize_mount_material_is_leanest_at_optimal_force():
    """minimize_mount_material returns a feasible, buildable geometry whose f + d is at
    least as small as the diverse alternatives' leanest, at (essentially) the optimal
    force, and it respects the given var_bounds."""
    from optimize import minimize_mount_material
    W, H = CONTAINER_PRESETS["standard"]
    bnds = {"a": (0.13, 1.010), "b": (0.13, 1.650), "d": (0.13, 1.000), "f": (0.13, 0.790)}
    lw = (0.667, 1.073)
    o = optimize_actuator(W, H, 1.20, 0.55, length_window=lw, length_exact=True,
                          stroke_ratio_max=3.0, roof_clearance=0.0, var_bounds=bnds,
                          alt_rel_tol=0.005, n_alternatives=20, alt_min_sep=0.02,
                          alt_target_sep=0.08)
    lean = minimize_mount_material(W, H, 1.20, 0.55, length_window=lw, length_exact=True,
                                   roof_clearance=0.0, var_bounds=bnds,
                                   force_cap=o["peak_force"] * 1.001, stroke_ratio_max=3.0)
    assert lean is not None
    diverse_leanest = min(g["f"] + g["d"] for g in o["alternatives"])
    assert lean["f"] + lean["d"] <= diverse_leanest + 1e-6, \
        "must be at least as lean as the diverse alternatives"
    assert lean["peak_force"] <= o["peak_force"] * 1.01, "at essentially the optimal force"
    assert bnds["f"][0] - 1e-6 <= lean["f"] <= bnds["f"][1] + 1e-6, "respects f bounds"
    assert bnds["d"][0] - 1e-6 <= lean["d"] <= bnds["d"][1] + 1e-6, "respects d bounds"
