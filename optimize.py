"""Find the actuator mounting geometry that minimizes the worst-case piston
force over the full 0-90 deg swing, subject to a hydraulic stroke limit.

The free design variables are the four mounting dimensions (a, b, d, f). The
center of gravity (x_cg, z_cg) and the container size are *fixed inputs* — they
describe the door you are lifting, not something you get to design.

Method (see README / the project notes): this is a constrained min-max problem.
For one candidate geometry we sweep theta across the whole swing and reduce the
force curve to a single number — its peak magnitude. A global, gradient-free
optimizer (scipy's differential_evolution) then searches the geometry space for
the candidate with the smallest peak. The stroke limit (extended length must not
exceed `stroke_ratio_max` times the retracted length) is folded in as a penalty:
violating it adds a steep cost, so the optimizer steers away from it.

Run `python3 optimize.py --help` for the command-line options.
"""

import argparse

import numpy as np
from scipy.optimize import differential_evolution

from wall import STROKE_RATIO_MAX, compute_F_piston, compute_cylinder_length

# External ISO container dimensions (width, height) in meters, matching app.py.
CONTAINER_PRESETS = {
    "standard": (2.438, 2.591),   # Standard 8'6"
    "highcube": (2.438, 2.896),   # High-Cube 9'6"
}

# Large multiplier turning the stroke inequality into a cost the optimizer feels.
# Big enough that the optimum sits essentially on the limit, not measurably over.
STROKE_PENALTY = 1.0e6

# Engineering tolerance for declaring the stroke limit "met" (penalty methods
# leave a tiny residual violation at the optimum).
FEASIBLE_TOL = 1.0e-3


def _metrics(p, theta, x_cg, z_cg, m_cg):
    """Peak |force| and stroke ratio for one geometry p=(a,b,d,f)."""
    a, b, d, f = p
    # Candidates near a singularity divide by ~0; we discard those samples
    # below, so silence the expected warning rather than spam the console.
    with np.errstate(divide="ignore", invalid="ignore"):
        F = compute_F_piston(theta, a=a, b=b, d=d, f=f,
                             x_cg=x_cg, z_cg=z_cg, m_cg=m_cg)
    F = F[np.isfinite(F)]
    peak = float(np.max(np.abs(F))) if F.size else float("inf")

    L = compute_cylinder_length(theta, a=a, b=b, d=d, f=f)
    L_min, L_max = float(L.min()), float(L.max())
    ratio = L_max / L_min if L_min > 0 else float("inf")
    return peak, ratio, L_min, L_max


def optimize_actuator(container_width, container_height, x_cg, z_cg,
                      stroke_ratio_max=STROKE_RATIO_MAX, n_theta=200, m_cg=1.0,
                      seed=0, maxiter=300):
    """Search for the (a, b, d, f) minimizing peak piston force over 0-90 deg.

    Returns a dict with the optimal geometry and the resulting metrics.
    """
    theta = np.linspace(0.0, np.pi / 2, n_theta)

    # Box bounds mirror the slider ranges in app.py.
    bounds = [
        (0.05, container_width / 2),   # a — hinge to cylinder base, along floor
        (0.05, container_height),      # b — hinge to attachment, along wall
        (0.00, 1.00),                  # d — wall to attachment, perpendicular
        (0.00, container_height),      # f — cylinder base height above floor
    ]

    def objective(p):
        peak, ratio, _, _ = _metrics(p, theta, x_cg, z_cg, m_cg)
        penalty = 0.0
        if ratio > stroke_ratio_max:
            penalty = STROKE_PENALTY * (ratio - stroke_ratio_max) ** 2
        return peak + penalty

    result = differential_evolution(
        objective, bounds, seed=seed, maxiter=maxiter,
        tol=1e-8, polish=True,
    )

    a, b, d, f = (float(v) for v in result.x)
    peak, ratio, L_min, L_max = _metrics(result.x, theta, x_cg, z_cg, m_cg)
    return {
        "a": a, "b": b, "d": d, "f": f,
        "peak_force": peak,        # N per kg of wall+equipment mass
        "stroke_ratio": ratio,     # L_max / L_min over the swing
        "L_min": L_min, "L_max": L_max,
        "feasible": ratio <= stroke_ratio_max + FEASIBLE_TOL,
        "stroke_ratio_max": stroke_ratio_max,
        "x_cg": x_cg, "z_cg": z_cg,
        "container_width": container_width,
        "container_height": container_height,
        "success": bool(result.success),
    }


def _build_parser():
    p = argparse.ArgumentParser(
        description="Optimize container-wall actuator geometry for minimum "
                    "peak piston force over the full 0-90 deg swing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--container", choices=sorted(CONTAINER_PRESETS),
                   default="standard",
                   help="ISO container preset (sets width and height).")
    p.add_argument("--width", type=float, default=None,
                   help="Override container width (m).")
    p.add_argument("--height", type=float, default=None,
                   help="Override container height / wall length (m).")
    p.add_argument("--x-cg", type=float, default=1.20,
                   help="Cg distance along wall from hinge (m).")
    p.add_argument("--z-cg", type=float, default=0.55,
                   help="Cg distance perpendicular off the wall (m).")
    p.add_argument("--stroke-ratio", type=float, default=STROKE_RATIO_MAX,
                   help="Max allowed extended/retracted cylinder length ratio.")
    p.add_argument("--grid", type=int, default=200,
                   help="Number of theta samples across the swing.")
    p.add_argument("--mass", type=float, default=1.0,
                   help="Wall+equipment mass (kg); 1.0 gives per-kg force.")
    p.add_argument("--seed", type=int, default=0,
                   help="Random seed for the global optimizer (reproducible).")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)

    width, height = CONTAINER_PRESETS[args.container]
    if args.width is not None:
        width = args.width
    if args.height is not None:
        height = args.height

    res = optimize_actuator(
        container_width=width, container_height=height,
        x_cg=args.x_cg, z_cg=args.z_cg,
        stroke_ratio_max=args.stroke_ratio,
        n_theta=args.grid, m_cg=args.mass, seed=args.seed,
    )

    print("\n=== Optimized actuator geometry ===")
    print(f"  container : {width:.3f} m wide x {height:.3f} m tall")
    print(f"  cg        : x_cg={res['x_cg']:.3f} m, z_cg={res['z_cg']:.3f} m")
    print(f"  stroke cap: extended <= {res['stroke_ratio_max']:.2f} x retracted")
    print("  ---------------------------------")
    print(f"  a = {res['a']:.4f} m   (hinge to cylinder base, along floor)")
    print(f"  b = {res['b']:.4f} m   (hinge to attachment, along wall)")
    print(f"  d = {res['d']:.4f} m   (wall to attachment, perpendicular)")
    print(f"  f = {res['f']:.4f} m   (cylinder base height above floor)")
    print("  ---------------------------------")
    force_unit = "N" if args.mass != 1.0 else "N/kg"
    print(f"  peak piston force : {res['peak_force']:.3f} {force_unit}")
    print(f"  stroke ratio      : {res['stroke_ratio']:.3f} "
          f"(L_min={res['L_min']:.3f} m, L_max={res['L_max']:.3f} m)")
    feas = "OK — within stroke limit" if res["feasible"] else \
        "WARNING — stroke limit NOT met"
    print(f"  feasibility       : {feas}")
    if not res["success"]:
        print("  note              : optimizer did not fully converge; "
              "try a finer --grid or different --seed.")

    # A line you can paste straight into app.py's sliders to visualize.
    print("\n  Paste into the app's sliders:")
    print(f"    a={res['a']:.2f}  b={res['b']:.2f}  "
          f"d={res['d']:.2f}  f={res['f']:.2f}\n")

    return res


if __name__ == "__main__":
    main()
