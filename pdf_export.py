"""Shared 'Export design (PDF)' block, used by the Designer (app.py), the Browse
inspector (browse.py), and the Reverse view (reverse.py) so a one-page spec sheet
is available wherever you land on a geometry.

Assembles the Setup / Geometry / Cylinder tables (both unit systems via
report.dual_*), captures the side view + force + length curves as PNGs (best
effort — a numbers-only PDF if no image backend), and wires the Generate /
Download buttons. `key` namespaces the widgets and the stored bytes per view; the
optional params let a view tweak the sheet (e.g. Reverse omits the bore section
and the max-stroke-ratio row, and adds the cylinder it was sized from).
"""
import datetime

import numpy as np
import plotly.graph_objects as go
import streamlit as st

import report
from lookup import (required_bore_mm, next_standard_bore_mm, pressure_for_bore_bar)

# The on-screen figures use tiny margins (Streamlit gives them width); exported
# standalone to PNG at a fixed size those margins clip the axis tick labels and
# collide the axis titles. These helpers rebuild each figure for print — full
# margins + automargin so nothing clips, centered titles, and (for the side view)
# an equal-aspect canvas sized to the data so there's no wasted whitespace, plus a
# legend naming each part since the sheet stands on its own.
_PRINT_FONT = dict(family="sans-serif", size=15, color="#0F172A")
_LEGEND_SKIP = {"post", "mounting post", ""}   # redundant support line, unnamed


def _fig_bounds(fig):
    """(x0, x1, y0, y1) data extent across every trace in the figure."""
    xs, ys = [], []
    for t in fig.data:
        tx, ty = getattr(t, "x", None), getattr(t, "y", None)
        if tx is not None:
            xs += [v for v in tx if v is not None]
        if ty is not None:
            ys += [v for v in ty if v is not None]
    if not xs or not ys:
        return 0.0, 1.0, 0.0, 1.0
    return min(xs), max(xs), min(ys), max(ys)


def _prep_diagram(fig, base_w=1000):
    """Equal-aspect side view for print. Returns (figure, width_px, height_px);
    the height is sized to the data aspect so the drawing fills the canvas."""
    f = go.Figure(fig)
    for t in f.data:                                    # legend names each part
        t.showlegend = (t.name or "") not in _LEGEND_SKIP
    x0, x1, y0, y1 = _fig_bounds(f)
    px = max((x1 - x0) * 0.06, 0.1)
    py = max((y1 - y0) * 0.08, 0.1)
    f.update_layout(
        template="plotly_white", font=_PRINT_FONT, showlegend=True,
        margin=dict(l=70, r=35, t=55, b=70),
        title=dict(x=0.5, xanchor="center", font=dict(size=18)),
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center",
                    x=0.5, font=dict(size=12)))
    # x scales to y (equal aspect) with explicit padded ranges; clear any anchor
    # the source figure set the other way so the two don't fight.
    f.update_yaxes(scaleanchor=None, range=[y0 - py, y1 + py],
                   title_standoff=12, ticks="outside", automargin=True)
    f.update_xaxes(scaleanchor="y", scaleratio=1, range=[x0 - px, x1 + px],
                   title_standoff=12, ticks="outside", automargin=True)
    xspan, yspan = (x1 - x0 + 2 * px), (y1 - y0 + 2 * py)
    height = int((base_w - 105) * (yspan / max(xspan, 1e-6))) + 170   # + margins/legend
    return f, base_w, max(360, min(height, 900))


def _prep_curve(fig, base_w=1000, height=430):
    """A force/length curve for print: full margins (nothing clips), no legend."""
    f = go.Figure(fig)
    f.update_layout(
        template="plotly_white", font=_PRINT_FONT, showlegend=False,
        margin=dict(l=70, r=35, t=55, b=60),
        title=dict(x=0.5, xanchor="center", font=dict(size=18)))
    f.update_xaxes(title_standoff=12, ticks="outside", automargin=True)
    f.update_yaxes(title_standoff=12, ticks="outside", automargin=True)
    return f, base_w, height


def _prep_panel(fig, base_w=1000, height=340):
    """A sensitivity chart (tornado bar / within-range strip) for print: full
    margins + automargin so the long y-labels and colorbar aren't clipped."""
    f = go.Figure(fig)
    f.update_layout(template="plotly_white", font=_PRINT_FONT,
                    margin=dict(l=75, r=40, t=20, b=60))
    f.update_xaxes(title_standoff=12, ticks="outside", automargin=True)
    f.update_yaxes(ticks="outside", automargin=True)
    return f, base_w, height


def render_pdf_export(*, key, size_key, n_cyl, x_cg, z_cg, mass, stroke_ratio_max,
                      roof_clearance, a, b, d, f, peak_pc, L_min, L_max,
                      fig_geom, fig_force, fig_len,
                      fig_sens_bar=None, fig_sens_strip=None, fig_interactions=None,
                      pressure_bar=None, series=None, sens_metric="force",
                      mass_label="Wall + load mass", extra_setup_rows=(),
                      extra_notes=(), stroke_tol=1e-9, show_stroke_ratio_max=True,
                      title="Container Wall Actuator - Design Report",
                      file_name="wall_actuator_design.pdf",
                      caption="A one-page spec sheet for this geometry — inputs, "
                              "forces, bore & pressure, the diagram, and the curves. "
                              "Click Generate to capture the design as it stands now."):
    """Render the PDF-export expander for one geometry. `pressure_bar`/`series`
    (from the cylinder-sizing card) add the bore section when present; omit them
    for views where the cylinder is the input rather than an output."""
    L_ratio = (L_max / L_min) if L_min > 0 else float("inf")
    stroke_ok = L_ratio <= stroke_ratio_max + stroke_tol
    with st.expander("Export design (PDF)"):
        st.caption(caption)
        if st.button("Generate PDF", key=f"{key}_gen"):
            with st.spinner("Rendering the PDF…"):
                # The PDF shows BOTH unit systems for every value (see report.dual_*),
                # regardless of the app's display toggle.
                _len, _force = report.dual_len, report.dual_force
                _press, _bore = report.dual_pressure, report.dual_bore

                # Per cylinder (n_cyl cylinders share the load).
                force_n = peak_pc * mass if np.isfinite(peak_pc) else float("nan")
                _pk = (f"{peak_pc:.2f} N/kg" if np.isfinite(peak_pc)
                       else "n/a (singular geometry)")
                _tot = _force(force_n) if np.isfinite(force_n) else "n/a"
                cyl_rows = [("Peak force per cylinder", _pk),
                            (f"Force per cylinder at {mass:,.0f} kg", _tot)]
                has_bore = bool(pressure_bar) and np.isfinite(peak_pc) and pressure_bar > 0
                if has_bore:
                    bore = required_bore_mm(force_n, pressure_bar)
                    cyl_rows.append(("Design pressure", _press(pressure_bar)))
                    if series == "Exact (no rounding)":
                        cyl_rows.append(("Required bore (diameter)", _bore(bore)))
                    else:
                        std_mm, std_label = next_standard_bore_mm(bore, series)
                        if std_mm:
                            other = (f"{std_mm / 25.4:.2f} in" if series == "ISO metric"
                                     else f"{std_mm:.1f} mm")
                            cyl_rows.append(("Required bore (diameter)",
                                             f"{_bore(bore)} -> standard {std_label} ({other})"))
                            cyl_rows.append(("Pressure at that bore",
                                             _press(pressure_for_bore_bar(force_n, std_mm))))
                        else:
                            cyl_rows.append(("Required bore (diameter)",
                                             f"{_bore(bore)} (exceeds largest standard)"))
                # Only flag "over limit" where there IS a stroke-ratio cap to be over
                # (the Designer/Browse have one; Reverse is bounded by length instead).
                over = " (over limit)" if (show_stroke_ratio_max and not stroke_ok) else ""
                cyl_rows += [
                    ("Stroke (L_max - L_min)", _len(L_max - L_min)),
                    ("Retracted / extended", f"{_len(L_min)} / {_len(L_max)}"),
                    ("Stroke ratio", f"{L_ratio:.2f}" + over),
                ]
                setup_rows = [
                    ("Container", size_key),
                    ("Cylinders sharing the load", str(n_cyl)),
                    ("Center of gravity x_cg", _len(x_cg)),
                    ("Center of gravity z_cg", _len(z_cg)),
                    (mass_label, report.dual_mass(mass)),
                ]
                if show_stroke_ratio_max:
                    setup_rows.append(("Max stroke ratio", f"{stroke_ratio_max:g}x"))
                setup_rows += [
                    ("Roof clearance", _len(roof_clearance)),
                ] + list(extra_setup_rows)
                tables = [
                    ("Setup", setup_rows),
                    ("Geometry (a, b, d, f)", [
                        ("a - base along floor", _len(a)),
                        ("b - attachment up wall", _len(b)),
                        ("d - bracket offset", _len(d)),
                        ("f - base height", _len(f)),
                    ]),
                    ("Cylinder", cyl_rows),
                ]
                # "the bore" only exists when the bore section was included.
                what = "All forces and the bore above" if has_bore else "All forces above"
                if n_cyl <= 1:
                    cyl_note = f"{what} are for ONE cylinder carrying the whole wall."
                else:
                    cyl_note = (f"{what} are PER CYLINDER; the wall load is shared across "
                                f"{n_cyl} cylinders (each carries 1/{n_cyl}).")
                notes = [
                    cyl_note,
                    "Forces are static holding forces (no inertia, friction, wind, or flex).",
                    "Apply a factor of safety (>=1.5x is a common start).",
                    "Bore is the barrel inner diameter.",
                ] + list(extra_notes)
                # Rebuild each figure for print (full margins, correct aspect) then
                # render to PNG. Needs an image backend (kaleido); if it is
                # unavailable, still produce a numbers-only PDF rather than crash.
                images = []
                try:
                    dgeom, dw, dh = _prep_diagram(fig_geom)
                    cforce, fw, fh = _prep_curve(fig_force)
                    clen, lw, lh = _prep_curve(fig_len)
                    images = [
                        ("Side view", dgeom.to_image(format="png", width=dw, height=dh, scale=2)),
                        ("Piston force vs. wall angle",
                         cforce.to_image(format="png", width=fw, height=fh, scale=2)),
                        ("Cylinder length vs. wall angle",
                         clen.to_image(format="png", width=lw, height=lh, scale=2)),
                    ]
                    # Sensitivity charts (tornado + within-range strip), if provided.
                    # `sens_metric` names what they color by (peak force / cylinder
                    # length), kept in step with the on-screen 'Color by' toggle.
                    mword = "cylinder length" if sens_metric == "length" else "peak force"
                    if fig_sens_bar is not None and fig_sens_strip is not None:
                        sb, sw, sh = _prep_panel(fig_sens_bar, height=300)
                        ss, ssw, ssh = _prep_panel(fig_sens_strip, height=360)
                        images += [
                            (f"Sensitivity - each dimension's total impact on {mword}",
                             sb.to_image(format="png", width=sw, height=sh, scale=2)),
                            (f"Sensitivity - {mword} at each position as a % of the current design",
                             ss.to_image(format="png", width=ssw, height=ssh, scale=2)),
                        ]
                    # Interaction matrix (all six variable pairs). Passed as a callable
                    # so the (heavier) grid is built only now, on Generate, not live.
                    if fig_interactions is not None:
                        fig_i = fig_interactions() if callable(fig_interactions) else fig_interactions
                        if fig_i is not None:
                            images.append((
                                f"Interaction maps - vary two dimensions at once ({mword} vs. current)",
                                fig_i.to_image(format="png", width=1000, height=760, scale=2)))
                except Exception:
                    notes.append("Diagrams omitted (image rendering unavailable here).")
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                st.session_state[f"{key}_pdf"] = report.build_spec_pdf(
                    title,
                    f"{size_key} - {n_cyl} cylinder(s) - generated {ts}",
                    tables, images=images, notes=notes)
        if st.session_state.get(f"{key}_pdf"):
            st.download_button("Download PDF", st.session_state[f"{key}_pdf"],
                               file_name=file_name, mime="application/pdf",
                               key=f"{key}_dl")
