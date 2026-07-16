"""UI validation for app.py via Streamlit's headless AppTest harness.

These render the real Streamlit script with various session state and assert it
never throws an uncaught exception — across both unit systems, the fine-precision
toggle, extreme slider values, container switches, malformed URL params, and the
clickable-alternatives flow.

Note on animation: the app's sweep mode calls ``st.rerun()`` in a loop by design
(fine in a browser). AppTest re-runs synchronously and would hit its timeout, so
the sweep can't be driven here — its bounce logic is unit-tested directly in
``test_advance_angle_*`` instead.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")

STANDARD_KEY = "Standard (8'6\") — 2.44 m W x 2.59 m H"
HIGHCUBE_KEY = "High-Cube (9'6\") — 2.44 m W x 2.90 m H"


def fresh_app():
    """A freshly loaded, once-run app instance (independent session state)."""
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.run()
    assert not at.exception, at.exception
    return at


def run_ok(at, ctx):
    at.run()
    assert not at.exception, f"{ctx}: {at.exception}"


def test_app_loads_clean():
    at = fresh_app()
    # Core state the rest of the app depends on must exist after a load.
    for key in ("a", "b", "d", "f", "x_cg", "z_cg", "theta_deg",
                "stroke_ratio", "roof_clearance", "size_key"):
        _ = at.session_state[key]


@pytest.mark.parametrize("units", ["meters", "inches"])
@pytest.mark.parametrize("fine", [False, True])
def test_units_and_precision_combinations(units, fine):
    at = fresh_app()
    at.session_state["units"] = units
    at.session_state["fine"] = fine
    run_ok(at, f"units={units} fine={fine}")


@pytest.mark.parametrize("geom", [
    pytest.param(dict(a=0.05, b=0.05, d=0.0, f=0.0), id="all-minimal"),
    pytest.param(dict(a=1.219, b=2.591, d=1.0, f=2.591), id="all-near-max"),
    pytest.param(dict(a=0.6, b=1.8, d=0.0, f=0.0), id="d-f-zero"),
    pytest.param(dict(a=0.05, b=2.591, d=1.0, f=2.591), id="singular-mix"),
])
def test_extreme_geometries_render(geom):
    at = fresh_app()
    for key, value in geom.items():
        at.session_state[key] = value
    run_ok(at, f"geom={geom}")


@pytest.mark.parametrize("x_cg,z_cg", [
    (0.0, 0.0), (2.591, 1.5), (0.0, 1.5), (2.591, 0.0), (1.2, 0.55),
])
def test_extreme_center_of_gravity(x_cg, z_cg):
    at = fresh_app()
    at.session_state["x_cg"] = x_cg
    at.session_state["z_cg"] = z_cg
    run_ok(at, f"cg=({x_cg},{z_cg})")


@pytest.mark.parametrize("stroke_ratio", [1.0, 1.8, 3.0])
@pytest.mark.parametrize("roof_clearance", [0.0, 0.25, 0.5])
def test_constraint_extremes(stroke_ratio, roof_clearance):
    at = fresh_app()
    at.session_state["stroke_ratio"] = stroke_ratio
    at.session_state["roof_clearance"] = roof_clearance
    run_ok(at, f"sr={stroke_ratio} clr={roof_clearance}")


@pytest.mark.parametrize("theta", [0.0, 45.0, 90.0])
def test_theta_endpoints(theta):
    at = fresh_app()
    at.session_state["theta_deg"] = theta
    run_ok(at, f"theta={theta}")


@pytest.mark.parametrize("size_key", [STANDARD_KEY, HIGHCUBE_KEY])
def test_container_switch(size_key):
    at = fresh_app()
    for key, value in dict(a=0.6, b=1.8, d=0.1, f=0.4, x_cg=1.2, z_cg=0.55).items():
        at.session_state[key] = value
    at.session_state["size_key"] = size_key
    run_ok(at, f"container={size_key[:10]}")


def test_narrowed_mounting_limits():
    at = fresh_app()
    at.session_state["rng_f"] = (0.0, 1.0)
    at.session_state["rng_a"] = (0.2, 0.4)
    run_ok(at, "mounting limits narrowed")


def test_untouched_mounting_limits_grow_with_container():
    """Switching Standard -> High-Cube must widen an *untouched* range (still at
    the old full extent) to the taller container, but leave a user-narrowed range
    alone."""
    at = fresh_app()
    at.session_state["size_key"] = STANDARD_KEY
    run_ok(at, "standard")
    assert at.session_state["rng_b"][1] == pytest.approx(2.591, abs=1e-3)
    # Narrow f deliberately; leave b untouched.
    at.session_state["rng_f"] = (0.3, 1.0)
    at.session_state["size_key"] = HIGHCUBE_KEY
    run_ok(at, "highcube")
    # Untouched b grew to the High-Cube height...
    assert at.session_state["rng_b"][1] == pytest.approx(2.896, abs=1e-3)
    # ...but the deliberately narrowed f range was preserved.
    assert at.session_state["rng_f"] == pytest.approx((0.3, 1.0), abs=1e-6)


def test_overlay_two_designs_renders():
    """Save A, change geometry, save B, then overlay — the plots must render both
    designs without error."""
    at = fresh_app()
    save_a = next(b for b in at.button if b.label == "Save as A")
    save_a.click()
    run_ok(at, "save A")
    at.session_state["a"] = 0.40
    at.session_state["b"] = 2.50
    run_ok(at, "change geometry")
    save_b = next(b for b in at.button if b.label == "Save as B")
    save_b.click()
    run_ok(at, "save B")
    at.session_state["overlay"] = True
    run_ok(at, "overlay on")
    assert "design_A" in at.session_state and "design_B" in at.session_state


def test_malformed_url_params_fall_back():
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.query_params["a"] = "not-a-number"
    at.query_params["size_key"] = "bogus"
    at.query_params["theta_deg"] = "999"
    at.query_params["stroke_ratio"] = "abc"
    at.query_params["roof_clearance"] = "-5"
    at.run()
    assert not at.exception, at.exception
    # Bad numeric -> default; out-of-range -> clamped; bad choice -> valid default.
    assert at.session_state["a"] == pytest.approx(0.60)
    assert at.session_state["size_key"] == STANDARD_KEY
    assert at.session_state["theta_deg"] == pytest.approx(90.0)
    assert at.session_state["roof_clearance"] == pytest.approx(0.0)


def test_clickable_alternatives_load_geometry():
    """Seeding two equally-good geometries renders one button each; clicking a
    button loads that geometry into the a/b/d/f sliders in the same run."""
    at = fresh_app()
    # Full mounting ranges so both seeded geometries are admissible.
    at.session_state["rng_a"] = (0.05, 1.219)
    at.session_state["rng_b"] = (0.05, 2.591)
    at.session_state["rng_d"] = (0.0, 1.0)
    at.session_state["rng_f"] = (0.0, 2.591)
    at.session_state["_alts"] = [
        {"a": 0.30, "b": 2.00, "d": 0.20, "f": 0.50, "peak_force": 13.0},
        {"a": 0.45, "b": 2.30, "d": 0.35, "f": 0.85, "peak_force": 13.0},
    ]
    run_ok(at, "alternatives seeded")

    alt_buttons = [b for b in at.button if b.key and b.key.startswith("alt_")]
    assert len(alt_buttons) == 2

    next(b for b in alt_buttons if b.key == "alt_1").click()
    run_ok(at, "click alt_1")
    for key, value in dict(a=0.45, b=2.30, d=0.35, f=0.85).items():
        assert at.session_state[key] == pytest.approx(value, abs=0.02)


def test_control_tabs_present():
    """The Designer's controls are organized into the four left-panel tabs."""
    at = fresh_app()
    labels = [t.label for t in at.tabs]
    for name in ("Setup", "Optimize", "Geometry", "Compare"):
        assert name in labels, f"missing control tab: {name}"


def test_summary_metrics_render():
    """The four glance metrics render with the expected labels and units."""
    at = fresh_app()
    labels = [m.label for m in at.metric]
    assert len(at.metric) == 4
    assert any("Peak force" in x for x in labels)
    assert any("Stroke ratio" in x for x in labels)
    # values carry their units
    by_label = {m.label: m.value for m in at.metric}
    assert "N/kg" in next(v for k, v in by_label.items() if "Peak force" in k)
    # the cylinder-sizing readout (force -> bore) renders below the metrics
    assert any("Required bore" in str(m.value) for m in at.markdown)
    # the Optimize tab shows a persistent a/b/d/f geometry readout
    assert any("Geometry (a, b, d, f)" in str(c.value) for c in at.caption)


def test_browse_view_renders():
    """Switching to the Browse view builds a (small) lookup table and renders a
    results table without error, and filtering/sorting reruns cleanly."""
    import browse
    browse.TABLE_RES = 12   # tiny grid so the build is fast in tests
    at = AppTest.from_file(APP_PATH, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    at.session_state["view"] = "Browse configurations"
    at.run()
    assert not at.exception, at.exception
    assert len(at.dataframe) >= 1
    # narrow a mounting limit and change the sort key -> still clean
    at.session_state["lk_rng_f"] = (0.0, 0.8)
    at.session_state["lk_sort"] = "f"
    at.run()
    assert not at.exception, at.exception


@pytest.mark.slow
@pytest.mark.parametrize("units", ["meters", "inches"])
def test_optimize_through_ui(units):
    """Press the Optimize button in each unit system and confirm it fills the
    geometry with a sane, in-range design and raises nothing."""
    at = fresh_app()
    at.session_state["units"] = units
    at.session_state["rng_a"] = (0.05, 1.219)
    at.session_state["rng_b"] = (0.05, 2.591)
    at.session_state["rng_d"] = (0.0, 1.0)
    at.session_state["rng_f"] = (0.0, 2.591)
    run_ok(at, f"pre-optimize {units}")

    button = next(b for b in at.sidebar.button if "Optimize" in b.label)
    button.click()
    run_ok(at, f"optimize {units}")
    for key in ("a", "b", "d", "f"):
        assert 0.0 <= at.session_state[key] <= 3.0


@pytest.mark.slow
def test_optimize_for_length_through_ui():
    """Length mode: set a force cap, press Optimize, and confirm it fills a sane
    geometry and renders (the cylinder-length objective) without error."""
    at = fresh_app()
    at.session_state["opt_mode"] = "Cylinder length"
    run_ok(at, "select length mode")
    at.session_state["force_cap_nkg"] = 40.0
    run_ok(at, "set force cap")
    button = next(b for b in at.sidebar.button if "Optimize" in b.label)
    button.click()
    run_ok(at, "optimize for length")
    for key in ("a", "b", "d", "f"):
        assert 0.0 <= at.session_state[key] <= 3.0
    # the found geometry (a, b, d, f) is reported in the result message itself,
    # not only pushed into the sliders
    msgs = [str(m.value) for m in list(at.success) + list(at.warning)]
    assert any(all(tok in m for tok in ("a =", "b =", "d =", "f =")) for m in msgs), msgs


# --- Animation bounce logic (unit-tested directly; see module docstring) ------

def _advance_angle():
    import app  # importing runs app.py in bare mode (harmless warnings only)
    return app._advance_angle


def test_advance_angle_bounces_at_upper_limit():
    advance = _advance_angle()
    angle, direction = advance(89.0, 1)
    assert angle == 90.0 and direction == -1


def test_advance_angle_bounces_at_lower_limit():
    advance = _advance_angle()
    angle, direction = advance(1.0, -1)
    assert angle == 0.0 and direction == 1


@pytest.mark.parametrize("start", [0.0, 0.1, 45.0, 89.9, 90.0])
@pytest.mark.parametrize("direction", [1, -1])
def test_advance_angle_stays_in_range(start, direction):
    advance = _advance_angle()
    angle, dir_ = start, direction
    for _ in range(400):
        angle, dir_ = advance(angle, dir_)
        assert 0.0 <= angle <= 90.0


def test_reverse_view_renders():
    """The 'Size from a cylinder' view builds the table and renders — for a
    feasible cylinder AND an impossible one (which shows the no-fit message)."""
    import browse
    browse.TABLE_RES = 12   # tiny grid so the build is fast in tests
    at = AppTest.from_file(APP_PATH, default_timeout=120)
    at.run()
    at.session_state["view"] = "Size from a cylinder"
    at.run()
    assert not at.exception, at.exception
    # an impossible cylinder window must not error (shows the no-fit path)
    at.session_state["rv_ret"] = 100.0
    at.session_state["rv_stroke"] = 50.0
    at.run()
    assert not at.exception, at.exception


def test_two_cylinder_mode_halves_designer_force():
    """With 2 cylinders sharing the load, the Designer peak-force metric is halved
    (per cylinder) and a banner states the count."""
    at = fresh_app()
    one = next(m.value for m in at.metric if "Peak force" in (m.label or ""))
    at.session_state["n_cyl"] = 2
    run_ok(at, "two cylinders")
    two = next(m.value for m in at.metric if "Peak force" in (m.label or ""))
    v1, v2 = float(one.split()[0]), float(two.split()[0])
    assert abs(v2 - v1 / 2) < 0.01
    assert any("per cylinder" in str(i.value) for i in at.info)
