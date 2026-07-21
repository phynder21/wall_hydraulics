"""Shared 'Cylinder sizing — bore & pressure' card, used by both the Designer
(app.py) and the Browse inspector (browse.py) so the two stay identical.

Turns the per-cylinder peak force (N/kg) x wall mass into a required bore
diameter, rounds it up to a real standard size, and reports the pressure that
size actually needs and how far it sits below the design pressure. Returns
(pressure_bar, series) so the caller can feed the PDF export the same numbers.
"""
import numpy as np
import streamlit as st

from lookup import (required_bore_mm, next_standard_bore_mm, pressure_for_bore_bar)


def render_cylinder_sizing(force_per_kg, mass, key_prefix=""):
    """Render the bore + operating-pressure card. `force_per_kg` is the per-cylinder
    peak force (N/kg); `mass` the wall + load mass (kg). `key_prefix` keeps widget
    keys unique across views (Designer uses '', Browse uses 'lk_'). Returns the
    resolved (design pressure in bar, bore-standard string)."""
    with st.container(border=True):
        st.markdown("**Cylinder sizing — bore & pressure**")
        st.caption("Bore = the cylinder barrel's inner **diameter**.")
        cs1, cs2 = st.columns([1, 1])
        series = cs1.selectbox(
            "Bore standard", ["ISO metric", "NFPA (inch)", "Exact (no rounding)"],
            key=f"{key_prefix}bore_series",
            help="Round the required bore up to a real catalog size, or show the "
                 "exact number.")
        if series == "NFPA (inch)":
            st.session_state.setdefault(f"{key_prefix}des_psi", 3000.0)
            press_psi = cs2.number_input("Design pressure (psi)", 200.0, 10000.0,
                                         step=50.0, key=f"{key_prefix}des_psi")
            pressure_bar = press_psi * 0.0689476
            press_label = f"{press_psi:,.0f} psi"
        else:
            st.session_state.setdefault(f"{key_prefix}des_bar", 210.0)
            pressure_bar = cs2.number_input("Design pressure (bar)", 20.0, 700.0,
                                            step=5.0, key=f"{key_prefix}des_bar")
            press_label = f"{pressure_bar:,.0f} bar"

        if np.isfinite(force_per_kg) and mass > 0 and pressure_bar > 0:
            force_n = force_per_kg * mass                   # per-cylinder peak push, N
            force_lbl = f"{force_n / 1000:.1f} kN ({force_n / 4.44822:,.0f} lbf)"
            bore_mm = required_bore_mm(force_n, pressure_bar)
            bore_in = bore_mm / 25.4
            if series == "Exact (no rounding)":
                st.markdown(
                    f"Required bore diameter **{bore_mm:.1f} mm** ({bore_in:.2f} in) to "
                    f"make **{force_lbl}** at {press_label}.")
            else:
                std_mm, std_label = next_standard_bore_mm(bore_mm, series)
                if std_mm is None:
                    st.warning(
                        f"Required bore diameter **{bore_mm:.1f} mm** is bigger than the "
                        f"largest standard size — raise the design pressure, or plan for "
                        f"two cylinders sharing the load.")
                else:
                    p_at_std = pressure_for_bore_bar(force_n, std_mm)
                    head = (1.0 - p_at_std / pressure_bar) * 100.0 if pressure_bar else 0.0
                    st.markdown(
                        f"Required bore diameter **{bore_mm:.1f} mm** ({bore_in:.2f} in) → "
                        f"next standard **{std_label}**, which needs **{p_at_std:.0f} bar** "
                        f"({p_at_std * 14.5038:.0f} psi) to make {force_lbl} "
                        f"— **{head:.0f}% below** your {press_label}.")
        else:
            st.caption("Set a valid geometry, wall mass, and pressure to size the bore.")
    return pressure_bar, series
