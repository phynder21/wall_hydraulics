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

from wall import force_profiles, peak_force
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
                              template="plotly_white", font=None, samples=SAMPLES):
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

    # Bottom — within-range strip. Color = the peak force AT each position as a
    # percent of your CURRENT design's force, so you can read "move this variable
    # there and the force becomes 150% of what it is now." 100% (white) = same as
    # now; red = higher (worse), blue = lower (better); black = over-center
    # (impossible). It's a ratio, so it's mass- and cylinder-count-independent and
    # each variable's range is normalized to 0->1 (one shared position axis).
    f0 = peak_force(a, b, d, f, x_cg, z_cg)              # current design's peak force
    if not (np.isfinite(f0) and f0 > 0):                 # current geometry impossible:
        allF = [prof[v][1][np.isfinite(prof[v][1])] for v in ordered]
        allF = np.concatenate([s for s in allF if s.size]) if any(s.size for s in allF) \
            else np.array([1.0])
        f0 = float(np.nanmin(allF)) if allF.size else 1.0   # fall back to best in view
    pos = np.linspace(0.0, 1.0, prof["a"][0].size)
    Z, black, finite = [], [], []
    for v in ordered:
        _vals, F = prof[v]
        ratio = F / f0 * 100.0                           # % of the current force
        Z.append(ratio)
        finite.append(ratio[np.isfinite(ratio)])
        # Over-center / impossible samples: peak_force is NaN there. Mark them so
        # the strip paints them black instead of leaving a misleading gap.
        black.append(np.where(np.isfinite(F), np.nan, 1.0))
    allr = np.concatenate([s for s in finite if s.size]) if any(s.size for s in finite) \
        else np.array([100.0])
    zmin = min(float(np.nanmin(allr)), 100.0)            # keep 100% (white) in range
    zmax = max(float(np.nanpercentile(allr, 95)), 101.0)  # clip a near-singular red spike
    curpos = [float(np.clip((cur[v] - bounds[v][0]) /
                            max(bounds[v][1] - bounds[v][0], 1e-9), 0.0, 1.0))
              for v in ordered]
    fig_strip = go.Figure(go.Heatmap(
        x=pos, y=ys, z=Z, zmin=zmin, zmax=zmax, zmid=100.0,
        # diverging, colorblind-safe, centered on 100% (your current force):
        # blue = lower (better), white = same, red = higher (worse).
        colorscale=[[0.0, "#2166ac"], [0.5, "#f7f7f7"], [1.0, "#b2182b"]],
        colorbar=dict(title="Force vs.<br>current", ticksuffix="%",
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
               f"**Bottom — how much better or worse each spot is.** Color = the peak "
               f"force if you moved *that* dimension to *that* position, as a **percent "
               f"of your current force** (so 200% = double, 50% = half). **White (100%) "
               f"= same as now**; **red = higher (worse)**, **blue = lower (better)**; "
               f"**black = the cylinder goes over-center there (impossible)**. The "
               f"**white dot** is your current design (100%). Reflects your cg and "
               f"mounting limits.")
    return fig_bar, fig_strip, caption


def render_sensitivity_panel(a, b, d, f, x_cg, z_cg, bounds, n_cyl=1,
                             template="plotly_white", font=None, samples=SAMPLES):
    """Render the two-chart sensitivity panel for one geometry inside a bordered
    container (uses build_sensitivity_figures so the on-screen charts match the PDF).
    Returns (fig_bar, fig_strip) so the caller can embed the same charts in the PDF."""
    fig_bar, fig_strip, caption = build_sensitivity_figures(
        a, b, d, f, x_cg, z_cg, bounds, n_cyl=n_cyl,
        template=template, font=font, samples=samples)
    with st.container(border=True):
        st.markdown("**Sensitivity — which dimension moves the force most?**")
        st.plotly_chart(fig_bar, width="stretch")
        st.plotly_chart(fig_strip, width="stretch")
        st.caption(caption)
    return fig_bar, fig_strip
