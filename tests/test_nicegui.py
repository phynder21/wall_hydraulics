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


def test_stroke_ok_flag_tracks_limit():
    loose = na.summary_metrics(**GEOM, stroke_ratio=3.0)
    tight = na.summary_metrics(**GEOM, stroke_ratio=1.0)
    assert loose["ok"] is True
    assert tight["ok"] is False


def test_default_state_is_within_slider_ranges():
    """Every default value sits inside the fixed slider extents the UI uses."""
    s = na.DEFAULT_STATE
    assert 0.05 <= s["a"] <= na.WIDTH / 2
    assert 0.05 <= s["b"] <= na.HEIGHT_MAX
    assert 0.0 <= s["d"] <= 1.0
    assert 0.0 <= s["f"] <= na.HEIGHT_MAX
    assert 0.0 <= s["theta_deg"] <= 90.0
