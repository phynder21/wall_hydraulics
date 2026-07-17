import math
import numpy as np

# Geometric parameters, in meters. Looking down the long axis of a shipping
# container; the hinged wall is one of the long sidewalls, swinging down to lie
# flat outside the container.
#
#   a    distance along floor from hinge to cylinder mounting base
#   b    distance along wall from hinge to piston attachment point (body frame)
#   d    distance from wall to piston attachment point (body frame)
#   f    height of cylinder mounting base above the floor
#   x_cg distance along wall from hinge to cg of wall + equipment (body frame)
#   z_cg distance from wall to cg of wall + equipment (body frame)
#   m_cg mass of wall + equipment (use 1.0 for per-unit-mass results)
#
# theta is angle of wall from floor, in radians (0 = lying flat, pi/2 = closed).

g = 9.81  # m/s^2

# Max allowed ratio of extended to retracted cylinder length over the swing.
# Single source of truth shared by the app and the optimizer. Unsure whether
# the right value is 1.8, 1.9, or 2.0 — change it here and it updates everywhere.
STROKE_RATIO_MAX = 1.8


def compute_geometry(theta, a=0.5, b=1.0, d=0.1, f=0.5, x_cg=1.2, z_cg=0.55):
    """World-frame positions of the key points at angle theta."""
    theta = np.asarray(theta, dtype=float)
    x_attachment = b * np.cos(theta) - d * np.sin(theta)
    z_attachment = b * np.sin(theta) + d * np.cos(theta)
    x_cg_world = x_cg * np.cos(theta) - z_cg * np.sin(theta)
    z_cg_world = x_cg * np.sin(theta) + z_cg * np.cos(theta)
    return {
        "attachment": (x_attachment, z_attachment),
        "cg": (x_cg_world, z_cg_world),
        "cylinder_base": (-a, f),
        "wall_axis_at_b": (b * np.cos(theta), b * np.sin(theta)),
        "wall_axis_at_xcg": (x_cg * np.cos(theta), x_cg * np.sin(theta)),
    }


def compute_cylinder_length(theta, a=0.5, b=1.0, d=0.1, f=0.5):
    """Distance between cylinder base (-a, f) and the piston attachment point."""
    theta = np.asarray(theta, dtype=float)
    x_attachment = b * np.cos(theta) - d * np.sin(theta)
    z_attachment = b * np.sin(theta) + d * np.cos(theta)
    return np.sqrt((x_attachment + a) ** 2 + (z_attachment - f) ** 2)


def compute_F_piston(theta, a=0.5, b=1.0, d=0.1, f=0.5,
                     x_cg=1.2, z_cg=0.55, m_cg=1.0):
    """Piston force needed to hold the wall at angle theta. Accepts a scalar
    or numpy array for theta."""
    geom = compute_geometry(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
    x_attachment, z_attachment = geom["attachment"]
    x_cg_world, z_cg_world = geom["cg"]

    r_attachment = np.sqrt(b**2 + d**2)
    beta = np.arctan2(z_attachment, x_attachment)
    r_cg = np.sqrt(x_cg**2 + z_cg**2)
    alpha = np.arctan2(z_cg_world, x_cg_world)
    phi = np.arctan2(z_attachment - f, x_attachment + a)

    torque_gravity = -(m_cg * g * r_cg * np.cos(alpha))
    return torque_gravity / (r_attachment * np.sin(beta - phi))


def peak_force(a, b, d, f, x_cg=1.2, z_cg=0.55, n_theta=200, cap=50.0):
    """Peak |piston force| (N/kg) over the 0-90 deg swing, ignoring near-singular
    samples above `cap` (the same rule the app uses for its Peak-force metric).
    Returns NaN if the geometry is singular across the whole swing."""
    theta = np.linspace(0.0, np.pi / 2, n_theta)
    with np.errstate(divide="ignore", invalid="ignore"):
        F = compute_F_piston(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
    F = F[np.isfinite(F) & (np.abs(F) <= cap)]
    return float(np.max(np.abs(F))) if F.size else float("nan")


def force_profiles(a, b, d, f, x_cg, z_cg, bounds, n=41):
    """For each of a, b, d, f: sweep that variable across bounds[var] = (lo, hi)
    with the other three held at (a, b, d, f) and record the peak force at each
    sample. Returns {var: (values, forces)} as numpy arrays (forces are NaN at
    near-singular samples). This is the raw curve behind both the tornado swing
    and the within-range (local-slope) sensitivity."""
    base = dict(a=a, b=b, d=d, f=f)
    out = {}
    for v in ("a", "b", "d", "f"):
        lo, hi = bounds[v]
        vals = np.linspace(lo, hi, n)
        forces = np.array([peak_force(**dict(base, **{v: float(x)}),
                                      x_cg=x_cg, z_cg=z_cg) for x in vals])
        out[v] = (vals, forces)
    return out


def force_sensitivity(a, b, d, f, x_cg, z_cg, bounds, n=41):
    """One-at-a-time sensitivity of peak force to each geometry variable: how much
    the peak force moves as each of a, b, d, f sweeps its range (others fixed).
    Returns {var: swing} where swing = max - min peak force over the buildable part
    of the sweep. Larger swing = more sensitive to that variable here."""
    swings = {}
    for v, (_vals, forces) in force_profiles(a, b, d, f, x_cg, z_cg, bounds, n).items():
        fin = forces[np.isfinite(forces)]
        swings[v] = float(fin.max() - fin.min()) if fin.size else 0.0
    return swings


if __name__ == "__main__":
    print(compute_F_piston(math.radians(45)))
