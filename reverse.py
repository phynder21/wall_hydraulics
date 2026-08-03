"""The 'Size from a cylinder' (reverse optimizer) view.

You enter a real hydraulic cylinder's specs; this finds the geometry that fits
the cylinder's length window AND needs the least force, then reports the largest
wall mass that cylinder can raise. Same precomputed table + optimizer as the
other views; some cylinders simply won't fit any geometry, which is flagged.
"""
import streamlit as st

from optimize import optimize_actuator
import lookup
import report
from browse import (_get_table, TABLE_RES, CONTAINERS, WIDTH, HEIGHT_MAX,
                    _diagram_figure, _force_length_figures, _sb_linked, _sb_range)
from sensitivity_panel import (render_sensitivity_panel, render_interaction_map,
                               selected_metric)
from pdf_export import render_pdf_export

# Per-unit spec for each cylinder input: (label, lo, hi, default, step, fmt,
# to_base) where to_base converts the shown value to the physics base unit —
# bore/rod -> mm, pressure -> bar, force -> N, closed/stroke -> m.
_CYL = {
    "Imperial": {
        "bore":   ("Bore diameter (in)", 0.75, 8.0, 2.5, 0.25, "%.2f", 25.4),
        "rod":    ("Rod diameter (in)", 0.4, 7.5, 1.5, 0.25, "%.2f", 25.4),
        "press":  ("Max pressure (psi)", 700.0, 5000.0, 2300.0, 50.0, "%.0f", 0.0689476),
        "frated": ("Rated push force (lbf)", 200.0, 70000.0, 11000.0, 100.0, "%.0f", 4.44822),
        "ret":    ("Closed length — retracted (in)", 4.0, 140.0, 28.0, 0.25, "%.2f", 0.0254),
        "stroke": ("Stroke — rod travel (in)", 2.0, 120.0, 20.0, 0.25, "%.2f", 0.0254),
    },
    "Metric": {
        "bore":   ("Bore diameter (mm)", 20.0, 200.0, 63.0, 1.0, "%.0f", 1.0),
        "rod":    ("Rod diameter (mm)", 10.0, 190.0, 36.0, 1.0, "%.0f", 1.0),
        "press":  ("Max pressure (bar)", 50.0, 350.0, 160.0, 5.0, "%.0f", 1.0),
        "frated": ("Rated push force (kN)", 1.0, 300.0, 50.0, 1.0, "%.1f", 1000.0),
        "ret":    ("Closed length — retracted (mm)", 100.0, 3500.0, 700.0, 5.0, "%.1f", 0.001),
        "stroke": ("Stroke — rod travel (mm)", 50.0, 3000.0, 500.0, 5.0, "%.1f", 0.001),
    },
}
_HELP = {
    "bore": "Inside diameter of the cylinder barrel. Bigger bore = more force at the same pressure.",
    "rod": "Diameter of the piston rod (used for the pull / retract force).",
    "press": "Highest hydraulic pressure the system runs at.",
    "frated": "The cylinder's push force straight from its datasheet, if you have it.",
    "ret": "Pin-to-pin length with the rod all the way in.",
    "stroke": "Rod travel. Extended length = closed length + stroke.",
}


def render_reverse():
    st.header("Size from a cylinder")
    # You enter ONE cylinder's spec; with n_cyl of them sharing the load they can
    # raise n_cyl times the wall mass (and the per-cylinder peak force is 1/n_cyl).
    n_cyl = int(st.session_state.get("n_cyl", 1))
    st.info(lookup.cylinder_banner(n_cyl))

    with st.spinner("Building the configuration database (first time only, ~15 s)…"):
        table = _get_table(TABLE_RES)

    # --- Units switch — at the TOP of the sidebar (above the tabs) so it's visible from
    # both the Cylinder and Wall tabs; converts stored cylinder values on flip. ---
    st.sidebar.markdown("<u>Units</u>", unsafe_allow_html=True)
    units = st.sidebar.radio("Units", ["Metric", "Imperial"], key="rv_units",
                             horizontal=True, label_visibility="collapsed")
    cfg = _CYL[units]
    prev = st.session_state.get("rv_units_prev")
    if prev is not None and prev != units:
        for k, spec in cfg.items():
            skey = f"rv_{k}"
            if skey in st.session_state:
                old_m, new_m = _CYL[prev][k][6], spec[6]
                lo, hi = spec[1], spec[2]
                st.session_state[skey] = float(
                    min(max(st.session_state[skey] * old_m / new_m, lo), hi))
    st.session_state["rv_units_prev"] = units
    len_fac, len_u = (39.37008, "in") if units == "Imperial" else (1000.0, "mm")
    fine = st.sidebar.toggle(
        "Fine precision", key="rv_fine",
        help="Finer steps and decimals in the cylinder AND wall inputs, so you can type "
             "exact sizes like a 20.25 in closed length instead of being rounded to 20.")
    # The wall geometry uses METRES / inches — the same length unit as the Designer and
    # Browse — so the Wall tab converts with the toggle but doesn't switch to the
    # cylinder's mm. (The cylinder inputs stay in mm/in, as datasheets quote them.)
    # Step/format track Fine.
    wall_fac, wall_u = (39.3700787, "in") if units == "Imperial" else (1.0, "m")
    if units == "Imperial":
        geo_step, geo_fmt = (0.05, "%.2f") if fine else (0.5, "%.1f")
    else:  # metres
        geo_step, geo_fmt = (0.01, "%.3f") if fine else (0.05, "%.2f")

    # Sidebar tabs (like the Designer): the Cylinder you enter, and the Wall it lifts.
    tab_cyl, tab_wall = st.sidebar.tabs(["Cylinder", "Wall"])

    def _cyl(k, ctx):
        """A cylinder input in the current units; returns (shown, base-unit value).
        With Fine precision on, use a 10x smaller step and an extra decimal so typed
        decimals (e.g. 20.25) are kept rather than rounded to a whole number."""
        label, lo, hi, default, step, fmt, mult = cfg[k]
        if fine:
            step = step / 10.0
            _dec = {"%.0f": 2, "%.1f": 2, "%.2f": 3, "%.3f": 3}.get(fmt, 2)
            fmt = f"%.{_dec}f"
        val = _sb_linked(label, f"rv_{k}", lo, hi, default, step, fmt=fmt,
                         help=_HELP[k], ctx=ctx)
        return val, val * mult

    # --- Cylinder force (Cylinder tab) ---
    tab_cyl.markdown("**Force**")
    mode = tab_cyl.radio("Give force as", ["Bore + pressure", "Rated force"],
                         key="rv_fmode", horizontal=True)
    if mode == "Bore + pressure":
        _, bore_mm = _cyl("bore", tab_cyl)
        _, rod_mm = _cyl("rod", tab_cyl)
        _, press_bar = _cyl("press", tab_cyl)
        push, pull = lookup.cylinder_force(bore_mm, min(rod_mm, bore_mm - 0.1), press_bar)
        tab_cyl.caption(f"Push **{push / 1000:.1f} kN** · Pull {pull / 1000:.1f} kN. "
                        "Raising the wall extends the cylinder, so push is used.")
        force_n = push
    else:
        _, force_n = _cyl("frated", tab_cyl)
    safety = _sb_linked("Safety factor", "rv_sf", 1.0, 3.0, 1.5, 0.1, fmt="%.1f",
                        help="Divide the cylinder force by this before sizing the "
                        "wall.", ctx=tab_cyl)
    force_use = force_n / safety

    # --- Cylinder length window (Cylinder tab) ---
    tab_cyl.markdown("**Length**")
    _, L_ret = _cyl("ret", tab_cyl)
    _, stroke_m = _cyl("stroke", tab_cyl)
    L_ext = L_ret + stroke_m
    tab_cyl.caption(f"Extended length **{L_ext * len_fac:.0f} {len_u}** "
                    f"(length ratio {L_ext / L_ret:.2f}).")

    # --- Wall / problem (Wall tab; the container and geometry are metric) ---
    size = tab_wall.selectbox("Container", list(CONTAINERS), key="rv_size")
    tab_wall.caption("**Internal (clear) dimensions** — the usable space inside the "
                     "container, not the outer shell.")
    width, height = CONTAINERS[size]
    x_cg = _sb_linked(f"x_cg — along wall from hinge ({wall_u})", "rv_xcg", 0.0,
                      HEIGHT_MAX, 1.20, 0.01, ctx=tab_wall, disp_factor=wall_fac,
                      disp_step=geo_step, fmt=geo_fmt)
    z_cg = _sb_linked(f"z_cg — off the wall ({wall_u})", "rv_zcg", 0.0, 1.5, 0.55, 0.01,
                      ctx=tab_wall, disp_factor=wall_fac, disp_step=geo_step, fmt=geo_fmt)
    clearance = _sb_linked(f"Roof clearance ({wall_u})", "rv_clear", 0.0, 0.5, 0.0, 0.01,
                           ctx=tab_wall, disp_factor=wall_fac, disp_step=geo_step,
                           fmt=geo_fmt)
    # Optional half-container cap on the base `a` AND the bracket offset `d` (see the
    # Designer): both stay in the near half of the container when on.
    half_a = tab_wall.checkbox("Keep base and bracket within half the container",
                               value=True, key="rv_half_a",
                               help="Caps a and d at half the width so the base and the "
                                    "attachment stay in the near half of the container. "
                                    "Uncheck to allow the full width.")
    _half = WIDTH / 2
    if half_a:
        tab_wall.caption(f"Active: **a ≤ {_half * wall_fac:.2f} {wall_u}** and **d ≤ "
                         f"{_half * wall_fac:.2f} {wall_u}** (half the "
                         f"{WIDTH * wall_fac:.2f} {wall_u} width).")
    else:
        tab_wall.caption(f"Off — **a** and **d** may use the full **{WIDTH * wall_fac:.2f} "
                         f"{wall_u}** width.")

    # --- Constrain the OUTCOME geometry (advanced; expander inside the Wall tab) ---
    ranges = {
        "a": (0.05, _half if half_a else WIDTH, f"a — base along floor ({wall_u})"),
        "b": (0.05, HEIGHT_MAX, f"b — attachment along wall ({wall_u})"),
        "d": (0.0, _half if half_a else WIDTH, f"d — bracket length ({wall_u})"),
        "f": (0.0, HEIGHT_MAX, f"f — base height ({wall_u})"),
    }
    bounds = {}
    with tab_wall.expander("Restrict the output geometry (a, b, d, f)", expanded=False):
        for v, (lo, hi, label) in ranges.items():
            bounds[v] = _sb_range(label, f"rv_rng_{v}", lo, hi, disp_factor=wall_fac,
                                  disp_step=geo_step, fmt=geo_fmt)

    # --- Solve: geometries whose cylinder length fits [L_ret, L_ext] ---
    res = lookup.cylinder_matches(table, height, x_cg, z_cg, L_ret, L_ext,
                                  bounds=bounds, roof_clearance=clearance, limit=5)
    n = res["peak_force"].size

    if n == 0:
        allrows = lookup.search(table, height, x_cg, z_cg, stroke_max=1e9,
                                roof_clearance=clearance, bounds=bounds, limit=1000000)
        st.error("### No geometry fits this cylinder")
        if allrows["peak_force"].size:
            lo = float(allrows["L_min"].min())
            hi = float(allrows["L_max"].max())
            st.markdown(
                f"No layout keeps the cylinder length inside your window "
                f"**{L_ret * len_fac:.1f}–{L_ext * len_fac:.1f} {len_u}** the whole "
                f"way up. Feasible layouts here need lengths somewhere in "
                f"**{lo * len_fac:.1f}–{hi * len_fac:.1f} {len_u}**. Try a longer "
                f"**stroke**, a different **closed length**, a bigger container, or "
                f"loosen the geometry limits.")
        else:
            st.markdown("Even ignoring the cylinder, no layout satisfies the "
                        "container + geometry limits. Loosen the geometry ranges "
                        "or the roof clearance.")
        return

    # --- Best geometry + the headline numbers ---
    a, b, d, f = (float(res["a"][0]), float(res["b"][0]),
                  float(res["d"][0]), float(res["f"][0]))
    peak = float(res["peak_force"][0])
    # n_cyl cylinders (each with this spec) share the load, so they raise n_cyl x
    # the mass; the per-cylinder peak force is peak / n_cyl.
    max_mass = force_use / peak * n_cyl    # safe: force already ÷ safety factor
    abs_mass = force_n / peak * n_cyl      # absolute: cylinder flat out, no margin

    m1, m2, m3 = st.columns(3)
    m1.metric(f"Safe max wall mass ({n_cyl} cyl)", f"{max_mass:,.0f} kg",
              help="The most you should load it — WITH your safety factor applied, "
                   "summed over all cylinders (n × cylinder force ÷ safety factor ÷ "
                   "peak force per kg).")
    m2.metric(f"Absolute max ({n_cyl} cyl)", f"{abs_mass:,.0f} kg",
              help="If every cylinder ran flat-out at 100% with no margin. The safe "
                   "figure is this ÷ your safety factor — use the safe one.")
    m3.metric("Peak force per cylinder", f"{peak / n_cyl:.2f} N/kg")
    st.markdown(
        f"**Best database match:** a = {a * wall_fac:.2f}  b = {b * wall_fac:.2f}  "
        f"d = {d * wall_fac:.2f}  f = {f * wall_fac:.2f} {wall_u} — its cylinder runs "
        f"**{res['L_min'][0] * len_fac:.1f}–{res['L_max'][0] * len_fac:.1f} {len_u}** "
        f"(inside your {L_ret * len_fac:.1f}–{L_ext * len_fac:.1f} {len_u} window). "
        f"{n if n < 5 else 'Many'} layouts fit; this is the lowest-force one **in the "
        f"precomputed grid** — a fast, only *near*-optimal pick. For the true best for "
        f"your exact inputs, run **Get the exact optimum** below.")

    # --- Plots: setup diagram large on top, curves small below ---
    stroke_ratio = float(res["stroke_ratio"][0])
    view_angle = st.slider("Diagram view angle (deg)", 0, 90, 45, 5, key="rv_view")
    diag = _diagram_figure(a, b, d, f, x_cg, z_cg, width, height, view_angle,
                           fig_height=560, scale=wall_fac, ulabel=wall_u)
    st.plotly_chart(diag, width="stretch")
    # Wall diagram is in metres/in; the cylinder-length plot stays in the cylinder unit
    # (mm/in) to match the closed/extended window. Force per cylinder to match the metric.
    ff, fl = _force_length_figures(
        a, b, d, f, x_cg, z_cg, stroke_ratio, u=len_fac, ulabel=len_u,
        pu=1.0 / n_cyl, plabel=f"N/kg{' per cyl' if n_cyl > 1 else ''}")
    pf, pl = st.columns(2)
    pf.plotly_chart(ff, width="stretch")
    pl.plotly_chart(fl, width="stretch")

    # Same sensitivity panel as the Designer, for the best-fit geometry. The
    # output-geometry limits bound each row; the chosen a, b, d, f mark the dot.
    sens_bar, sens_strip = render_sensitivity_panel(
        a, b, d, f, x_cg, z_cg, bounds, n_cyl=n_cyl,
        roof_clearance=clearance, width=width, height=height,
        length_window=(L_ret, L_ext))

    # Same 2-D interaction map: vary two of a, b, d, f (others fixed at the best fit).
    # Here "black" = a geometry whose cylinder length falls outside the cylinder you
    # entered, so the colored (feasible) region is the ring of designs THIS cylinder
    # can drive — lower force (blue) = more wall mass it can raise.
    render_interaction_map(
        a, b, d, f, x_cg, z_cg, bounds, n_cyl=n_cyl,
        roof_clearance=clearance, width=width, height=height,
        length_window=(L_ret, L_ext))

    # One-page PDF sheet: the cylinder you entered + the geometry it sized. The
    # cylinder is the input here (no bore-sizing card), so the mass shown is the
    # SAFE max this cylinder can raise, and the cylinder window is noted. The setup
    # table lists EVERY cylinder input — including bore/rod/pressure when the force was
    # given that way (so the sheet fully records what you entered).
    _cyl_rows = [
        ("Absolute max wall mass (no margin)", report.dual_mass(abs_mass)),
        ("Cylinder push force", report.dual_force(force_n)),
        ("Safety factor", f"{safety:g}x"),
        ("Cylinder length window",
         f"{L_ret * len_fac:.1f}-{L_ext * len_fac:.1f} {len_u}"),
    ]
    if mode == "Bore + pressure":
        _cyl_rows[1:1] = [                          # right after the push force
            ("Cylinder bore", report.dual_bore(bore_mm)),
            ("Rod diameter", report.dual_bore(rod_mm)),
            ("Design pressure", report.dual_pressure(press_bar)),
        ]
    render_pdf_export(
        key="reverse", size_key=size, n_cyl=n_cyl, x_cg=x_cg, z_cg=z_cg,
        mass=max_mass, stroke_ratio_max=stroke_ratio, roof_clearance=clearance,
        a=a, b=b, d=d, f=f, peak_pc=peak / n_cyl,
        L_min=float(res["L_min"][0]), L_max=float(res["L_max"][0]),
        fig_geom=diag, fig_force=ff, fig_len=fl,
        fig_sens_bar=sens_bar, fig_sens_strip=sens_strip,
        mass_label="Safe max wall mass", show_stroke_ratio_max=False,
        extra_setup_rows=_cyl_rows,
        extra_notes=["Safe max wall mass = cylinder push force / safety factor / "
                     "peak force per kg, summed over all cylinders. The absolute "
                     "max drops the safety factor — use the safe figure."],
        sens_metric=selected_metric(),
        title="Container Wall Actuator - Cylinder Sizing Report",
        file_name="wall_actuator_sizing.pdf",
        caption="A one-page sheet: the cylinder you entered and the geometry it "
                "sized, with forces and the curves. Click Generate to capture it.")

    # --- Refine to the exact optimum for this cylinder ---
    st.subheader("Get the exact optimum")
    st.caption("Two results, two methods: the **best database match** above is picked "
               "instantly from a precomputed *grid* of geometries (fast, but the grid "
               "only lands *near* the ideal). This button runs the **actual optimizer** "
               "to find the **best-possible geometry for your parameters** — the true "
               "continuous optimum, usually a little better — and tells you how far the "
               "grid was off. (Same idea as Browse's 'Get the exact optimum'.)")
    if st.button("Get the exact optimum — run optimizer"):
        with st.spinner("Optimizing…"):
            opt = optimize_actuator(width, height, x_cg, z_cg,
                                    length_window=(L_ret, L_ext), stroke_ratio_max=3.0,
                                    roof_clearance=clearance, var_bounds=bounds)
        if opt["feasible"]:
            st.success(
                f"**Best-possible geometry for your parameters:** peak "
                f"**{opt['peak_force'] / n_cyl:.2f} N/kg** per cylinder → safe max "
                f"**{force_use / opt['peak_force'] * n_cyl:,.0f} kg** at "
                f"a = {opt['a'] * wall_fac:.2f} b = {opt['b'] * wall_fac:.2f} "
                f"d = {opt['d'] * wall_fac:.2f} f = {opt['f'] * wall_fac:.2f} {wall_u} — "
                f"the exact optimum for your exact cylinder (the database match above gave "
                f"{max_mass:,.0f} kg).")
        else:
            st.warning("The optimizer couldn't find a geometry that fits the exact "
                       "cylinder window here — the grid match above is the closest.")
