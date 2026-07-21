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
import streamlit as st

import report
from lookup import (required_bore_mm, next_standard_bore_mm, pressure_for_bore_bar)


def render_pdf_export(*, key, size_key, n_cyl, x_cg, z_cg, mass, stroke_ratio_max,
                      roof_clearance, a, b, d, f, peak_pc, L_min, L_max,
                      fig_geom, fig_force, fig_len, pressure_bar=None, series=None,
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
                if pressure_bar and np.isfinite(peak_pc) and pressure_bar > 0:
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
                cyl_rows += [
                    ("Stroke (L_max - L_min)", _len(L_max - L_min)),
                    ("Retracted / extended", f"{_len(L_min)} / {_len(L_max)}"),
                    ("Stroke ratio", f"{L_ratio:.2f}" + ("" if stroke_ok else " (over limit)")),
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
                if n_cyl <= 1:
                    cyl_note = ("All forces and the bore above are for ONE cylinder "
                                "carrying the whole wall.")
                else:
                    cyl_note = (f"All forces and the bore above are PER CYLINDER; the wall "
                                f"load is shared across {n_cyl} cylinders (each carries "
                                f"1/{n_cyl}).")
                notes = [
                    cyl_note,
                    "Forces are static holding forces (no inertia, friction, wind, or flex).",
                    "Apply a factor of safety (>=1.5x is a common start).",
                    "Bore is the barrel inner diameter.",
                ] + list(extra_notes)
                # Rendering figures to PNG needs an image backend (kaleido); if it is
                # unavailable, still produce a numbers-only PDF rather than crash.
                images = []
                try:
                    images = [
                        ("Side view", fig_geom.to_image(format="png", width=900, height=560, scale=2)),
                        ("Piston force vs. wall angle",
                         fig_force.to_image(format="png", width=900, height=380, scale=2)),
                        ("Cylinder length vs. wall angle",
                         fig_len.to_image(format="png", width=900, height=380, scale=2)),
                    ]
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
