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

STANDARD_KEY = "Standard (8'6\") — 2.35 × 2.39 m internal"
HIGHCUBE_KEY = "High-Cube (9'6\") — 2.35 × 2.70 m internal"


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


@pytest.mark.parametrize("units", ["Metric", "Imperial"])
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
    assert at.session_state["rng_b"][1] == pytest.approx(2.393, abs=1e-3)
    # Narrow f deliberately; leave b untouched.
    at.session_state["rng_f"] = (0.3, 1.0)
    at.session_state["size_key"] = HIGHCUBE_KEY
    run_ok(at, "highcube")
    # Untouched b grew to the High-Cube (internal) height...
    assert at.session_state["rng_b"][1] == pytest.approx(2.698, abs=1e-3)
    # ...but the deliberately narrowed f range was preserved.
    assert at.session_state["rng_f"] == pytest.approx((0.3, 1.0), abs=1e-6)


def test_half_container_toggle_controls_a_and_d_bounds():
    """The 'Keep base and bracket within half the container' toggle caps BOTH a and d
    at half the internal width when on (default) and opens them to the full width off."""
    at = fresh_app()
    at.session_state["size_key"] = STANDARD_KEY
    run_ok(at, "half on (default)")
    assert at.session_state["half_a_cap"] is True
    assert at.session_state["rng_a"][1] == pytest.approx(2.352 / 2, abs=1e-3)
    assert at.session_state["rng_d"][1] == pytest.approx(2.352 / 2, abs=1e-3)
    # Uncheck -> the (untouched) a and d ranges grow to the full internal width.
    at.session_state["half_a_cap"] = False
    run_ok(at, "half off")
    assert at.session_state["rng_a"][1] == pytest.approx(2.352, abs=1e-3)
    assert at.session_state["rng_d"][1] == pytest.approx(2.352, abs=1e-3)


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


def test_quick_guide_link_opens():
    """A quick-guide link sits under the view tabs and opens its modal without error."""
    at = fresh_app()
    btn = [b for b in at.button if b.key == "guide_btn"]
    assert btn, "quick-guide link missing under the view tabs"
    btn[0].click().run()
    assert not at.exception, at.exception


def test_summary_metrics_render():
    """The glance metrics render with the expected labels and units, including the
    large a/b/d/f geometry row at the top."""
    at = fresh_app()
    labels = [m.label for m in at.metric]
    # geometry front and centre: a, b, d, f each shown as a large metric
    for v in ("a — base", "b — attach", "d — bracket", "f — base"):
        assert any(v in x for x in labels), f"missing geometry metric {v}: {labels}"
    assert any("Peak force" in x for x in labels)
    assert any("Stroke ratio" in x for x in labels)
    # retracted + extended cylinder lengths are shown explicitly
    assert any("Retracted" in x for x in labels), labels
    assert any("Extended" in x for x in labels), labels
    # values carry their units
    by_label = {m.label: m.value for m in at.metric}
    assert "N/kg" in next(v for k, v in by_label.items() if "Peak force" in k)
    # the cylinder-sizing readout (force -> bore) renders below the metrics
    assert any("Required bore" in str(m.value) for m in at.markdown)
    # the Optimize tab shows a persistent a/b/d/f geometry readout
    assert any("Geometry (a, b, d, f)" in str(c.value) for c in at.caption)


def test_imperial_units_switch_all_readouts():
    """Switching Units to Imperial flips the whole Designer, not just lengths: the
    Peak force metric reads lbf/lb and the bore card follows too (pressure in psi,
    no bar input), all without error."""
    at = fresh_app()
    at.session_state["units"] = "Imperial"
    at.run()
    assert not at.exception, at.exception
    peak = next(v for k, v in {m.label: m.value for m in at.metric}.items()
                if "Peak force" in k)
    assert "lbf/lb" in peak, f"peak metric should read lbf/lb, got {peak}"
    press_labels = [n.label or "" for n in at.number_input]
    assert any("psi" in lbl for lbl in press_labels), "bore card should ask pressure in psi"
    assert not any("bar" in lbl for lbl in press_labels), "no bar input in imperial mode"


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


def test_reverse_units_convert_wall_and_have_fine_precision():
    """Reverse: the Wall geometry uses metres/inches (like the Designer, NOT the
    cylinder's mm) and converts with the toggle; a Fine-precision toggle exists; and the
    closed-length input keeps typed decimals (%.2f, not rounded to a whole number)."""
    import browse
    browse.TABLE_RES = 12
    at = AppTest.from_file(APP_PATH, default_timeout=120)
    at.run()
    at.session_state["view"] = "Size from a cylinder"
    at.session_state["units"] = "Imperial"
    at.run()
    assert not at.exception, at.exception
    assert any(t.key == "rv_fine" for t in at.toggle), "Reverse needs a fine-precision toggle"

    def _label(substr):
        for w in list(at.slider) + list(at.number_input):
            if substr in (w.label or ""):
                return w.label
        return ""
    assert "(in)" in _label("x_cg"), f"x_cg should be inches in Imperial: {_label('x_cg')}"
    # closed length keeps a decimal when typed (2-decimal format, not %.0f)
    at.number_input(key="rv_ret__n").set_value(20.25).run()
    assert at.number_input(key="rv_ret__n").value == pytest.approx(20.25)
    at.session_state["units"] = "Metric"
    at.run()
    assert not at.exception, at.exception
    xcg = _label("x_cg")
    assert "(m)" in xcg and "(mm)" not in xcg, f"x_cg should be metres in Metric: {xcg}"
    # With Fine on, the linked SLIDER must show the same decimals as its number box
    # (else typing 1.125 displays 1.13 on the slider). Both should be %.3f.
    at.session_state["rv_fine"] = True
    at.run()
    sfmt = {s.key: getattr(s, "format", None) for s in at.slider}
    assert sfmt.get("rv_xcg__s") == "%.3f", f"slider should match the box format: {sfmt.get('rv_xcg__s')}"
    at.number_input(key="rv_xcg__n").set_value(1.125).run()
    assert at.number_input(key="rv_xcg__n").value == pytest.approx(1.125)
    assert at.slider(key="rv_xcg__s").value == pytest.approx(1.125), "slider holds the exact value"


def test_browse_imperial_units():
    """Browse honors the Imperial toggle: the results-table headers switch to inches /
    lbf-lb (no m / N/kg), and it renders without error."""
    import browse
    browse.TABLE_RES = 12
    at = AppTest.from_file(APP_PATH, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    at.session_state["view"] = "Browse configurations"
    at.session_state["units"] = "Imperial"
    at.run()
    assert not at.exception, at.exception
    cols = " ".join(str(c) for c in at.dataframe[0].value.columns)
    assert "(in)" in cols and "lbf/lb" in cols, cols
    assert "(m)" not in cols and "N/kg" not in cols, cols


@pytest.mark.slow
@pytest.mark.parametrize("units", ["Metric", "Imperial"])
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
    # One slider now sets the max force; the per-kg cap = max force / Setup mass.
    at.session_state["mass"] = 5000.0
    at.session_state["max_force_n"] = 200000.0   # 200 kN / 5000 kg = 40 N/kg cap
    run_ok(at, "set max cylinder force")
    button = next(b for b in at.sidebar.button if "Optimize" in b.label)
    button.click()
    run_ok(at, "optimize for length")
    for key in ("a", "b", "d", "f"):
        assert 0.0 <= at.session_state[key] <= 3.0
    # the found geometry (a, b, d, f) is reported in the result message itself,
    # not only pushed into the sliders
    msgs = [str(m.value) for m in list(at.success) + list(at.warning)]
    assert any(all(tok in m for tok in ("a =", "b =", "d =", "f =")) for m in msgs), msgs


def test_length_mode_single_max_force_slider():
    """Length mode folds the old per-kg cap + duplicate mass sliders into ONE 'Max
    cylinder force' slider; the per-kg cap the optimizer uses is derived from the
    Setup mass (200 kN / 5000 kg = 40 N/kg) and shown as a caption."""
    at = fresh_app()
    at.session_state["opt_mode"] = "Cylinder length"
    at.session_state["mass"] = 5000.0
    at.session_state["max_force_n"] = 200000.0
    at.run()
    assert not at.exception, at.exception
    labels = [w.label or "" for w in list(at.slider) + list(at.number_input)]
    assert any("Max cylinder force" in lbl for lbl in labels), "single max-force slider expected"
    assert not any("Max piston force" in lbl for lbl in labels), "old per-kg cap slider is gone"
    caps = " ".join(str(c.value) for c in at.caption)
    assert "40.00 N/kg" in caps, caps


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
    """The 'Size from a cylinder' view shows the INSTANT grid pick up top with an
    optimizer button (no picker until it's run); clicking the button reveals the exact
    optimum + an alternatives picker. Also: 'no sensor' wording is gone, and an
    impossible cylinder shows the no-fit message."""
    import browse
    browse.TABLE_RES = 12   # tiny grid so the build is fast in tests
    at = AppTest.from_file(APP_PATH, default_timeout=180)
    at.run()
    at.session_state["view"] = "Size from a cylinder"
    at.run()
    assert not at.exception, at.exception
    # instant grid headline: a/b/d/f + mass metrics on top...
    labels = [m.label or "" for m in at.metric]
    assert any("base along floor" in l for l in labels), "geometry metrics on top"
    assert any("Safe max wall mass" in l for l in labels), "mass metric on top"
    # ...an optimizer button (explained), and NO picker until it's run
    def _picker(a):
        return [s for s in a.selectbox if "mount material" in (s.label or "")]
    optbtns = [b for b in at.button if "exact optimum" in (b.label or "").lower()]
    assert optbtns, "the exact-optimum button should be present near the top"
    assert not _picker(at), "no picker before the optimizer is run"
    blurb = " ".join(str(m.value) for m in at.markdown)
    assert "sensor" not in blurb.lower(), "the 'no sensor' wording must be gone"
    assert "near-optimal" in blurb.lower(), "the button must explain the grid pick"
    # running the optimizer reveals the picker + exact-optimum result
    optbtns[0].click().run()
    assert not at.exception, at.exception
    picker = _picker(at)
    assert picker, "picker appears after run"
    # options are labeled with f+d and ordered by it (least mount material first);
    # all are at the optimal force, so no per-option force/tag is shown
    import re
    opts = list(picker[0].options)
    fds = [float(re.search(r"f\+d = ([\d.]+)", o).group(1)) for o in opts]
    assert fds == sorted(fds), f"options must be ordered by f+d ascending: {fds}"
    assert not any("least force" in o or "% force" in o for o in opts), \
        "no force tag on options (all at the optimal force)"
    # changing a NON-geometry input (bore) after optimizing must not error and must
    # keep the stored result (regression: the picker index used to be read from the
    # widget and compared as the wrong type).
    at.session_state["rv_bore"] = 0.08
    at.run()
    assert not at.exception, at.exception
    assert _picker(at), "the optimizer result persists across a bore change"
    # the full-stroke toggle renders and explains
    at.session_state["rv_full_stroke"] = True
    at.run()
    assert not at.exception, at.exception
    assert any(t.key == "rv_full_stroke" for t in at.toggle), "full-stroke toggle exists"
    blurb = " ".join(str(m.value) for m in at.markdown) \
        + " ".join(str(i.value) for i in at.info)
    assert "full stroke" in blurb.lower() and "sensor" not in blurb.lower()
    # an impossible cylinder window must not error (shows the no-fit path), exact on
    at.session_state["rv_ret"] = 0.1
    at.session_state["rv_stroke"] = 0.05
    at.run()
    assert not at.exception, at.exception


def test_reverse_empty_reason_names_over_center():
    """The no-fit diagnosis tells an over-center (singular) region — where every layout
    that clears the roof crosses the hinge — apart from an ordinary roof/limits block."""
    from reverse import _empty_reason
    H = 2.393
    # a tight box on a known over-center geometry reads as the singularity...
    oc = {"a": (0.049, 0.051), "b": (0.049, 0.051),
          "d": (0.049, 0.051), "f": (0.173, 0.175)}
    assert _empty_reason(oc, H, 0.0) == "over_center"
    # ...while a wide, ordinary box (buildable layouts exist) does not.
    wide = {"a": (0.1, 1.0), "b": (0.1, 2.0), "d": (0.0, 1.0), "f": (0.0, 1.0)}
    assert _empty_reason(wide, H, 0.0) == "limits"


def test_reverse_nearest_window_is_one_real_layout():
    """The no-fit 'closest layout' band must come from a SINGLE layout, not a mix of
    min(L_min) and max(L_max) across different layouts (which overstates the need)."""
    import numpy as np
    from reverse import _nearest_window
    # three layouts; window is 0.70-1.20. The mixed envelope would read 0.60-2.90, but
    # the layout that pokes out least is #1 (0.75-1.35), a real, achievable band.
    L_min = np.array([0.60, 0.75, 1.90])
    L_max = np.array([2.90, 1.35, 2.10])
    lo, hi, longer = _nearest_window(L_min, L_max, 0.70, 1.20)
    assert (lo, hi) == (0.75, 1.35), "must report one layout's own band, not an envelope"
    assert longer is True, "the miss (1.35 > 1.20) is at the extended end"


def test_reverse_nearest_window_exact_prefers_fullest_stroke():
    """In full-stroke mode the closest layout is the one nearest to MATCHING the window
    (both ends), not just any layout that fits inside it."""
    import numpy as np
    from reverse import _nearest_window
    # both fit inside 0.70-1.20; A barely uses the stroke, B nearly fills it.
    L_min = np.array([0.90, 0.72])
    L_max = np.array([1.00, 1.18])
    assert _nearest_window(L_min, L_max, 0.70, 1.20, exact=False)[:2] == (0.90, 1.00)
    assert _nearest_window(L_min, L_max, 0.70, 1.20, exact=True)[:2] == (0.72, 1.18)


def test_reverse_optimizer_alternatives_and_length_span():
    """The Reverse optimizer button feeds the picker: the optimizer returns a feasible
    optimum plus near-optimal alternatives, and reverse._length_span agrees with the
    optimizer's own L_max for the winning geometry."""
    from reverse import _length_span
    from optimize import optimize_actuator, CONTAINER_PRESETS
    W, H = CONTAINER_PRESETS["standard"]
    bnds = {"a": (0.05, 1.176), "b": (0.05, 2.393), "d": (0.0, 1.176), "f": (0.0, 2.393)}
    opt = optimize_actuator(W, H, 1.2, 0.55, length_window=(0.70, 1.20),
                            stroke_ratio_max=3.0, roof_clearance=0.0, var_bounds=bnds,
                            alt_rel_tol=0.15)
    assert opt["feasible"]
    assert len(opt.get("alternatives", [])) >= 1, "should offer alternatives to pick from"
    lo, hi, ratio = _length_span(opt["a"], opt["b"], opt["d"], opt["f"])
    assert lo <= hi and ratio >= 1.0
    assert abs(hi - opt["L_max"]) < 1e-2, "span helper must match the optimizer's L_max"


def test_reverse_asks_for_many_alternatives_default_stays_small():
    """Reverse asks the optimizer for a big spread of distinct layouts (~20) to pick
    from, while the default (Designer/Browse) keeps a small set."""
    from optimize import optimize_actuator, CONTAINER_PRESETS
    W, H = CONTAINER_PRESETS["standard"]
    bnds = {"a": (0.05, 1.176), "b": (0.05, 2.393), "d": (0.0, 1.176), "f": (0.0, 2.393)}
    kw = dict(length_window=(0.70, 1.20), stroke_ratio_max=3.0, roof_clearance=0.0,
              var_bounds=bnds)
    many = optimize_actuator(W, H, 1.2, 0.55, n_alternatives=20, alt_min_sep=0.02,
                             alt_target_sep=0.08, **kw)          # Reverse settings
    few = optimize_actuator(W, H, 1.2, 0.55, **kw)               # default (other views)
    assert len(many["alternatives"]) >= 15, len(many["alternatives"])
    assert len(few["alternatives"]) <= 6, "default count must stay small for other views"
    geoms = [(a["a"], a["b"], a["d"], a["f"]) for a in many["alternatives"]]
    assert len(set(geoms)) == len(geoms), "the options must be distinct geometries"


def test_full_stroke_stays_inside_stroke_so_door_completes():
    """The full-stroke toggle must fill the stroke WITHOUT exceeding it: the swing has
    to stay inside [retracted, extended] (L_min >= retracted, L_max <= extended) or the
    cylinder bottoms out before the door reaches its end and the door stops short. Near-
    full: within tol of each end. The continuous optimizer fills it to the last mm."""
    import lookup, lookup_build
    from optimize import optimize_actuator, CONTAINER_PRESETS
    table = lookup_build.build_table(res=40)[0]
    W, H = CONTAINER_PRESETS["standard"]
    L_ret, L_ext = 0.70, 1.20
    tol = 0.02
    grid = lookup.cylinder_matches(table, H, 1.2, 0.55, L_ret, L_ext, roof_clearance=0.0,
                                   limit=1, exact=True, exact_tol=tol)
    assert grid["peak_force"].size, "an exact-match grid layout should exist here"
    lmin, lmax = float(grid["L_min"][0]), float(grid["L_max"][0])
    # CONTAINED (door completes): never below retracted, never above extended...
    assert L_ret <= lmin <= L_ret + tol, f"L_min {lmin} must be inside [retracted, +tol]"
    assert L_ext - tol <= lmax <= L_ext, f"L_max {lmax} must be inside [-tol, extended]"
    opt = optimize_actuator(W, H, 1.2, 0.55, length_window=(L_ret, L_ext),
                            length_exact=True, stroke_ratio_max=3.0, roof_clearance=0.0)
    assert opt["feasible"]
    # optimizer fills the stroke and stays inside it (door reaches both ends)
    assert L_ret - 1e-3 <= opt["L_min"] <= L_ret + 5e-3
    assert L_ext - 5e-3 <= opt["L_max"] <= L_ext + 1e-3


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


def _all_markdown(at):
    """Concatenate every markdown/caption string the run emitted."""
    return " ".join(str(m.value) for m in at.markdown)


def _pdf_text(pdf):
    """Concatenate the text-show operators from a (compressed) fpdf2 PDF, so tests
    can assert on the sheet's actual content."""
    import re
    import zlib
    data = bytes(pdf)
    shows = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL):
        try:
            txt = zlib.decompress(m.group(1)).decode("latin-1", "replace")
            shows += re.findall(r"\((.*?)\)\s*Tj", txt)
        except Exception:
            pass
    return " | ".join(shows)


def _pdf_image_count(pdf):
    """How many embedded images (the diagram + 2 curves) the PDF contains."""
    import re
    return len(re.findall(rb"/Subtype\s*/Image", bytes(pdf)))


def test_sensitivity_strip_shows_force_relative_to_current():
    """The within-range strip colors each spot by the peak force THERE as a percent
    of the current design's force: centered on 100% (white dot = current), with
    higher-force (worse) spots >100% and lower-force (better) spots <100%."""
    import numpy as np
    import sensitivity_panel as sp
    bounds = {"a": (0.05, 1.2), "b": (0.05, 2.5), "d": (0.0, 1.0), "f": (0.0, 2.5)}
    a, b, d, f = 0.6, 1.8, 0.1, 0.4
    _bar, strip, caption = sp.build_sensitivity_figures(a, b, d, f, 1.2, 0.55, bounds)
    heat = strip.data[0]                       # the diverging Heatmap trace
    assert heat.zmin <= 100.0 <= heat.zmax, "100% (current) must be within the color range"
    # White (#f7f7f7) sits exactly at the 100% fraction of [zmin, zmax], so blue is
    # strictly below 100% and red strictly above — the key can't show phantom blue.
    wpos = (100.0 - heat.zmin) / (heat.zmax - heat.zmin)
    white = [c for pos_, c in heat.colorscale if c.lower() == "#f7f7f7"]
    white_pos = [pos_ for pos_, c in heat.colorscale if c.lower() == "#f7f7f7"]
    assert white, "the scale must have a white (100%) point"
    assert min(abs(p - wpos) for p in white_pos) < 1e-2, "white must sit at the 100% mark"
    z = np.array(heat.z, dtype=float)
    finite = z[np.isfinite(z)]
    # This design is not optimal, so some spots are better (<100%) and some worse.
    assert (finite < 100).any() and (finite > 100).any()
    assert "% of now" in caption and "200%" in caption
    assert "over-center" in caption, "caption must spell out what makes a spot black"


def test_blackout_sentence_is_view_specific():
    """The 'why is it black' sentence lists only the rules that apply in each view:
    stroke ratio for Designer/Browse, the cylinder-length window for Reverse; roof and
    over-center in both."""
    from sensitivity_panel import _blackout_sentence, _capacity_note
    designer = _blackout_sentence(1.8, 2.44, 2.59, None)
    assert "over-center" in designer and "roof" in designer
    assert "stroke ratio" in designer and "cylinder longer" not in designer
    reverse = _blackout_sentence(None, 2.44, 2.59, (1.4, 2.0))
    assert "over-center" in reverse and "roof" in reverse
    # Reverse says the geometry needs a length the cylinder can't reach, not "stroke ratio".
    assert "extended length" in reverse and "closed length" in reverse
    assert "stroke ratio" not in reverse
    # The capacity note (lower force = more mass) is Reverse-only.
    assert "wall mass" in _capacity_note((1.4, 2.0)) and _capacity_note(None) == ""


def test_peak_force_flags_over_center_as_impossible():
    """Over-center geometries (the cylinder line crosses the hinge, force diverges)
    return NaN, not a masked finite value; buildable ones stay finite and clipped."""
    import numpy as np
    from wall import peak_force
    assert np.isnan(peak_force(0.05, 0.1, 0.9, 2.5, 1.2, 0.55)), "over-center must be NaN"
    assert np.isfinite(peak_force(0.6, 1.8, 0.1, 0.4, 1.2, 0.55)), "buildable stays finite"


def test_sensitivity_strip_paints_over_center_black():
    """When a variable's range contains over-center geometries, the strip carries a
    black-mask heatmap (data[1]) with cells there — so impossible spots read as
    black, not as a misleading low-force (blue) gap."""
    import numpy as np
    import sensitivity_panel as sp
    # Wide ranges so each variable's sweep passes through an over-center region.
    bounds = {"a": (0.05, 1.219), "b": (0.05, 2.9), "d": (0.0, 1.0), "f": (0.0, 2.9)}
    _bar, strip, _cap = sp.build_sensitivity_figures(
        0.6, 1.8, 0.1, 0.4, 1.2, 0.55, bounds)
    black = np.array(strip.data[1].z, dtype=float)     # the black-mask heatmap
    assert np.isfinite(black).any(), "impossible cells should be marked for the black layer"


def test_peak_force_feasible_flags_rule_violations():
    """peak_force_feasible reports (peak, L_max, feasible): a buildable geometry with
    no rules is feasible and reports a finite extended length; a too-tight stroke ratio
    makes it infeasible; over-center is (NaN, NaN, False)."""
    import numpy as np
    from wall import peak_force_feasible
    peak, l_max, feas = peak_force_feasible(0.6, 1.8, 0.1, 0.4, 1.2, 0.55)
    assert np.isfinite(peak) and feas
    assert np.isfinite(l_max) and l_max > 0, "extended length must be finite and positive"
    _, _, tight = peak_force_feasible(0.6, 1.8, 0.1, 0.4, 1.2, 0.55, stroke_max=1.05)
    assert not tight, "stroke ratio 1.63 must fail a 1.05 cap"
    p3, l3, feas3 = peak_force_feasible(0.05, 0.1, 0.9, 2.5, 1.2, 0.55)
    assert np.isnan(p3) and np.isnan(l3) and not feas3


def test_sensitivity_colors_by_force_with_no_color_by_toggle():
    """The sensitivity colors by peak force only — there is no 'Color by' (force /
    cylinder length) toggle, and the charts report force in N/kg."""
    import sensitivity_panel as sp
    bounds = {"a": (0.05, 1.2), "b": (0.05, 2.5), "d": (0.0, 1.0), "f": (0.0, 2.5)}
    a, b, d, f = 0.6, 1.8, 0.1, 0.4
    bar, strip, cap = sp.build_sensitivity_figures(a, b, d, f, 1.2, 0.55, bounds)
    assert "N/kg" in bar.layout.xaxis.title.text
    assert "peak force" in cap and "cylinder length" not in cap
    # The removed toggle must not be in the app.
    at = fresh_app()
    assert not [r for r in at.radio if r.key == "sens_metric"], "no color-by toggle"


def test_sensitivity_hover_shows_force_not_percent():
    """Hovering the strip reports the actual peak force (N/kg, per cylinder) via
    customdata, not the % used for the color."""
    import numpy as np
    import sensitivity_panel as sp
    bounds = {"a": (0.05, 1.2), "b": (0.05, 2.5), "d": (0.0, 1.0), "f": (0.0, 2.5)}
    _bar, strip, _c = sp.build_sensitivity_figures(0.6, 1.8, 0.1, 0.4, 1.2, 0.55,
                                                   bounds, n_cyl=2)
    hm = strip.data[0]
    assert "N/kg" in hm.hovertemplate and "customdata[1]" in hm.hovertemplate
    cd2 = np.array(hm.customdata)
    assert cd2.shape[-1] == 2, "customdata carries [value, force]"
    # force is per cylinder: half the whole-wall force at n_cyl=2
    _b1, s1, _c1 = sp.build_sensitivity_figures(0.6, 1.8, 0.1, 0.4, 1.2, 0.55, bounds)
    cd1 = np.array(s1.data[0].customdata)
    fin = np.isfinite(cd1[..., 1]) & np.isfinite(cd2[..., 1])
    assert np.allclose(cd2[..., 1][fin], cd1[..., 1][fin] / 2, rtol=1e-6)


def test_interaction_matrix_has_all_six_pairs():
    """The PDF interaction matrix is a 2x3 of all six variable pairs: 6 force
    heatmaps + 6 black-mask heatmaps + 6 current-design dots, on one shared scale."""
    from sensitivity_panel import build_interaction_matrix
    bounds = {"a": (0.05, 1.219), "b": (0.05, 2.59), "d": (0.0, 1.0), "f": (0.0, 2.59)}
    fig = build_interaction_matrix(0.6, 1.8, 0.1, 0.4, 1.2, 0.55, bounds, res=15,
                                   stroke_max=1.8, roof_clearance=0.0,
                                   width=2.44, height=2.59)
    heatmaps = [t for t in fig.data if t.type == "heatmap"]
    scatters = [t for t in fig.data if t.type == "scatter"]
    assert len(heatmaps) == 12, "6 force + 6 black-mask heatmaps"
    assert len(scatters) == 6, "one current-design dot per pair"
    assert fig.layout.coloraxis.cmin is not None, "one shared colour scale"


def test_sensitivity_strip_blacks_out_rule_violations():
    """Passing the optimizer's rules (stroke ratio, roof, container) blacks out MORE
    of the strip than over-center alone — the extra cells are the rule-breaking spots
    that otherwise showed as misleading blue at the optimum."""
    import numpy as np
    import sensitivity_panel as sp
    bounds = {"a": (0.05, 1.219), "b": (0.05, 2.9), "d": (0.0, 1.0), "f": (0.0, 2.9)}
    _b1, s_norule, _c1 = sp.build_sensitivity_figures(0.6, 1.8, 0.1, 0.4, 1.2, 0.55, bounds)
    _b2, s_rule, _c2 = sp.build_sensitivity_figures(
        0.6, 1.8, 0.1, 0.4, 1.2, 0.55, bounds,
        stroke_max=1.2, roof_clearance=0.0, width=2.44, height=2.59)
    black_no = int(np.isfinite(np.array(s_norule.data[1].z, dtype=float)).sum())
    black_yes = int(np.isfinite(np.array(s_rule.data[1].z, dtype=float)).sum())
    assert black_yes > black_no, "stroke/roof rules should black out extra cells"


def test_pair_grid_shapes_and_feasibility():
    """The 2-D interaction grid sweeps two variables (others fixed) and returns a
    res x res peak/feasible grid; a tighter stroke cap rejects at least as many cells."""
    import numpy as np
    from sensitivity_panel import _pair_grid
    feas = (("stroke_max", 1.8), ("roof_clearance", 0.0), ("width", 2.44),
            ("height", 2.59), ("length_window", None))
    v1, v2, peak, ok = _pair_grid("b", "d", 0.6, 1.8, 0.1, 0.4, 1.2, 0.55,
                                  (0.05, 2.5), (0.0, 1.0), 21, feas)
    assert v1.shape == (21,) and v2.shape == (21,)
    assert peak.shape == (21, 21) and ok.shape == (21, 21)
    assert np.isfinite(peak[ok]).all(), "feasible cells carry a finite peak force"
    assert ok.any() and not ok.all(), "some (b,d) cells feasible, some rejected"
    tight = (("stroke_max", 1.2),) + feas[1:]
    _, _, _, ok2 = _pair_grid("b", "d", 0.6, 1.8, 0.1, 0.4, 1.2, 0.55,
                              (0.05, 2.5), (0.0, 1.0), 21, tight)
    assert ok2.sum() <= ok.sum(), "a tighter stroke cap can't add feasible cells"


def test_interaction_map_snaps_current_to_a_feasible_cell():
    """The 2-D grid snaps a sample onto the EXACT current value of each swept
    variable, so the dot's own cell is the real design — feasible when the design is,
    even if it sits right on a constraint boundary (else the dot lands on a black
    cell whose center is a neighbouring grid value that just breaks a rule)."""
    import numpy as np
    from sensitivity_panel import _pair_grid
    from wall import peak_force_feasible
    a, b, d, f = 1.219, 1.063, 0.205, 2.591          # optimum: right on the 1.8 stroke cap
    rules = dict(stroke_max=1.8, roof_clearance=0.0, width=2.438, height=2.591)
    assert peak_force_feasible(a, b, d, f, 1.2, 0.55, **rules)[2], "design must be feasible"
    feas = (("stroke_max", 1.8), ("roof_clearance", 0.0), ("width", 2.438),
            ("height", 2.591), ("length_window", None))
    vals1, vals2, _peak, okg = _pair_grid("a", "b", a, b, d, f, 1.2, 0.55,
                                           (0.05, 1.219), (0.05, 2.591), 51, feas)
    i1 = int(np.argmin(np.abs(vals1 - a)))
    i2 = int(np.argmin(np.abs(vals2 - b)))
    assert vals1[i1] == a and vals2[i2] == b, "a sample must land exactly on the current value"
    assert okg[i2, i1], "the dot's own cell must be feasible for a feasible design"


def test_designer_interaction_map_renders():
    """The Designer's 2-D interaction map has two letter dropdowns; picking the SAME
    variable in both shows a hint (no error), and two different ones render the map."""
    at = fresh_app()
    keys = {s.key for s in at.selectbox}
    assert "interact_v1" in keys and "interact_v2" in keys, "two dropdowns expected"
    # same variable in both must not error
    at.session_state["interact_v1"] = "b"
    at.session_state["interact_v2"] = "b"
    at.run()
    assert not at.exception, at.exception
    assert any("different" in str(i.value) for i in at.info), "expected a 'pick two different' hint"
    # two different variables -> the map renders cleanly
    at.session_state["interact_v2"] = "d"
    at.run()
    assert not at.exception, at.exception


def test_browse_inspector_has_shared_panels():
    """The Browse inspector carries the Designer's cylinder-sizing and sensitivity
    panels plus a PDF export, all wired through the shared helpers."""
    import browse
    browse.TABLE_RES = 12
    at = AppTest.from_file(APP_PATH, default_timeout=120)
    at.run()
    at.session_state["view"] = "Browse configurations"
    at.run()
    assert not at.exception, at.exception
    md = _all_markdown(at)
    assert "Cylinder sizing" in md, "bore & pressure card missing from Browse"
    assert "Sensitivity" in md, "sensitivity panel missing from Browse"
    assert "Interaction map" in md, "2-D interaction map missing from Browse"
    assert any(s.key == "interact_v1" for s in at.selectbox), "interaction dropdowns missing"
    assert any(b.key == "browse_gen" for b in at.button), "Browse PDF export missing"


def test_reverse_shows_sensitivity_and_pdf_when_feasible():
    """For a feasible cylinder, the Reverse view renders the sensitivity panel and
    a PDF export whose sheet is accurate: it reports BOTH the safe and absolute max
    wall mass, is titled as a sizing report, and — since Reverse has no bore section
    and no stroke-ratio cap — never says 'bore above' or '(over limit)'."""
    import browse
    browse.TABLE_RES = 12
    at = AppTest.from_file(APP_PATH, default_timeout=180)
    at.run()
    at.session_state["view"] = "Size from a cylinder"
    at.session_state["units"] = "Metric"
    at.session_state["rv_ret"] = 0.4        # wide window (0.4-2.9 m) so a
    at.session_state["rv_stroke"] = 2.5     #   geometry in the tiny grid fits
    at.run()
    assert not at.exception, at.exception
    # a, b, d, f shown as large metrics (like the Designer), not just buried in text
    mlabels = [m.label or "" for m in at.metric]
    for v in ("a — base", "b — attach", "d — bracket", "f — base"):
        assert any(v in x for x in mlabels), f"Reverse should show {v} as a metric: {mlabels}"
    md = _all_markdown(at)
    assert "Sensitivity" in md, "sensitivity panel missing from Reverse"
    assert "Interaction map" in md, "2-D interaction map missing from Reverse"
    assert any(s.key == "interact_v1" for s in at.selectbox), "interaction dropdowns missing"
    btn = next(b for b in at.button if b.key == "reverse_gen")
    btn.click().run()
    assert not at.exception, at.exception
    pdf = at.session_state["reverse_pdf"]
    assert bytes(pdf[:4]) == b"%PDF"
    text = _pdf_text(pdf)
    assert "Cylinder Sizing Report" in text
    assert "Safe max wall mass" in text and "Absolute max wall mass" in text
    assert "Cylinder push force" in text and "Cylinder length window" in text
    # every cylinder input is recorded — including bore & rod (default is bore+pressure)
    assert "Cylinder bore" in text and "Rod diameter" in text, \
        "the sizing PDF must list the bore & rod inputs"
    assert "over limit" not in text, "Reverse has no stroke-ratio cap to be over"
    assert "bore above" not in text, "Reverse has no bore section"
    assert "Sensitivity" in text, "sensitivity charts missing from the Reverse PDF"
    # Side view + force + length curves + the two sensitivity charts.
    assert _pdf_image_count(pdf) == 5, "diagram, two curves and two sensitivity charts"


@pytest.mark.parametrize("view,btn_key,pdf_key,n_imgs", [
    # Designer adds the 6-pair interaction matrix (6 figures); Browse doesn't (5).
    ("Designer", "design_gen", "design_pdf", 6),
    ("Browse configurations", "browse_gen", "browse_pdf", 5),
])
def test_pdf_export_generates_pdf_bytes(view, btn_key, pdf_key, n_imgs):
    """Clicking Generate PDF routes through the shared pdf_export and produces real
    PDF bytes with the diagrams embedded, in each view that offers it."""
    import browse
    browse.TABLE_RES = 12
    at = AppTest.from_file(APP_PATH, default_timeout=120)
    at.run()
    if view != "Designer":
        at.session_state["view"] = view
        at.run()
    assert not at.exception, at.exception
    btn = next(b for b in at.button if b.key == btn_key)
    btn.click().run()
    assert not at.exception, at.exception
    assert pdf_key in at.session_state, f"{view}: no PDF produced"
    pdf = at.session_state[pdf_key]
    assert pdf and bytes(pdf[:4]) == b"%PDF", f"{view}: not a PDF"
    # Side view + force + length curves + two sensitivity charts (+ interaction matrix
    # in the Designer).
    assert _pdf_image_count(pdf) == n_imgs, f"{view}: expected {n_imgs} figures"
