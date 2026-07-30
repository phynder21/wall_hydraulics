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
from plotly.subplots import make_subplots
import streamlit as st

from wall import force_feasibility_profiles, peak_force_feasible
from lookup import force_color

_LABELS = {"a": "a — base along floor", "b": "b — attach up wall",
           "d": "d — bracket offset", "f": "f — base height"}

# The two things the panel can color by. The optimizer minimizes one or the other
# (least force, or the shortest cylinder), so the sensitivity charts can track
# whichever objective you care about. `arr` indexes the per-variable profile tuple
# (values, forces, lengths, ok); `per_cyl` divides by cylinder count (force splits
# between cylinders; a length is the same for both). Lower is better for both, so
# blue = better / red = worse holds either way.
_METRICS = {
    "force": dict(arr=1, key_label="Force vs.<br>current", word="peak force",
                  short="force", unit="N/kg", swing="peak-force", fmt=".1f",
                  per_cyl=True),
    "length": dict(arr=2, key_label="Length vs.<br>current", word="cylinder length",
                   short="cylinder length", unit="m", swing="length", fmt=".3f",
                   per_cyl=False),
}


def selected_metric():
    """Which metric the shared 'Color by' toggle is set to ('force' or 'length').
    The toggle lives in render_sensitivity_panel; the interaction map and the PDF
    export read this so one switch drives every part of the sensitivity."""
    return "length" if st.session_state.get("sens_metric") == "Cylinder length" \
        else "force"


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
    """Shared 'force vs. current %' coloring. Given the finite % ratios, return
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


def _ratio_colorbar(dtick, key_label="Force vs.<br>current"):
    """The larger, tick-labelled key shared by the strip and the interaction map.
    `key_label` names the metric (force or cylinder length) being colored."""
    return dict(title=dict(text=key_label, side="top"),
                ticksuffix="%", tick0=100.0, dtick=dtick, ticks="outside",
                ticklen=6, tickwidth=1.2, thickness=20, len=1.0,
                outlinewidth=1, outlinecolor="#888")


def _current_metric_value(metric, a, b, d, f, x_cg, z_cg):
    """The current design's value of the chosen metric (peak force, or extended
    cylinder length) — the 100% reference the strip and map color relative to."""
    peak, l_max, _ = peak_force_feasible(a, b, d, f, x_cg, z_cg)
    return peak if metric == "force" else l_max


def _blackout_sentence(stroke_max, width, height, length_window):
    """Explicit 'why a spot is black' text, listing only the rules that apply in this
    view: over-center and the roof always, plus the stroke-ratio cap (Designer/Browse)
    or the cylinder-length window (Reverse), whichever the view uses."""
    why = ["the cylinder goes over-center"]
    if stroke_max is not None:
        why.append("the stroke ratio exceeds your limit")
    if width is not None and height is not None:
        why.append("the attachment rises through the roof")
    if length_window is not None:
        why.append("somewhere in the swing the geometry needs the cylinder longer "
                   "than its extended length or shorter than its closed length")
    joined = why[0] if len(why) == 1 else ", ".join(why[:-1]) + ", or " + why[-1]
    return f"**Black = a geometry you can't use** — where {joined}."


def _capacity_note(length_window):
    """A Reverse-only clause: since the cylinder is fixed, lower force = more wall
    mass it can raise, and the colored region is the geometries it can actually
    drive. Empty for the Designer/Browse views."""
    if length_window is None:
        return ""
    return (" You're sizing from a fixed cylinder here, so the colored region is the "
            "set of geometries **that cylinder can actually drive**, and within it "
            "**lower force (blue) = more wall mass it can raise**.")


def build_sensitivity_figures(a, b, d, f, x_cg, z_cg, bounds, n_cyl=1,
                              template="plotly_white", font=None, samples=SAMPLES,
                              stroke_max=None, roof_clearance=0.0, width=None,
                              height=None, length_window=None, metric="force"):
    """Build the (tornado bar, within-range strip) figures and the caption text for
    one geometry. Shared by the on-screen panel and the PDF export so both show the
    identical charts. `bounds` maps each of a, b, d, f to its (min, max) range; the
    current a, b, d, f mark the white dot. The optimizer rules (stroke_max,
    roof_clearance, width/height, length_window) black out geometries that would be
    rejected. `metric` picks what the charts track — 'force' (peak piston force) or
    'length' (extended cylinder length). Returns (fig_bar, fig_strip, caption)."""
    M = _METRICS[metric]
    ai = M["arr"]                                        # profile-tuple index of metric
    div = n_cyl if M["per_cyl"] else 1
    bounds_items = tuple(sorted((k, tuple(bounds[k])) for k in ("a", "b", "d", "f")))
    feas = (("stroke_max", stroke_max), ("roof_clearance", roof_clearance),
            ("width", width), ("height", height), ("length_window", length_window))
    prof = _profiles(a, b, d, f, x_cg, z_cg, bounds_items, samples, feas)
    cur = {"a": a, "b": b, "d": d, "f": f}

    def swing(v):
        vals = prof[v][ai][np.isfinite(prof[v][ai])]    # raw leverage over buildable range
        return float(vals.max() - vals.min()) / div if vals.size else 0.0

    ordered = sorted(("a", "b", "d", "f"), key=swing)   # small→big (big on top)
    ys = [_LABELS[v] for v in ordered]

    # Top — tornado: total metric swing per variable (length + color = impact).
    xs = [swing(v) for v in ordered]
    mx = max(xs) if any(xs) else 1.0
    cols = [force_color(x, 0.0, mx) or "#63be7b" for x in xs]
    fig_bar = go.Figure(go.Bar(
        x=xs, y=ys, orientation="h", marker=dict(color=cols),
        text=[f"{x:{M['fmt']}}" for x in xs], textposition="outside", hoverinfo="skip"))
    percyl = " per cyl" if (n_cyl > 1 and M["per_cyl"]) else ""
    fig_bar.update_layout(
        template=template, font=font, height=190,
        xaxis_title=f"Total {M['swing']} swing ({M['unit']}{percyl})",
        xaxis=dict(range=[0, mx * 1.18]), margin=dict(l=10, r=10, t=6, b=30))

    # Bottom — within-range strip. Color = the chosen metric AT each position as a
    # percent of your CURRENT design's value, so you can read "move this variable
    # there and the force (or length) becomes 150% of what it is now." 100% (white) =
    # same as now; red = higher (worse), blue = lower (better). Any spot the OPTIMIZER
    # would reject — over-center, over the stroke ratio, through the roof, or outside
    # the cylinder length window — is painted black and left out of the color scale,
    # so after optimizing there is no "better" (blue) spot the design isn't already
    # using. It's a ratio, so it's mass- and cylinder-count-independent and each
    # variable's range is normalized to 0->1 (one shared position axis).
    m0 = _current_metric_value(metric, a, b, d, f, x_cg, z_cg)   # current value = 100%
    if not (np.isfinite(m0) and m0 > 0):                 # current geometry impossible:
        allM = [prof[v][ai][prof[v][3] & np.isfinite(prof[v][ai])] for v in ordered]
        allM = np.concatenate([s for s in allM if s.size]) if any(s.size for s in allM) \
            else np.array([1.0])
        m0 = float(np.nanmin(allM)) if allM.size else 1.0   # fall back to best in view
    pos = np.linspace(0.0, 1.0, prof["a"][0].size)
    Z, black, finite, cdata = [], [], [], []
    for v in ordered:
        vals, val_arr, ok = prof[v][0], prof[v][ai], prof[v][3]
        ratio = np.where(ok, val_arr / m0 * 100.0, np.nan)   # color only feasible spots
        Z.append(ratio)
        finite.append(ratio[np.isfinite(ratio)])
        # Everything the optimizer rejects (over-center OR a broken rule) -> black.
        black.append(np.where(ok, np.nan, 1.0))
        # Hover shows the actual value + the metric (per cylinder for force), not the %.
        cdata.append(np.stack([vals, val_arr / div], axis=-1))
    allr = np.concatenate([s for s in finite if s.size]) if any(s.size for s in finite) \
        else np.array([100.0])
    zmin, zmax, strip_cs, dtick = _ratio_colorscale(allr)
    curpos = [float(np.clip((cur[v] - bounds[v][0]) /
                            max(bounds[v][1] - bounds[v][0], 1e-9), 0.0, 1.0))
              for v in ordered]
    fig_strip = go.Figure(go.Heatmap(
        x=pos, y=ys, z=Z, zmin=zmin, zmax=zmax, customdata=np.array(cdata),
        hovertemplate="%{y}<br>value = %{customdata[0]:.3f} m<br>"
                      f"{M['word']} = %{{customdata[1]:{M['fmt']}}} {M['unit']}<extra></extra>",
        # blue = lower (better), white = 100% (same), red = higher (worse).
        colorscale=strip_cs, colorbar=_ratio_colorbar(dtick, M["key_label"])))
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
    caption = (f"**Top:** each dimension's overall impact on the {M['short']}. "
               f"**Bottom:** move a dimension to any spot and the color is the "
               f"{M['word']} there as a **% of now** (200% = double, 50% = half) — "
               f"**white = same**, **red = worse**, **blue = better**. "
               f"{_blackout_sentence(stroke_max, width, height, length_window)} "
               f"The **white dot** is your current design."
               f"{_capacity_note(length_window) if metric == 'force' else ''}")
    return fig_bar, fig_strip, caption


def render_sensitivity_panel(a, b, d, f, x_cg, z_cg, bounds, n_cyl=1,
                             template="plotly_white", font=None, samples=SAMPLES,
                             stroke_max=None, roof_clearance=0.0, width=None,
                             height=None, length_window=None):
    """Render the two-chart sensitivity panel for one geometry inside a bordered
    container (uses build_sensitivity_figures so the on-screen charts match the PDF).
    A 'Color by' toggle switches every part of the sensitivity — this panel, the
    interaction map below, and the PDF — between peak force and cylinder length (the
    two things the optimizer can minimize). Returns (fig_bar, fig_strip) so the caller
    can embed the same charts in the PDF."""
    with st.container(border=True):
        choice = st.radio(
            "Color the charts by", ["Peak force", "Cylinder length"],
            key="sens_metric", horizontal=True,
            help="The two things you can optimize for. **Peak force** = the push the "
                 "cylinder must give (smaller = a cheaper cylinder). **Cylinder "
                 "length** = the extended length (smaller = a shorter, more compact "
                 "actuator). Lower is better either way, so blue always = better.")
        metric = "force" if choice == "Peak force" else "length"
        fig_bar, fig_strip, caption = build_sensitivity_figures(
            a, b, d, f, x_cg, z_cg, bounds, n_cyl=n_cyl,
            template=template, font=font, samples=samples, stroke_max=stroke_max,
            roof_clearance=roof_clearance, width=width, height=height,
            length_window=length_window, metric=metric)
        st.markdown(f"**Sensitivity — which dimension moves the {_METRICS[metric]['short']} "
                    f"most?**")
        st.plotly_chart(fig_bar, width="stretch")
        st.plotly_chart(fig_strip, width="stretch")
        st.caption(caption)
    return fig_bar, fig_strip


# --- 2-D interaction map: lock two variables, sweep the other two -------------
@st.cache_data(show_spinner=False)
def _pair_grid(v1, v2, a, b, d, f, x_cg, z_cg, r1, r2, res, feas):
    """2-D (peak, L_max, feasible) grid: sweep v1 across r1=(lo,hi) (columns) and v2
    across r2 (rows) with the other two variables fixed at (a, b, d, f). feas is
    ((name, value), ...) of the optimizer rules. Carries both metrics (force and
    extended cylinder length) so the map can color by either. All args hashable ->
    cached."""
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
    lmax = np.full((res, res), np.nan)
    ok = np.zeros((res, res), dtype=bool)
    for i, yv in enumerate(vals2):
        for j, xv in enumerate(vals1):
            p, lm, fe = peak_force_feasible(**{**base, v1: float(xv), v2: float(yv)},
                                            x_cg=x_cg, z_cg=z_cg, **fk)
            peak[i, j] = p
            lmax[i, j] = lm
            ok[i, j] = bool(fe)
    return vals1, vals2, peak, lmax, ok


def render_interaction_map(a, b, d, f, x_cg, z_cg, bounds, n_cyl=1,
                           template="plotly_white", font=None, res=91, stroke_max=None,
                           roof_clearance=0.0, width=None, height=None,
                           length_window=None):
    """A 2-D 'vary two dimensions at once' heatmap. Pick two of a, b, d, f from the
    dropdown; the other two stay at the current design. Same color language as the
    strip (% of the current metric; black = a spot the optimizer would reject), so it
    exposes the interactions the one-at-a-time strip can't see (combined moves). Colors
    by whatever the panel's 'Color by' toggle selects — peak force or cylinder length."""
    metric = selected_metric()
    M = _METRICS[metric]
    div = n_cyl if M["per_cyl"] else 1
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
        vals1, vals2, peak, lmax, ok = _pair_grid(
            v1, v2, a, b, d, f, x_cg, z_cg,
            tuple(bounds[v1]), tuple(bounds[v2]), res, feas)
        grid = peak if metric == "force" else lmax        # metric to color by
        m0 = _current_metric_value(metric, a, b, d, f, x_cg, z_cg)   # current = 100%
        if not (np.isfinite(m0) and m0 > 0):             # current impossible: best in view
            fin = grid[ok & np.isfinite(grid)]
            m0 = float(np.nanmin(fin)) if fin.size else 1.0
        ratio = np.where(ok, grid / m0 * 100.0, np.nan)
        black = np.where(ok, np.nan, 1.0)
        zmin, zmax, cs, dtick = _ratio_colorscale(ratio[np.isfinite(ratio)])
        cur = {"a": a, "b": b, "d": d, "f": f}
        fig = go.Figure(go.Heatmap(
            x=vals1, y=vals2, z=ratio, zmin=zmin, zmax=zmax, colorscale=cs,
            customdata=grid / div,                        # hover shows the metric, not %
            hovertemplate=(f"{v1} = %{{x:.3f}} m<br>{v2} = %{{y:.3f}} m<br>"
                           f"{M['word']} = %{{customdata:{M['fmt']}}} {M['unit']}<extra></extra>"),
            colorbar=_ratio_colorbar(dtick, M["key_label"])))
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
            f"Color = the {M['word']} at each (**{v1}**, **{v2}**) as a **% of now** — "
            f"**white = same**, **red = worse**, **blue = better**; the **white dot** "
            f"is your design. "
            f"{_blackout_sentence(stroke_max, width, height, length_window)} "
            f"Sometimes the {M['short']} only drops when you change **both** dimensions "
            f"together — those designs show up as blue here, but the one-at-a-time "
            f"strip above can't find them."
            f"{_capacity_note(length_window) if metric == 'force' else ''}")


_ALL_PAIRS = (("a", "b"), ("a", "d"), ("a", "f"), ("b", "d"), ("b", "f"), ("d", "f"))


def build_interaction_matrix(a, b, d, f, x_cg, z_cg, bounds, res=41, stroke_max=None,
                             roof_clearance=0.0, width=None, height=None,
                             length_window=None, template="plotly_white", metric="force"):
    """A 2x3 small-multiples matrix of ALL six 2-D interaction maps (every pair of
    a, b, d, f), on ONE shared 'metric vs. current %' scale so the panels compare.
    `metric` picks peak force or cylinder length. Built on demand (for the PDF), not
    live. Returns a print-ready figure. Uses the cached _pair_grid per pair, so any
    pair already shown on screen is reused."""
    M = _METRICS[metric]
    feas = (("stroke_max", stroke_max), ("roof_clearance", roof_clearance),
            ("width", width), ("height", height), ("length_window", length_window))
    cur = {"a": a, "b": b, "d": d, "f": f}
    grids, all_feas = [], []
    for v1, v2 in _ALL_PAIRS:
        vals1, vals2, peak, lmax, ok = _pair_grid(
            v1, v2, a, b, d, f, x_cg, z_cg, tuple(bounds[v1]), tuple(bounds[v2]), res, feas)
        grid = peak if metric == "force" else lmax
        grids.append((v1, v2, vals1, vals2, grid, ok))
        r = grid[ok & np.isfinite(grid)]
        if r.size:
            all_feas.append(r.ravel())
    m0 = _current_metric_value(metric, a, b, d, f, x_cg, z_cg)   # shared ref = current
    if not (np.isfinite(m0) and m0 > 0):
        m0 = float(np.nanmin(np.concatenate(all_feas))) if all_feas else 1.0
    allr = (np.concatenate(all_feas) / m0 * 100.0) if all_feas else np.array([100.0])
    zmin, zmax, cs, dtick = _ratio_colorscale(allr)     # one scale for all six panels
    fig = make_subplots(rows=2, cols=3,
                        subplot_titles=[f"{v1} x {v2}" for v1, v2, *_ in grids],
                        horizontal_spacing=0.09, vertical_spacing=0.14)
    for k, (v1, v2, vals1, vals2, grid, ok) in enumerate(grids):
        rr, cc = k // 3 + 1, k % 3 + 1
        ratio = np.where(ok, grid / m0 * 100.0, np.nan)
        black = np.where(ok, np.nan, 1.0)
        fig.add_trace(go.Heatmap(x=vals1, y=vals2, z=ratio, coloraxis="coloraxis",
                                 hoverinfo="skip"), row=rr, col=cc)
        fig.add_trace(go.Heatmap(x=vals1, y=vals2, z=black, zmin=0.0, zmax=1.0,
                                 showscale=False, hoverinfo="skip",
                                 colorscale=[[0.0, "#111111"], [1.0, "#111111"]]),
                      row=rr, col=cc)
        fig.add_trace(go.Scatter(x=[cur[v1]], y=[cur[v2]], mode="markers",
                                 hoverinfo="skip", showlegend=False,
                                 marker=dict(color="white", size=8,
                                             line=dict(color="#111", width=1.3))),
                      row=rr, col=cc)
        fig.update_xaxes(title_text=v1, title_standoff=3, row=rr, col=cc)
        fig.update_yaxes(title_text=v2, title_standoff=3, row=rr, col=cc)
    fig.update_layout(
        template=template, font=dict(family="sans-serif", size=12, color="#0F172A"),
        showlegend=False, margin=dict(l=55, r=40, t=45, b=45),
        coloraxis=dict(colorscale=cs, cmin=zmin, cmax=zmax,
                       colorbar=_ratio_colorbar(dtick, M["key_label"])))
    return fig
