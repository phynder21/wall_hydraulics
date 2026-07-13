"""The 'Size from a cylinder' (reverse optimizer) view.

You enter a real hydraulic cylinder's specs; this finds the geometry that fits
the cylinder's length window AND needs the least force, then reports the largest
wall mass that cylinder can raise. Same precomputed table + optimizer as the
other views; some cylinders simply won't fit any geometry, which is flagged.
"""
import streamlit as st

from optimize import optimize_actuator
import lookup
from browse import (_get_table, TABLE_RES, CONTAINERS, WIDTH, HEIGHT_MAX,
                    _diagram_figure, _force_length_figures, _sb_linked, _sb_range)

# Per-unit spec for each cylinder input: (label, lo, hi, default, step, fmt,
# to_base) where to_base converts the shown value to the physics base unit —
# bore/rod -> mm, pressure -> bar, force -> N, closed/stroke -> m.
_CYL = {
    "Imperial": {
        "bore":   ("Bore diameter (in)", 0.75, 8.0, 2.5, 0.25, "%.2f", 25.4),
        "rod":    ("Rod diameter (in)", 0.4, 7.5, 1.5, 0.25, "%.2f", 25.4),
        "press":  ("Max pressure (psi)", 700.0, 5000.0, 2300.0, 50.0, "%.0f", 0.0689476),
        "frated": ("Rated push force (lbf)", 200.0, 70000.0, 11000.0, 100.0, "%.0f", 4.44822),
        "ret":    ("Closed length — retracted (in)", 4.0, 140.0, 28.0, 1.0, "%.0f", 0.0254),
        "stroke": ("Stroke — rod travel (in)", 2.0, 120.0, 20.0, 1.0, "%.0f", 0.0254),
    },
    "Metric": {
        "bore":   ("Bore diameter (mm)", 20.0, 200.0, 63.0, 1.0, "%.0f", 1.0),
        "rod":    ("Rod diameter (mm)", 10.0, 190.0, 36.0, 1.0, "%.0f", 1.0),
        "press":  ("Max pressure (bar)", 50.0, 350.0, 160.0, 5.0, "%.0f", 1.0),
        "frated": ("Rated push force (kN)", 1.0, 300.0, 50.0, 1.0, "%.1f", 1000.0),
        "ret":    ("Closed length — retracted (mm)", 100.0, 3500.0, 700.0, 10.0, "%.0f", 0.001),
        "stroke": ("Stroke — rod travel (mm)", 50.0, 3000.0, 500.0, 10.0, "%.0f", 0.001),
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

    with st.spinner("Building the configuration database (first time only, ~15 s)…"):
        table = _get_table(TABLE_RES)

    # --- Units switch: converts the stored values in place when you flip it. ---
    units = st.sidebar.radio("Units", ["Imperial", "Metric"], key="rv_units",
                             horizontal=True)
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

    def _cyl(k, ctx):
        """A cylinder input in the current units; returns (shown, base-unit value)."""
        label, lo, hi, default, step, fmt, mult = cfg[k]
        val = _sb_linked(label, f"rv_{k}", lo, hi, default, step, fmt=fmt,
                         help=_HELP[k], ctx=ctx)
        return val, val * mult

    # --- Cylinder force ---
    force_exp = st.sidebar.expander("Cylinder — force", expanded=True)
    mode = force_exp.radio("Give force as", ["Bore + pressure", "Rated force"],
                           key="rv_fmode", horizontal=True)
    if mode == "Bore + pressure":
        _, bore_mm = _cyl("bore", force_exp)
        _, rod_mm = _cyl("rod", force_exp)
        _, press_bar = _cyl("press", force_exp)
        push, pull = lookup.cylinder_force(bore_mm, min(rod_mm, bore_mm - 0.1), press_bar)
        force_exp.caption(f"Push **{push / 1000:.1f} kN** · Pull {pull / 1000:.1f} kN. "
                          "Raising the wall extends the cylinder, so push is used.")
        force_n = push
    else:
        _, force_n = _cyl("frated", force_exp)
    safety = _sb_linked("Safety factor", "rv_sf", 1.0, 3.0, 1.5, 0.1, fmt="%.1f",
                        help="Divide the cylinder force by this before sizing the "
                        "wall.", ctx=force_exp)
    force_use = force_n / safety

    # --- Cylinder length window ---
    len_exp = st.sidebar.expander("Cylinder — length", expanded=True)
    _, L_ret = _cyl("ret", len_exp)
    _, stroke_m = _cyl("stroke", len_exp)
    L_ext = L_ret + stroke_m
    len_exp.caption(f"Extended length **{L_ext * len_fac:.0f} {len_u}** "
                    f"(length ratio {L_ext / L_ret:.2f}).")

    # --- Wall / problem (metric: the container and geometry are metric) ---
    wall_exp = st.sidebar.expander("Wall", expanded=True)
    size = wall_exp.selectbox("Container", list(CONTAINERS), key="rv_size")
    width, height = CONTAINERS[size]
    x_cg = _sb_linked("x_cg — along wall from hinge (m)", "rv_xcg", 0.0, HEIGHT_MAX,
                      1.20, 0.01, ctx=wall_exp)
    z_cg = _sb_linked("z_cg — off the wall (m)", "rv_zcg", 0.0, 1.5, 0.55, 0.01,
                      ctx=wall_exp)
    clearance = _sb_linked("Roof clearance (m)", "rv_clear", 0.0, 0.5, 0.0, 0.01,
                           ctx=wall_exp)

    # --- Constrain the OUTCOME geometry (mounting limits on a, b, d, f) ---
    ranges = {
        "a": (0.05, WIDTH / 2, "a — base along floor (m)"),
        "b": (0.05, HEIGHT_MAX, "b — attachment along wall (m)"),
        "d": (0.0, 1.0, "d — bracket length (m)"),
        "f": (0.0, HEIGHT_MAX, "f — base height (m)"),
    }
    bounds = {}
    with st.sidebar.expander("Restrict the output geometry (a, b, d, f)",
                             expanded=False):
        for v, (lo, hi, label) in ranges.items():
            bounds[v] = _sb_range(label, f"rv_rng_{v}", lo, hi)

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
    max_mass = force_use / peak            # safe: force already ÷ safety factor
    abs_mass = force_n / peak              # absolute: cylinder flat out, no margin

    m1, m2, m3 = st.columns(3)
    m1.metric("Safe max wall mass", f"{max_mass:,.0f} kg",
              help="The most you should load it — WITH your safety factor applied "
                   "(cylinder force ÷ safety factor ÷ peak force per kg).")
    m2.metric("Absolute cylinder max", f"{abs_mass:,.0f} kg",
              help="If the cylinder ran flat-out at 100% with no margin. The safe "
                   "figure is this ÷ your safety factor — use the safe one.")
    m3.metric("Peak force needed", f"{peak:.2f} N/kg")
    st.markdown(
        f"**Best geometry:** a={a:.3f}  b={b:.3f}  d={d:.3f}  f={f:.3f} m — its "
        f"cylinder runs **{res['L_min'][0] * len_fac:.1f}–{res['L_max'][0] * len_fac:.1f} {len_u}** "
        f"(inside your {L_ret * len_fac:.1f}–{L_ext * len_fac:.1f} {len_u} window). "
        f"{n if n < 5 else 'Many'} layouts fit; this is the lowest-force one.")

    # --- Plots: setup diagram large on top, curves small below ---
    stroke_ratio = float(res["stroke_ratio"][0])
    view_angle = st.slider("Diagram view angle (deg)", 0, 90, 45, 5, key="rv_view")
    diag = _diagram_figure(a, b, d, f, x_cg, z_cg, width, height, view_angle,
                           fig_height=560)
    st.plotly_chart(diag, width="stretch")
    ff, fl = _force_length_figures(a, b, d, f, x_cg, z_cg, stroke_ratio)
    pf, pl = st.columns(2)
    pf.plotly_chart(ff, width="stretch")
    pl.plotly_chart(fl, width="stretch")

    # --- Refine to the exact optimum for this cylinder ---
    st.subheader("Get the exact optimum")
    if st.button("Get the exact optimum — run optimizer"):
        with st.spinner("Optimizing…"):
            opt = optimize_actuator(width, height, x_cg, z_cg,
                                    length_window=(L_ret, L_ext), stroke_ratio_max=3.0,
                                    roof_clearance=clearance, var_bounds=bounds)
        if opt["feasible"]:
            st.success(
                f"Exact optimum: peak **{opt['peak_force']:.2f} N/kg** → safe max "
                f"**{force_use / opt['peak_force']:,.0f} kg** at a={opt['a']:.3f} "
                f"b={opt['b']:.3f} d={opt['d']:.3f} f={opt['f']:.3f} m "
                f"(grid best was {max_mass:,.0f} kg).")
        else:
            st.warning("The optimizer couldn't find a geometry that fits the exact "
                       "cylinder window here — the grid match above is the closest.")
