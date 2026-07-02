"""Precompute a lookup table of actuator geometries for instant browsing.

Instead of running the optimizer on demand (~20 s), we sweep the 4-D geometry
grid (a, b, d, f) once and store, per geometry, only the numbers that depend on
geometry *alone*: the stroke ratio, retracted/extended length, the over-center
moment-arm margin, and how high the attachment reaches toward the roof. The
piston force is deliberately NOT stored: because

    F(theta) = (z_cg*sin(theta) - x_cg*cos(theta)) * G(theta),   G = g / D(theta)

is a fixed geometry curve `G` scaled by a query-side cg factor, the force for any
center of gravity is reconstructed at query time for just the filtered survivors
(see lookup.py). So the table is small and every constraint/filter is a plain
column lookup.

Impossible or useless geometries are pruned at build time: any that over-center
(moment arm crosses zero) or fall short of the MIN_MOMENT_ARM margin, and any
whose stroke ratio exceeds the largest limit the app allows (3.0).

Run `python3 lookup_build.py --res 40` to (re)generate `lookup_table.npz`.
"""
import argparse

import numpy as np

from wall import g
from optimize import MIN_MOMENT_ARM, CONTAINER_PRESETS

# The grid spans the full physical design space, sized to the *tallest* container
# (High-Cube) so one table serves both — Standard is just a b,f <= 2.591 filter.
CONTAINER_WIDTH = CONTAINER_PRESETS["highcube"][0]   # 2.438 m (same for both)
HEIGHT_MAX = CONTAINER_PRESETS["highcube"][1]        # 2.896 m

# Geometry-only feasibility gates applied at build time (query-independent).
STROKE_RATIO_CAP = 3.0        # largest stroke ratio the app's slider allows
BUILD_THETA = 181             # theta samples for accurate build metrics (every 0.5 deg)
# The force-gain curve G(theta) = g/D(theta) stored per geometry, so a query
# reconstructs peak force by a plain multiply-and-max instead of recomputing
# trig for every row. 46 samples (every 2 deg) is ample for ranking; the selected
# design's curve is always redrawn exactly from wall.py.
STORE_THETA = 46

VAR_RANGES = {
    "a": (0.05, CONTAINER_WIDTH / 2),   # hinge to cylinder base, along floor
    "b": (0.05, HEIGHT_MAX),            # hinge to attachment, along wall
    "d": (0.00, 1.00),                  # wall to attachment, perpendicular
    "f": (0.00, HEIGHT_MAX),            # cylinder base height above floor
}


def geometry_metrics(a, b, d, f, theta):
    """Geometry-only metrics for arrays of geometries over the theta sweep.

    a, b, d, f are 1-D arrays of length N (broadcast against theta of length T).
    Returns a dict of length-N arrays. No dependence on the center of gravity.
    """
    a = a[:, None]; b = b[:, None]; d = d[:, None]; f = f[:, None]   # (N,1)
    ct = np.cos(theta)[None, :]; st = np.sin(theta)[None, :]          # (1,T)

    x_att = b * ct - d * st                    # (N,T)
    z_att = b * st + d * ct
    r_att = np.sqrt(b**2 + d**2)               # (N,1)

    # Cylinder length -> stroke ratio.
    L = np.sqrt((x_att + a) ** 2 + (z_att - f) ** 2)
    L_min = L.min(axis=1); L_max = L.max(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        stroke_ratio = np.where(L_min > 0, L_max / L_min, np.inf)

    # Over-center: sign of the moment arm sin(beta - phi) across the swing.
    beta = np.arctan2(z_att, x_att)
    phi = np.arctan2(z_att - f, x_att + a)
    m_arm = np.sin(beta - phi)                 # (N,T)
    crosses = (m_arm.min(axis=1) < 0.0) & (m_arm.max(axis=1) > 0.0)
    closest = np.abs(m_arm).min(axis=1)
    moment_arm = np.where(crosses, -closest, closest)   # signed; <0 over-centers

    # Roof: highest the attachment reaches while inside the container footprint
    # (-W <= x_att <= 0). If it never enters the footprint, it can never breach
    # the roof -> sentinel -1.0 (always <= H - clearance).
    inside = (x_att >= -CONTAINER_WIDTH) & (x_att <= 0.0)
    z_inside = np.where(inside, z_att, -np.inf)
    max_ceiling = z_inside.max(axis=1)
    max_ceiling = np.where(np.isfinite(max_ceiling), max_ceiling, -1.0)

    return {"stroke_ratio": stroke_ratio, "L_min": L_min, "L_max": L_max,
            "moment_arm": moment_arm, "max_ceiling": max_ceiling}


def force_gain(a, b, d, f, theta):
    """G(theta) = g / D(theta) per geometry, where D = r_att*sin(beta - phi).

    Force for any cg is F(theta) = (z_cg*sin(theta) - x_cg*cos(theta)) * G(theta).
    """
    a = a[:, None]; b = b[:, None]; d = d[:, None]; f = f[:, None]
    ct = np.cos(theta)[None, :]; st = np.sin(theta)[None, :]
    x_att = b * ct - d * st
    z_att = b * st + d * ct
    r_att = np.sqrt(b**2 + d**2)
    beta = np.arctan2(z_att, x_att)
    phi = np.arctan2(z_att - f, x_att + a)
    with np.errstate(divide="ignore", invalid="ignore"):
        return g / (r_att * np.sin(beta - phi))


def build_table(res, chunk=20000, theta_n=BUILD_THETA):
    """Sweep the res^4 geometry grid, compute metrics, prune, return columns."""
    axes = {v: np.linspace(lo, hi, res) for v, (lo, hi) in VAR_RANGES.items()}
    A, B, D, F = np.meshgrid(axes["a"], axes["b"], axes["d"], axes["f"], indexing="ij")
    A = A.ravel(); B = B.ravel(); D = D.ravel(); F = F.ravel()
    theta = np.linspace(0.0, np.pi / 2, theta_n)
    store_theta = np.linspace(0.0, np.pi / 2, STORE_THETA)

    cols = {k: [] for k in ("a", "b", "d", "f", "stroke_ratio", "L_min",
                            "L_max", "moment_arm", "max_ceiling")}
    gcurves = []
    total = A.size
    for start in range(0, total, chunk):
        sl = slice(start, start + chunk)
        with np.errstate(divide="ignore", invalid="ignore"):
            m = geometry_metrics(A[sl], B[sl], D[sl], F[sl], theta)
        # Prune geometry-only-impossible designs: over-center / too-close margin,
        # and stroke ratios no allowed limit could accept.
        keep = (m["moment_arm"] >= MIN_MOMENT_ARM) & (m["stroke_ratio"] <= STROKE_RATIO_CAP)
        keep &= np.isfinite(m["stroke_ratio"])
        cols["a"].append(A[sl][keep]); cols["b"].append(B[sl][keep])
        cols["d"].append(D[sl][keep]); cols["f"].append(F[sl][keep])
        for k in ("stroke_ratio", "L_min", "L_max", "moment_arm", "max_ceiling"):
            cols[k].append(m[k][keep])
        with np.errstate(divide="ignore", invalid="ignore"):
            gcurves.append(force_gain(A[sl][keep], B[sl][keep],
                                      D[sl][keep], F[sl][keep], store_theta))

    table = {k: np.concatenate(v).astype(np.float32) for k, v in cols.items()}
    # float16 halves RAM (~100 MB total) at ~0.05% peak-force error, negligible
    # for ranking; the selected design's curve is redrawn exactly from wall.py.
    table["G"] = np.concatenate(gcurves).astype(np.float16)     # (kept, STORE_THETA)
    table["store_theta"] = store_theta.astype(np.float32)
    return table, total


def main(argv=None):
    p = argparse.ArgumentParser(description="Build the geometry lookup table.")
    p.add_argument("--res", type=int, default=40, help="grid points per dimension")
    p.add_argument("--out", default="lookup_table.npz", help="output .npz path")
    p.add_argument("--chunk", type=int, default=20000)
    args = p.parse_args(argv)

    table, total = build_table(args.res, chunk=args.chunk)
    kept = table["a"].size
    np.savez_compressed(args.out, res=args.res, **table)
    print(f"grid {args.res}^4 = {total:,} geometries -> {kept:,} kept "
          f"({100*kept/total:.1f}%) after pruning")
    print(f"saved {args.out}")
    return table


if __name__ == "__main__":
    main()
