"""The 'Size from a cylinder' (reverse optimizer) view.

You enter a real hydraulic cylinder's specs; this finds the geometry that fits
the cylinder's length window AND needs the least force, then reports the largest
wall mass that cylinder can raise. Same precomputed table + optimizer as the
other views; some cylinders simply won't fit any geometry, which is flagged.
"""
import numpy as np
import streamlit as st

from optimize import optimize_actuator
import lookup

IN_TO_M, PSI_TO_BAR, LBF_TO_N, M_TO_IN = 0.0254, 0.0689476, 4.44822, 39.37008
from browse import (_get_table, TABLE_RES, CONTAINERS, WIDTH, HEIGHT_MAX,
                    _diagram_figure, _force_length_figures, _sb_linked, _sb_range)


def render_reverse():
    st.header("Size from a cylinder")

    with st.spinner("Building the configuration database (first time only, ~15 s)…"):
        table = _get_table(TABLE_RES)

    # --- Cylinder force ---
    force_exp = st.sidebar.expander("Cylinder — force", expanded=True)
    mode = force_exp.radio("Give force as", ["Bore + pressure", "Rated force"],
                           key="rv_fmode", horizontal=True)
    if mode == "Bore + pressure":
        bore = _sb_linked(
            "Bore diameter (in)", "rv_bore", 0.75, 8.0, 2.5, 0.25, fmt="%.2f",
            help="Inside diameter of the cylinder barrel. A bigger bore makes more "
                 "force at the same pressure.", ctx=force_exp)
        rod = _sb_linked(
            "Rod diameter (in)", "rv_rod", 0.4, 7.5, 1.5, 0.25, fmt="%.2f",
            help="Diameter of the piston rod (used for the pull / retract force).",
            ctx=force_exp)
        pressure = _sb_linked(
            "Max pressure (psi)", "rv_press", 700.0, 5000.0, 2300.0, 50.0, fmt="%.0f",
            help="Highest hydraulic pressure the system runs at.", ctx=force_exp)
        push, pull = lookup.cylinder_force(bore * 25.4, min(rod, bore - 0.01) * 25.4,
                                           pressure * PSI_TO_BAR)
        force_exp.caption(f"Push **{push / 1000:.1f} kN** · Pull {pull / 1000:.1f} kN. "
                          "Raising the wall extends the cylinder, so push is used.")
        force_n = push
    else:
        force_n = _sb_linked(
            "Rated push force (lbf)", "rv_frated", 200.0, 70000.0, 11000.0, 100.0,
            fmt="%.0f", help="The cylinder's push force straight from its "
            "datasheet, if you have it.", ctx=force_exp) * LBF_TO_N
    safety = _sb_linked("Safety factor", "rv_sf", 1.0, 3.0, 1.5, 0.1, fmt="%.1f",
                        help="Divide the cylinder force by this before sizing the "
                        "wall.", ctx=force_exp)
    force_use = force_n / safety

    # --- Cylinder length window ---
    len_exp = st.sidebar.expander("Cylinder — length", expanded=True)
    retracted = _sb_linked(
        "Closed length — fully retracted (in)", "rv_ret", 4.0, 140.0, 28.0, 1.0,
        fmt="%.0f", help="Pin-to-pin length with the rod all the way in.",
        ctx=len_exp)
    stroke = _sb_linked(
        "Stroke — how far the rod extends (in)", "rv_stroke", 2.0, 120.0, 20.0, 1.0,
        fmt="%.0f", help="Rod travel. Extended length = closed length + stroke.",
        ctx=len_exp)
    L_ret, L_ext = retracted * IN_TO_M, (retracted + stroke) * IN_TO_M
    len_exp.caption(f"Extended length **{retracted + stroke:.0f} in** "
                    f"(length ratio {L_ext / L_ret:.2f}).")

    # --- Wall / problem ---
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
        # Diagnose: what cylinder lengths ARE achievable here?
        allrows = lookup.search(table, height, x_cg, z_cg, stroke_max=1e9,
                                roof_clearance=clearance, bounds=bounds, limit=1000000)
        st.error("### No geometry fits this cylinder")
        if allrows["peak_force"].size:
            lo = float(allrows["L_min"].min())
            hi = float(allrows["L_max"].max())
            st.markdown(
                f"No layout keeps the cylinder length inside your window "
                f"**{L_ret * M_TO_IN:.1f}–{L_ext * M_TO_IN:.1f} in** the whole way "
                f"up. Feasible layouts here need lengths somewhere in "
                f"**{lo * M_TO_IN:.1f}–{hi * M_TO_IN:.1f} in**. Try a longer "
                f"**stroke**, a different **closed length**, a bigger container, or "
                f"geometry limits.")
        else:
            st.markdown("Even ignoring the cylinder, no layout satisfies the "
                        "container + geometry limits. Loosen the geometry ranges "
                        "or the roof clearance.")
        return

    # --- Best geometry + the headline: max wall mass ---
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
        f"cylinder runs **{res['L_min'][0] * M_TO_IN:.1f}–{res['L_max'][0] * M_TO_IN:.1f} in** "
        f"(inside your {L_ret * M_TO_IN:.1f}–{L_ext * M_TO_IN:.1f} in window). "
        f"{n if n < 5 else 'Many'} layouts fit; this is the lowest-force one.")

    # --- Plots: curves small on top, setup diagram large below ---
    stroke_ratio = float(res["stroke_ratio"][0])
    ff, fl = _force_length_figures(a, b, d, f, x_cg, z_cg, stroke_ratio)
    pf, pl = st.columns(2)
    pf.plotly_chart(ff, width="stretch")
    pl.plotly_chart(fl, width="stretch")
    view_angle = st.slider("Diagram view angle (deg)", 0, 90, 45, 5, key="rv_view")
    diag = _diagram_figure(a, b, d, f, x_cg, z_cg, width, height, view_angle,
                           fig_height=560)
    st.plotly_chart(diag, width="stretch")

    # --- Refine to the exact optimum for this cylinder ---
    st.subheader("Get the exact optimum")
    if st.button("Get the exact optimum — run optimizer"):
        with st.spinner("Optimizing…"):
            opt = optimize_actuator(width, height, x_cg, z_cg,
                                    length_window=(L_ret, L_ext), stroke_ratio_max=3.0,
                                    roof_clearance=clearance, var_bounds=bounds)
        if opt["feasible"]:
            st.success(
                f"Exact optimum: peak **{opt['peak_force']:.2f} N/kg** → raises up to "
                f"**{force_use / opt['peak_force']:,.0f} kg** at a={opt['a']:.3f} "
                f"b={opt['b']:.3f} d={opt['d']:.3f} f={opt['f']:.3f} m "
                f"(grid best raised {max_mass:,.0f} kg).")
        else:
            st.warning("The optimizer couldn't find a geometry that fits the exact "
                       "cylinder window here — the grid match above is the closest.")
