"""The 'Browse configurations' view: search the precomputed geometry database.

Rendered by app.py when the sidebar view switch is set to Browse. Instead of
running the optimizer, it filters the precomputed table (lookup.py) by the
prompts you set, reconstructs peak force for your exact cg, and lets you sort by
any attribute and inspect / refine any configuration.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from wall import (compute_F_piston, compute_cylinder_length,
                  compute_geometry, STROKE_RATIO_MAX)
from optimize import CONTAINER_PRESETS, optimize_actuator
from sensitivity_panel import (render_sensitivity_panel, render_interaction_map,
                               selected_metric)
from cylinder_panel import render_cylinder_sizing
from container_view import add_container_shell
from pdf_export import render_pdf_export
import lookup
import lookup_build

# Grid resolution for the precomputed table. Fine (40) in production; tests set
# this lower for speed since the build is done once per process.
TABLE_RES = 40

# Labels show INTERNAL (clear) dimensions — the usable interior, not the outer shell
# (values come from optimize.CONTAINER_PRESETS, which are internal).
CONTAINERS = {
    "Standard (8'6\") — 2.35 × 2.39 m internal": CONTAINER_PRESETS["standard"],
    "High-Cube (9'6\") — 2.35 × 2.70 m internal": CONTAINER_PRESETS["highcube"],
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


def _diagram_figure(a, b, d, f, x_cg, z_cg, width, height, theta_deg=45.0,
                    fig_height=360):
    """Side-view of the geometry at one wall angle: container, wall/door, bracket,
    cylinder, and the key points (hinge, base, attachment, cg)."""
    th = np.radians(theta_deg)
    geo = compute_geometry(th, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
    x_att, z_att = float(geo["attachment"][0]), float(geo["attachment"][1])
    x_cgw, z_cgw = float(geo["cg"][0]), float(geo["cg"][1])
    x_wb, z_wb = float(geo["wall_axis_at_b"][0]), float(geo["wall_axis_at_b"][1])
    xb, zb = -a, f                                   # cylinder base
    door = (height * np.cos(th), height * np.sin(th))
    fig = go.Figure()
    # Container steel shell around the internal clear space (width/height are internal),
    # so the mechanism reads as working inside the clear interior, not the outer box.
    shell_x, shell_zb, shell_zt = add_container_shell(fig, width, height)
    # Invisible anchors at the shell's outer corners so autorange includes the shell.
    fig.add_trace(go.Scatter(x=[shell_x, shell_x], y=[shell_zb, shell_zt], mode="markers",
                             marker=dict(size=0.1, opacity=0), hoverinfo="skip",
                             showlegend=False))
    fig.add_hline(y=0, line=dict(color="lightgray", dash="dash"))
    fig.add_trace(go.Scatter(x=[0, -width, -width, 0], y=[0, 0, height, height],
                             mode="lines", line=dict(color="darkgray", width=2),
                             name="container (clear)", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=[0, door[0]], y=[0, door[1]], mode="lines",
                             line=dict(color="black", width=5), name="wall"))
    fig.add_trace(go.Scatter(x=[x_wb, x_att], y=[z_wb, z_att], mode="lines",
                             line=dict(color="gray", width=3), name="bracket"))
    fig.add_trace(go.Scatter(x=[xb, xb], y=[0, zb], mode="lines",
                             line=dict(color="black", width=3), name="post",
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=[xb, x_att], y=[zb, z_att], mode="lines",
                             line=dict(color="#d62728", width=4), name="cylinder"))
    fig.add_trace(go.Scatter(x=[0], y=[0], mode="markers",
                             marker=dict(size=10, color="black"), name="hinge"))
    fig.add_trace(go.Scatter(x=[xb], y=[zb], mode="markers",
                             marker=dict(size=11, color="#d62728", symbol="square"),
                             name="cylinder base"))
    fig.add_trace(go.Scatter(x=[x_att], y=[z_att], mode="markers",
                             marker=dict(size=9, color="#1f77b4"), name="attachment"))
    fig.add_trace(go.Scatter(x=[x_cgw], y=[z_cgw], mode="markers",
                             marker=dict(size=12, color="green", symbol="cross"),
                             name="cg"))
    fig.update_layout(title=f"Geometry at theta = {theta_deg:.0f} deg",
                      xaxis_title="x (m)", yaxis_title="z (m)", height=fig_height,
                      margin=dict(l=10, r=10, t=40, b=10), showlegend=False)
    fig.update_yaxes(scaleanchor="x", scaleratio=1)   # equal aspect ratio
    return fig


def _sb_linked(label, key, lo, hi, default, step, fmt="%.2f", help=None, ctx=None):
    """Slider + typeable number box bound to one canonical value in
    st.session_state[key]. Renders into `ctx` (default the sidebar; pass an
    expander to group it)."""
    ctx = ctx if ctx is not None else st.sidebar
    if key not in st.session_state:
        st.session_state[key] = float(default)
    skey, nkey = f"{key}__s", f"{key}__n"
    st.session_state[skey] = st.session_state[key]
    st.session_state[nkey] = st.session_state[key]

    def _from_s():
        st.session_state[key] = st.session_state[skey]

    def _from_n():
        st.session_state[key] = float(min(max(st.session_state[nkey], lo), hi))

    ctx.markdown(f"**{label}**")
    c1, c2 = ctx.columns([2, 1])
    c1.slider(label, lo, hi, step=step, key=skey, on_change=_from_s,
              help=help, label_visibility="collapsed")
    c2.number_input(label, min_value=lo, max_value=hi, step=step, key=nkey,
                    on_change=_from_n, format=fmt, label_visibility="collapsed")
    return st.session_state[key]


def _sb_range(label, key, full_lo, full_hi, step=0.01, fmt="%.2f"):
    """Sidebar range slider + typeable min/max number boxes, bound to a canonical
    (lo, hi) tuple in st.session_state[key]."""
    st.session_state.setdefault(key, (full_lo, full_hi))
    lo, hi = st.session_state[key]
    lo = min(max(lo, full_lo), full_hi)
    hi = min(max(hi, lo), full_hi)
    st.session_state[key] = (lo, hi)
    rk, lok, hik = f"{key}__r", f"{key}__lo", f"{key}__hi"
    st.session_state[rk] = (lo, hi)
    st.session_state[lok] = lo
    st.session_state[hik] = hi

    def _from_r():
        a, b = st.session_state[rk]
        st.session_state[key] = (a, b)

    def _from_box():
        a, b = st.session_state[lok], st.session_state[hik]
        st.session_state[key] = (min(a, b), max(a, b))

    st.markdown(f"**{label}**")
    st.slider(label, full_lo, full_hi, step=step, key=rk, on_change=_from_r,
              label_visibility="collapsed")
    cc1, cc2 = st.columns(2)
    cc1.number_input("min", min_value=full_lo, max_value=full_hi, step=step,
                     key=lok, on_change=_from_box, format=fmt)
    cc2.number_input("max", min_value=full_lo, max_value=full_hi, step=step,
                     key=hik, on_change=_from_box, format=fmt)
    return st.session_state[key]


def render_browse():
    st.header("Browse configurations")
    # Per-cylinder display: the table's peak force is the whole-wall (one-cylinder)
    # value; with n_cyl cylinders sharing the load each carries 1/n_cyl, so every
    # displayed force is divided by n_cyl (and a user force cap is scaled up).
    n_cyl = int(st.session_state.get("n_cyl", 1))
    st.info(lookup.cylinder_banner(n_cyl))

    with st.spinner("Building the configuration database (first time only, ~15 s)…"):
        table = _get_table(TABLE_RES)

    # --- Prompts (sidebar) ---
    # Slider ranges are FIXED (High-Cube extents), never container-dependent, so
    # switching containers doesn't reset any value. The container only filters the
    # results (b, f must fit under its height).
    # Browse's controls are few enough to sit in one section (not tabs); the optional
    # mounting limits stay in a collapsible expander below.
    st.sidebar.header("Problem")
    size = st.sidebar.selectbox("Container", list(CONTAINERS), key="lk_size")
    st.sidebar.caption("**Internal (clear) dimensions** — the usable space inside the "
                       "container, not the outer shell.")
    width, height = CONTAINERS[size]
    # Optional half-container cap on the base position `a` (see the Designer).
    half_a = st.sidebar.checkbox("Keep base within half the container", value=True,
                                 key="lk_half_a",
                                 help="Caps a at half the width so the base stays in "
                                      "the near half of the floor. Uncheck to allow "
                                      "the full width.")
    if half_a:
        st.sidebar.caption(f"Active: **a ≤ {WIDTH / 2:.2f} m** (half the {WIDTH:.2f} m "
                           f"width).")
    else:
        st.sidebar.caption(f"Off — **a** may use the full **{WIDTH:.2f} m** width.")
    x_cg = _sb_linked("x_cg — along wall from hinge (m)", "lk_xcg",
                      0.0, HEIGHT_MAX, 1.20, 0.01)
    z_cg = _sb_linked("z_cg — off the wall (m)", "lk_zcg", 0.0, 1.5, 0.55, 0.01)
    stroke_max = _sb_linked(
        "Max stroke ratio", "lk_stroke", 1.0, 3.0, float(STROKE_RATIO_MAX), 0.05,
        help="Hard cap: only designs with L_max/L_min at or below this appear. "
             "Real hydraulic cylinders are typically ~1.8–2×.")
    clearance = _sb_linked(
        "Roof clearance (m)", "lk_clear", 0.0, 0.5, 0.0, 0.01,
        help="Keep the piston attachment this far below the roof.")
    mass = _sb_linked("Wall + load mass (kg)", "lk_mass", 50.0, 20000.0, 500.0, 10.0,
                      fmt="%.0f",
                      help="Converts the per-kg peak force into the real cylinder "
                           "force (shown for the inspected design).")

    ranges = {
        "a": (0.05, WIDTH / 2 if half_a else WIDTH, "a — base along floor (m)"),
        "b": (0.05, HEIGHT_MAX, "b — attachment along wall (m)"),
        "d": (0.0, 1.0, "d — bracket length (m)"),
        "f": (0.0, HEIGHT_MAX, "f — base height (m)"),
    }
    bounds = {}
    with st.sidebar.expander("Mounting limits", expanded=False):
        for v, (lo, hi, label) in ranges.items():
            bounds[v] = _sb_range(label, f"lk_rng_{v}", lo, hi)

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
        group_cap = st.number_input(
            "Max rows per sorted value (0 = no cap)", 0, 1000, 20, 5, key="lk_gcap",
            help="When you sort by a column with repeats (like f), show at most "
                 "this many of the best (lowest-force) rows per distinct value, so "
                 "one value can't flood the list.")

    filters = {}
    if max_force > 0:
        # The cap is entered per cylinder; the table stores whole-wall force.
        filters["peak_force"] = (None, max_force * n_cyl)

    res = lookup.search(table, height, x_cg, z_cg, stroke_max=stroke_max,
                        roof_clearance=clearance, bounds=bounds, filters=filters,
                        sort_by=sort_by, ascending=ascending, limit=int(top_n),
                        group_cap=int(group_cap) or None)
    n = res["peak_force"].size                 # rows returned (capped at "Show top")
    total = int(res.get("n_matches", n))       # true matches before that cap
    if n == 0:
        st.warning("No configurations match these settings. Loosen a mounting "
                   "limit, raise the stroke ratio, or reduce the clearance.")
        return

    # Peak force first, then whatever we're sorting by, then the rest.
    show = lookup.order_columns(cols or DEFAULT_COLUMNS, sort_by)
    # Rank the list from 1 (not 0); the "rank" index matches the inspector below.
    # Peak force is shown PER CYLINDER (divided by n_cyl); other columns are as-is.
    df = pd.DataFrame(
        {COLUMNS[k]: np.round(res[k] / n_cyl if k == "peak_force" else res[k], 3)
         for k in show},
        index=np.arange(1, n + 1))
    df.index.name = "rank"
    capped = f" — showing the top {n}" if total > n else ""
    st.markdown(f"**{total:,} matching configurations**{capped} (best "
                f"`{COLUMNS[sort_by]}` first). Every Problem, Mounting-limit and "
                f"filter setting changes this count. Peak force is shaded "
                f"green (low / good) → red (high).")
    styler = df.style.format(precision=3)
    peak_label = COLUMNS["peak_force"]
    if peak_label in df.columns:                   # green->red shade on peak force
        pv = df[peak_label].to_numpy(dtype=float)
        fin = pv[np.isfinite(pv)]
        plo, phi = (float(fin.min()), float(fin.max())) if fin.size else (0.0, 1.0)

        def _shade(col):
            styles = []
            for v in col:
                c = lookup.force_color(float(v), plo, phi)
                styles.append(f"background-color: {c}; color: #111" if c else "")
            return styles
        styler = styler.apply(_shade, subset=[peak_label])
    st.dataframe(styler, height=300, width="stretch")

    # --- Inspect one configuration (exact physics) ---
    st.subheader("Inspect a configuration")
    ic1, ic2 = st.columns([1, 1])
    rank = ic1.number_input("Rank to inspect (1 = top of the list)", 1, n, 1, 1,
                            key="lk_rank") - 1
    rank = int(np.clip(rank, 0, n - 1))   # guard if a filter shrank the list
    view_angle = ic2.slider("Diagram view angle (deg)", 0, 90, 45, 5, key="lk_view")
    a, b, d, f = (float(res["a"][rank]), float(res["b"][rank]),
                  float(res["d"][rank]), float(res["f"][rank]))
    peak_pc = float(res["peak_force"][rank]) / n_cyl        # per cylinder
    st.markdown(
        f"**a = {a:.3f}  b = {b:.3f}  d = {d:.3f}  f = {f:.3f} m** — "
        f"peak **{peak_pc:.2f} N/kg** per cylinder, stroke "
        f"{res['stroke'][rank]:.2f} m (ratio {res['stroke_ratio'][rank]:.2f})")
    total_kn, bar_fill, bar_color = lookup.force_bar(peak_pc, mass)
    st.caption(f"**Peak cylinder force at {mass:,.0f} kg:**")
    st.markdown(lookup.force_bar_html(bar_fill, lookup.BAR_NEUTRAL, f"{total_kn:.1f} kN"),
                unsafe_allow_html=True)
    # Same bore & pressure sizing card as the Designer, for the inspected force.
    pressure_bar, series = render_cylinder_sizing(peak_pc, mass, key_prefix="lk_")
    # The setup diagram is the main thing to read — show it large, on top.
    diag = _diagram_figure(a, b, d, f, x_cg, z_cg, width, height, view_angle,
                           fig_height=560)
    st.plotly_chart(diag, width="stretch")
    ff, fl = _force_length_figures(a, b, d, f, x_cg, z_cg, stroke_max)
    pf, pl = st.columns(2)
    pf.plotly_chart(ff, width="stretch")
    pl.plotly_chart(fl, width="stretch")

    # Same sensitivity panel as the Designer, for the inspected geometry. The
    # mounting-limit ranges bound each row; the inspected a, b, d, f mark the dot.
    sens_bar, sens_strip = render_sensitivity_panel(
        a, b, d, f, x_cg, z_cg, bounds, n_cyl=n_cyl,
        stroke_max=stroke_max, roof_clearance=clearance, width=width, height=height)

    # Same 2-D interaction map as the Designer: vary two of a, b, d, f (others fixed
    # at the inspected row), same rules (stroke ratio, roof, over-center).
    render_interaction_map(
        a, b, d, f, x_cg, z_cg, bounds, n_cyl=n_cyl,
        stroke_max=stroke_max, roof_clearance=clearance, width=width, height=height)

    # Same one-page PDF spec sheet as the Designer, for the inspected geometry.
    render_pdf_export(
        key="browse", size_key=size, n_cyl=n_cyl, x_cg=x_cg, z_cg=z_cg, mass=mass,
        stroke_ratio_max=stroke_max, roof_clearance=clearance,
        a=a, b=b, d=d, f=f, peak_pc=peak_pc,
        L_min=float(res["L_min"][rank]), L_max=float(res["L_max"][rank]),
        fig_geom=diag, fig_force=ff, fig_len=fl,
        fig_sens_bar=sens_bar, fig_sens_strip=sens_strip,
        pressure_bar=pressure_bar, series=series, sens_metric=selected_metric(),
        file_name="wall_actuator_config.pdf")

    # --- Refine to the exact continuous optimum for this query ---
    st.subheader("Get the exact optimum")
    if st.button("Get the exact optimum — run optimizer"):
        with st.spinner("Optimizing…"):
            opt = optimize_actuator(width, height, x_cg, z_cg,
                                    stroke_ratio_max=stroke_max,
                                    roof_clearance=clearance, var_bounds=bounds)
        grid_best = float(res["peak_force"].min()) / n_cyl
        st.success(
            f"Exact optimum: peak **{opt['peak_force'] / n_cyl:.2f} N/kg** per cylinder at "
            f"a = {opt['a']:.3f} b = {opt['b']:.3f} d = {opt['d']:.3f} f = {opt['f']:.3f} m "
            f"(grid best in the list was {grid_best:.2f}).")
