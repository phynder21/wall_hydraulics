"""Query layer over the precomputed geometry table (see lookup_build.py).

Loads the table once, then answers "search" queries in milliseconds: filter the
geometries by the constraints/limits the user sets, reconstruct the peak piston
force for their exact center of gravity (the only cg-dependent step), and rank.

The force is reconstructed from the factorization

    F(theta) = (z_cg*sin(theta) - x_cg*cos(theta)) * g / D(theta)

where D = r_att*sin(beta - phi) depends only on geometry. So we recompute D for
the *surviving* rows only (cheap and vectorized), never for the whole grid.
"""
import numpy as np

from wall import g
from optimize import MIN_MOMENT_ARM

# Stroke-ratio filter is a HARD cap: a design shown for "max ratio 1.8" must
# actually be <= 1.8 so the limit can be trusted. (A previous version added grid
# slack so near-boundary grid points appeared, but that surfaced designs a few %
# OVER the limit, which is misleading.) The grid's best feasible design can sit a
# little short of the true boundary optimum; "Get the exact optimum" (Refine)
# closes that gap by running the optimizer at the exact limit.
STROKE_GRID_TOL = 0.0


def load_table(path="lookup_table.npz"):
    """Load a table built by lookup_build into a dict of numpy arrays."""
    data = np.load(path)
    return {k: data[k] for k in data.files}


def _peak_from_gain(G, store_theta, x_cg, z_cg):
    """Peak |F| per row from the stored force-gain curves G (fast path).

    F(theta) = (z_cg*sin - x_cg*cos) * G(theta); peak = max over theta of |F|.
    """
    cg_factor = z_cg * np.sin(store_theta) - x_cg * np.cos(store_theta)   # (T,)
    F = cg_factor[None, :] * G                                            # (N,T)
    return np.nanmax(np.abs(F), axis=1)


def _peak_recompute(a, b, d, f, x_cg, z_cg, theta):
    """Peak |F| recomputed from geometry (independent cross-check for tests)."""
    a = a[:, None]; b = b[:, None]; d = d[:, None]; f = f[:, None]
    ct = np.cos(theta)[None, :]; st = np.sin(theta)[None, :]
    x_att = b * ct - d * st
    z_att = b * st + d * ct
    r_att = np.sqrt(b**2 + d**2)
    beta = np.arctan2(z_att, x_att)
    phi = np.arctan2(z_att - f, x_att + a)
    with np.errstate(divide="ignore", invalid="ignore"):
        F = g * (z_cg * st - x_cg * ct) / (r_att * np.sin(beta - phi))
    return np.nanmax(np.abs(F), axis=1)


# Attribute columns exposed for filtering/sorting in the UI (label -> spec).
# derived=True columns are computed from the table, not stored directly.
ATTRIBUTES = {
    "peak_force": {"label": "Peak force (N/kg)", "better": "min"},
    "a": {"label": "a — base along floor (m)", "better": None},
    "b": {"label": "b — attach along wall (m)", "better": None},
    "d": {"label": "d — bracket length (m)", "better": "min"},
    "f": {"label": "f — base height (m)", "better": "min"},
    "stroke": {"label": "Stroke (m)", "better": "min"},
    "stroke_ratio": {"label": "Stroke ratio", "better": "min"},
    "L_min": {"label": "Retracted length (m)", "better": None},
    "L_max": {"label": "Extended length (m)", "better": None},
    "moment_arm": {"label": "Over-center margin", "better": "max"},
}


# Excel-style 3-colour scale for the peak-force column: green = low force (good),
# yellow = middling, red = high (needs a bigger cylinder). Continuous linear
# interpolation, so two nearly-equal forces get nearly-identical colours.
_FORCE_SCALE = ((0x63, 0xbe, 0x7b), (0xff, 0xeb, 0x84), (0xf8, 0x69, 0x6b))


def force_color(value, lo, hi):
    """Hex colour ('#rrggbb') for `value` on a green(lo) -> red(hi) scale, scaled
    to the [lo, hi] range of the shown results. Returns '' if not colourable."""
    if not np.isfinite(value) or hi <= lo:
        return ""
    t = min(max((value - lo) / (hi - lo), 0.0), 1.0)
    green, yellow, red = _FORCE_SCALE
    (c0, c1), f = ((green, yellow), t / 0.5) if t < 0.5 else ((yellow, red), (t - 0.5) / 0.5)
    r, g, b = (int(round(a + (bb - a) * f)) for a, bb in zip(c0, c1))
    return "#%02x%02x%02x" % (r, g, b)


def search(table, container_height, x_cg, z_cg, stroke_max=1.8, roof_clearance=0.0,
           bounds=None, filters=None, sort_by="peak_force", ascending=True,
           limit=200):
    """Filter and rank the table for one query. Returns a dict of column arrays.

    - container_height: 2.591 (Standard) or 2.896 (High-Cube); caps b, f and the roof.
    - x_cg, z_cg: exact center of gravity (continuous, not gridded).
    - stroke_max, roof_clearance: constraint thresholds.
    - bounds: optional {var: (lo, hi)} mounting limits on a, b, d, f.
    - filters: optional {attribute: (lo, hi)} extra numeric filters (e.g. f max).
    - sort_by: an ATTRIBUTES key; ascending controls direction.
    - limit: max rows returned.
    """
    n = table["a"].size
    keep = np.ones(n, dtype=bool)

    # Container: the geometry must fit under this container's height.
    keep &= table["b"] <= container_height
    keep &= table["f"] <= container_height
    # Constraints shared with the optimizer (stroke is a hard cap; see above).
    keep &= table["stroke_ratio"] <= stroke_max + STROKE_GRID_TOL
    keep &= table["moment_arm"] >= MIN_MOMENT_ARM
    keep &= table["max_ceiling"] <= container_height - roof_clearance
    # Mounting limits.
    for v, (lo, hi) in (bounds or {}).items():
        keep &= (table[v] >= lo) & (table[v] <= hi)

    idx = np.nonzero(keep)[0]
    if idx.size == 0:
        return {"n_matches": 0, "peak_force": np.array([]),
                **{k: np.array([]) for k in
                   ("a", "b", "d", "f", "stroke", "stroke_ratio", "L_min",
                    "L_max", "moment_arm")}}

    a, b = table["a"][idx], table["b"][idx]
    d, f = table["d"][idx], table["f"][idx]
    peak = _peak_from_gain(table["G"][idx], table["store_theta"], x_cg, z_cg)
    stroke = table["L_max"][idx] - table["L_min"][idx]

    result = {"peak_force": peak, "a": a, "b": b, "d": d, "f": f,
              "stroke": stroke, "stroke_ratio": table["stroke_ratio"][idx],
              "L_min": table["L_min"][idx], "L_max": table["L_max"][idx],
              "moment_arm": table["moment_arm"][idx]}

    # Extra numeric filters on any attribute (e.g. base height below 0.8 m).
    if filters:
        mask = np.ones(peak.size, dtype=bool)
        for attr, (lo, hi) in filters.items():
            col = result[attr]
            if lo is not None:
                mask &= col >= lo
            if hi is not None:
                mask &= col <= hi
        result = {k: v[mask] for k, v in result.items()}

    # True match count BEFORE the top-N cap, so the UI can report how many
    # geometries pass the current filters (the returned rows are capped at limit).
    n_matches = int(result["peak_force"].size)
    order = np.argsort(result[sort_by], kind="stable")
    if not ascending:
        order = order[::-1]
    order = order[:limit]
    out = {k: v[order] for k, v in result.items()}
    out["n_matches"] = n_matches
    return out


def best(table, container_height, x_cg, z_cg, **kw):
    """Convenience: the single lowest-peak-force feasible geometry, or None."""
    res = search(table, container_height, x_cg, z_cg, limit=1, **kw)
    if res["peak_force"].size == 0:
        return None
    keys = ("peak_force", "a", "b", "d", "f", "stroke", "stroke_ratio",
            "L_min", "L_max", "moment_arm")
    return {k: float(res[k][0]) for k in keys}
