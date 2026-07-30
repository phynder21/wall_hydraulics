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
    """Peak |piston force| (N/kg) over the 0-90 deg swing for a BUILDABLE geometry.

    Returns NaN when the cylinder goes **over-center** anywhere in the swing — its
    line of action crosses the hinge, sin(beta - phi) changes sign, and the required
    force diverges. Such a geometry is physically impossible, so it must not report a
    finite force (the same over-center test the optimizer uses, see optimize.py).

    For a buildable geometry the force stays bounded; each sample is *clipped* to
    `cap` (not dropped) so a near-over-center spike can't dominate, yet moving toward
    the boundary still reads as the force RISING rather than a spurious dip."""
    theta = np.linspace(0.0, np.pi / 2, n_theta)
    c, s = np.cos(theta), np.sin(theta)
    x_att = b * c - d * s
    z_att = b * s + d * c
    m_arm = np.sin(np.arctan2(z_att, x_att) - np.arctan2(z_att - f, x_att + a))
    if m_arm.min() < 0.0 < m_arm.max():          # sign flip -> over-center -> impossible
        return float("nan")
    with np.errstate(divide="ignore", invalid="ignore"):
        F = np.abs(compute_F_piston(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg))
    F = F[np.isfinite(F)]
    return float(np.minimum(F, cap).max()) if F.size else float("nan")


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


def peak_force_feasible(a, b, d, f, x_cg=1.2, z_cg=0.55, n_theta=200, cap=50.0,
                        stroke_max=None, roof_clearance=0.0, width=None, height=None,
                        length_window=None):
    """(peak, L_max, feasible) for one geometry. `peak` is peak_force and `L_max` the
    extended (longest) cylinder length over the swing — the two metrics the sensitivity
    panel can color by; both are NaN if over-center. `feasible` is False if over-center
    OR any provided rule is broken over the swing:

      * stroke ratio L_max / L_min > stroke_max,
      * cylinder length falls outside length_window = (lo, hi),
      * the attachment rises above the ceiling (height - roof_clearance) while inside
        the container footprint [-width, 0].

    These mirror the optimizer's constraints, so a caller (the sensitivity strip) can
    black out exactly the geometries the optimizer would reject — not just the
    physically impossible over-center ones."""
    theta = np.linspace(0.0, np.pi / 2, n_theta)
    c, s = np.cos(theta), np.sin(theta)
    x_att = b * c - d * s
    z_att = b * s + d * c
    L = np.sqrt((x_att + a) ** 2 + (z_att - f) ** 2)
    L_min, L_max = float(L.min()), float(L.max())
    m_arm = np.sin(np.arctan2(z_att, x_att) - np.arctan2(z_att - f, x_att + a))
    if m_arm.min() < 0.0 < m_arm.max():          # over-center -> impossible
        return float("nan"), float("nan"), False
    with np.errstate(divide="ignore", invalid="ignore"):
        F = np.abs(compute_F_piston(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg))
    F = F[np.isfinite(F)]
    peak = float(np.minimum(F, cap).max()) if F.size else float("nan")
    if not np.isfinite(peak):
        return peak, L_max, False

    feasible = True
    if stroke_max is not None and L_min > 0.0 and L_max / L_min > stroke_max + 1e-3:
        feasible = False
    if length_window is not None:
        lo, hi = length_window
        if L_min < lo - 1e-3 or L_max > hi + 1e-3:
            feasible = False
    if width is not None and height is not None:
        inside = (x_att >= -width) & (x_att <= 0.0)
        overshoot = np.where(inside, z_att - (height - roof_clearance), 0.0)
        if float(np.maximum(overshoot, 0.0).max()) > 1e-3:
            feasible = False
    return peak, L_max, feasible


def force_feasibility_profiles(a, b, d, f, x_cg, z_cg, bounds, n=41, stroke_max=None,
                               roof_clearance=0.0, width=None, height=None,
                               length_window=None):
    """Like force_profiles, but each variable's sweep also carries the extended
    cylinder length and a feasibility mask (the optimizer's rules, see
    peak_force_feasible). Returns {var: (values, forces, lengths, feasible)} where
    forces/lengths are NaN at over-center samples and feasible is False wherever a
    rule is broken. `lengths` lets the sensitivity panel color by cylinder length
    instead of force."""
    base = dict(a=a, b=b, d=d, f=f)
    feas = dict(stroke_max=stroke_max, roof_clearance=roof_clearance, width=width,
                height=height, length_window=length_window)
    out = {}
    for v in ("a", "b", "d", "f"):
        lo, hi = bounds[v]
        vals = np.linspace(lo, hi, n)
        triples = [peak_force_feasible(**dict(base, **{v: float(x)}),
                                       x_cg=x_cg, z_cg=z_cg, **feas) for x in vals]
        forces = np.array([p for p, _, _ in triples])
        lengths = np.array([lm for _, lm, _ in triples])
        ok = np.array([bool(fe) for _, _, fe in triples])
        out[v] = (vals, forces, lengths, ok)
    return out


if __name__ == "__main__":
    print(compute_F_piston(math.radians(45)))
