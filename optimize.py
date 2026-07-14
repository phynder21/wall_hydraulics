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

from wall import STROKE_RATIO_MAX, compute_F_piston, compute_cylinder_length, g

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
LENGTH_PENALTY = 1.0e6       # for a cylinder length outside [retracted, extended]
FORCE_CAP_PENALTY = 1.0e4    # for peak force above the cap when minimizing length
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
LENGTH_TOL = 1.0e-3          # cylinder length window (meters)
FORCE_CAP_TOL = 1.0e-2       # peak force cap (N/kg)
CEILING_TOL = 1.0e-3         # meters
MOMENT_ARM_TOL = 1.0e-3      # moment-arm clearance (dimensionless)

# Multi-start: one differential-evolution run can settle into a good-but-not-best
# basin (its answer depends on the random seed). We run several independent
# starts from fixed seeds and keep the best -- empirically ~28% of seeds find the
# global basin for a hard case, so 20 starts finds it ~99.9% of the time.
# (Bigger per-seed populations and corner-seeded starts were both tried and gave
# no reliability gain; independent restarts are the effective lever.)
N_STARTS = 20
# Near-optimal alternatives: designs whose peak force is within this relative
# tolerance of the best are acceptable fallbacks. Instead of listing near-
# duplicates, we surface a geometrically DIVERSE spread of them, so you can
# trade a little force for an easier-to-build geometry. Each extra design is
# found by re-optimizing with a repulsion penalty that pushes it away from the
# designs already chosen -- i.e. the lowest-force geometry that is meaningfully
# different from them -- and kept only if it stays within tolerance.
ALT_REL_TOL = 0.15      # default: keep alternatives within 15% of the optimum's
                        # peak force. A sharp optimum often sits alone in its own
                        # basin, so the nearest genuinely different design can be
                        # ~10% worse; 15% reliably surfaces at least one. The app
                        # exposes this as a slider (alt_rel_tol) so you can tighten
                        # it (fewer, closer designs) or loosen it (more options).
N_ALTERNATIVES = 6      # most designs to return (including the optimum itself)
ALT_TARGET_SEP = 0.20   # separation (normalized geometry distance) each new design aims for
ALT_MIN_SEP = 0.08      # min separation to accept a design as genuinely distinct
ALT_REPEL = 1.0e3       # repulsion strength enforcing separation during the search


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


# Grid density per number of free variables, keeping the seed grid ~<=10k cells.
_GRID_NPTS = {1: 400, 2: 60, 3: 18, 4: 11}


def _batch_metrics(P, theta, x_cg, z_cg, m_cg, W, H, roof_clearance):
    """peak |force|, stroke ratio, signed moment arm, ceiling breach for a BATCH
    of geometries P (shape (N, 4) = a,b,d,f), vectorized over the theta sweep."""
    a, b, d, f = P[:, 0:1], P[:, 1:2], P[:, 2:3], P[:, 3:4]
    ct, st = np.cos(theta)[None, :], np.sin(theta)[None, :]
    x_att, z_att = b * ct - d * st, b * st + d * ct
    r_att = np.sqrt(b**2 + d**2)
    beta = np.arctan2(z_att, x_att)
    phi = np.arctan2(z_att - f, x_att + a)
    with np.errstate(divide="ignore", invalid="ignore"):
        F = -(m_cg * g * (x_cg * ct - z_cg * st)) / (r_att * np.sin(beta - phi))
    Fabs = np.where(np.isfinite(F), np.abs(F), np.nan)
    with np.errstate(invalid="ignore"):
        peak = np.nanmax(Fabs, axis=1)
    peak = np.where(np.isnan(peak), np.inf, peak)
    L = np.sqrt((x_att + a) ** 2 + (z_att - f) ** 2)
    Lmin, Lmax = L.min(axis=1), L.max(axis=1)
    ratio = np.where(Lmin > 0, Lmax / Lmin, np.inf)
    m_arm = np.sin(beta - phi)
    crosses = (m_arm.min(axis=1) < 0) & (m_arm.max(axis=1) > 0)
    moment = np.where(crosses, -np.abs(m_arm).min(axis=1), np.abs(m_arm).min(axis=1))
    inside = (x_att >= -W) & (x_att <= 0.0)
    top = np.where(inside, z_att, -np.inf).max(axis=1)
    ceiling = np.maximum(top - (H - roof_clearance), 0.0)
    ceiling = np.where(np.isfinite(ceiling), ceiling, 0.0)
    return peak, ratio, moment, ceiling, Lmax


_ZOOM_NPTS = {1: 33, 2: 15, 3: 11, 4: 8}   # local-grid points per free variable
_ZOOM_ROUNDS = 10                           # zoom iterations (window shrinks each)
_ZOOM_SHRINK = 0.5                          # window multiplier per round
_ZOOM_THETA = 121                           # theta samples for the refine sweep


def _zoom_refine(cell, spacing, free, locked, full_bounds, x_cg, z_cg, m_cg,
                 W, H, roof_clearance, score_fn):
    """Sharpen a coarse-grid seed to its local optimum with a pure-NumPy zoom:
    evaluate a small grid inside a window, keep the best point, recenter on it and
    shrink the window, repeat. Replaces the scipy DE polish -- no per-iteration
    Python overhead, so it stays fast on a throttled CPU (e.g. Render's free tier).
    `score_fn(peak, ratio, moment, ceiling, Lmax)` is the batch score to minimize;
    it mirrors the scalar `objective` (with the same full-weight penalties)."""
    theta = np.linspace(0.0, np.pi / 2, _ZOOM_THETA)
    fcol = {v: i for i, v in enumerate(free)}
    npz = _ZOOM_NPTS.get(len(free), 7)
    center = np.array(cell, dtype=float)
    half = 2.0 * np.array(spacing, dtype=float)   # start at the old polish's +/-2 cells
    best = center.copy()
    for _ in range(_ZOOM_ROUNDS):
        axes = []
        for i, v in enumerate(free):
            lo = max(full_bounds[v][0], center[i] - half[i])
            hi = min(full_bounds[v][1], center[i] + half[i])
            axes.append(np.linspace(lo, hi, npz) if hi > lo else np.array([lo]))
        mesh = [m.ravel() for m in np.meshgrid(*axes, indexing="ij")]
        P = np.empty((mesh[0].size, 4))
        for j, v in enumerate(VAR_NAMES):
            P[:, j] = mesh[fcol[v]] if v in fcol else locked[v]
        peak, ratio, moment, ceiling, Lmax = _batch_metrics(
            P, theta, x_cg, z_cg, m_cg, W, H, roof_clearance)
        score = score_fn(peak, ratio, moment, ceiling, Lmax)
        k = int(np.argmin(score))
        center = np.array([mesh[fcol[v]][k] for v in free])
        best = center
        half = half * _ZOOM_SHRINK
    return best


def _fast_runs(free, locked, full_bounds, assemble, objective, evaluate,
               x_cg, z_cg, m_cg, W, H, roof_clearance, seed_score_fn, refine_score_fn):
    """Replace the 20 blind DE restarts AND the scipy polish with a vectorized
    coarse grid sweep (finds the good basin) plus a pure-NumPy zoom refine on the
    best few cells. Lands on the constraint-boundary global optimum with no scipy
    in the hot path, so it is fast even on a throttled CPU. The seed/refine scores
    are supplied by the caller so this works for either objective (min force, or
    min length under a force cap)."""
    npg = _GRID_NPTS.get(len(free), 9)
    axes = [np.linspace(*full_bounds[v], npg) for v in free]
    mesh = [m.ravel() for m in np.meshgrid(*axes, indexing="ij")]
    col = {v: i for i, v in enumerate(free)}
    N = mesh[0].size
    P = np.empty((N, 4))
    for j, v in enumerate(VAR_NAMES):
        P[:, j] = mesh[col[v]] if v in col else locked[v]

    theta_c = np.linspace(0.0, np.pi / 2, 61)     # coarse sweep is enough to rank
    peak, ratio, moment, ceiling, Lmax = _batch_metrics(
        P, theta_c, x_cg, z_cg, m_cg, W, H, roof_clearance)
    # SOFT ranking: mostly by the objective, with a gentle push toward feasibility
    # and a hard reject for over-center. Soft (not hard) so a grid cell near the
    # boundary optimum — a step over the stroke limit — still ranks well and gets
    # refined; the refine then enforces the real limit via the same penalties.
    order = np.argsort(seed_score_fn(peak, ratio, moment, ceiling, Lmax))

    spacing = [(full_bounds[v][1] - full_bounds[v][0]) / (npg - 1) for v in free]
    seeds, runs = [], []
    for oi in order:
        if len(runs) >= 5:
            break
        cell = np.array([mesh[col[v]][oi] for v in free])
        if any(np.max(np.abs(cell - c) / (np.array(spacing) + 1e-12)) < 1.0 for c in seeds):
            continue                               # too close to an already-refined cell
        seeds.append(cell)
        best_vals = _zoom_refine(cell, spacing, free, locked, full_bounds,
                                 x_cg, z_cg, m_cg, W, H, roof_clearance, refine_score_fn)
        r = evaluate(assemble(best_vals))
        r["fun"], r["success"] = float(objective(best_vals)), True
        runs.append(r)
    return runs


def optimize_actuator(container_width, container_height, x_cg, z_cg,
                      stroke_ratio_max=STROKE_RATIO_MAX,
                      roof_clearance=ROOF_CLEARANCE, locked=None, var_bounds=None,
                      n_theta=200, m_cg=1.0, seed=0, maxiter=300,
                      n_starts=N_STARTS, popsize=None, alt_rel_tol=ALT_REL_TOL,
                      fast=False, length_window=None,
                      objective_mode="force", force_cap=None):
    """Search for the (a, b, d, f) minimizing peak piston force over 0-90 deg.

    Runs `n_starts` independent differential-evolution starts (fixed seeds, so the
    result is reproducible) and keeps the best, because a single start can settle
    into a good-but-not-best basin. `popsize` optionally overrides the per-start
    population (None = SciPy default of 15 x n_free); it does not improve
    reliability here, so it's a tuning knob rather than the fix.

    `locked` is an optional {name: value} dict (names in VAR_NAMES) holding those
    variables fixed; only the remaining variables are optimized. If all four are
    locked, the fixed geometry is simply evaluated.

    `var_bounds` optionally overrides the (lo, hi) search range per variable to a
    sub-range (e.g. mounting limits). A zero-width range is treated as a lock.

    `alt_rel_tol` sets how far above the optimum's peak force an alternative may
    sit (a fraction, e.g. 0.15 = within 15%).

    `objective_mode` picks what to minimize: "force" (default) minimizes peak
    piston force; "length" minimizes the cylinder's extended length (L_max) —
    the smallest actuator that still holds peak force at or below `force_cap`
    (in N per kg; None = no cap). Use "length" when force is cheap and physical
    size is what you pay for (e.g. an electromechanical actuator).

    Returns a dict with the geometry and resulting metrics, plus `alternatives`:
    a geometrically DIVERSE set of near-optimal designs (each within
    `alt_rel_tol` of the best objective value, tagged with its `penalty_pct`), so
    you can trade a little of the objective for an easier-to-build geometry. The
    optimum itself is always `alternatives[0]`.
    """
    locked = dict(locked or {})
    if length_window is not None:
        fast = False   # the fast zoom doesn't model the absolute length window
    n_starts = max(1, int(n_starts))   # at least one start
    theta = np.linspace(0.0, np.pi / 2, n_theta)

    # Search box per variable: the full physical range, unless var_bounds narrows
    # it (mounting limits). Mirrors the slider ranges in app.py.
    full_bounds = {
        "a": (0.05, container_width / 2),   # hinge to cylinder base, along floor
        "b": (0.05, container_height),      # hinge to attachment, along wall
        "d": (0.00, 1.00),                  # wall to attachment, perpendicular
        "f": (0.00, container_height),      # cylinder base height above floor
    }
    if var_bounds:
        full_bounds.update({k: tuple(v) for k, v in var_bounds.items()})
    # A zero-width range pins that variable -> treat as locked at its value.
    for v in VAR_NAMES:
        lo, hi = full_bounds[v]
        if v not in locked and hi - lo < 1e-9:
            locked[v] = lo
    free = [v for v in VAR_NAMES if v not in locked]
    bounds = [full_bounds[v] for v in free]

    def assemble(free_vals):
        """Combine searched (free) values with the locked ones into (a,b,d,f)."""
        vals = dict(zip(free, free_vals))
        vals.update(locked)
        return tuple(float(vals[v]) for v in VAR_NAMES)

    def objective(free_vals):
        peak, ratio, L_min, L_max, ceiling, moment_arm = _metrics(
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
        if length_window is not None:   # cylinder length must fit [retracted, extended]
            L_ret, L_ext = length_window
            penalty += LENGTH_PENALTY * max(L_ret - L_min, 0.0) ** 2
            penalty += LENGTH_PENALTY * max(L_max - L_ext, 0.0) ** 2
        if objective_mode == "length":
            # Minimize the extended length; keep peak force at or below the cap.
            if force_cap is not None:
                penalty += FORCE_CAP_PENALTY * max(peak - force_cap, 0.0) ** 2
            return L_max + penalty
        return peak + penalty

    def evaluate(geom):
        """Full metrics + feasibility for an assembled (a,b,d,f) geometry."""
        peak, ratio, L_min, L_max, ceiling, moment_arm = _metrics(
            geom, theta, x_cg, z_cg, m_cg, container_width, container_height,
            roof_clearance)
        feasible = (ratio <= stroke_ratio_max + STROKE_TOL
                    and ceiling <= CEILING_TOL
                    and moment_arm >= MIN_MOMENT_ARM - MOMENT_ARM_TOL)
        if length_window is not None:
            L_ret, L_ext = length_window
            feasible = (feasible and L_min >= L_ret - LENGTH_TOL
                        and L_max <= L_ext + LENGTH_TOL)
        if objective_mode == "length" and force_cap is not None:
            feasible = feasible and peak <= force_cap + FORCE_CAP_TOL
        return {"geom": geom, "peak": peak, "ratio": ratio, "L_min": L_min,
                "L_max": L_max, "ceiling": ceiling, "moment_arm": moment_arm,
                "feasible": feasible}

    de_kwargs = {"maxiter": maxiter, "tol": 1e-8, "polish": True}
    if popsize is not None:
        de_kwargs["popsize"] = popsize

    # Batch scores for the fast grid solver, matching the active objective. Each is
    # a SEED score (soft feasibility so near-boundary cells still rank and then get
    # refined) and a REFINE score (full-weight penalties, to land on the boundary).
    # 'length' minimizes L_max and pushes peak force to at-or-below the cap; 'force'
    # minimizes peak force — byte-identical to the original hardcoded scores.
    if objective_mode == "length":
        def seed_score(peak, ratio, moment, ceiling, Lmax):
            s = np.where(np.isfinite(Lmax) & np.isfinite(peak), Lmax, 1e18)
            if force_cap is not None:
                s = s + 10.0 * np.maximum(peak - force_cap, 0.0) ** 2
            return (s + 10.0 * np.maximum(ratio - stroke_ratio_max, 0.0) ** 2
                    + 10.0 * ceiling ** 2 + np.where(moment < 0.0, 1e18, 0.0))

        def refine_score(peak, ratio, moment, ceiling, Lmax):
            s = np.where(np.isfinite(Lmax) & np.isfinite(peak), Lmax, np.inf)
            if force_cap is not None:
                s = s + FORCE_CAP_PENALTY * np.maximum(peak - force_cap, 0.0) ** 2
            return (s + STROKE_PENALTY * np.maximum(ratio - stroke_ratio_max, 0.0) ** 2
                    + CEILING_PENALTY * np.maximum(ceiling, 0.0) ** 2
                    + np.where(moment < 0.0, OVERCENTER_HARD, 0.0)
                    + OVERCENTER_PENALTY * np.maximum(MIN_MOMENT_ARM - moment, 0.0) ** 2)
    else:
        def seed_score(peak, ratio, moment, ceiling, Lmax):
            return (np.where(np.isfinite(peak), peak, 1e18)
                    + 10.0 * np.maximum(ratio - stroke_ratio_max, 0.0) ** 2
                    + 10.0 * ceiling ** 2 + np.where(moment < 0.0, 1e18, 0.0))

        def refine_score(peak, ratio, moment, ceiling, Lmax):
            return (np.where(np.isfinite(peak), peak, np.inf)
                    + STROKE_PENALTY * np.maximum(ratio - stroke_ratio_max, 0.0) ** 2
                    + CEILING_PENALTY * np.maximum(ceiling, 0.0) ** 2
                    + np.where(moment < 0.0, OVERCENTER_HARD, 0.0)
                    + OVERCENTER_PENALTY * np.maximum(MIN_MOMENT_ARM - moment, 0.0) ** 2)

    if free and fast:
        # Fast: coarse grid seed + a pure-NumPy zoom refine instead of 20 blind DE
        # restarts (no scipy in the hot path). ~15x faster and just as accurate;
        # suitable for interactive / low-power hosts (e.g. Render's free tier).
        runs = _fast_runs(free, locked, full_bounds, assemble, objective, evaluate,
                          x_cg, z_cg, m_cg, container_width, container_height,
                          roof_clearance, seed_score, refine_score)
        best = min(runs, key=lambda r: r["fun"])
        success = best["success"]
    elif free:
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
        best["fun"] = best["L_max"] if objective_mode == "length" else best["peak"]
        best["success"] = True
        success = True
        runs = [best]

    # Alternatives: geometrically DIVERSE designs whose peak force is within
    # ALT_REL_TOL of the best -- near-optimal fallbacks for when the true optimum
    # is awkward to build. Because the optimum typically sits on a constraint
    # boundary (e.g. the stroke limit), the feasible near-optimal set is thin and
    # jittering around the optimum finds nothing new. Instead we seed with any
    # distinct feasible multi-start winners, then repeatedly RE-OPTIMIZE with a
    # repulsion penalty that pushes the search away from the designs already
    # chosen -- yielding, each time, the lowest-force geometry that is genuinely
    # different from them. The global best is always first, so alternatives[0] is
    # the geometry shown in the sliders.
    # Rank/gauge alternatives by whatever is being optimized: L_max in length
    # mode, else peak force.
    score = (lambda r: r["L_max"]) if objective_mode == "length" else (lambda r: r["peak"])
    best_score = score(best)
    threshold = best_score * (1 + alt_rel_tol)
    ranges = {v: max(full_bounds[v][1] - full_bounds[v][0], 1e-9) for v in free}

    def _norm_dist(g1, g2):
        """Geometry distance over the FREE variables, each normalized by its
        search range so every dimension contributes comparably."""
        if not free:
            return 0.0
        return float(np.sqrt(sum(
            ((g1[VAR_NAMES.index(v)] - g2[VAR_NAMES.index(v)]) / ranges[v]) ** 2
            for v in free)))

    def _min_sep(geom, chosen):
        return min((_norm_dist(geom, g) for g in chosen), default=float("inf"))

    # Each entry carries geom + both display metrics (peak force, L_max) + the
    # optimized `score` (L_max in length mode, else peak). The optimum is first.
    def _entry(r):
        return {"geom": r["geom"], "peak": r["peak"], "L_max": r["L_max"],
                "score": score(r)}

    selected = [_entry(best)]

    # First, reuse any feasible multi-start winners that are already distinct --
    # they're free (already computed) and capture separate basins.
    for r in sorted((r for r in runs if r["feasible"] and score(r) <= threshold),
                    key=lambda r: r["fun"]):
        if len(selected) >= N_ALTERNATIVES:
            break
        if _min_sep(r["geom"], [s["geom"] for s in selected]) >= ALT_MIN_SEP:
            selected.append(_entry(r))

    # Then top up by re-optimizing with a repulsion penalty away from the chosen
    # designs. Stop as soon as the best distinct design exceeds tolerance.
    n_alt = 4 if fast else N_ALTERNATIVES        # fewer, cheaper alternatives in fast mode
    if free and best["feasible"]:
        alt_de_kwargs = {"maxiter": 30 if fast else 80, "tol": 1e-7, "polish": True}
        while len(selected) < n_alt:
            chosen = [s["geom"] for s in selected]

            def repelled(free_vals):
                geom = assemble(free_vals)
                penalty = 0.0
                for g in chosen:
                    gap = ALT_TARGET_SEP - _norm_dist(geom, g)
                    if gap > 0.0:
                        penalty += ALT_REPEL * gap ** 2
                return objective(free_vals) + penalty

            result = differential_evolution(
                repelled, bounds, seed=seed + 1000 + len(selected), **alt_de_kwargs)
            geom = assemble(result.x)
            ev = evaluate(geom)
            if not (ev["feasible"] and np.isfinite(ev["peak"])
                    and score(ev) <= threshold):
                break   # no distinct design left within tolerance
            if _min_sep(geom, chosen) < ALT_MIN_SEP:
                break   # search could not get far enough from the chosen designs
            selected.append(_entry(ev))

    alternatives = [
        {"a": s["geom"][0], "b": s["geom"][1], "d": s["geom"][2], "f": s["geom"][3],
         "peak_force": s["peak"], "L_max": s["L_max"],
         "penalty_pct": (s["score"] / best_score - 1.0) * 100.0 if best_score > 0 else 0.0}
        for s in selected]

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
        "alternatives": alternatives,   # diverse near-optimal geometries
        "alt_rel_tol": alt_rel_tol,      # tolerance band the alternatives sit within
        "n_starts": n_starts if free else 0,
        "stroke_ratio_max": stroke_ratio_max,
        "x_cg": x_cg, "z_cg": z_cg,
        "container_width": container_width,
        "container_height": container_height,
        "success": success,
        "objective_mode": objective_mode,
        "force_cap": force_cap,          # N/kg ceiling (length mode); None otherwise
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
    p.add_argument("--alt-tol", type=float, default=ALT_REL_TOL,
                   help="Alternatives tolerance: list diverse designs whose peak "
                        "force is within this fraction of the optimum (e.g. 0.15).")
    p.add_argument("--fast", action="store_true",
                   help="Grid-seed + polish instead of 20 restarts (~10x faster).")
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
        n_starts=args.starts, alt_rel_tol=args.alt_tol, fast=args.fast,
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
        print(f"  {len(alts) - 1} near-optimal alternatives (diverse geometries "
              f"within {res['alt_rel_tol'] * 100:.0f}% of the optimum — pick by "
              f"build convenience):")
        for x in alts:
            tag = "optimum" if x["penalty_pct"] < 1e-6 else f"+{x['penalty_pct']:.1f}%"
            print(f"    a={x['a']:.3f} b={x['b']:.3f} d={x['d']:.3f} "
                  f"f={x['f']:.3f}  ({x['peak_force']:.3f} {force_unit}, {tag})")

    # A line you can paste straight into app.py's sliders to visualize.
    print("\n  Paste into the app's sliders:")
    print(f"    a={res['a']:.2f}  b={res['b']:.2f}  "
          f"d={res['d']:.2f}  f={res['f']:.2f}\n")

    return res


if __name__ == "__main__":
    main()
