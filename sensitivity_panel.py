"""Shared 'sensitivity' panel used by the Designer (app.py), the Browse inspector
(browse.py) and the Reverse view (reverse.py), so they stay identical.

Two aligned charts for one geometry:
  * Top (tornado bars) — how much the peak force swings as each of a, b, d, f
    sweeps its allowed range (others fixed). Longer / redder = more impact.
  * Bottom (within-range strip) — WHERE inside each variable's range the force
    is most sensitive: color = the % the peak force changes per 1 cm (metric) or
    1 in (imperial) you nudge that variable. The white dot is the current value.

build_sensitivity_figures() builds the two figures (+ the caption) so the same
charts can be shown on screen and embedded in the PDF export.
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


def build_sensitivity_figures(a, b, d, f, x_cg, z_cg, bounds, n_cyl=1,
                              inches=False, template="plotly_white", font=None,
                              samples=SAMPLES):
    """Build the (tornado bar, within-range strip) figures and the caption text for
    one geometry. Shared by the on-screen panel and the PDF export so both show the
    identical charts. `bounds` maps each of a, b, d, f to its (min, max) range; the
    current a, b, d, f mark the white dot. Returns (fig_bar, fig_strip, caption)."""
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

    # Bottom — within-range strip. Color = the SIGNED % the peak force changes per
    # +1 step (1 cm metric / 1 in imperial) you INCREASE that variable, i.e.
    # (dForce/dx) x step / force x 100. The sign is the direction: blue = increasing
    # the dimension lowers the force (nudge it up to cut force), red = increasing it
    # raises the force (nudge it down). Intensity = how fast. Mass- and cylinder-
    # count-independent (a ratio); symmetric scale so rows and directions compare.
    step_m, step_lbl = (0.0254, "1 in") if inches else (0.01, "1 cm")
    pos = np.linspace(0.0, 1.0, prof["a"][0].size)
    Z, mags, black = [], [], []
    for v in ordered:
        vals, F = prof[v]
        with np.errstate(invalid="ignore", divide="ignore"):
            pct = np.gradient(F, vals) * step_m / F * 100.0   # SIGNED % per +step
        pct = np.where(np.isfinite(F) & (F > 0.0), pct, np.nan)
        Z.append(pct)
        mags.append(np.abs(pct[np.isfinite(pct)]))
        # Over-center / impossible samples: peak_force is NaN there. Mark them so
        # the strip paints them black instead of leaving a misleading gap.
        black.append(np.where(np.isfinite(F), np.nan, 1.0))
    allmag = np.concatenate([s for s in mags if s.size]) if any(s.size for s in mags) \
        else np.array([1.0])
    zlim = float(np.nanpercentile(allmag, 95)) or 1.0   # symmetric clip so a near-
    zlim = zlim if zlim > 0 else 1.0                    #   singular spike doesn't wash out
    curpos = [float(np.clip((cur[v] - bounds[v][0]) /
                            max(bounds[v][1] - bounds[v][0], 1e-9), 0.0, 1.0))
              for v in ordered]
    fig_strip = go.Figure(go.Heatmap(
        x=pos, y=ys, z=Z, zmin=-zlim, zmax=zlim,
        # diverging, colorblind-safe: blue = force drops (good to increase),
        # white = flat, red = force rises (good to decrease).
        colorscale=[[0.0, "#2166ac"], [0.5, "#f7f7f7"], [1.0, "#b2182b"]],
        colorbar=dict(title=f"Force change<br>per +{step_lbl}", ticksuffix="%",
                      thickness=10, len=0.9)))
    # Over-center (impossible) cells on top of the diverging layer, in black.
    fig_strip.add_trace(go.Heatmap(
        x=pos, y=ys, z=black, zmin=0.0, zmax=1.0, showscale=False, hoverinfo="skip",
        colorscale=[[0.0, "#111111"], [1.0, "#111111"]]))
    fig_strip.add_trace(go.Scatter(
        x=curpos, y=ys, mode="markers", hoverinfo="skip", showlegend=False,
        marker=dict(color="white", size=10, line=dict(color="#111", width=1.6))))
    fig_strip.update_layout(
        template=template, font=font, height=210,
        xaxis=dict(title="Position in each variable's range  (0 = min → 1 = max)",
                   range=[0.0, 1.0]),
        margin=dict(l=10, r=10, t=6, b=40))
    caption = (f"**Top:** each dimension's total impact (bar length + color). "
               f"**Bottom — which way to move.** Color = the **signed** % the peak "
               f"force changes per **+{step_lbl}** you *increase* that dimension. "
               f"**Blue = increasing it lowers the force** (nudge it up to cut force); "
               f"**red = increasing it raises the force** (nudge it down). Deeper = "
               f"faster; white = flat; **black = the cylinder goes over-center there "
               f"(impossible)**. The **white dot** is your current value. Follows the "
               f"m/in units toggle; reflects your cg and mounting limits.")
    return fig_bar, fig_strip, caption


def render_sensitivity_panel(a, b, d, f, x_cg, z_cg, bounds, n_cyl=1,
                             inches=False, template="plotly_white", font=None,
                             samples=SAMPLES):
    """Render the two-chart sensitivity panel for one geometry inside a bordered
    container (uses build_sensitivity_figures so the on-screen charts match the PDF).
    Returns (fig_bar, fig_strip) so the caller can embed the same charts in the PDF."""
    fig_bar, fig_strip, caption = build_sensitivity_figures(
        a, b, d, f, x_cg, z_cg, bounds, n_cyl=n_cyl, inches=inches,
        template=template, font=font, samples=samples)
    with st.container(border=True):
        st.markdown("**Sensitivity — which dimension moves the force most?**")
        st.plotly_chart(fig_bar, width="stretch")
        st.plotly_chart(fig_strip, width="stretch")
        st.caption(caption)
    return fig_bar, fig_strip
