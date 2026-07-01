"""Find the actuator mounting geometry that minimizes the worst-case piston
force over the full 0-90 deg swing, subject to a hydraulic stroke limit.

The free design variables are the four mounting dimensions (a, b, d, f). The
center of gravity (x_cg, z_cg) and the container size are *fixed inputs* — they
describe the door you are lifting, not something you get to design.

Method (see README / the project notes): this is a constrained min-max problem.
For one candidate geometry we sweep theta across the whole swing and reduce the
force curve to a single number — its peak magnitude. A global, gradient-free
optimizer (scipy's differential_evolution) then searches the geometry space for
the candidate with the smallest peak. Two constraints are folded in as penalties
that add a steep cost when violated, so the optimizer steers away from them:

  * stroke limit  — extended length must not exceed `stroke_ratio_max` times
                    the retracted length, over the swing.
  * roof clearance — the attachment endpoint, while horizontally inside the
                    container footprint, must stay `roof_clearance` meters below
                    the ceiling (i.e. z <= container_height - roof_clearance).
  * no over-center — the cylinder's moment arm about the hinge, sin(beta - phi),
                    must keep one sign over the swing and stay >= MIN_MOMENT_ARM.
                    A sign change means the line of action crosses the hinge and
                    the force diverges -- a physically impossible geometry.

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

# The four design variables, in the order _metrics expects them.
VAR_NAMES = ("a", "b", "d", "f")

# Large multipliers turning the inequality constraints into costs the optimizer
# feels. Big enough that the optimum sits essentially on the limit, not over it.
STROKE_PENALTY = 1.0e6
CEILING_PENALTY = 1.0e6
OVERCENTER_PENALTY = 1.0e6
# A crossing (moment arm goes negative) is physically impossible, not merely
# costly. This hard floor makes ANY non-crossing geometry beat ANY crossing one,
# so the optimizer always returns the best *buildable* design -- giving up the
# stroke/roof limits before it ever hands back an impossible (over-center) one.
OVERCENTER_HARD = 1.0e12

# Minimum moment-arm clearance the cylinder must keep about the hinge over the
# whole swing: |sin(beta - phi)| >= this. When sin(beta - phi) reaches zero the
# cylinder's line of action passes through the hinge (base, hinge, and
# attachment go collinear), the lever arm vanishes, and the required force
# diverges -- a physically impossible "over-center". A small positive floor both
# forbids that crossing and keeps a real, build-tolerant margin away from it.
MIN_MOMENT_ARM = 0.05

# Mechanical design margin: how far BELOW the ceiling the attachment endpoint
# must stay (meters). The effective ceiling becomes (container_height - this).
# 0.0 lets the endpoint just touch the roof; raise it for real clearance (e.g.
# 0.025 for 25 mm). Override per run with --clearance.
ROOF_CLEARANCE = 0.0

# Numerical tolerances for declaring a constraint "met" — penalty methods leave
# a tiny residual violation at the optimum. These are SOLVER slack, not design
# margins (for a ceiling design margin, use ROOF_CLEARANCE above).
STROKE_TOL = 1.0e-3          # stroke ratio (dimensionless)
CEILING_TOL = 1.0e-3         # meters
MOMENT_ARM_TOL = 1.0e-3      # moment-arm clearance (dimensionless)

# Multi-start: one differential-evolution run can settle into a good-but-not-best
# basin (its answer depends on the random seed). We run several independent
# starts from fixed seeds and keep the best -- empirically ~28% of seeds find the
# global basin for a hard case, so 20 starts finds it ~99.9% of the time.
# (Bigger per-seed populations and corner-seeded starts were both tried and gave
# no reliability gain; independent restarts are the effective lever.)
N_STARTS = 20
# Two feasible geometries count as reaching "the same optimum" if their peak
# forces are within this relative tolerance -- used to list equivalent designs.
ALT_REL_TOL = 0.01


def _metrics(p, theta, x_cg, z_cg, m_cg, container_width, container_height,
             roof_clearance):
    """Peak |force|, stroke ratio, ceiling overshoot, and moment-arm clearance
    for geometry p=(a,b,d,f) over the swept theta."""
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

    # Ceiling clearance: the attachment endpoint sweeps an arc about the hinge.
    # Wherever it is horizontally inside the container footprint (-W <= x <= 0),
    # it must stay below the effective ceiling (z <= H - roof_clearance), i.e.
    # leave roof_clearance meters of air under the roof. Measure worst overshoot.
    effective_ceiling = container_height - roof_clearance
    x_att = b * np.cos(theta) - d * np.sin(theta)
    z_att = b * np.sin(theta) + d * np.cos(theta)
    inside = (x_att >= -container_width) & (x_att <= 0.0)
    overshoot = np.where(inside, z_att - effective_ceiling, 0.0)
    ceiling_violation = float(np.maximum(overshoot, 0.0).max())

    # Over-center guard: the cylinder's moment arm about the hinge is
    # r_att * sin(beta - phi), where beta points hinge->attachment and phi points
    # base->attachment. It vanishes when base, hinge, and attachment go collinear
    # (line of action through the hinge) and the required force diverges. Track
    # sin(beta - phi): if it takes both signs over the swing the geometry
    # over-centers. `moment_arm` is the signed worst-case clearance from zero --
    # the closest approach, made NEGATIVE when the sign flips (crosses the pole).
    beta = np.arctan2(z_att, x_att)
    phi = np.arctan2(z_att - f, x_att + a)
    m_arm = np.sin(beta - phi)
    crosses = bool(m_arm.min() < 0.0 and m_arm.max() > 0.0)
    closest = float(np.abs(m_arm).min())
    moment_arm = -closest if crosses else closest

    return peak, ratio, L_min, L_max, ceiling_violation, moment_arm


def optimize_actuator(container_width, container_height, x_cg, z_cg,
                      stroke_ratio_max=STROKE_RATIO_MAX,
                      roof_clearance=ROOF_CLEARANCE, locked=None,
                      n_theta=200, m_cg=1.0, seed=0, maxiter=300,
                      n_starts=N_STARTS, popsize=None):
    """Search for the (a, b, d, f) minimizing peak piston force over 0-90 deg.

    Runs `n_starts` independent differential-evolution starts (fixed seeds, so the
    result is reproducible) and keeps the best, because a single start can settle
    into a good-but-not-best basin. `popsize` optionally overrides the per-start
    population (None = SciPy default of 15 x n_free); it does not improve
    reliability here, so it's a tuning knob rather than the fix.

    `locked` is an optional {name: value} dict (names in VAR_NAMES) holding those
    variables fixed; only the remaining variables are optimized. If all four are
    locked, the fixed geometry is simply evaluated.

    Returns a dict with the geometry and resulting metrics, plus `alternatives`:
    the distinct feasible geometries whose peak force ties the best (within
    ALT_REL_TOL), so a flat optimum surfaces as several equivalent designs.
    """
    locked = dict(locked or {})
    n_starts = max(1, int(n_starts))   # at least one start
    theta = np.linspace(0.0, np.pi / 2, n_theta)

    # Full box bounds (mirror the slider ranges in app.py); we keep only the
    # unlocked variables for the actual search.
    full_bounds = {
        "a": (0.05, container_width / 2),   # hinge to cylinder base, along floor
        "b": (0.05, container_height),      # hinge to attachment, along wall
        "d": (0.00, 1.00),                  # wall to attachment, perpendicular
        "f": (0.00, container_height),      # cylinder base height above floor
    }
    free = [v for v in VAR_NAMES if v not in locked]
    bounds = [full_bounds[v] for v in free]

    def assemble(free_vals):
        """Combine searched (free) values with the locked ones into (a,b,d,f)."""
        vals = dict(zip(free, free_vals))
        vals.update(locked)
        return tuple(float(vals[v]) for v in VAR_NAMES)

    def objective(free_vals):
        peak, ratio, _, _, ceiling, moment_arm = _metrics(
            assemble(free_vals), theta, x_cg, z_cg, m_cg, container_width,
            container_height, roof_clearance)
        penalty = 0.0
        if ratio > stroke_ratio_max:
            penalty += STROKE_PENALTY * (ratio - stroke_ratio_max) ** 2
        if ceiling > 0.0:
            penalty += CEILING_PENALTY * ceiling ** 2
        if moment_arm < 0.0:
            penalty += OVERCENTER_HARD   # crossing the hinge: impossible, reject hard
        if moment_arm < MIN_MOMENT_ARM:
            penalty += OVERCENTER_PENALTY * (MIN_MOMENT_ARM - moment_arm) ** 2
        return peak + penalty

    def evaluate(geom):
        """Full metrics + feasibility for an assembled (a,b,d,f) geometry."""
        peak, ratio, L_min, L_max, ceiling, moment_arm = _metrics(
            geom, theta, x_cg, z_cg, m_cg, container_width, container_height,
            roof_clearance)
        feasible = (ratio <= stroke_ratio_max + STROKE_TOL
                    and ceiling <= CEILING_TOL
                    and moment_arm >= MIN_MOMENT_ARM - MOMENT_ARM_TOL)
        return {"geom": geom, "peak": peak, "ratio": ratio, "L_min": L_min,
                "L_max": L_max, "ceiling": ceiling, "moment_arm": moment_arm,
                "feasible": feasible}

    de_kwargs = {"maxiter": maxiter, "tol": 1e-8, "polish": True}
    if popsize is not None:
        de_kwargs["popsize"] = popsize

    if free:
        # Multi-start: run n_starts independent DE searches from fixed seeds and
        # keep the best. The objective already folds feasibility in as penalties,
        # so the lowest objective is the best *feasible* design when one exists.
        runs = []
        for s in range(seed, seed + n_starts):
            result = differential_evolution(objective, bounds, seed=s, **de_kwargs)
            r = evaluate(assemble(result.x))
            r["fun"] = float(result.fun)
            r["success"] = bool(result.success)
            runs.append(r)
        best = min(runs, key=lambda r: r["fun"])
        success = best["success"]
    else:
        # Everything locked: nothing to search, just evaluate the fixed geometry.
        best = evaluate(assemble([]))
        best["fun"] = best["peak"]
        best["success"] = True
        success = True
        runs = [best]

    # Alternatives: distinct feasible geometries whose peak force ties the best
    # (within ALT_REL_TOL). A unique optimum yields one; a flat optimum surfaces
    # several equally-good designs. Deduped at slider precision (2 decimals).
    tied = [r for r in runs
            if r["feasible"] and r["peak"] <= best["peak"] * (1 + ALT_REL_TOL)]
    alternatives, seen = [], set()
    # Sort by objective so the returned best (chosen by objective) is always the
    # first alternative -- i.e. alternatives[0] is the geometry in the sliders.
    for r in sorted(tied or [best], key=lambda r: r["fun"]):
        key = tuple(round(v, 2) for v in r["geom"])
        if key not in seen:
            seen.add(key)
            g = r["geom"]
            alternatives.append({"a": g[0], "b": g[1], "d": g[2], "f": g[3],
                                 "peak_force": r["peak"]})

    a, b, d, f = best["geom"]
    return {
        "a": a, "b": b, "d": d, "f": f,
        "locked": locked,
        "peak_force": best["peak"],     # N per kg of wall+equipment mass
        "stroke_ratio": best["ratio"],  # L_max / L_min over the swing
        "L_min": best["L_min"], "L_max": best["L_max"],
        "ceiling_violation": best["ceiling"],   # meters the endpoint breaches the roof
        "roof_clearance": roof_clearance,
        "moment_arm": best["moment_arm"],  # signed worst |sin(beta-phi)|; <0 over-centers
        "over_center": best["moment_arm"] < 0.0,
        "feasible": best["feasible"],
        "alternatives": alternatives,   # distinct equally-good geometries
        "n_starts": n_starts if free else 0,
        "stroke_ratio_max": stroke_ratio_max,
        "x_cg": x_cg, "z_cg": z_cg,
        "container_width": container_width,
        "container_height": container_height,
        "success": success,
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
    p.add_argument("--clearance", type=float, default=ROOF_CLEARANCE,
                   help="Mechanical gap (m) the endpoint must keep below the "
                        "ceiling; effective ceiling = height - clearance.")
    p.add_argument("--lock", action="append", default=[], metavar="VAR=VALUE",
                   help="Hold a variable fixed during optimization, e.g. "
                        "--lock f=0.5 (repeatable). VAR is one of a, b, d, f.")
    p.add_argument("--grid", type=int, default=200,
                   help="Number of theta samples across the swing.")
    p.add_argument("--mass", type=float, default=1.0,
                   help="Wall+equipment mass (kg); 1.0 gives per-kg force.")
    p.add_argument("--seed", type=int, default=0,
                   help="Base random seed; multi-start uses seed .. seed+starts-1.")
    p.add_argument("--starts", type=int, default=N_STARTS,
                   help="Number of independent optimizer restarts (multi-start).")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)

    width, height = CONTAINER_PRESETS[args.container]
    if args.width is not None:
        width = args.width
    if args.height is not None:
        height = args.height

    locked = {}
    for item in args.lock:
        name, sep, value = item.partition("=")
        name = name.strip()
        if name not in VAR_NAMES or not sep or not value.strip():
            raise SystemExit(
                f"--lock expects VAR=VALUE with VAR in {', '.join(VAR_NAMES)}; "
                f"got '{item}'")
        try:
            locked[name] = float(value)
        except ValueError:
            raise SystemExit(f"--lock VALUE must be a number; got '{item}'")

    res = optimize_actuator(
        container_width=width, container_height=height,
        x_cg=args.x_cg, z_cg=args.z_cg,
        stroke_ratio_max=args.stroke_ratio, roof_clearance=args.clearance,
        locked=locked, n_theta=args.grid, m_cg=args.mass, seed=args.seed,
        n_starts=args.starts,
    )

    print("\n=== Optimized actuator geometry ===")
    print(f"  container : {width:.3f} m wide x {height:.3f} m tall")
    print(f"  cg        : x_cg={res['x_cg']:.3f} m, z_cg={res['z_cg']:.3f} m")
    print(f"  stroke cap: extended <= {res['stroke_ratio_max']:.2f} x retracted")
    print(f"  roof gap  : keep >= {res['roof_clearance']:.3f} m below ceiling "
          f"(effective ceiling {height - res['roof_clearance']:.3f} m)")
    if res["locked"]:
        locks = ", ".join(f"{k}={v:.3f}" for k, v in sorted(res["locked"].items()))
        print(f"  locked    : {locks} (held fixed; remaining vars optimized)")
    print("  ---------------------------------")
    print(f"  a = {res['a']:.4f} m   (hinge to cylinder base, along floor)")
    print(f"  b = {res['b']:.4f} m   (hinge to attachment, along wall)")
    print(f"  d = {res['d']:.4f} m   (wall to attachment, perpendicular)")
    print(f"  f = {res['f']:.4f} m   (cylinder base height above floor)")
    print("  ---------------------------------")
    force_unit = "N" if args.mass != 1.0 else "N/kg"
    print(f"  peak piston force : {res['peak_force']:.3f} {force_unit}")
    print(f"  cylinder stroke   : {res['L_max'] - res['L_min']:.3f} m "
          f"(L_min={res['L_min']:.3f} m, L_max={res['L_max']:.3f} m)")
    print(f"  stroke ratio      : {res['stroke_ratio']:.3f} "
          f"(L_max / L_min; limit {res['stroke_ratio_max']:.2f})")
    print(f"  ceiling clearance : endpoint breaches roof by "
          f"{res['ceiling_violation']:.4f} m (0 = clears)")
    oc = ("OVER-CENTERS (cylinder line crosses the hinge — impossible)"
          if res["over_center"] else f"clear (min |sin(beta-phi)| = {res['moment_arm']:.3f})")
    print(f"  over-center       : {oc}")
    feas = "OK — all constraints met" if res["feasible"] else \
        "WARNING — a constraint is NOT met (see above)"
    print(f"  feasibility       : {feas}")
    if not res["success"]:
        print("  note              : optimizer did not fully converge; "
              "try a finer --grid or different --seed.")

    alts = res["alternatives"]
    if len(alts) > 1:
        print(f"  ---------------------------------")
        print(f"  {len(alts)} equally-good geometries reach this force "
              f"(flat optimum — pick by build convenience):")
        for x in alts:
            print(f"    a={x['a']:.3f} b={x['b']:.3f} d={x['d']:.3f} "
                  f"f={x['f']:.3f}  ({x['peak_force']:.3f} {force_unit})")

    # A line you can paste straight into app.py's sliders to visualize.
    print("\n  Paste into the app's sliders:")
    print(f"    a={res['a']:.2f}  b={res['b']:.2f}  "
          f"d={res['d']:.2f}  f={res['f']:.2f}\n")

    return res


if __name__ == "__main__":
    main()
