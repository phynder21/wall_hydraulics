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
from nicegui import ui, run

from wall import (STROKE_RATIO_MAX, compute_F_piston, compute_geometry,
                  compute_cylinder_length)
from optimize import optimize_actuator, CONTAINER_PRESETS

PRIMARY = "#2563EB"
PLOT_TEMPLATE = "plotly_white"
PLOT_FONT = dict(family="sans-serif", size=13, color="#0F172A")
F_CAP = 50.0   # N/kg; forces beyond this are "off the chart" near a singularity

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
}


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
    _, _, valid, F_here = _force_curves(a, b, d, f, x_cg, z_cg, theta_deg)
    peak = (max(abs(float(valid.min())), abs(float(valid.max())))
            if valid.size else float("nan"))
    L = compute_cylinder_length(np.linspace(0, np.pi / 2, 400), a=a, b=b, d=d, f=f)
    L_min, L_max = float(L.min()), float(L.max())
    ratio = L_max / L_min if L_min > 0 else float("inf")
    return {"peak": peak, "here": F_here, "stroke": L_max - L_min,
            "ratio": ratio, "ok": ratio <= stroke_ratio}


def force_figure(a, b, d, f, x_cg, z_cg, theta_deg):
    theta, F_plot, valid, F_here = _force_curves(a, b, d, f, x_cg, z_cg, theta_deg)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=np.degrees(theta), y=F_plot, mode="lines", name="F(θ)",
                             line=dict(color=PRIMARY, width=2.5)))
    fig.add_trace(go.Scatter(x=[theta_deg], y=[F_here], mode="markers",
                             marker=dict(size=13, color="red"), name="current"))
    if valid.size:
        fmin, fmax = float(valid.min()), float(valid.max())
        fig.add_hline(y=fmin, line=dict(color="green", dash="dot"),
                      annotation_text=f"F_min = {fmin:.2f}")
        fig.add_hline(y=fmax, line=dict(color="red", dash="dot"),
                      annotation_text=f"F_max = {fmax:.2f}")
    fig.update_layout(template=PLOT_TEMPLATE, font=PLOT_FONT,
                      title="Piston force vs. wall angle",
                      xaxis_title="θ (deg)", yaxis_title="force (N/kg)",
                      xaxis=dict(range=[0, 90]), height=340, showlegend=False,
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


def length_figure(a, b, d, f, theta_deg, stroke_ratio):
    theta = np.linspace(0.0, np.pi / 2, 400)
    L = compute_cylinder_length(theta, a=a, b=b, d=d, f=f)
    L_here = float(compute_cylinder_length(np.radians(theta_deg), a=a, b=b, d=d, f=f))
    L_min = float(L.min())
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=np.degrees(theta), y=L, mode="lines", name="L(θ)",
                             line=dict(color=PRIMARY, width=2.5)))
    fig.add_trace(go.Scatter(x=[theta_deg], y=[L_here], mode="markers",
                             marker=dict(size=13, color="red"), name="current"))
    fig.add_hline(y=L_min, line=dict(color="green", dash="dot"),
                  annotation_text=f"L_min = {L_min:.2f}")
    fig.add_hline(y=stroke_ratio * L_min, line=dict(color="red", dash="dot"),
                  annotation_text=f"{stroke_ratio:g}× limit")
    fig.update_layout(template=PLOT_TEMPLATE, font=PLOT_FONT,
                      title="Cylinder length vs. wall angle",
                      xaxis_title="θ (deg)", yaxis_title="length (m)",
                      xaxis=dict(range=[0, 90]), height=300, showlegend=False,
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


def diagram_figure(a, b, d, f, x_cg, z_cg, theta_deg, width, height, roof_clearance):
    theta = np.radians(theta_deg)
    geom = compute_geometry(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
    x_att, z_att = (float(v) for v in geom["attachment"])
    x_cgw, z_cgw = (float(v) for v in geom["cg"])
    xb, zb = (float(v) for v in geom["cylinder_base"])
    x_tip, z_tip = (float(v) for v in geom["wall_axis_at_b"])
    x_cgf, z_cgf = (float(v) for v in geom["wall_axis_at_xcg"])
    x_door, z_door = height * np.cos(theta), height * np.sin(theta)
    pad = 0.5
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
    fig.add_annotation(x=x_cgw, y=z_cgw - 0.35, ax=x_cgw, ay=z_cgw,
                       xref="x", yref="y", axref="x", ayref="y", showarrow=True,
                       arrowhead=2, arrowsize=1, arrowwidth=2, arrowcolor="blue")
    fig.update_layout(template=PLOT_TEMPLATE, font=PLOT_FONT,
                      title=f"Side view (θ = {theta_deg:.0f}°)",
                      xaxis=dict(range=[-width - pad, height + pad], title="x (m)",
                                 zeroline=False),
                      yaxis=dict(range=[-pad, height + pad], title="z (m)",
                                 scaleanchor="x", scaleratio=1, zeroline=False),
                      height=440, legend=dict(orientation="h", y=-0.18),
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


# --- The page (per-client state so many public visitors stay independent) ----
@ui.page("/")
def index():
    ui.colors(primary=PRIMARY)
    s = dict(DEFAULT_STATE)
    guard = {"building": True}   # bound inputs fire on_change while being built;
                                 # ignore refresh until the plots exist.

    def refresh():
        if guard["building"]:
            return
        w, h = CONTAINERS[s["container"]]
        diag_plot.update_figure(diagram_figure(
            s["a"], s["b"], s["d"], s["f"], s["x_cg"], s["z_cg"], s["theta_deg"],
            w, h, s["roof_clearance"]))
        force_plot.update_figure(force_figure(
            s["a"], s["b"], s["d"], s["f"], s["x_cg"], s["z_cg"], s["theta_deg"]))
        length_plot.update_figure(length_figure(
            s["a"], s["b"], s["d"], s["f"], s["theta_deg"], s["stroke_ratio"]))
        m = summary_metrics(s["a"], s["b"], s["d"], s["f"], s["x_cg"], s["z_cg"],
                            s["theta_deg"], s["stroke_ratio"])
        peak_m.text = f"{m['peak']:.2f} N/kg"
        here_m.text = f"{m['here']:.2f} N/kg"
        stroke_m.text = f"{m['stroke']:.2f} m"
        ratio_m.text = f"{m['ratio']:.2f}" + ("  ✓" if m["ok"] else "  ⚠ over")

    def linked(label, key, lo, hi, step=0.01, fmt="%.2f"):
        """A slider AND a typeable number box, both bound to s[key] (so they stay
        in sync) — the NiceGUI equivalent of the Streamlit linked_input."""
        ui.label(label).classes("text-sm mt-2 mb-0")
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            sld = (ui.slider(min=lo, max=hi, step=step, on_change=refresh)
                   .bind_value(s, key).props("label-always").classes("grow"))
            (ui.number(min=lo, max=hi, step=step, format=fmt, on_change=refresh)
             .bind_value(s, key).classes("w-24"))
        return sld

    def metric(title):
        with ui.column().classes("items-center gap-0"):
            ui.label(title).classes("text-xs text-gray-500")
            return ui.label("—").classes("text-xl font-semibold")

    async def do_optimize():
        opt_btn.disable()
        opt_status.text = "Optimizing… (~20 s)"
        try:
            w, h = CONTAINERS[s["container"]]
            # io_bound (thread) rather than cpu_bound (process): no subprocess to
            # re-import this module, and numpy/scipy release the GIL during the
            # search so the event loop stays responsive.
            res = await run.io_bound(
                optimize_actuator, w, h, s["x_cg"], s["z_cg"],
                stroke_ratio_max=s["stroke_ratio"], roof_clearance=s["roof_clearance"])
            for sld, k in ((ga, "a"), (gb, "b"), (gd, "d"), (gf, "f")):
                s[k] = round(float(res[k]), 3)
                sld.value = s[k]
            refresh()
            opt_status.text = (f"Optimized — peak {res['peak_force']:.2f} N/kg, "
                               f"stroke ratio {res['stroke_ratio']:.2f}"
                               + ("" if res["feasible"] else " (limits not all met)"))
            ui.notify("Optimized", type="positive")
        except Exception as exc:
            opt_status.text = f"Optimizer failed: {exc}"
            ui.notify("Optimizer failed", type="negative")
        finally:
            opt_btn.enable()

    with ui.header().classes("items-center justify-between bg-primary text-white"):
        ui.label("Container wall actuator").classes("text-lg font-medium")
        ui.label("hinged-wall hydraulic sizing").classes("text-sm opacity-80")

    with ui.row().classes("w-full no-wrap gap-4 p-2"):
        # ---- Left: control panel with tabs --------------------------------
        with ui.card().classes("w-96 shrink-0"):
            with ui.tabs().classes("w-full") as tabs:
                ui.tab("Setup")
                ui.tab("Geometry")
                ui.tab("Optimize")
            with ui.tab_panels(tabs, value="Setup").classes("w-full"):
                with ui.tab_panel("Setup"):
                    ui.select(list(CONTAINERS), value=s["container"], label="Container",
                              on_change=lambda e: (s.__setitem__("container", e.value), refresh())
                              ).classes("w-full")
                    linked("x_cg — along wall (m)", "x_cg", 0.0, HEIGHT_MAX)
                    linked("z_cg — off the wall (m)", "z_cg", 0.0, 1.5)
                    ui.label("Max stroke ratio").classes("text-sm mt-2 mb-0")
                    ui.number(value=s["stroke_ratio"], min=1.0, max=3.0, step=0.05,
                              on_change=lambda e: (s.__setitem__("stroke_ratio", e.value), refresh())
                              ).classes("w-full")
                    linked("Roof clearance (m)", "roof_clearance", 0.0, 0.5, 0.01)
                with ui.tab_panel("Geometry"):
                    ga = linked("a — base along floor (m)", "a", 0.05, WIDTH / 2)
                    gb = linked("b — attachment along wall (m)", "b", 0.05, HEIGHT_MAX)
                    gd = linked("d — bracket length (m)", "d", 0.0, 1.0)
                    gf = linked("f — base height (m)", "f", 0.0, HEIGHT_MAX)
                    ui.separator()
                    linked("Wall angle θ (deg)", "theta_deg", 0.0, 90.0, 1.0, "%.0f")
                with ui.tab_panel("Optimize"):
                    ui.label("Find the a, b, d, f that minimize the worst-case "
                             "piston force for the current setup.").classes("text-sm")
                    opt_btn = ui.button("Optimize geometry", on_click=do_optimize
                                        ).props("color=primary").classes("w-full")
                    opt_status = ui.label("").classes("text-sm text-gray-600")

        # ---- Right: visualization -----------------------------------------
        with ui.column().classes("flex-1 gap-3"):
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full justify-around"):
                    peak_m = metric("Peak force (worst case)")
                    here_m = metric("Force at θ")
                    stroke_m = metric("Stroke")
                    ratio_m = metric("Stroke ratio")
            with ui.row().classes("w-full no-wrap gap-3"):
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

    guard["building"] = False   # layout complete; refresh may touch the plots now
    refresh()   # first paint of the metrics


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)),
           title="Container Wall Actuator", reload=False, show=False)
