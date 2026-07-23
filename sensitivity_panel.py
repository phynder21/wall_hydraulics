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

from wall import force_feasibility_profiles, peak_force, peak_force_feasible
from lookup import force_color

_LABELS = {"a": "a — base along floor", "b": "b — attach up wall",
           "d": "d — bracket offset", "f": "f — base height"}


# Samples per variable across its range. This sets the width of each strip cell
# (range / (SAMPLES - 1)); more samples = narrower cells = a smoother color gradient.
SAMPLES = 81


@st.cache_data(show_spinner=False)
def _profiles(a, b, d, f, x_cg, z_cg, bounds_items, samples, feas):
    """Cached force-and-feasibility curves for each variable (the raw sensitivity
    data). All args are hashable and part of the cache key (do NOT prefix with '_',
    which st.cache_data EXCLUDES), so the charts update when the design OR its rules
    change but repeat reruns hit the cache. bounds_items is ((var, (lo, hi)), ...);
    feas is ((name, value), ...) of the optimizer rules (stroke_max, roof_clearance,
    width, height, length_window)."""
    return force_feasibility_profiles(a, b, d, f, x_cg, z_cg, dict(bounds_items),
                                      n=samples, **dict(feas))


def _ratio_colorscale(finite):
    """Shared 'force vs. current %' colouring. Given the finite % ratios, return
    (zmin, zmax, colorscale, dtick): the key spans the real data range with white
    placed exactly at 100%, blue below (better), red above (worse) — so the legend
    never shows a phantom blue band and 100% is always a labelled tick."""
    finite = np.asarray(finite, dtype=float)
    finite = finite[np.isfinite(finite)]
    allr = finite if finite.size else np.array([100.0])
    zmin = min(float(np.nanmin(allr)), 100.0)
    zmax = max(float(np.nanpercentile(allr, 95)), 101.0)
    wpos = min(max((100.0 - zmin) / (zmax - zmin), 0.0), 1.0) if zmax > zmin else 0.0
    if wpos <= 1e-3:                                     # nothing feasible beats current
        cs = [[0.0, "#f7f7f7"], [1.0, "#b2182b"]]        # white -> red
    elif wpos >= 1.0 - 1e-3:                             # nothing feasible is worse
        cs = [[0.0, "#2166ac"], [1.0, "#f7f7f7"]]        # blue -> white
    else:
        cs = [[0.0, "#2166ac"], [wpos, "#f7f7f7"], [1.0, "#b2182b"]]
    dtick = next((s for s in (10, 20, 25, 50, 100, 200, 500)
                  if (zmax - zmin) / s <= 6), 1000)
    return zmin, zmax, cs, dtick


def _ratio_colorbar(dtick):
    """The larger, tick-labelled key shared by the strip and the interaction map."""
    return dict(title=dict(text="Force vs.<br>current", side="top"),
                ticksuffix="%", tick0=100.0, dtick=dtick, ticks="outside",
                ticklen=6, tickwidth=1.2, thickness=20, len=1.0,
                outlinewidth=1, outlinecolor="#888")


def build_sensitivity_figures(a, b, d, f, x_cg, z_cg, bounds, n_cyl=1,
                              template="plotly_white", font=None, samples=SAMPLES,
                              stroke_max=None, roof_clearance=0.0, width=None,
                              height=None, length_window=None):
    """Build the (tornado bar, within-range strip) figures and the caption text for
    one geometry. Shared by the on-screen panel and the PDF export so both show the
    identical charts. `bounds` maps each of a, b, d, f to its (min, max) range; the
    current a, b, d, f mark the white dot. The optimizer rules (stroke_max,
    roof_clearance, width/height, length_window) black out geometries that would be
    rejected. Returns (fig_bar, fig_strip, caption)."""
    bounds_items = tuple(sorted((k, tuple(bounds[k])) for k in ("a", "b", "d", "f")))
    feas = (("stroke_max", stroke_max), ("roof_clearance", roof_clearance),
            ("width", width), ("height", height), ("length_window", length_window))
    prof = _profiles(a, b, d, f, x_cg, z_cg, bounds_items, samples, feas)
    cur = {"a": a, "b": b, "d": d, "f": f}

    def swing(v):
        _vals, F, _ok = prof[v]
        F = F[np.isfinite(F)]           # raw leverage over the buildable range
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
    # now; red = higher (worse), blue = lower (better). Any spot the OPTIMIZER would
    # reject — over-center, over the stroke ratio, through the roof, or outside the
    # cylinder length window — is painted black and left out of the color scale, so
    # after optimizing there is no "better" (blue) spot the design isn't already
    # using. It's a ratio, so it's mass- and cylinder-count-independent and each
    # variable's range is normalized to 0->1 (one shared position axis).
    f0 = peak_force(a, b, d, f, x_cg, z_cg)              # current design's peak force
    if not (np.isfinite(f0) and f0 > 0):                 # current geometry impossible:
        allF = [prof[v][1][prof[v][2] & np.isfinite(prof[v][1])] for v in ordered]
        allF = np.concatenate([s for s in allF if s.size]) if any(s.size for s in allF) \
            else np.array([1.0])
        f0 = float(np.nanmin(allF)) if allF.size else 1.0   # fall back to best in view
    pos = np.linspace(0.0, 1.0, prof["a"][0].size)
    Z, black, finite = [], [], []
    for v in ordered:
        _vals, F, ok = prof[v]
        ratio = np.where(ok, F / f0 * 100.0, np.nan)     # colour only feasible spots
        Z.append(ratio)
        finite.append(ratio[np.isfinite(ratio)])
        # Everything the optimizer rejects (over-center OR a broken rule) -> black.
        black.append(np.where(ok, np.nan, 1.0))
    allr = np.concatenate([s for s in finite if s.size]) if any(s.size for s in finite) \
        else np.array([100.0])
    zmin, zmax, strip_cs, dtick = _ratio_colorscale(allr)
    curpos = [float(np.clip((cur[v] - bounds[v][0]) /
                            max(bounds[v][1] - bounds[v][0], 1e-9), 0.0, 1.0))
              for v in ordered]
    fig_strip = go.Figure(go.Heatmap(
        x=pos, y=ys, z=Z, zmin=zmin, zmax=zmax,
        # blue = lower (better), white = 100% (same), red = higher (worse).
        colorscale=strip_cs, colorbar=_ratio_colorbar(dtick)))
    # Rejected cells (over-center or rule-breaking) on top of the color layer, black.
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
               f"**black = a spot the optimizer would reject** — over-center, over the "
               f"stroke ratio, through the roof, or outside the cylinder's length. The "
               f"**white dot** is your current design (100%). Reflects your cg and "
               f"mounting limits.")
    return fig_bar, fig_strip, caption


def render_sensitivity_panel(a, b, d, f, x_cg, z_cg, bounds, n_cyl=1,
                             template="plotly_white", font=None, samples=SAMPLES,
                             stroke_max=None, roof_clearance=0.0, width=None,
                             height=None, length_window=None):
    """Render the two-chart sensitivity panel for one geometry inside a bordered
    container (uses build_sensitivity_figures so the on-screen charts match the PDF).
    Returns (fig_bar, fig_strip) so the caller can embed the same charts in the PDF."""
    fig_bar, fig_strip, caption = build_sensitivity_figures(
        a, b, d, f, x_cg, z_cg, bounds, n_cyl=n_cyl,
        template=template, font=font, samples=samples, stroke_max=stroke_max,
        roof_clearance=roof_clearance, width=width, height=height,
        length_window=length_window)
    with st.container(border=True):
        st.markdown("**Sensitivity — which dimension moves the force most?**")
        st.plotly_chart(fig_bar, width="stretch")
        st.plotly_chart(fig_strip, width="stretch")
        st.caption(caption)
    return fig_bar, fig_strip


# --- 2-D interaction map: lock two variables, sweep the other two -------------
@st.cache_data(show_spinner=False)
def _pair_grid(v1, v2, a, b, d, f, x_cg, z_cg, r1, r2, res, feas):
    """2-D (peak, feasible) grid: sweep v1 across r1=(lo,hi) (columns) and v2 across
    r2 (rows) with the other two variables fixed at (a, b, d, f). feas is
    ((name, value), ...) of the optimizer rules. All args hashable -> cached."""
    base = dict(a=a, b=b, d=d, f=f)
    fk = dict(feas)
    vals1 = np.linspace(r1[0], r1[1], res)
    vals2 = np.linspace(r2[0], r2[1], res)
    # Snap the nearest sample to the current value of each swept variable, so the cell
    # under the white dot is evaluated at your EXACT design. Without this the dot can
    # land in a cell whose center is a neighbouring grid value that falls just over a
    # limit (e.g. stroke ratio), painting the dot's own cell black even though your
    # design is feasible.
    vals1[int(np.argmin(np.abs(vals1 - base[v1])))] = base[v1]
    vals2[int(np.argmin(np.abs(vals2 - base[v2])))] = base[v2]
    peak = np.full((res, res), np.nan)
    ok = np.zeros((res, res), dtype=bool)
    for i, yv in enumerate(vals2):
        for j, xv in enumerate(vals1):
            p, fe = peak_force_feasible(**{**base, v1: float(xv), v2: float(yv)},
                                        x_cg=x_cg, z_cg=z_cg, **fk)
            peak[i, j] = p
            ok[i, j] = bool(fe)
    return vals1, vals2, peak, ok


def render_interaction_map(a, b, d, f, x_cg, z_cg, bounds, template="plotly_white",
                           font=None, res=51, stroke_max=None, roof_clearance=0.0,
                           width=None, height=None, length_window=None):
    """A 2-D 'vary two dimensions at once' heatmap. Pick two of a, b, d, f from the
    dropdown; the other two stay at the current design. Same colour language as the
    strip (% of the current force; black = a spot the optimizer would reject), so it
    exposes the interactions the one-at-a-time strip can't see (combined moves)."""
    with st.container(border=True):
        st.markdown("**Interaction map — vary two dimensions at once**")
        st.caption("Pick two dimensions to vary; the other two stay at your current "
                   "design. (a = base along floor, b = attach up wall, "
                   "d = bracket offset, f = base height.)")
        cc1, cc2 = st.columns(2)
        v1 = cc1.selectbox("Horizontal axis", ["a", "b", "d", "f"], index=0,
                           key="interact_v1")
        v2 = cc2.selectbox("Vertical axis", ["a", "b", "d", "f"], index=1,
                           key="interact_v2")
        if v1 == v2:
            st.info("Choose two **different** dimensions to see how they interact.")
            return
        feas = (("stroke_max", stroke_max), ("roof_clearance", roof_clearance),
                ("width", width), ("height", height), ("length_window", length_window))
        vals1, vals2, peak, ok = _pair_grid(
            v1, v2, a, b, d, f, x_cg, z_cg,
            tuple(bounds[v1]), tuple(bounds[v2]), res, feas)
        f0 = peak_force(a, b, d, f, x_cg, z_cg)          # current design's peak force
        if not (np.isfinite(f0) and f0 > 0):             # current impossible: best in view
            fin = peak[ok & np.isfinite(peak)]
            f0 = float(np.nanmin(fin)) if fin.size else 1.0
        ratio = np.where(ok, peak / f0 * 100.0, np.nan)
        black = np.where(ok, np.nan, 1.0)
        zmin, zmax, cs, dtick = _ratio_colorscale(ratio[np.isfinite(ratio)])
        cur = {"a": a, "b": b, "d": d, "f": f}
        fig = go.Figure(go.Heatmap(
            x=vals1, y=vals2, z=ratio, zmin=zmin, zmax=zmax, colorscale=cs,
            colorbar=_ratio_colorbar(dtick)))
        fig.add_trace(go.Heatmap(                        # rejected cells -> black
            x=vals1, y=vals2, z=black, zmin=0.0, zmax=1.0, showscale=False,
            hoverinfo="skip", colorscale=[[0.0, "#111111"], [1.0, "#111111"]]))
        fig.add_trace(go.Scatter(                        # current design
            x=[cur[v1]], y=[cur[v2]], mode="markers", hoverinfo="skip",
            showlegend=False,
            marker=dict(color="white", size=12, line=dict(color="#111", width=1.8))))
        fig.update_layout(
            template=template, font=font, height=430,
            xaxis_title=f"{_LABELS[v1]}  (m)", yaxis_title=f"{_LABELS[v2]}  (m)",
            margin=dict(l=10, r=10, t=6, b=40))
        st.plotly_chart(fig, width="stretch")
        st.caption(
            f"Color = the peak force at that (**{v1}**, **{v2}**) combination as a "
            f"**percent of your current force** (the other two dimensions stay put). "
            f"**White (100%) = same as now** (the **white dot**), **red = worse**, "
            f"**blue = better**, **black = a spot the optimizer would reject**. Unlike "
            f"the strip above, this moves *two* dimensions together, so it shows their "
            f"**interaction** — a diagonal blue pocket is an improvement the one-at-a-"
            f"time view can't reach.")
