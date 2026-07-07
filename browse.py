"""The 'Browse configurations' view: search the precomputed geometry database.

Rendered by app.py when the sidebar view switch is set to Browse. Instead of
running the optimizer, it filters the precomputed table (lookup.py) by the
prompts you set, reconstructs peak force for your exact cg, and lets you sort by
any attribute and inspect / refine any configuration.
"""
import numpy as np
import plotly.graph_objects as go
import streamlit as st

from wall import compute_F_piston, compute_cylinder_length, STROKE_RATIO_MAX
from optimize import CONTAINER_PRESETS, optimize_actuator
import lookup
import lookup_build

# Grid resolution for the precomputed table. Fine (40) in production; tests set
# this lower for speed since the build is done once per process.
TABLE_RES = 40

CONTAINERS = {
    "Standard (8'6\") — 2.44 m W x 2.59 m H": CONTAINER_PRESETS["standard"],
    "High-Cube (9'6\") — 2.44 m W x 2.90 m H": CONTAINER_PRESETS["highcube"],
}
# Widest physical extents (High-Cube). Sliders use these FIXED ranges regardless
# of the selected container, so switching container never changes a slider's
# bounds and therefore never resets its value; the container is applied purely as
# a search filter (b, f <= its height).
WIDTH = CONTAINER_PRESETS["highcube"][0]
HEIGHT_MAX = CONTAINER_PRESETS["highcube"][1]

# Columns offerable in the results table (key -> label).
COLUMNS = {
    "peak_force": "peak force (N/kg)",
    "a": "a (m)", "b": "b (m)", "d": "d (m)", "f": "f (m)",
    "stroke": "stroke (m)", "stroke_ratio": "stroke ratio",
    "L_min": "retracted (m)", "L_max": "extended (m)",
    "moment_arm": "over-center margin",
}
DEFAULT_COLUMNS = ["peak_force", "a", "b", "d", "f", "stroke", "stroke_ratio"]


@st.cache_resource(show_spinner=False)
def _get_table(res):
    """Build the lookup table once per process (cached across reruns)."""
    return lookup_build.build_table(res=res)[0]


def _force_length_figures(a, b, d, f, x_cg, z_cg, stroke_max):
    """Exact force and length curves for one geometry, straight from wall.py."""
    theta = np.linspace(0.0, np.pi / 2, 400)
    deg = np.degrees(theta)
    with np.errstate(divide="ignore", invalid="ignore"):
        F = compute_F_piston(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
    F = np.where(np.isfinite(F) & (np.abs(F) <= 50.0), F, np.nan)
    L = compute_cylinder_length(theta, a=a, b=b, d=d, f=f)

    ff = go.Figure()
    ff.add_trace(go.Scatter(x=deg, y=F, mode="lines", name="F"))
    ff.update_layout(title="Piston force vs. angle (exact)",
                     xaxis_title="theta (deg)", yaxis_title="N/kg",
                     height=320, margin=dict(l=10, r=10, t=40, b=10))
    fl = go.Figure()
    fl.add_trace(go.Scatter(x=deg, y=L, mode="lines", name="L"))
    fl.add_hline(y=float(L.min()), line=dict(color="green", dash="dot"))
    fl.add_hline(y=stroke_max * float(L.min()), line=dict(color="red", dash="dot"),
                 annotation_text=f"{stroke_max:g}x limit")
    fl.update_layout(title="Cylinder length vs. angle (exact)",
                     xaxis_title="theta (deg)", yaxis_title="m",
                     height=320, margin=dict(l=10, r=10, t=40, b=10))
    return ff, fl


def render_browse():
    st.header("Browse configurations")
    st.caption("Search a precomputed database of geometries — instant, no "
               "optimizer. Set your problem and mounting limits, then filter and "
               "sort. Lengths are in meters. Because the database is a grid, the "
               "best rows may sit a hair over your stroke limit (see the *stroke "
               "ratio* column); **Refine** below gives the exact-limit optimum.")

    with st.spinner("Building the configuration database (first time only, ~15 s)…"):
        table = _get_table(TABLE_RES)

    # --- Prompts (sidebar) ---
    # Slider ranges are FIXED (High-Cube extents), never container-dependent, so
    # switching containers doesn't reset any value. The container only filters the
    # results (b, f must fit under its height).
    st.sidebar.header("Problem")
    size = st.sidebar.selectbox("Container", list(CONTAINERS), key="lk_size")
    width, height = CONTAINERS[size]
    x_cg = st.sidebar.slider("x_cg — along wall from hinge (m)", 0.0, HEIGHT_MAX,
                             1.20, 0.01, key="lk_xcg")
    z_cg = st.sidebar.slider("z_cg — off the wall (m)", 0.0, 1.5, 0.55, 0.01,
                             key="lk_zcg")
    stroke_max = st.sidebar.slider("Max stroke ratio", 1.0, 3.0,
                                   float(STROKE_RATIO_MAX), 0.05, key="lk_stroke")
    clearance = st.sidebar.slider("Roof clearance (m)", 0.0, 0.5, 0.0, 0.01,
                                  key="lk_clear")

    st.sidebar.header("Mounting limits")
    st.sidebar.caption("Each slider is a min–max range for that dimension — this "
                       "is where you set the max (or min) for every value. The "
                       "search keeps only geometries inside all four ranges.")
    ranges = {
        "a": (0.05, WIDTH / 2, "a — base along floor (m)"),
        "b": (0.05, HEIGHT_MAX, "b — attachment along wall (m)"),
        "d": (0.0, 1.0, "d — bracket length (m)"),
        "f": (0.0, HEIGHT_MAX, "f — base height (m)"),
    }
    bounds = {}
    for v, (lo, hi, label) in ranges.items():
        bounds[v] = st.sidebar.slider(label, lo, hi, (lo, hi), key=f"lk_rng_{v}")

    # --- Filter / sort controls (main area) ---
    with st.expander("Columns, extra filters & sorting", expanded=True):
        cols = st.multiselect("Columns to show", list(COLUMNS),
                              default=DEFAULT_COLUMNS,
                              format_func=lambda k: COLUMNS[k], key="lk_cols")
        c1, c2, c3 = st.columns(3)
        sort_by = c1.selectbox("Sort by", list(COLUMNS),
                               format_func=lambda k: COLUMNS[k], key="lk_sort")
        ascending = c2.radio("Order", ["ascending", "descending"],
                             key="lk_order") == "ascending"
        top_n = c3.number_input("Show top", 10, 1000, 100, 10, key="lk_top")
        # A RESULT cap only. Every GEOMETRY value (a, b, d, f) has its own min AND
        # max in the sidebar's "Mounting limits" — that's the single place to bound
        # the geometry, so we don't duplicate f/d caps here.
        max_force = st.number_input(
            "Max peak force (N/kg) — 0 = no cap", 0.0, 500.0, 0.0, 1.0,
            key="lk_fmax",
            help="Hide any configuration whose peak force exceeds this. To cap the "
                 "geometry itself (a, b, d, f), use the Mounting-limits sliders in "
                 "the sidebar — each sets that dimension's min and max.")

    filters = {}
    if max_force > 0:
        filters["peak_force"] = (None, max_force)

    res = lookup.search(table, height, x_cg, z_cg, stroke_max=stroke_max,
                        roof_clearance=clearance, bounds=bounds, filters=filters,
                        sort_by=sort_by, ascending=ascending, limit=int(top_n))
    n = res["peak_force"].size
    if n == 0:
        st.warning("No configurations match these settings. Loosen a mounting "
                   "limit, raise the stroke ratio, or reduce the clearance.")
        return

    show = cols or DEFAULT_COLUMNS
    data = {COLUMNS[k]: np.round(res[k], 3) for k in show}
    st.markdown(f"**{n} matching configurations** (best `{COLUMNS[sort_by]}` first)")
    st.dataframe(data, height=300, width="stretch")

    # --- Inspect one configuration (exact physics) ---
    st.subheader("Inspect a configuration")
    rank = st.number_input("Rank to inspect (1 = top of the list)", 1, n, 1, 1,
                           key="lk_rank") - 1
    rank = int(np.clip(rank, 0, n - 1))   # guard if a filter shrank the list
    a, b, d, f = (float(res["a"][rank]), float(res["b"][rank]),
                  float(res["d"][rank]), float(res["f"][rank]))
    st.markdown(
        f"**a={a:.3f}  b={b:.3f}  d={d:.3f}  f={f:.3f} m** — "
        f"peak **{res['peak_force'][rank]:.2f} N/kg**, stroke "
        f"{res['stroke'][rank]:.2f} m (ratio {res['stroke_ratio'][rank]:.2f})")
    ff, fl = _force_length_figures(a, b, d, f, x_cg, z_cg, stroke_max)
    p1, p2 = st.columns(2)
    p1.plotly_chart(ff, width="stretch")
    p2.plotly_chart(fl, width="stretch")

    # --- Refine to the exact continuous optimum for this query ---
    st.subheader("Get the exact optimum")
    st.caption("The list is a precomputed GRID, so even its top row is only "
               "near-optimal — it can sit a hair off the true best. This runs the "
               "optimizer once for your current Problem + Mounting-limits settings "
               "to compute the exact best geometry, and shows how far the grid was "
               "off. (Same math as the Designer's Optimize, scoped to this query.)")
    if st.button("Get the exact optimum — run optimizer"):
        with st.spinner("Optimizing…"):
            opt = optimize_actuator(width, height, x_cg, z_cg,
                                    stroke_ratio_max=stroke_max,
                                    roof_clearance=clearance, var_bounds=bounds)
        grid_best = float(res["peak_force"].min())
        st.success(
            f"Exact optimum: peak **{opt['peak_force']:.2f} N/kg** at "
            f"a={opt['a']:.3f} b={opt['b']:.3f} d={opt['d']:.3f} f={opt['f']:.3f} m "
            f"(grid best in the list was {grid_best:.2f}).")
