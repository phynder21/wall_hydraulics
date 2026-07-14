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


FORCE_REF = 25.0   # N/kg treated as "high demand" (a full total-force bar)
# The total-force bar shows ONE design, so a green->red scale is misleading
# (even the optimum would look "bad"); the fill uses a neutral colour instead.
BAR_NEUTRAL = "#9fb3c8"


def force_bar(peak_per_kg, mass_kg):
    """Convert a peak force (N/kg) at a given wall+load mass into a total-force
    readout: (total force in kN, bar fill 0-1, hex colour). Fill/colour are on the
    same green(low)->red(high) demand scale as the table, scaled to FORCE_REF."""
    if not np.isfinite(peak_per_kg):
        return float("nan"), 0.0, ""
    total_kn = peak_per_kg * mass_kg / 1000.0
    fill = min(max(peak_per_kg / FORCE_REF, 0.0), 1.0)
    return total_kn, fill, force_color(peak_per_kg, 0.0, FORCE_REF)


def force_bar_html(fill, color, label):
    """A horizontal fill bar as an HTML string (for st.markdown or ui.html)."""
    pct = max(0.0, min(fill, 1.0)) * 100.0
    color = color or "#bbbbbb"
    return (
        '<div style="background:#e9e4d6;border:1px solid #d8cdb5;border-radius:5px;'
        'height:26px;position:relative;overflow:hidden">'
        f'<div style="background:{color};width:{pct:.1f}%;height:100%"></div>'
        '<div style="position:absolute;inset:0;display:flex;align-items:center;'
        f'padding-left:10px;font-weight:600;color:#1a1a1a">{label}</div></div>')


def order_columns(columns, sort_by):
    """Display order for the results table: peak force first, then the column
    being sorted by, then the rest in their original order. The sort column is
    added even if it wasn't picked, so you always see the values you're sorting by
    (e.g. sorting by extended length surfaces that column automatically)."""
    ordered = []
    if "peak_force" in columns or sort_by == "peak_force":
        ordered.append("peak_force")
    if sort_by != "peak_force" and sort_by not in ordered:
        ordered.append(sort_by)
    ordered += [c for c in columns if c not in ordered]
    return ordered


def search(table, container_height, x_cg, z_cg, stroke_max=1.8, roof_clearance=0.0,
           bounds=None, filters=None, sort_by="peak_force", ascending=True,
           limit=200, group_cap=None):
    """Filter and rank the table for one query. Returns a dict of column arrays.

    - container_height: 2.591 (Standard) or 2.896 (High-Cube); caps b, f and the roof.
    - x_cg, z_cg: exact center of gravity (continuous, not gridded).
    - stroke_max, roof_clearance: constraint thresholds.
    - bounds: optional {var: (lo, hi)} mounting limits on a, b, d, f.
    - filters: optional {attribute: (lo, hi)} extra numeric filters (e.g. f max).
    - sort_by: an ATTRIBUTES key; ascending controls direction.
    - limit: max rows returned.
    - group_cap: max rows per distinct sort_by value (None = no cap).
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
    # Primary sort by the requested attribute; WITHIN groups of equal primary
    # value (many grid rows share e.g. a=0.05) break ties by ASCENDING peak force,
    # so the lowest-force design in each group is on top -- regardless of the
    # primary direction. lexsort's last key is primary; earlier keys break ties.
    primary = result[sort_by]
    key = primary if ascending else -primary
    order = np.lexsort((result["peak_force"], key))
    if group_cap and order.size:
        # Cap how many rows share each distinct sort value (keeping the best,
        # lowest-force ones since each group is already peak-ascending), so e.g.
        # sorting by f isn't 1000 rows all at f=0.
        sp = primary[order]
        change = np.concatenate(([True], sp[1:] != sp[:-1]))
        starts = np.flatnonzero(change)
        within = np.arange(order.size) - starts[np.cumsum(change) - 1]
        order = order[within < group_cap]
    order = order[:limit]
    out = {k: v[order] for k, v in result.items()}
    out["n_matches"] = n_matches
    return out


def cylinder_matches(table, container_height, x_cg, z_cg, retracted, extended,
                     bounds=None, roof_clearance=0.0, limit=200):
    """Geometries whose cylinder length stays ENTIRELY within a real cylinder's
    [retracted, extended] window (metres), ranked by peak force (lowest first).
    Max wall mass a row supports = cylinder force / peak_force. The stroke-ratio
    limit is left open here -- the absolute length window is the real constraint."""
    filters = {"L_min": (retracted, None), "L_max": (None, extended)}
    return search(table, container_height, x_cg, z_cg, stroke_max=1e9,
                  roof_clearance=roof_clearance, bounds=bounds, filters=filters,
                  sort_by="peak_force", ascending=True, limit=limit)


def cylinder_force(bore_mm, rod_mm, pressure_bar):
    """(push, pull) force in newtons: pressure x area. Push uses the full bore;
    pull uses the bore area minus the rod area (the annulus)."""
    import math
    pa = pressure_bar * 1.0e5                          # bar -> Pa
    a_bore = math.pi / 4.0 * (bore_mm / 1000.0) ** 2
    a_rod = math.pi / 4.0 * (rod_mm / 1000.0) ** 2
    return pa * a_bore, pa * max(a_bore - a_rod, 0.0)


# Standard cylinder bores. ISO 6020/6022 metric (mm) and NFPA inch series.
ISO_BORES_MM = [40, 50, 63, 80, 100, 125, 160, 200, 250, 320]
NFPA_BORES_IN = [1.5, 2.0, 2.5, 3.25, 4.0, 5.0, 6.0, 7.0, 8.0]


def required_bore_mm(force_n, pressure_bar):
    """Exact bore diameter (mm) whose full-bore push area gives `force_n` newtons
    at `pressure_bar`. Inverse of the push side of cylinder_force:
    F = P x (pi/4) x bore^2  ->  bore = sqrt(4 F / (pi P))."""
    import math
    pa = pressure_bar * 1.0e5
    if pa <= 0.0 or force_n <= 0.0:
        return float("nan")
    area = force_n / pa                        # m^2
    return math.sqrt(4.0 * area / math.pi) * 1000.0


def next_standard_bore_mm(bore_mm, series):
    """Smallest standard bore (mm) >= bore_mm for the series, with a label, or
    (None, None) if it exceeds the largest listed size. `series` is
    'ISO metric' or 'NFPA (inch)'."""
    if series == "NFPA (inch)":
        for b in NFPA_BORES_IN:
            if b * 25.4 >= bore_mm - 1e-9:
                return b * 25.4, f"{b:g} in"
        return None, None
    for b in ISO_BORES_MM:                     # default: ISO metric
        if b >= bore_mm - 1e-9:
            return float(b), f"{b:.0f} mm"
    return None, None


def pressure_for_bore_bar(force_n, bore_mm):
    """Operating pressure (bar) a given bore needs to make `force_n` on push."""
    import math
    area = math.pi / 4.0 * (bore_mm / 1000.0) ** 2
    if area <= 0.0:
        return float("nan")
    return force_n / area / 1.0e5


def best(table, container_height, x_cg, z_cg, **kw):
    """Convenience: the single lowest-peak-force feasible geometry, or None."""
    res = search(table, container_height, x_cg, z_cg, limit=1, **kw)
    if res["peak_force"].size == 0:
        return None
    keys = ("peak_force", "a", "b", "d", "f", "stroke", "stroke_ratio",
            "L_min", "L_max", "moment_arm")
    return {k: float(res[k][0]) for k in keys}
