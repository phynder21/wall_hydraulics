"""NiceGUI front-end for the container wall actuator tool.

A parallel UI to the Streamlit app (app.py) — same physics and optimizer, a
different, snappier interface. It imports the SHARED core (wall.py, optimize.py)
so any change to the physics/optimizer benefits both UIs automatically; only the
presentation here is NiceGUI-specific.

Run locally:      python nicegui_app.py      (opens http://localhost:8080)
Public deploy:    see NICEGUI.md (Render one-click via render.yaml)

The Streamlit app (app.py) is untouched; this is a separate entry point with its
own dependency file (requirements-nicegui.txt).
"""
import os

import numpy as np
import plotly.graph_objects as go
from nicegui import ui, run, app

from wall import (STROKE_RATIO_MAX, compute_F_piston, compute_geometry,
                  compute_cylinder_length)
from optimize import optimize_actuator, CONTAINER_PRESETS
import lookup
import lookup_build

TABLE_RES = 40                 # lookup-table grid resolution (tests lower this)
_TABLE = {"data": None}        # process-wide cache (shared, read-only)


def get_table():
    if _TABLE["data"] is None:
        _TABLE["data"] = lookup_build.build_table(res=TABLE_RES)[0]
    return _TABLE["data"]

PRIMARY = "#2563EB"
PLOT_TEMPLATE = "plotly_white"
PLOT_FONT = dict(family="sans-serif", size=13, color="#0F172A")
F_CAP = 50.0   # N/kg; forces beyond this are "off the chart" near a singularity

# On narrow screens (phones), containers tagged `.stack` switch to a vertical
# layout and their children go full-width, so nothing overflows off-screen.
RESPONSIVE_CSS = """
<style>
@media (max-width: 820px) {
  .stack { flex-direction: column !important; }
  .stack > * { width: 100% !important; max-width: 100% !important; flex: 0 0 auto !important; }
  .q-page, body { overflow-x: hidden; }
}
</style>
"""

CONTAINERS = {
    "Standard (2.44 × 2.59 m)": CONTAINER_PRESETS["standard"],
    "High-Cube (2.44 × 2.90 m)": CONTAINER_PRESETS["highcube"],
}
WIDTH = CONTAINER_PRESETS["highcube"][0]
HEIGHT_MAX = CONTAINER_PRESETS["highcube"][1]     # tallest; fixes slider extents

DEFAULT_STATE = {
    "container": next(iter(CONTAINERS)),
    "a": 0.60, "b": 1.80, "d": 0.10, "f": 0.40,
    "x_cg": 1.20, "z_cg": 0.55, "theta_deg": 45.0,
    "stroke_ratio": STROKE_RATIO_MAX, "roof_clearance": 0.0,
    "units": "meters", "fine": False, "alt_pct": 15,
    "design_A": None, "design_B": None, "overlay": False,
}


def disp(units, fine):
    """Display factor/step/format for the current units + precision. Values are
    stored in METERS; this only governs how lengths are shown/entered."""
    inches = units == "inches"
    U = 39.3700787 if inches else 1.0
    ulabel = "in" if inches else "m"
    if inches:
        step, fmt = (0.01, "%.3f") if fine else (0.1, "%.2f")
    else:
        step, fmt = (0.001, "%.3f") if fine else (0.01, "%.2f")
    round_dp = 3 if fine else 2          # meters precision the optimizer snaps to
    return U, step, fmt, ulabel, round_dp


ANIM_STEP_DEG = 3.0     # degrees advanced per animation frame


def advance_angle(angle, direction, step=ANIM_STEP_DEG):
    """Next sweep angle, bouncing back at the 0 and 90 degree limits."""
    nxt = angle + direction * step
    if nxt >= 90.0:
        return 90.0, -1
    if nxt <= 0.0:
        return 0.0, 1
    return nxt, direction


# --- Pure computation + plot builders (no UI framework; reusable and testable)
def _force_curves(a, b, d, f, x_cg, z_cg, theta_deg):
    theta = np.linspace(0.0, np.pi / 2, 400)
    with np.errstate(divide="ignore", invalid="ignore"):
        F = compute_F_piston(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
        F_here = float(compute_F_piston(np.radians(theta_deg), a=a, b=b, d=d, f=f,
                                        x_cg=x_cg, z_cg=z_cg))
    usable = np.isfinite(F) & (np.abs(F) <= F_CAP)
    return theta, np.where(usable, F, np.nan), F[usable], F_here


def summary_metrics(a, b, d, f, x_cg, z_cg, theta_deg, stroke_ratio):
    theta, _, valid, F_here = _force_curves(a, b, d, f, x_cg, z_cg, theta_deg)
    peak = (max(abs(float(valid.min())), abs(float(valid.max())))
            if valid.size else float("nan"))
    L = compute_cylinder_length(np.linspace(0, np.pi / 2, 400), a=a, b=b, d=d, f=f)
    L_min, L_max = float(L.min()), float(L.max())
    L_here = float(compute_cylinder_length(np.radians(theta_deg), a=a, b=b, d=d, f=f))
    ratio = L_max / L_min if L_min > 0 else float("inf")
    return {"peak": peak, "here": F_here, "stroke": L_max - L_min,
            "ratio": ratio, "ok": ratio <= stroke_ratio,
            "L_min": L_min, "L_max": L_max, "L_here": L_here,
            "singular": valid.size < theta.size}


def force_figure(a, b, d, f, x_cg, z_cg, theta_deg, overlays=()):
    theta, F_plot, valid, F_here = _force_curves(a, b, d, f, x_cg, z_cg, theta_deg)
    deg = np.degrees(theta)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=deg, y=F_plot, mode="lines", name="F(θ)",
                             line=dict(color=PRIMARY, width=2.5)))
    fig.add_trace(go.Scatter(x=[theta_deg], y=[F_here], mode="markers",
                             marker=dict(size=13, color="red"), name="current"))
    for lab, dd, col in overlays:
        _, fp, _, _ = _force_curves(dd["a"], dd["b"], dd["d"], dd["f"],
                                    dd["x_cg"], dd["z_cg"], theta_deg)
        fig.add_trace(go.Scatter(x=deg, y=fp, mode="lines", name=lab,
                                 line=dict(color=col, width=2, dash="dash")))
    if valid.size:
        fmin, fmax = float(valid.min()), float(valid.max())
        fig.add_hline(y=fmin, line=dict(color="green", dash="dot"),
                      annotation_text=f"F_min = {fmin:.2f}")
        fig.add_hline(y=fmax, line=dict(color="red", dash="dot"),
                      annotation_text=f"F_max = {fmax:.2f}")
    fig.update_layout(template=PLOT_TEMPLATE, font=PLOT_FONT,
                      title="Piston force vs. wall angle",
                      xaxis_title="θ (deg)", yaxis_title="force (N/kg)",
                      xaxis=dict(range=[0, 90]), height=340, showlegend=bool(overlays),
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


def length_figure(a, b, d, f, theta_deg, stroke_ratio, u=1.0, ulabel="m", overlays=()):
    theta = np.linspace(0.0, np.pi / 2, 400)
    deg = np.degrees(theta)
    L = compute_cylinder_length(theta, a=a, b=b, d=d, f=f) * u
    L_here = float(compute_cylinder_length(np.radians(theta_deg), a=a, b=b, d=d, f=f)) * u
    L_min = float(L.min())
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=deg, y=L, mode="lines", name="L(θ)",
                             line=dict(color=PRIMARY, width=2.5)))
    fig.add_trace(go.Scatter(x=[theta_deg], y=[L_here], mode="markers",
                             marker=dict(size=13, color="red"), name="current"))
    for lab, dd, col in overlays:
        Ld = compute_cylinder_length(theta, a=dd["a"], b=dd["b"], d=dd["d"], f=dd["f"]) * u
        fig.add_trace(go.Scatter(x=deg, y=Ld, mode="lines", name=lab,
                                 line=dict(color=col, width=2, dash="dash")))
    fig.add_hline(y=L_min, line=dict(color="green", dash="dot"),
                  annotation_text=f"L_min = {L_min:.2f}")
    fig.add_hline(y=stroke_ratio * L_min, line=dict(color="red", dash="dot"),
                  annotation_text=f"{stroke_ratio:g}× limit")
    fig.update_layout(template=PLOT_TEMPLATE, font=PLOT_FONT,
                      title="Cylinder length vs. wall angle",
                      xaxis_title="θ (deg)", yaxis_title=f"length ({ulabel})",
                      xaxis=dict(range=[0, 90]), height=300, showlegend=bool(overlays),
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


def diagram_figure(a, b, d, f, x_cg, z_cg, theta_deg, width, height, roof_clearance,
                   u=1.0, ulabel="m"):
    theta = np.radians(theta_deg)
    geom = compute_geometry(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
    x_att, z_att = (float(v) * u for v in geom["attachment"])
    x_cgw, z_cgw = (float(v) * u for v in geom["cg"])
    xb, zb = (float(v) * u for v in geom["cylinder_base"])
    x_tip, z_tip = (float(v) * u for v in geom["wall_axis_at_b"])
    x_cgf, z_cgf = (float(v) * u for v in geom["wall_axis_at_xcg"])
    width, height, roof_clearance = width * u, height * u, roof_clearance * u
    x_door, z_door = height * np.cos(theta), height * np.sin(theta)
    pad = 0.5 * u
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[-width - pad, height + pad], y=[0, 0], mode="lines",
                             line=dict(color="lightgray", dash="dash"),
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=[0, -width, -width, 0], y=[0, 0, height, height],
                             mode="lines", line=dict(color="darkgray", width=3),
                             hoverinfo="skip", name="container"))
    if roof_clearance > 0:
        z_eff = height - roof_clearance
        fig.add_trace(go.Scatter(x=[-width, 0], y=[z_eff, z_eff], mode="lines",
                                 line=dict(color="firebrick", width=1, dash="dash"),
                                 hoverinfo="skip", name="effective ceiling"))
    fig.add_trace(go.Scatter(x=[0, x_door], y=[0, z_door], mode="lines",
                             line=dict(color="black", width=6), name="door"))
    fig.add_trace(go.Scatter(x=[x_tip, x_att], y=[z_tip, z_att], mode="lines",
                             line=dict(color="black", width=4), name="bracket"))
    fig.add_trace(go.Scatter(x=[x_cgf, x_cgw], y=[z_cgf, z_cgw], mode="lines",
                             line=dict(color="gray", width=1, dash="dot"),
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=[xb, xb], y=[0, zb], mode="lines",
                             line=dict(color="black", width=4), name="mounting post"))
    fig.add_trace(go.Scatter(x=[xb, x_att], y=[zb, z_att], mode="lines",
                             line=dict(color="orange", width=4), name="cylinder"))
    fig.add_trace(go.Scatter(x=[0], y=[0], mode="markers",
                             marker=dict(size=11, color="black"), name="hinge"))
    fig.add_trace(go.Scatter(x=[xb], y=[zb], mode="markers",
                             marker=dict(size=11, color="orange", symbol="square"),
                             name="cylinder base"))
    fig.add_trace(go.Scatter(x=[x_att], y=[z_att], mode="markers",
                             marker=dict(size=9, color="red"), name="attachment"))
    fig.add_trace(go.Scatter(x=[x_cgw], y=[z_cgw], mode="markers",
                             marker=dict(size=13, color="blue", symbol="cross"), name="cg"))
    fig.add_annotation(x=x_cgw, y=z_cgw - 0.35 * u, ax=x_cgw, ay=z_cgw,
                       xref="x", yref="y", axref="x", ayref="y", showarrow=True,
                       arrowhead=2, arrowsize=1, arrowwidth=2, arrowcolor="blue")
    fig.update_layout(template=PLOT_TEMPLATE, font=PLOT_FONT,
                      title=f"Side view (θ = {theta_deg:.0f}°)",
                      xaxis=dict(range=[-width - pad, height + pad], title=f"x ({ulabel})",
                                 zeroline=False),
                      yaxis=dict(range=[-pad, height + pad], title=f"z ({ulabel})",
                                 scaleanchor="x", scaleratio=1, zeroline=False),
                      height=440, legend=dict(orientation="h", y=-0.18),
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


# --- The page (per-client state so many public visitors stay independent) ----
@ui.page("/")
def index():
    ui.colors(primary=PRIMARY)
    ui.add_head_html(RESPONSIVE_CSS)
    s = dict(DEFAULT_STATE)
    # Restore this browser's last session (persists across reloads).
    saved = app.storage.user.get("wall_state")
    if isinstance(saved, dict):
        for k, v in saved.items():
            if k in DEFAULT_STATE or k.startswith(("rng_", "lock_")):
                s[k] = v
    guard = {"building": True}   # bound inputs fire on_change while being built;
                                 # ignore refresh until the plots exist.

    def save_state():
        app.storage.user["wall_state"] = {
            k: v for k, v in s.items()
            if k in DEFAULT_STATE or k.startswith(("rng_", "lock_"))}

    reseeding = {"v": False}     # suppress input on_change while we set values
    inputs = []                  # every linked control (for reseed / units re-scale)
    range_inputs = []            # mounting-limit range controls

    def refresh():
        if guard["building"]:
            return
        U, _, _, ulabel, _ = disp(s["units"], s["fine"])
        w, h = CONTAINERS[s["container"]]
        overlays = []
        if s["overlay"] and s["design_A"] and s["design_B"]:
            overlays = [("design A", s["design_A"], "green"),
                        ("design B", s["design_B"], "darkorange")]
        diag_plot.update_figure(diagram_figure(
            s["a"], s["b"], s["d"], s["f"], s["x_cg"], s["z_cg"], s["theta_deg"],
            w, h, s["roof_clearance"], U, ulabel))
        force_plot.update_figure(force_figure(
            s["a"], s["b"], s["d"], s["f"], s["x_cg"], s["z_cg"], s["theta_deg"], overlays))
        length_plot.update_figure(length_figure(
            s["a"], s["b"], s["d"], s["f"], s["theta_deg"], s["stroke_ratio"], U, ulabel,
            overlays))
        cmp_a.text = f"A (green): {_fmt_design(s['design_A'])}"
        cmp_b.text = f"B (orange): {_fmt_design(s['design_B'])}"
        if not s.get("_anim"):      # don't hit storage 20×/s during the sweep
            save_state()
        m = summary_metrics(s["a"], s["b"], s["d"], s["f"], s["x_cg"], s["z_cg"],
                            s["theta_deg"], s["stroke_ratio"])
        peak_m.text = f"{m['peak']:.2f} N/kg"
        here_m.text = f"{m['here']:.2f} N/kg"
        stroke_m.text = f"{m['stroke'] * U:.2f} {ulabel}"
        ratio_m.text = f"{m['ratio']:.2f}" + ("  ✓" if m["ok"] else "  ⚠ over")
        sing_cap.text = ("⚠️ Part of the swing needs more than "
                         f"{F_CAP:.0f} N/kg (near-singular geometry) and is hidden "
                         "— the extremes shown are over the usable range only."
                         if m["singular"] else "")
        status = (f"within {s['stroke_ratio']:g}× limit" if m["ok"]
                  else f"EXCEEDS {s['stroke_ratio']:g}× stroke limit")
        summary_cap.text = (
            f"At θ = {s['theta_deg']:.0f}°: force = {m['here']:.2f} N/kg, "
            f"length = {m['L_here'] * U:.2f} {ulabel}.  Across 0–90°: "
            f"L_min = {m['L_min'] * U:.2f}, L_max = {m['L_max'] * U:.2f}, "
            f"stroke = {m['stroke'] * U:.2f} {ulabel} (ratio {m['ratio']:.2f}, {status}).")

    def _eff_hi(hi_m, hcap):
        # container-height cap (like Streamlit's GEOM_BOUNDS) so b/f/x_cg can't
        # exceed the selected container.
        return min(hi_m, CONTAINERS[s["container"]][1]) if hcap else hi_m

    def linked(base, key, lo_m, hi_m, is_length=True, lockable=False, hcap=False):
        """Slider + number box for one value, stored in METERS at s[key]. hcap caps
        the upper bound at the current container height. lockable adds a 🔒."""
        U, step, fmt, ulabel, _ = disp(s["units"], s["fine"])
        du, st_, ft = (U, step, fmt) if is_length else (1.0, 1.0, "%.0f")
        hc = hcap and is_length
        ehi = _eff_hi(hi_m, hc)
        s[key] = min(max(s[key], lo_m), ehi)
        lbl = ui.label(f"{base} ({ulabel})" if is_length else base).classes("text-sm mt-2 mb-0")
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            sld = ui.slider(min=lo_m * du, max=ehi * du, step=st_, value=s[key] * du
                            ).props("label-always").classes("grow")
            num = ui.number(min=lo_m * du, max=ehi * du, step=st_, value=s[key] * du,
                            format=ft).classes("w-24")
            if lockable:
                s.setdefault(f"lock_{key}", False)
                ui.checkbox("🔒").bind_value(s, f"lock_{key}").props("dense") \
                    .tooltip("Hold this value fixed when you press Optimize")

        def commit(value):
            uu = disp(s["units"], s["fine"])[0] if is_length else 1.0
            hi = _eff_hi(hi_m, hc)
            value = min(max(value if value is not None else s[key] * uu,
                            lo_m * uu), hi * uu)
            reseeding["v"] = True
            sld.value = num.value = value
            reseeding["v"] = False
            s[key] = value / uu
            refresh()

        sld.on_value_change(lambda: reseeding["v"] or commit(sld.value))
        num.on_value_change(lambda: reseeding["v"] or commit(num.value))
        inputs.append({"slider": sld, "number": num, "key": key, "lo": lo_m,
                       "hi": hi_m, "base": base, "label": lbl,
                       "is_length": is_length, "hcap": hc})
        return sld

    def apply_units():
        """Re-scale every control to the current units + precision (lengths only)."""
        U, step, fmt, ulabel, _ = disp(s["units"], s["fine"])
        reseeding["v"] = True
        for li in inputs:
            uu = U if li["is_length"] else 1.0
            st_ = step if li["is_length"] else 1.0
            for el in (li["slider"], li["number"]):
                el._props["min"] = li["lo"] * uu
                el._props["max"] = li["hi"] * uu
                el._props["step"] = st_
                el.value = s[li["key"]] * uu
                el.update()
            li["label"].text = (f'{li["base"]} ({ulabel})' if li["is_length"]
                                else li["base"])
        for ri in range_inputs:
            lo, hi = s[f"rng_{ri['key']}"]
            rng = ri["range"]
            rng._props["min"] = ri["full_lo"] * U
            rng._props["max"] = ri["full_hi"] * U
            rng._props["step"] = step
            rng.value = {"min": lo * U, "max": hi * U}
            rng.update()
            ri["label"].text = f'{ri["base"]} range ({ulabel})'
        reseeding["v"] = False
        refresh()

    def range_control(base, key, full_lo, full_hi, hcap=False):
        """Mounting-limit [min, max] range, stored in METERS at s['rng_<key>'].
        Narrowing restricts the optimizer AND the value slider; hcap caps the
        extent at the container height."""
        s.setdefault(f"rng_{key}", (full_lo, full_hi))
        U, step, fmt, ulabel, _ = disp(s["units"], s["fine"])
        fhi = _eff_hi(full_hi, hcap)
        lo, hi = s[f"rng_{key}"]
        lo = min(max(lo, full_lo), fhi); hi = min(max(hi, lo), fhi)
        s[f"rng_{key}"] = (lo, hi)
        lbl = ui.label(f"{base} range ({ulabel})").classes("text-xs mt-2 mb-0")
        rng = ui.range(min=full_lo * U, max=fhi * U, step=step,
                       value={"min": lo * U, "max": hi * U}).props("label-always").classes("w-full")

        def on_range():
            uu = disp(s["units"], s["fine"])[0]
            cap = _eff_hi(full_hi, hcap)
            v = rng.value
            lo_m, hi_m = v["min"] / uu, v["max"] / uu
            if hi_m - lo_m < 0.01:                       # keep a non-zero window
                hi_m = min(lo_m + 0.01, cap)
                lo_m = max(hi_m - 0.01, full_lo)
            s[f"rng_{key}"] = (lo_m, hi_m)
            gi = next((x for x in inputs if x["key"] == key), None)
            if gi:                                       # restrict the value slider
                gi["lo"], gi["hi"] = lo_m, hi_m
                s[key] = min(max(s[key], lo_m), hi_m)
            apply_units()

        rng.on_value_change(lambda: reseeding["v"] or on_range())
        range_inputs.append({"range": rng, "key": key, "full_lo": full_lo,
                             "full_hi": full_hi, "base": base, "label": lbl,
                             "hcap": hcap})
        return rng

    def set_value(key, meters):
        """Set one control's value from meters (used by the sweep animation)."""
        li = next(x for x in inputs if x["key"] == key)
        uu = disp(s["units"], s["fine"])[0] if li["is_length"] else 1.0
        s[key] = meters
        reseeding["v"] = True
        li["slider"].value = li["number"].value = meters * uu
        reseeding["v"] = False

    def load_alt(x):
        """Load a near-optimal alternative geometry into the a/b/d/f controls."""
        for k in ("a", "b", "d", "f"):
            set_value(k, float(x[k]))
        refresh()

    def _fmt_design(dd):
        if not dd:
            return "empty"
        U = disp(s["units"], s["fine"])[0]
        ul = disp(s["units"], s["fine"])[3]
        return (f"a={dd['a'] * U:.2f} b={dd['b'] * U:.2f} d={dd['d'] * U:.2f} "
                f"f={dd['f'] * U:.2f} {ul}")

    def save_design(tag):
        s[f"design_{tag}"] = {k: s[k] for k in ("a", "b", "d", "f", "x_cg", "z_cg")}
        refresh()

    def clear_design(tag):
        s[f"design_{tag}"] = None
        refresh()

    anim = {"dir": 1}

    def sweep_tick():
        new, anim["dir"] = advance_angle(s["theta_deg"], anim["dir"])
        set_value("theta_deg", new)
        refresh()

    def metric(title):
        with ui.column().classes("items-center gap-0"):
            ui.label(title).classes("text-xs text-gray-500")
            return ui.label("—").classes("text-xl font-semibold")

    async def do_optimize():
        opt_btn.disable()
        opt_status.text = "Optimizing… (~20 s)"
        try:
            w, h = CONTAINERS[s["container"]]
            U, _, _, ulabel, round_dp = disp(s["units"], s["fine"])
            # Locked variables are held fixed; only the rest are searched.
            locked = {k: round(float(s[k]), round_dp)
                      for k in ("a", "b", "d", "f") if s.get(f"lock_{k}")}
            cb = {"a": (0.05, w / 2), "b": (0.05, h), "d": (0.0, 1.0), "f": (0.0, h)}
            var_bounds = {}
            for _k in ("a", "b", "d", "f"):
                _lo = max(s[f"rng_{_k}"][0], cb[_k][0])
                _hi = min(s[f"rng_{_k}"][1], cb[_k][1])
                var_bounds[_k] = (min(_lo, _hi), _hi)
            # io_bound (thread) rather than cpu_bound (process): no subprocess to
            # re-import this module, and numpy/scipy release the GIL during the
            # search so the event loop stays responsive.
            res = await run.io_bound(
                optimize_actuator, w, h, s["x_cg"], s["z_cg"],
                stroke_ratio_max=s["stroke_ratio"], roof_clearance=s["roof_clearance"],
                locked=locked, var_bounds=var_bounds, alt_rel_tol=s["alt_pct"] / 100.0,
                fast=True)
            for k in ("a", "b", "d", "f"):
                lo, hi = var_bounds[k]
                s[k] = float(min(max(round(float(res[k]), 4), lo), hi))
            apply_units()   # reseed the a/b/d/f controls from the new meters + refresh
            held = f" (held: {', '.join(sorted(locked))})" if locked else ""
            action = "Evaluated" if len(locked) == 4 else "Optimized"
            detail = (f"peak {res['peak_force']:.2f} N/kg, stroke ratio "
                      f"{res['stroke_ratio']:.2f}, roof breach "
                      f"{res['ceiling_violation'] * U:.3f} {ulabel}")
            if res.get("over_center"):
                msg, css, ntype = (
                    f"{action}{held}: OVER-CENTERS — the cylinder line crosses the "
                    "hinge so the force diverges and it can't be built. Unlock a "
                    "variable (or change the pinned values) and re-optimize.",
                    "text-sm text-red-600", "negative")
            elif res["feasible"]:
                msg, css, ntype = (f"{action}{held} — buildable, all limits met: "
                                   f"{detail}.", "text-sm text-green-700", "positive")
            else:
                msg, css, ntype = (f"{action}{held} — best buildable design, but not "
                                   f"all limits are met: {detail}.",
                                   "text-sm text-amber-600", "warning")
            opt_status.text = msg
            opt_status.classes(replace=css)
            ui.notify(action, type=ntype)

            # Clickable near-optimal alternatives (rebuilt each optimize).
            alts = res.get("alternatives", [])
            alts_box.clear()
            if len(alts) > 1:
                with alts_box:
                    ui.label(f"{len(alts) - 1} near-optimal alternatives "
                             "(click to load):").classes("text-sm mt-2")
                    for x in alts:
                        pen = x.get("penalty_pct", 0.0)
                        tag = "optimum" if pen < 1e-6 else f"+{pen:.1f}%"
                        lab = (f"a={x['a'] * U:.2f}  b={x['b'] * U:.2f}  "
                               f"d={x['d'] * U:.2f}  f={x['f'] * U:.2f} {ulabel}  — "
                               f"{x['peak_force']:.2f} N/kg ({tag})")
                        ui.button(lab, on_click=lambda e, xx=x: load_alt(xx)) \
                            .props("flat dense no-caps align=left").classes("w-full")
        except Exception as exc:
            opt_status.text = f"Optimizer failed: {exc}"
            ui.notify("Optimizer failed", type="negative")
        finally:
            opt_btn.enable()

    with ui.header().classes("items-center justify-between bg-primary text-white"):
        ui.label("Container wall actuator").classes("text-lg font-medium")
        ui.button("🔎 Browse configurations", on_click=lambda: ui.navigate.to("/browse")) \
            .props("flat color=white no-caps")

    with ui.row().classes("w-full no-wrap gap-4 p-2 stack"):
        # ---- Left: control panel with tabs --------------------------------
        with ui.card().classes("w-96 shrink-0"):
            with ui.tabs().classes("w-full") as tabs:
                ui.tab("Setup")
                ui.tab("Geometry")
                ui.tab("Optimize")
                ui.tab("Compare")
            with ui.tab_panels(tabs, value="Setup").classes("w-full"):
                with ui.tab_panel("Setup"):
                    ui.select(list(CONTAINERS), value=s["container"], label="Container",
                              on_change=lambda e: (s.__setitem__("container", e.value), apply_units())
                              ).classes("w-full")
                    with ui.row().classes("items-center gap-3 mt-1"):
                        ui.toggle({"meters": "m", "inches": "in"}, value=s["units"],
                                  on_change=lambda e: (s.__setitem__("units", e.value), apply_units())
                                  ).props("dense")
                        ui.switch("Fine precision", value=s["fine"],
                                  on_change=lambda e: (s.__setitem__("fine", e.value), apply_units()))
                    linked("x_cg — along wall", "x_cg", 0.0, HEIGHT_MAX, hcap=True)
                    linked("z_cg — off the wall", "z_cg", 0.0, 1.5)
                    ui.label("Max stroke ratio").classes("text-sm mt-2 mb-0")
                    ui.number(value=s["stroke_ratio"], min=1.0, max=3.0, step=0.05,
                              on_change=lambda e: (s.__setitem__("stroke_ratio", e.value), refresh())
                              ).classes("w-full")
                    linked("Roof clearance", "roof_clearance", 0.0, 0.5)
                with ui.tab_panel("Geometry"):
                    with ui.expansion("Variable ranges (mounting limits)").classes("w-full"):
                        ui.label("Narrow where a dimension may sit; the optimizer "
                                 "and its value slider stay within it.").classes("text-xs")
                        range_control("a — floor position", "a", 0.05, WIDTH / 2)
                        range_control("b — along wall", "b", 0.05, HEIGHT_MAX, hcap=True)
                        range_control("d — bracket length", "d", 0.0, 1.0)
                        range_control("f — base height", "f", 0.0, HEIGHT_MAX, hcap=True)
                    ga = linked("a — base along floor", "a", 0.05, WIDTH / 2, lockable=True)
                    gb = linked("b — attachment along wall", "b", 0.05, HEIGHT_MAX, lockable=True, hcap=True)
                    gd = linked("d — bracket length", "d", 0.0, 1.0, lockable=True)
                    gf = linked("f — base height", "f", 0.0, HEIGHT_MAX, lockable=True, hcap=True)
                    ui.separator()
                    linked("Wall angle θ (deg)", "theta_deg", 0.0, 90.0, is_length=False)
                    _sweep = ui.timer(0.05, sweep_tick, active=False)
                    ui.switch("▶ Sweep θ (0 → 90 → 0)",
                              on_change=lambda e: (setattr(_sweep, "active", bool(e.value)),
                                                   s.__setitem__("_anim", bool(e.value))))
                with ui.tab_panel("Optimize"):
                    ui.label("Find the a, b, d, f that minimize the worst-case "
                             "piston force for the current setup.").classes("text-sm")
                    ui.label("Show alternatives within __% of the optimum").classes("text-sm mt-2 mb-0")
                    ui.slider(min=0, max=30, step=1).props("label-always") \
                        .bind_value(s, "alt_pct").classes("w-full")
                    opt_btn = ui.button("Optimize geometry", on_click=do_optimize
                                        ).props("color=primary").classes("w-full")
                    opt_status = ui.label("").classes("text-sm text-gray-600")
                    alts_box = ui.column().classes("w-full gap-1")
                with ui.tab_panel("Compare"):
                    ui.label("Snapshot the current geometry as A or B, then "
                             "overlay both on the plots.").classes("text-sm")
                    with ui.row().classes("gap-2 w-full"):
                        ui.button("📌 Save as A", on_click=lambda: save_design("A")
                                  ).props("outline no-caps").classes("grow")
                        ui.button("📌 Save as B", on_click=lambda: save_design("B")
                                  ).props("outline no-caps").classes("grow")
                    with ui.row().classes("gap-2 w-full"):
                        ui.button("Clear A", on_click=lambda: clear_design("A")
                                  ).props("flat no-caps").classes("grow")
                        ui.button("Clear B", on_click=lambda: clear_design("B")
                                  ).props("flat no-caps").classes("grow")
                    cmp_a = ui.label("A (green): empty").classes("text-sm")
                    cmp_b = ui.label("B (orange): empty").classes("text-sm")
                    ui.switch("Overlay A & B on plots",
                              on_change=lambda: refresh()).bind_value(s, "overlay")

        # ---- Right: visualization -----------------------------------------
        with ui.column().classes("flex-1 gap-3"):
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full justify-around flex-wrap gap-2"):
                    peak_m = metric("Peak force (worst case)")
                    here_m = metric("Force at θ")
                    stroke_m = metric("Stroke")
                    ratio_m = metric("Stroke ratio")
            with ui.row().classes("w-full no-wrap gap-3 stack"):
                diag_plot = ui.plotly(diagram_figure(
                    s["a"], s["b"], s["d"], s["f"], s["x_cg"], s["z_cg"],
                    s["theta_deg"], *CONTAINERS[s["container"]], s["roof_clearance"])
                    ).classes("w-1/2")
                force_plot = ui.plotly(force_figure(
                    s["a"], s["b"], s["d"], s["f"], s["x_cg"], s["z_cg"], s["theta_deg"])
                    ).classes("w-1/2")
            length_plot = ui.plotly(length_figure(
                s["a"], s["b"], s["d"], s["f"], s["theta_deg"], s["stroke_ratio"])
                ).classes("w-full")
            sing_cap = ui.label("").classes("text-sm text-amber-600")
            summary_cap = ui.label("").classes("text-sm text-gray-600")

    guard["building"] = False   # layout complete; refresh may touch the plots now
    refresh()   # first paint of the metrics


BROWSE_COLS = ["peak_force", "a", "b", "d", "f", "stroke", "stroke_ratio"]
BROWSE_LABELS = {"peak_force": "peak (N/kg)", "a": "a", "b": "b", "d": "d",
                 "f": "f", "stroke": "stroke", "stroke_ratio": "ratio",
                 "L_min": "retracted", "L_max": "extended", "moment_arm": "OC margin"}


@ui.page("/browse")
def browse_page():
    ui.colors(primary=PRIMARY)
    ui.add_head_html(RESPONSIVE_CSS)
    b = {"container": next(iter(CONTAINERS)), "x_cg": 1.20, "z_cg": 0.55,
         "stroke": float(STROKE_RATIO_MAX), "clear": 0.0, "sort": "peak_force",
         "asc": True, "topn": 100, "max_f": 0.0, "max_d": 0.0, "results": None}

    with ui.header().classes("items-center justify-between bg-primary text-white"):
        ui.label("Browse configurations").classes("text-lg font-medium")
        ui.button("🛠 Designer", on_click=lambda: ui.navigate.to("/")) \
            .props("flat color=white no-caps")

    async def run_search():
        search_btn.disable()
        if _TABLE["data"] is None:
            ui.notify("Building the configuration database (first time, ~15 s)…")
            await run.io_bound(get_table)
        table = get_table()
        w, h = CONTAINERS[b["container"]]
        filters = {}
        if b["max_f"] > 0:
            filters["f"] = (None, b["max_f"])
        if b["max_d"] > 0:
            filters["d"] = (None, b["max_d"])
        res = lookup.search(table, h, b["x_cg"], b["z_cg"], stroke_max=b["stroke"],
                            roof_clearance=b["clear"], filters=filters,
                            sort_by=b["sort"], ascending=b["asc"], limit=int(b["topn"]))
        b["results"] = res
        n = res["peak_force"].size
        rows = [{"rank": i + 1, **{c: round(float(res[c][i]), 3) for c in BROWSE_COLS}}
                for i in range(n)]
        table_el.rows = rows
        table_el.update()
        count_lbl.text = f"{n} matching configurations" if n else "No matches — loosen the settings."
        rank_in.max = max(n, 1)
        inspect()
        search_btn.enable()

    def inspect():
        res = b["results"]
        if not res or res["peak_force"].size == 0:
            return
        i = int(min(max(rank_in.value or 1, 1), res["peak_force"].size)) - 1
        a, bb, d, f = (float(res["a"][i]), float(res["b"][i]),
                       float(res["d"][i]), float(res["f"][i]))
        pick_lbl.text = (f"#{i+1}:  a={a:.3f} b={bb:.3f} d={d:.3f} f={f:.3f} m  —  "
                         f"peak {float(res['peak_force'][i]):.2f} N/kg, "
                         f"ratio {float(res['stroke_ratio'][i]):.2f}")
        force_el.update_figure(force_figure(a, bb, d, f, b["x_cg"], b["z_cg"], 45.0))
        length_el.update_figure(length_figure(a, bb, d, f, 45.0, b["stroke"]))

    async def refine():
        w, h = CONTAINERS[b["container"]]
        ui.notify("Optimizing for the exact optimum…")
        opt = await run.io_bound(optimize_actuator, w, h, b["x_cg"], b["z_cg"],
                                 stroke_ratio_max=b["stroke"], roof_clearance=b["clear"], fast=True)
        ui.notify(f"Exact optimum: {opt['peak_force']:.2f} N/kg at a={opt['a']:.3f} "
                  f"b={opt['b']:.3f} d={opt['d']:.3f} f={opt['f']:.3f}", type="positive")

    with ui.row().classes("w-full no-wrap gap-4 p-2 stack"):
        with ui.card().classes("w-96 shrink-0"):
            ui.label("Problem").classes("font-medium")
            ui.select(list(CONTAINERS), label="Container").bind_value(b, "container")
            ui.number("x_cg (m)", min=0, max=HEIGHT_MAX, step=0.01).bind_value(b, "x_cg").classes("w-full")
            ui.number("z_cg (m)", min=0, max=1.5, step=0.01).bind_value(b, "z_cg").classes("w-full")
            ui.number("Max stroke ratio", min=1.0, max=3.0, step=0.05).bind_value(b, "stroke").classes("w-full")
            ui.number("Roof clearance (m)", min=0.0, max=0.5, step=0.01).bind_value(b, "clear").classes("w-full")
            ui.label("Filter / sort").classes("font-medium mt-2")
            ui.select({c: BROWSE_LABELS[c] for c in BROWSE_LABELS}, label="Sort by").bind_value(b, "sort")
            ui.switch("Ascending", value=True).bind_value(b, "asc")
            ui.number("Max base height f (0 = any)", min=0.0, max=3.0, step=0.05).bind_value(b, "max_f").classes("w-full")
            ui.number("Max bracket d (0 = any)", min=0.0, max=1.0, step=0.05).bind_value(b, "max_d").classes("w-full")
            ui.number("Show top N", min=10, max=1000, step=10).bind_value(b, "topn").classes("w-full")
            search_btn = ui.button("Search", on_click=run_search).props("color=primary").classes("w-full")

        with ui.column().classes("flex-1 gap-2"):
            count_lbl = ui.label("Set your query and press Search.").classes("text-sm")
            cols = [{"name": "rank", "label": "#", "field": "rank", "align": "left"}]
            cols += [{"name": c, "label": BROWSE_LABELS[c], "field": c} for c in BROWSE_COLS]
            table_el = ui.table(columns=cols, rows=[], row_key="rank").classes("w-full").props("dense")
            with ui.row().classes("items-center gap-2"):
                ui.label("Inspect rank")
                rank_in = ui.number(value=1, min=1, max=1, step=1,
                                    on_change=lambda: inspect()).classes("w-24")
                ui.button("Refine — exact optimizer", on_click=refine).props("outline no-caps")
            pick_lbl = ui.label("").classes("text-sm")
            with ui.row().classes("w-full no-wrap gap-2 stack"):
                force_el = ui.plotly(force_figure(0.6, 1.8, 0.1, 0.4, 1.2, 0.55, 45.0)).classes("w-1/2")
                length_el = ui.plotly(length_figure(0.6, 1.8, 0.1, 0.4, 45.0, 1.8)).classes("w-1/2")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)),
           title="Container Wall Actuator", reload=False, show=False,
           storage_secret=os.environ.get("STORAGE_SECRET", "wall-actuator-secret"))
