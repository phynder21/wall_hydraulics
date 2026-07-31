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
from display_units import Units
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

# Columns offerable in the results table. Their display LABELS (with units) are built
# per-render in render_browse so they follow the Imperial/Metric toggle; here we only
# fix the default selection (keys).
DEFAULT_COLUMNS = ["peak_force", "a", "b", "d", "f", "stroke", "stroke_ratio"]


@st.cache_resource(show_spinner=False)
def _get_table(res):
    """Build the lookup table once per process (cached across reruns)."""
    return lookup_build.build_table(res=res)[0]


def _force_length_figures(a, b, d, f, x_cg, z_cg, stroke_max, u=1.0, ulabel="m",
                          pu=1.0, plabel="N/kg"):
    """Exact force and length curves for one geometry, straight from wall.py. `u`/`pu`
    scale length / specific-force to the display unit (with labels ulabel/plabel)."""
    theta = np.linspace(0.0, np.pi / 2, 400)
    deg = np.degrees(theta)
    with np.errstate(divide="ignore", invalid="ignore"):
        F = compute_F_piston(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
    F = np.where(np.isfinite(F) & (np.abs(F) <= 50.0), F, np.nan)
    L = compute_cylinder_length(theta, a=a, b=b, d=d, f=f)

    ff = go.Figure()
    ff.add_trace(go.Scatter(x=deg, y=F * pu, mode="lines", name="F"))
    ff.update_layout(title="Piston force vs. angle (exact)",
                     xaxis_title="theta (deg)", yaxis_title=plabel,
                     height=320, margin=dict(l=10, r=10, t=40, b=10))
    fl = go.Figure()
    fl.add_trace(go.Scatter(x=deg, y=L * u, mode="lines", name="L"))
    fl.add_hline(y=float(L.min()) * u, line=dict(color="green", dash="dot"))
    fl.add_hline(y=stroke_max * float(L.min()) * u, line=dict(color="red", dash="dot"),
                 annotation_text=f"{stroke_max:g}x limit")
    fl.update_layout(title="Cylinder length vs. angle (exact)",
                     xaxis_title="theta (deg)", yaxis_title=ulabel,
                     height=320, margin=dict(l=10, r=10, t=40, b=10))
    return ff, fl


def _diagram_figure(a, b, d, f, x_cg, z_cg, width, height, theta_deg=45.0,
                    fig_height=360, scale=1.0, ulabel="m"):
    """Side-view of the geometry at one wall angle: container, wall/door, bracket,
    cylinder, and the key points (hinge, base, attachment, cg). `scale` converts the
    coordinates to the display unit (m->in)."""
    th = np.radians(theta_deg)
    geo = compute_geometry(th, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
    s = scale
    x_att, z_att = float(geo["attachment"][0]) * s, float(geo["attachment"][1]) * s
    x_cgw, z_cgw = float(geo["cg"][0]) * s, float(geo["cg"][1]) * s
    x_wb, z_wb = float(geo["wall_axis_at_b"][0]) * s, float(geo["wall_axis_at_b"][1]) * s
    xb, zb = -a * s, f * s                            # cylinder base
    W, H = width * s, height * s
    door = (H * np.cos(th), H * np.sin(th))
    fig = go.Figure()
    # Container steel shell around the internal clear space (width/height are internal),
    # so the mechanism reads as working inside the clear interior, not the outer box.
    shell_x, shell_zb, shell_zt = add_container_shell(fig, width, height, scale=s)
    # Invisible anchors at the shell's outer corners so autorange includes the shell.
    fig.add_trace(go.Scatter(x=[shell_x, shell_x], y=[shell_zb, shell_zt], mode="markers",
                             marker=dict(size=0.1, opacity=0), hoverinfo="skip",
                             showlegend=False))
    fig.add_hline(y=0, line=dict(color="lightgray", dash="dash"))
    fig.add_trace(go.Scatter(x=[0, -W, -W, 0], y=[0, 0, H, H],
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
                      xaxis_title=f"x ({ulabel})", yaxis_title=f"z ({ulabel})",
                      height=fig_height, margin=dict(l=10, r=10, t=40, b=10),
                      showlegend=False)
    fig.update_yaxes(scaleanchor="x", scaleratio=1)   # equal aspect ratio
    return fig


def _sb_linked(label, key, lo, hi, default, step, fmt="%.2f", help=None, ctx=None,
               disp_factor=1.0, disp_step=None):
    """Slider + typeable number box bound to one canonical value in
    st.session_state[key] (kept in BASE units). Renders into `ctx` (default the
    sidebar). `disp_factor` scales the canonical value for display (e.g. m->in): the
    widgets show value*factor and lo/hi*factor, converting edits back by dividing."""
    ctx = ctx if ctx is not None else st.sidebar
    Uf = disp_factor
    dstep = disp_step if disp_step is not None else step
    if key not in st.session_state:
        st.session_state[key] = float(default)
    skey, nkey = f"{key}__s", f"{key}__n"
    st.session_state[skey] = st.session_state[key] * Uf
    st.session_state[nkey] = st.session_state[key] * Uf

    def _from_s():
        st.session_state[key] = float(min(max(st.session_state[skey] / Uf, lo), hi))

    def _from_n():
        st.session_state[key] = float(min(max(st.session_state[nkey] / Uf, lo), hi))

    ctx.markdown(f"**{label}**")
    c1, c2 = ctx.columns([2, 1])
    c1.slider(label, lo * Uf, hi * Uf, step=dstep, key=skey, on_change=_from_s,
              help=help, label_visibility="collapsed")
    c2.number_input(label, min_value=lo * Uf, max_value=hi * Uf, step=dstep, key=nkey,
                    on_change=_from_n, format=fmt, label_visibility="collapsed")
    return st.session_state[key]


def _sb_range(label, key, full_lo, full_hi, step=0.01, fmt="%.2f", disp_factor=1.0,
              disp_step=None):
    """Sidebar range slider + typeable min/max number boxes, bound to a canonical
    (lo, hi) tuple in st.session_state[key] (BASE units). `disp_factor` scales for
    display (m->in); canonical (lo, hi) stay in base units."""
    Uf = disp_factor
    dstep = disp_step if disp_step is not None else step
    st.session_state.setdefault(key, (full_lo, full_hi))
    lo, hi = st.session_state[key]
    lo = min(max(lo, full_lo), full_hi)
    hi = min(max(hi, lo), full_hi)
    st.session_state[key] = (lo, hi)
    rk, lok, hik = f"{key}__r", f"{key}__lo", f"{key}__hi"
    st.session_state[rk] = (lo * Uf, hi * Uf)
    st.session_state[lok] = lo * Uf
    st.session_state[hik] = hi * Uf

    def _from_r():
        a, b = st.session_state[rk]
        st.session_state[key] = (a / Uf, b / Uf)

    def _from_box():
        a, b = st.session_state[lok] / Uf, st.session_state[hik] / Uf
        st.session_state[key] = (min(a, b), max(a, b))

    st.markdown(f"**{label}**")
    st.slider(label, full_lo * Uf, full_hi * Uf, step=dstep, key=rk, on_change=_from_r,
              label_visibility="collapsed")
    cc1, cc2 = st.columns(2)
    cc1.number_input("min", min_value=full_lo * Uf, max_value=full_hi * Uf, step=dstep,
                     key=lok, on_change=_from_box, format=fmt)
    cc2.number_input("max", min_value=full_lo * Uf, max_value=full_hi * Uf, step=dstep,
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

    # --- Display units — at the TOP of the sidebar (matches the Designer), visible
    # always. Shares the Designer's "units"/"fine" keys so the preference follows you
    # between views. Everything is stored in SI base units; this only affects display.
    st.sidebar.markdown("<u>Units</u>", unsafe_allow_html=True)
    units = st.sidebar.radio("Units", ["Metric", "Imperial"], key="units",
                             horizontal=True, label_visibility="collapsed")
    fine = st.sidebar.toggle(
        "Fine precision", key="fine",
        help="Finer slider / number steps for exact values (0.001 m / 0.01 in).")
    _u = Units(units, fine)
    U, ULABEL, PU, PLABEL = _u.U, _u.ULABEL, _u.PU, _u.PLABEL
    MU, MLABEL, LEN_STEP, LEN_FMT = _u.MU, _u.MLABEL, _u.LEN_STEP, _u.LEN_FMT

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
    # Optional half-container cap on the base `a` AND the bracket offset `d` (see the
    # Designer): both stay in the near half of the container when on.
    half_a = st.sidebar.checkbox("Keep base and bracket within half the container",
                                 value=True, key="lk_half_a",
                                 help="Caps a and d at half the width so the base and "
                                      "the attachment stay in the near half of the "
                                      "container. Uncheck to allow the full width.")
    _half = WIDTH / 2
    if half_a:
        st.sidebar.caption(f"Active: **a ≤ {_half * U:.2f} {ULABEL}** and **d ≤ "
                           f"{_half * U:.2f} {ULABEL}** (half the {WIDTH * U:.2f} "
                           f"{ULABEL} width).")
    else:
        st.sidebar.caption(f"Off — **a** and **d** may use the full **{WIDTH * U:.2f} "
                           f"{ULABEL}** width. (The precomputed table only covers up to "
                           f"half the width; for wider layouts use the Designer.)")
    x_cg = _sb_linked(f"x_cg — along wall from hinge ({ULABEL})", "lk_xcg",
                      0.0, HEIGHT_MAX, 1.20, 0.01, disp_factor=U, disp_step=LEN_STEP,
                      fmt=LEN_FMT)
    z_cg = _sb_linked(f"z_cg — off the wall ({ULABEL})", "lk_zcg", 0.0, 1.5, 0.55, 0.01,
                      disp_factor=U, disp_step=LEN_STEP, fmt=LEN_FMT)
    stroke_max = _sb_linked(
        "Max stroke ratio", "lk_stroke", 1.0, 3.0, float(STROKE_RATIO_MAX), 0.05,
        help="Hard cap: only designs with L_max/L_min at or below this appear. "
             "Real hydraulic cylinders are typically ~1.8–2×.")
    clearance = _sb_linked(
        f"Roof clearance ({ULABEL})", "lk_clear", 0.0, 0.5, 0.0, 0.01,
        disp_factor=U, disp_step=LEN_STEP, fmt=LEN_FMT,
        help="Keep the piston attachment this far below the roof.")
    mass = _sb_linked(f"Wall + load mass ({MLABEL})", "lk_mass", 50.0, 20000.0, 500.0,
                      10.0, disp_factor=MU, disp_step=10.0, fmt="%.0f",
                      help="Converts the per-mass peak force into the real cylinder "
                           "force (shown for the inspected design).")

    ranges = {
        "a": (0.05, _half if half_a else WIDTH, f"a — base along floor ({ULABEL})"),
        "b": (0.05, HEIGHT_MAX, f"b — attachment along wall ({ULABEL})"),
        "d": (0.0, _half if half_a else WIDTH, f"d — bracket length ({ULABEL})"),
        "f": (0.0, HEIGHT_MAX, f"f — base height ({ULABEL})"),
    }
    bounds = {}
    with st.sidebar.expander("Mounting limits", expanded=False):
        for v, (lo, hi, label) in ranges.items():
            bounds[v] = _sb_range(label, f"lk_rng_{v}", lo, hi, disp_factor=U,
                                  disp_step=LEN_STEP, fmt=LEN_FMT)

    # Unit-aware column labels (lengths -> ULABEL, peak force -> PLABEL); the length
    # columns and peak force are converted to the display unit when the table is built.
    columns = {
        "peak_force": f"peak force ({PLABEL})",
        "a": f"a ({ULABEL})", "b": f"b ({ULABEL})", "d": f"d ({ULABEL})",
        "f": f"f ({ULABEL})", "stroke": f"stroke ({ULABEL})",
        "stroke_ratio": "stroke ratio",
        "L_min": f"retracted ({ULABEL})", "L_max": f"extended ({ULABEL})",
        "moment_arm": "over-center margin",
    }
    _LEN_COLS = {"a", "b", "d", "f", "stroke", "L_min", "L_max"}

    def _col_display(k, arr):
        """A table column's values in the display unit (per cylinder for force)."""
        if k == "peak_force":
            return arr / n_cyl * PU
        return arr * U if k in _LEN_COLS else arr

    # --- Filter / sort controls (main area) ---
    with st.expander("Columns, extra filters & sorting", expanded=True):
        cols = st.multiselect("Columns to show", list(columns),
                              default=DEFAULT_COLUMNS,
                              format_func=lambda k: columns[k], key="lk_cols")
        c1, c2, c3 = st.columns(3)
        sort_by = c1.selectbox("Sort by", list(columns),
                               format_func=lambda k: columns[k], key="lk_sort")
        ascending = c2.radio("Order", ["ascending", "descending"],
                             key="lk_order") == "ascending"
        top_n = c3.number_input("Show top", 10, 1000, 100, 10, key="lk_top")
        # A RESULT cap only. Every GEOMETRY value (a, b, d, f) has its own min AND
        # max in the sidebar's "Mounting limits" — that's the single place to bound
        # the geometry, so we don't duplicate f/d caps here.
        max_force_disp = st.number_input(
            f"Max peak force ({PLABEL}) — 0 = no cap", 0.0, 500.0, 0.0, 1.0,
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
    if max_force_disp > 0:
        # Entered per cylinder in the display unit; the table stores whole-wall N/kg.
        filters["peak_force"] = (None, max_force_disp / PU * n_cyl)

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
    # Peak force is shown PER CYLINDER; lengths and force are in the display unit.
    df = pd.DataFrame(
        {columns[k]: np.round(_col_display(k, res[k]), 3) for k in show},
        index=np.arange(1, n + 1))
    df.index.name = "rank"
    capped = f" — showing the top {n}" if total > n else ""
    st.markdown(f"**{total:,} matching configurations**{capped} (best "
                f"`{columns[sort_by]}` first). Every Problem, Mounting-limit and "
                f"filter setting changes this count. Peak force is shaded "
                f"green (low / good) → red (high).")
    styler = df.style.format(precision=3)
    peak_label = columns["peak_force"]
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
        f"**a = {a * U:.3f}  b = {b * U:.3f}  d = {d * U:.3f}  f = {f * U:.3f} "
        f"{ULABEL}** — peak **{_u.pk(peak_pc)}** per cylinder, stroke "
        f"{res['stroke'][rank] * U:.2f} {ULABEL} "
        f"(ratio {res['stroke_ratio'][rank]:.2f})")
    _total, bar_fill, bar_color = lookup.force_bar(peak_pc, mass)
    st.caption(f"**Peak cylinder force at {_u.mass(mass)}:**")
    st.markdown(lookup.force_bar_html(bar_fill, lookup.BAR_NEUTRAL,
                                      _u.total(peak_pc * mass)), unsafe_allow_html=True)
    # Same bore & pressure sizing card as the Designer, tied to the units toggle.
    pressure_bar, series = render_cylinder_sizing(peak_pc, mass, key_prefix="lk_",
                                                  imperial=_u.imperial)
    # The setup diagram is the main thing to read — show it large, on top.
    diag = _diagram_figure(a, b, d, f, x_cg, z_cg, width, height, view_angle,
                           fig_height=560, scale=U, ulabel=ULABEL)
    st.plotly_chart(diag, width="stretch")
    # Force is shown PER CYLINDER (pu carries the ÷ n_cyl) to match the readout/banner.
    ff, fl = _force_length_figures(
        a, b, d, f, x_cg, z_cg, stroke_max, u=U, ulabel=ULABEL, pu=PU / n_cyl,
        plabel=f"{PLABEL}{' per cyl' if n_cyl > 1 else ''}")
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
            f"Exact optimum: peak **{_u.pk(opt['peak_force'] / n_cyl)}** per cylinder at "
            f"a = {opt['a'] * U:.3f} b = {opt['b'] * U:.3f} d = {opt['d'] * U:.3f} "
            f"f = {opt['f'] * U:.3f} {ULABEL} "
            f"(grid best in the list was {_u.pk(grid_best)}).")
