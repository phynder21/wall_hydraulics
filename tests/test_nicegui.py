"""Tests for the NiceGUI front-end's pure builders (nicegui_app.py).

Skipped automatically where NiceGUI isn't installed, so this never affects the
Streamlit deploy or its test run. Only the framework-free figure/metric builders
are tested — the UI wiring is exercised by running the app."""
import numpy as np
import pytest

pytest.importorskip("nicegui")

import nicegui_app as na
from wall import compute_F_piston, compute_cylinder_length
from optimize import CONTAINER_PRESETS

GEOM = dict(a=0.6, b=1.8, d=0.1, f=0.4, x_cg=1.2, z_cg=0.55, theta_deg=45.0)


def test_builders_return_figures():
    W, H = CONTAINER_PRESETS["standard"]
    assert na.diagram_figure(0.6, 1.8, 0.1, 0.4, 1.2, 0.55, 45.0, W, H, 0.05).data
    assert na.force_figure(0.6, 1.8, 0.1, 0.4, 1.2, 0.55, 45.0).data
    assert na.length_figure(0.6, 1.8, 0.1, 0.4, 45.0, 1.8).data


def test_metrics_match_shared_physics():
    """The NiceGUI metrics come from the same wall.py used by Streamlit."""
    m = na.summary_metrics(**GEOM, stroke_ratio=1.8)
    # force at the current angle equals a direct wall.py call
    want_here = float(compute_F_piston(np.radians(GEOM["theta_deg"]),
                                       a=GEOM["a"], b=GEOM["b"], d=GEOM["d"],
                                       f=GEOM["f"], x_cg=GEOM["x_cg"], z_cg=GEOM["z_cg"]))
    assert m["here"] == pytest.approx(want_here, abs=1e-9)
    # stroke equals L_max - L_min from wall.py over the swing
    L = compute_cylinder_length(np.linspace(0, np.pi / 2, 400),
                                a=GEOM["a"], b=GEOM["b"], d=GEOM["d"], f=GEOM["f"])
    assert m["stroke"] == pytest.approx(float(L.max() - L.min()), abs=1e-9)
    assert m["ratio"] == pytest.approx(float(L.max() / L.min()), abs=1e-9)


def test_summary_reports_lengths_and_singularity():
    m = na.summary_metrics(**GEOM, stroke_ratio=1.8)
    assert m["L_max"] >= m["L_min"] > 0
    assert m["singular"] is False               # a sane geometry isn't singular
    # a near-singular geometry (force diverges) is flagged
    ms = na.summary_metrics(a=0.2, b=0.3, d=0.3, f=0.3, x_cg=1.2, z_cg=0.55,
                            theta_deg=45.0, stroke_ratio=1.8)
    assert ms["singular"] is True


def test_stroke_ok_flag_tracks_limit():
    loose = na.summary_metrics(**GEOM, stroke_ratio=3.0)
    tight = na.summary_metrics(**GEOM, stroke_ratio=1.0)
    assert loose["ok"] is True
    assert tight["ok"] is False


def test_disp_units_and_precision():
    U, step, fmt, ulabel, dp = na.disp("meters", False)
    assert (U, ulabel, dp) == (1.0, "m", 2)
    Ui, _, _, uli, _ = na.disp("inches", False)
    assert uli == "in" and Ui == pytest.approx(39.3700787)
    # fine precision tightens the step and rounding in both unit systems
    assert na.disp("meters", True)[1] < na.disp("meters", False)[1]
    assert na.disp("meters", True)[4] == 3


def test_length_figure_scales_with_units():
    L_m = na.length_figure(0.6, 1.8, 0.1, 0.4, 45.0, 1.8, u=1.0, ulabel="m")
    L_in = na.length_figure(0.6, 1.8, 0.1, 0.4, 45.0, 1.8, u=39.3700787, ulabel="in")
    ym = float(np.nanmax(L_m.data[0].y))
    yi = float(np.nanmax(L_in.data[0].y))
    assert yi == pytest.approx(ym * 39.3700787, rel=1e-6)
    assert "in" in L_in.layout.yaxis.title.text


def test_diagram_scales_with_units():
    W, H = CONTAINER_PRESETS["standard"]
    d_in = na.diagram_figure(0.6, 1.8, 0.1, 0.4, 1.2, 0.55, 45.0, W, H, 0.0,
                             u=39.3700787, ulabel="in")
    assert "in" in d_in.layout.xaxis.title.text


def test_advance_angle_bounces_and_stays_in_range():
    assert na.advance_angle(89.0, 1) == (90.0, -1)
    assert na.advance_angle(1.0, -1) == (0.0, 1)
    a, d = 45.0, 1
    for _ in range(400):
        a, d = na.advance_angle(a, d)
        assert 0.0 <= a <= 90.0


def test_overlays_add_traces():
    design = dict(a=0.4, b=2.3, d=0.3, f=0.8, x_cg=1.2, z_cg=0.55)
    base = na.force_figure(0.6, 1.8, 0.1, 0.4, 1.2, 0.55, 45.0)
    over = na.force_figure(0.6, 1.8, 0.1, 0.4, 1.2, 0.55, 45.0,
                           overlays=[("A", design, "green")])
    assert len(over.data) == len(base.data) + 1
    lbase = na.length_figure(0.6, 1.8, 0.1, 0.4, 45.0, 1.8)
    lover = na.length_figure(0.6, 1.8, 0.1, 0.4, 45.0, 1.8,
                             overlays=[("A", design, "green")])
    assert len(lover.data) == len(lbase.data) + 1


def test_browse_table_and_search():
    """The Browse view builds and queries the shared lookup table."""
    na.TABLE_RES = 12          # tiny grid for a fast test
    na._TABLE["data"] = None
    import lookup
    table = na.get_table()
    assert table["a"].size > 0
    W, H = CONTAINER_PRESETS["standard"]
    res = lookup.search(table, H, 1.2, 0.55, stroke_max=1.8)
    assert res["peak_force"].size > 0


def test_default_state_is_within_slider_ranges():
    """Every default value sits inside the fixed slider extents the UI uses."""
    s = na.DEFAULT_STATE
    assert 0.05 <= s["a"] <= na.WIDTH / 2
    assert 0.05 <= s["b"] <= na.HEIGHT_MAX
    assert 0.0 <= s["d"] <= 1.0
    assert 0.0 <= s["f"] <= na.HEIGHT_MAX
    assert 0.0 <= s["theta_deg"] <= 90.0
