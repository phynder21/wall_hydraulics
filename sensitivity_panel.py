"""Shared 'sensitivity' panel used by both the Designer (app.py) and the Browse
inspector (browse.py), so the two stay identical.

Two aligned charts for one geometry:
  * Top (tornado bars) — how much the peak force swings as each of a, b, d, f
    sweeps its allowed range (others fixed). Longer / redder = more impact.
  * Bottom (within-range strip) — WHERE inside each variable's range the force
    is most sensitive: color = the % the peak force changes per 1 cm (metric) or
    1 in (imperial) you nudge that variable. The white dot is the current value.
"""
import numpy as np
import plotly.graph_objects as go
import streamlit as st

from wall import force_profiles
from lookup import force_color

_LABELS = {"a": "a — base along floor", "b": "b — attach up wall",
           "d": "d — bracket offset", "f": "f — base height"}


# Samples per variable across its range. This sets the width of each strip cell
# (range / (SAMPLES - 1)); more samples = narrower cells = a smoother color gradient.
SAMPLES = 81


@st.cache_data(show_spinner=False)
def _profiles(a, b, d, f, x_cg, z_cg, bounds_items, samples):
    """Cached force-vs-value curves for each variable (the raw sensitivity data).
    All args are hashable and part of the cache key (do NOT prefix with '_', which
    st.cache_data EXCLUDES from the key), so the charts update when the design
    changes but repeat reruns hit the cache. bounds_items is ((var, (lo, hi)), ...).
    """
    return force_profiles(a, b, d, f, x_cg, z_cg, dict(bounds_items), n=samples)


def render_sensitivity_panel(a, b, d, f, x_cg, z_cg, bounds, n_cyl=1,
                             inches=False, template="plotly_white", font=None,
                             samples=SAMPLES):
    """Render the two-chart sensitivity panel for one geometry inside a bordered
    container. `bounds` maps each of a, b, d, f to its (min, max) mounting range;
    the current a, b, d, f mark the white dot in each row. `samples` sets the strip
    resolution (more = smoother color)."""
    with st.container(border=True):
        st.markdown("**Sensitivity — which dimension moves the force most?**")
        bounds_items = tuple(sorted((k, tuple(bounds[k])) for k in ("a", "b", "d", "f")))
        prof = _profiles(a, b, d, f, x_cg, z_cg, bounds_items, samples)
        cur = {"a": a, "b": b, "d": d, "f": f}

        def swing(v):
            F = prof[v][1]
            F = F[np.isfinite(F)]
            return float(F.max() - F.min()) / n_cyl if F.size else 0.0

        ordered = sorted(("a", "b", "d", "f"), key=swing)   # small→big (big on top)
        ys = [_LABELS[v] for v in ordered]

        # Top — tornado: total peak-force swing per variable (length + color = impact).
        xs = [swing(v) for v in ordered]
        mx = max(xs) if any(xs) else 1.0
        cols = [force_color(x, 0.0, mx) or "#63be7b" for x in xs]
        fig_bar = go.Figure(go.Bar(
            x=xs, y=ys, orientation="h", marker=dict(color=cols),
            text=[f"{x:.1f}" for x in xs], textposition="outside", hoverinfo="skip"))
        fig_bar.update_layout(
            template=template, font=font, height=190,
            xaxis_title=f"Total peak-force swing (N/kg{' per cyl' if n_cyl > 1 else ''})",
            xaxis=dict(range=[0, mx * 1.18]), margin=dict(l=10, r=10, t=6, b=30))
        st.plotly_chart(fig_bar, width="stretch")

        # Bottom — within-range strip. Color = the % the peak force changes for each
        # step you move that variable (1 cm in metric, 1 in in imperial — follows the
        # units toggle), i.e. |dForce/dx| x step, as a percent of the local force.
        # Mass- and cylinder-count-independent (it's a ratio). Shared scale across
        # variables so rows are comparable; the dot marks the current value.
        step_m, step_lbl = (0.0254, "1 in") if inches else (0.01, "1 cm")
        pos = np.linspace(0.0, 1.0, prof["a"][0].size)
        Z, finite = [], []
        for v in ordered:
            vals, F = prof[v]
            with np.errstate(invalid="ignore", divide="ignore"):
                pct = np.abs(np.gradient(F, vals)) * step_m / F * 100.0   # % per step
            pct = np.where(np.isfinite(F) & (F > 0.0), pct, np.nan)
            Z.append(pct)
            finite.append(pct[np.isfinite(pct)])
        allv = np.concatenate([s for s in finite if s.size]) if any(s.size for s in finite) \
            else np.array([1.0])
        zmax = float(np.nanpercentile(allv, 95)) or 1.0   # clip so a near-singular spike
        zmax = zmax if zmax > 0 else 1.0                  #   doesn't wash out the rest
        curpos = [float(np.clip((cur[v] - bounds[v][0]) /
                                max(bounds[v][1] - bounds[v][0], 1e-9), 0.0, 1.0))
                  for v in ordered]
        fig_strip = go.Figure(go.Heatmap(
            x=pos, y=ys, z=Z, zmin=0.0, zmax=zmax,
            colorscale=[[0.0, "#f6f6f6"], [0.5, "#fca082"], [1.0, "#a50f15"]],
            colorbar=dict(title=f"Force change<br>per {step_lbl}", ticksuffix="%",
                          thickness=10, len=0.9)))
        fig_strip.add_trace(go.Scatter(
            x=curpos, y=ys, mode="markers", hoverinfo="skip", showlegend=False,
            marker=dict(color="white", size=10, line=dict(color="#111", width=1.6))))
        fig_strip.update_layout(
            template=template, font=font, height=210,
            xaxis=dict(title="Position in each variable's range  (0 = min → 1 = max)",
                       range=[0.0, 1.0]),
            margin=dict(l=10, r=10, t=6, b=40))
        st.plotly_chart(fig_strip, width="stretch")
        st.caption(f"**Top:** each dimension's total impact (bar length + color). "
                   f"**Bottom:** color = **how much the peak force changes for each "
                   f"{step_lbl}** you move that dimension, as a percent of the force (so "
                   f"2% means a {step_lbl} nudge shifts the force about 2%). Redder = more "
                   f"sensitive there; blank = over-center. The **white dot** is your "
                   f"current value. Follows the m/in units toggle; reflects your cg and "
                   f"mounting limits.")
