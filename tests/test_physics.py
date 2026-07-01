"""Physics validation for wall.py.

The core claim of the whole app is that ``compute_F_piston`` returns the static
piston force that holds the wall at a given angle. These tests pin that down by
checking it against an *independent* derivation of the same quantity (a torque
balance about the hinge), and by confirming the helpers behave sanely at the
boundaries and under degenerate input.
"""
import numpy as np
import pytest

from wall import (
    g,
    compute_F_piston,
    compute_geometry,
    compute_cylinder_length,
)

# A plausible working geometry, reused as a baseline across tests.
BASELINE = dict(a=0.60, b=1.80, d=0.10, f=0.40, x_cg=1.20, z_cg=0.55)


def _independent_force(theta, a, b, d, f, x_cg, z_cg, m_cg=1.0):
    """Piston force from first principles, derived independently of wall.py.

    Torque balance about the hinge: the piston force along the cylinder line
    must cancel the gravity torque of the load. This uses a perpendicular-lever
    (cross-product) formulation rather than the ``sin(beta - phi)`` form in
    ``wall.py``, so agreement between the two is a genuine cross-check.
    """
    th = float(theta)
    x_att = b * np.cos(th) - d * np.sin(th)
    z_att = b * np.sin(th) + d * np.cos(th)
    x_cg_world = x_cg * np.cos(th) - z_cg * np.sin(th)

    # Gravity torque about the hinge (z-component of r x F, with F = (0, -m g)).
    tau_gravity = -m_cg * g * x_cg_world

    # Unit vector along the cylinder, from base (-a, f) to the attachment point.
    ux, uz = x_att + a, z_att - f
    length = np.hypot(ux, uz)
    ux, uz = ux / length, uz / length

    # Perpendicular lever arm of that line about the hinge (z of r_att x u).
    lever = x_att * uz - z_att * ux

    # Force whose piston torque cancels gravity: F * lever + tau_gravity = 0.
    return -tau_gravity / lever


def test_force_matches_independent_torque_balance():
    """Over thousands of random geometries and angles, ``compute_F_piston``
    agrees with the independent torque-balance derivation."""
    rng = np.random.default_rng(1234)
    compared = 0
    for _ in range(8000):
        a = rng.uniform(0.05, 1.22)
        b = rng.uniform(0.05, 2.90)
        d = rng.uniform(0.00, 1.00)
        f = rng.uniform(0.00, 2.90)
        x_cg = rng.uniform(0.00, 2.60)
        z_cg = rng.uniform(0.00, 1.50)
        theta = rng.uniform(0.001, np.pi / 2 - 0.001)

        with np.errstate(all="ignore"):
            got = float(compute_F_piston(theta, a=a, b=b, d=d, f=f,
                                         x_cg=x_cg, z_cg=z_cg))
            want = _independent_force(theta, a, b, d, f, x_cg, z_cg)

        # Skip near-singular samples where both formulations are ill-conditioned.
        if not (np.isfinite(got) and np.isfinite(want)):
            continue
        rel = abs(got - want) / max(abs(want), 1.0)
        assert rel < 1e-6, (
            f"mismatch a={a:.4f} b={b:.4f} d={d:.4f} f={f:.4f} "
            f"theta={theta:.4f}: got {got:.8f}, want {want:.8f} (rel {rel:.2e})")
        compared += 1

    # Sanity: the great majority of random samples are non-singular and compared.
    assert compared > 6000, f"too few finite comparisons: {compared}"


def test_accepts_array_and_matches_scalar():
    """``compute_F_piston`` must accept a theta array and return per-element the
    same values as scalar calls (the app relies on this to plot the curve)."""
    thetas = np.linspace(0.01, np.pi / 2 - 0.01, 64)
    curve = compute_F_piston(thetas, **BASELINE)
    assert curve.shape == thetas.shape
    for i, t in enumerate(thetas):
        scalar = float(compute_F_piston(float(t), **BASELINE))
        assert abs(scalar - curve[i]) < 1e-9


@pytest.mark.parametrize("geom", [
    pytest.param(dict(a=0.05, b=0.05, d=0.0, f=0.0, x_cg=0.0, z_cg=0.0), id="all-minimal"),
    pytest.param(dict(a=1e-9, b=1e-9, d=1e-9, f=1e-9, x_cg=1e-9, z_cg=1e-9), id="near-zero"),
    pytest.param(dict(a=1e6, b=1e6, d=1e6, f=1e6, x_cg=1e6, z_cg=1e6), id="huge"),
    pytest.param(dict(a=0.6, b=1.8, d=0.1, f=0.4, x_cg=0.0, z_cg=0.0), id="cg-at-hinge"),
    pytest.param(dict(a=0.0, b=1.0, d=0.0, f=0.0, x_cg=1.0, z_cg=0.0), id="collinear-ish"),
])
def test_extreme_inputs_do_not_raise(geom):
    """Degenerate geometries may return inf/nan, but must never raise — the app
    masks non-finite samples rather than guarding every call."""
    thetas = np.linspace(0.0, np.pi / 2, 200)
    only_geom = {k: geom[k] for k in ("a", "b", "d", "f")}
    with np.errstate(all="ignore"):
        compute_F_piston(thetas, **geom)
        compute_cylinder_length(thetas, **only_geom)
        compute_geometry(0.5, **geom)


@pytest.mark.parametrize("theta", [0.0, np.pi / 2])
def test_swing_endpoints_evaluate(theta):
    """The exact 0 deg and 90 deg endpoints must evaluate without error."""
    only_geom = {k: BASELINE[k] for k in ("a", "b", "d", "f")}
    with np.errstate(all="ignore"):
        compute_F_piston(theta, **BASELINE)
        compute_cylinder_length(theta, **only_geom)


def test_cg_at_hinge_gives_zero_force():
    """With the center of gravity on the hinge there is no gravity moment, so
    the required piston force is ~0 across the whole swing."""
    thetas = np.linspace(0.05, np.pi / 2 - 0.05, 100)
    geom = {**BASELINE, "x_cg": 0.0, "z_cg": 0.0}
    with np.errstate(all="ignore"):
        force = compute_F_piston(thetas, **geom)
    assert np.nanmax(np.abs(force)) < 1e-9


def test_cylinder_length_is_base_to_attachment_distance():
    """``compute_cylinder_length`` is the Euclidean distance from the cylinder
    base (-a, f) to the moving attachment point."""
    rng = np.random.default_rng(7)
    for _ in range(200):
        a, b, d, f = (rng.uniform(0.05, 1.0), rng.uniform(0.05, 2.5),
                      rng.uniform(0.0, 1.0), rng.uniform(0.0, 2.5))
        th = rng.uniform(0.0, np.pi / 2)
        geom = compute_geometry(th, a=a, b=b, d=d, f=f)
        ax, az = geom["attachment"]
        bx, bz = geom["cylinder_base"]
        expected = np.hypot(float(ax) - float(bx), float(az) - float(bz))
        got = float(compute_cylinder_length(th, a=a, b=b, d=d, f=f))
        assert abs(got - expected) < 1e-12
