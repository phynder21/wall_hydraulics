import time

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from wall import (
    STROKE_RATIO_MAX,
    compute_F_piston,
    compute_geometry,
    compute_cylinder_length,
)
# Imported at top level (not lazily inside the button) so Streamlit's file
# watcher tracks optimize.py and reloads it on edit, like wall.py.
from optimize import optimize_actuator, STROKE_TOL
from browse import render_browse
from reverse import render_reverse
from lookup import force_bar, force_bar_html, BAR_NEUTRAL, cylinder_banner
from sensitivity_panel import (render_sensitivity_panel, render_interaction_map,
                               build_interaction_matrix, selected_metric)
from display_units import Units
from cylinder_panel import render_cylinder_sizing
from pdf_export import render_pdf_export

# Human-readable build marker. Bump on notable changes so you can tell at a
# glance whether a running/deployed page has the latest code (a stale process
# shows the OLD marker). If the app errors right after a push, check this — an
# old marker means the deploy hasn't reloaded yet (reboot it).
BUILD = "tabbed inspector layout · 2026-07-06"

# Shared plot styling for a consistent, clean look across all charts.
PLOT_TEMPLATE = "plotly_white"
PRIMARY = "#2563EB"        # accent blue, matches the app theme
PLOT_FONT = dict(family="sans-serif", size=13, color="#0F172A")

st.set_page_config(page_title="Container Wall Actuator", layout="wide")

# Left rail: a build marker + the cylinder count, beside the tabbed control panel.
st.sidebar.markdown("### Wall actuator")
st.sidebar.markdown("<u>Cylinders sharing the load</u>", unsafe_allow_html=True)
n_cyl = st.sidebar.radio(
    "Cylinders sharing the load", [1, 2], key="n_cyl", horizontal=True,
    label_visibility="collapsed",
    help="How many cylinders share the wall load equally. With 2, each carries "
         "half — so every force and bore size shown is PER CYLINDER. The geometry "
         "is the same either way.")
st.sidebar.caption(f"build: {BUILD}")
# --- Quick-start guide, opened as a page-like modal from a link under the tabs ---
_GUIDE_INTRO = """
### What this tool is for

It sizes the **hydraulic cylinder that raises a hinged shipping-container sidewall**
— or, going the other way, finds the geometry a cylinder you already have can drive.
The aim is a design that needs the **least force** — or the **shortest cylinder** — so
you can use a smaller, cheaper actuator. (You pick which to minimize in the Designer,
and the sensitivity charts can be switched to track either one.)

The wall pivots on a hinge and swings from flat (0°) to upright (90°) while the
cylinder pushes it up. Four numbers place the cylinder (see the diagram below):

- **a** — base position along the floor
- **b** — attachment point up the wall
- **d** — how far the bracket sticks off the wall
- **f** — height of the base above the floor
- **x_cg, z_cg** — where the wall's weight acts (along the wall, and off it)
"""

_GUIDE_REST = """
### The three tabs

- **Designer** — set your wall (container size, weight) and **optimize** a, b, d, f to
  the smallest force. It also reports the cylinder you'd need: bore, pressure, stroke,
  and closed/extended length.
- **Browse configurations** — an instant search of pre-computed geometries; a faster
  way to explore than waiting on the optimizer.
- **Size from a cylinder** — enter a **real cylinder** you can buy; it finds the best
  geometry that cylinder can drive and the heaviest wall it can raise.

### How to use it

1. **Designer** — dial in your wall and optimize. Read off the **cylinder spec** it
   needs (force, stroke, closed/extended length). This tells you *what to buy*.
2. **Shop** for a real cylinder as close to that spec as you can find.
3. **Size from a cylinder** — plug that real cylinder in. It gives the **final
   a, b, d, f** to build and the max wall mass it can raise. This tells you *how to
   mount what you bought*.

The geometry in step 3 won't exactly match step 1 — that's expected: the real
cylinder's length range re-shapes the best layout. Just check that its **max wall
mass is at least your actual wall + load** (with your safety factor).

### Reading the diagrams

Under each result, the **sensitivity** charts show which dimension moves the result
most and which way to nudge it, and the **interaction map** shows two dimensions at
once. A **Color by** toggle switches all of them between **peak force** and **cylinder
length**, so you can chase whichever you're minimizing. Everywhere: **blue = lower
(better)**, **red = higher (worse)**, **black = a geometry that breaks a rule** (e.g.
over-center, over the stroke ratio, or — in Reverse — outside your cylinder's length).
"""


def _guide_diagram():
    """A labelled schematic of the geometry for the guide: hinge, wall, cylinder,
    base, attachment and cg, with a and f dimensioned in Cartesian, and b (along the
    wall) and d (perpendicular off it) dimensioned in the wall frame. Illustrative
    values (a bigger d than typical) so every dimension reads clearly."""
    a, b, d, f, xcg, zcg = 0.6, 1.55, 0.5, 0.4, 1.0, 0.42
    W, H = 2.352, 2.393                             # internal (clear) — Standard
    th = np.radians(52)
    c, s = np.cos(th), np.sin(th)
    wall = np.array([c, s])                        # unit vector up the wall
    perp = np.array([-s, c])                        # unit vector off the wall (bracket side)
    base = np.array([-a, f])
    tip = 2.25 * wall
    footb = b * wall                                # wall-axis point at distance b
    att = b * wall + d * perp                       # attachment: b up, d off
    cg = xcg * wall + zcg * perp
    fig = go.Figure()

    def line(p, q, color, w):
        fig.add_trace(go.Scatter(x=[p[0], q[0]], y=[p[1], q[1]], mode="lines",
                                 hoverinfo="skip", showlegend=False,
                                 line=dict(color=color, width=w)))
    # Container outline (internal clear dimensions)
    fig.add_trace(go.Scatter(x=[0, -W, -W, 0], y=[0, 0, H, H], mode="lines",
                             line=dict(color="#cbd5e1", width=2), hoverinfo="skip",
                             showlegend=False))
    fig.add_hline(y=0, line=dict(color="#cbd5e1", dash="dot"))
    line((0, 0), tip, "#111827", 7)                # wall
    line(base, (base[0], 0), "#94a3b8", 3)         # base post
    line(footb, att, "#94a3b8", 3)                 # bracket (this IS d)
    line(base, att, "#dc2626", 4)                  # cylinder

    def dot(p, color, name, sym="circle", size=11):
        fig.add_trace(go.Scatter(x=[p[0]], y=[p[1]], mode="markers", name=name,
                                 marker=dict(size=size, color=color, symbol=sym),
                                 hoverinfo="skip"))
    dot((0, 0), "#111827", "hinge")
    dot(base, "#dc2626", "cylinder base", "square")
    dot(att, "#2563eb", "piston attachment")
    dot(cg, "#16a34a", "center of gravity", "cross", 13)
    # a (floor) and f (post): Cartesian dimension lines with end ticks
    fig.add_shape(type="line", x0=0, y0=-0.16, x1=-a, y1=-0.16, line=dict(color="#475569", width=1))
    for xx in (0, -a):
        fig.add_shape(type="line", x0=xx, y0=-0.10, x1=xx, y1=-0.22, line=dict(color="#475569", width=1))
    fig.add_annotation(x=-a / 2, y=-0.34, text="<b>a</b> — base along the floor",
                       showarrow=False, font=dict(size=13, color="#0f172a"))
    fig.add_shape(type="line", x0=-a - 0.16, y0=0, x1=-a - 0.16, y1=f, line=dict(color="#475569", width=1))
    for yy in (0, f):
        fig.add_shape(type="line", x0=-a - 0.10, y0=yy, x1=-a - 0.22, y1=yy, line=dict(color="#475569", width=1))
    fig.add_annotation(x=-a - 0.5, y=f / 2, text="<b>f</b> — base height",
                       showarrow=False, font=dict(size=13, color="#0f172a"), textangle=-90)
    # b: a dimension line PARALLEL to the wall, offset to the side away from the
    # bracket, with ticks — so it clearly reads as a distance measured UP the wall.
    o = 0.28 * (-perp)
    p0, p1 = np.array([0.0, 0.0]) + o, footb + o
    line((0, 0), p0, "#475569", 1)                 # tick at the hinge end
    line(footb, p1, "#475569", 1)                  # tick at the b end
    line(p0, p1, "#475569", 1)                     # the dimension line
    lab = (p0 + p1) / 2 + 0.17 * (-perp)
    fig.add_annotation(x=lab[0], y=lab[1], text="<b>b</b> — up the wall", showarrow=False,
                       textangle=-(90 - np.degrees(th)), font=dict(size=13, color="#0f172a"))
    # d: the bracket itself IS the dimension. End ticks (parallel to the wall) at both
    # ends turn it into a measured distance, and a right-angle mark shows it leaves the
    # wall square; the label sits in open space with the arrow pointing at the bracket.
    tk = 0.06 * wall
    line(footb - tk, footb + tk, "#475569", 1)     # tick at the wall end
    line(att - tk, att + tk, "#475569", 1)         # tick at the attachment end
    ra = 0.12
    line(footb + ra * wall, footb + ra * wall + ra * perp, "#475569", 1)
    line(footb + ra * wall + ra * perp, footb + ra * perp, "#475569", 1)
    mid = (footb + att) / 2
    fig.add_annotation(x=mid[0], y=mid[1], ax=0.42, ay=1.82, axref="x", ayref="y",
                       text="<b>d</b> — sticks off the wall", showarrow=True, arrowhead=3,
                       arrowwidth=1.3, arrowcolor="#475569", font=dict(size=13, color="#0f172a"),
                       bgcolor="rgba(255,255,255,0.85)")
    fig.add_annotation(x=cg[0], y=cg[1], ax=cg[0] - 0.8, ay=cg[1] + 0.5, axref="x", ayref="y",
                       text="<b>cg</b> — weight acts here", showarrow=True, arrowhead=3,
                       arrowwidth=1.3, arrowcolor="#475569", font=dict(size=12, color="#0f172a"),
                       bgcolor="rgba(255,255,255,0.85)")
    fig.add_annotation(x=tip[0], y=tip[1], text="wall (swings 0–90°)", showarrow=False,
                       font=dict(size=12, color="#374151"), yshift=14, xshift=30)
    fig.update_layout(template=PLOT_TEMPLATE, font=PLOT_FONT, height=520,
                      legend=dict(orientation="h", y=-0.1, x=0.5, xanchor="center"),
                      margin=dict(l=55, r=25, t=10, b=70),
                      xaxis_title="x (m)", yaxis_title="z (m)")
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    return fig


@st.dialog("How this tool works", width="large")
def _show_guide():
    st.markdown(_GUIDE_INTRO)
    st.plotly_chart(_guide_diagram(), width="stretch")
    st.markdown(_GUIDE_REST)


# Top-of-page view switch as a header bar: full-width buttons (large), the active
# view colored as a primary button, the rest secondary. Native buttons render
# reliably (CSS styling of the segmented control didn't take on the deployment),
# and `type="primary"` colors the active tab; st.stop renders only the chosen view.
_VIEWS = ["Designer", "Browse configurations", "Size from a cylinder"]
st.session_state.setdefault("view", "Designer")
with st.container(border=True):
    _cols = st.columns(len(_VIEWS))
    for _col, _name in zip(_cols, _VIEWS):
        if _col.button(_name, key=f"viewbtn_{_name}", use_container_width=True,
                       type="primary" if st.session_state["view"] == _name else "secondary"):
            st.session_state["view"] = _name
            st.rerun()
_view = st.session_state["view"]
st.caption("New here? What this tool is for and how to use it —")
if st.button("Open the quick guide", type="tertiary", key="guide_btn"):
    _show_guide()
st.divider()
if _view == "Browse configurations":
    render_browse()
    st.stop()
if _view == "Size from a cylinder":
    render_reverse()
    st.stop()

# --- Display units — at the TOP of the Designer sidebar so it's visible from every
# tab (Geometry/Setup/Optimize/Compare), not buried in Setup. Everything is stored and
# computed in SI base units internally — lengths in METERS, mass in KG, force in N,
# specific force in N/kg, pressure in bar — so the physics, the optimizer, and shared
# URLs stay consistent; this single Imperial/Metric switch only changes how values are
# *displayed* (and the bore card follows it).
st.sidebar.markdown("<u>Units</u>", unsafe_allow_html=True)
units = st.sidebar.radio("Units", ["Metric", "Imperial"], key="units", horizontal=True,
                         label_visibility="collapsed")
fine = st.sidebar.toggle(
    "Fine precision", key="fine",
    help="Finer slider/number steps for exact values (0.001 m / 0.01 in), and the "
         "optimizer rounds to that precision — so the plotted force matches the "
         "reported one more closely.")
# Shared with Browse via display_units so the two convert identically.
_u = Units(units, fine)
imperial, U, ULABEL, UWORD = _u.imperial, _u.U, _u.ULABEL, _u.UWORD
MU, MLABEL, PU, PLABEL = _u.MU, _u.MLABEL, _u.PU, _u.PLABEL
FU, FLABEL = _u.FU, _u.FLABEL
LEN_STEP, LEN_FMT, ROUND_DP = _u.LEN_STEP, _u.LEN_FMT, _u.ROUND_DP
fmt_pk, fmt_total, fmt_mass = _u.pk, _u.total, _u.mass


# ISO container dimensions (external)
# Values are INTERNAL (clear) dimensions — the usable space inside the shell, which
# is what constrains the mechanism (see optimize.CONTAINER_PRESETS). The 8'6"/9'6"
# in the labels is the container's external name; the meters are the clear interior.
CONTAINER_SIZES = {
    "Standard (8'6\") — 2.35 × 2.39 m internal": (2.352, 2.393),
    "High-Cube (9'6\") — 2.35 × 2.70 m internal": (2.352, 2.698),
}

# Initial values used on first load (no URL params). Chosen to give a plausible
# working configuration for a real container door.
DEFAULTS = {
    "size_key": list(CONTAINER_SIZES.keys())[0],
    "a": 0.60,
    "b": 1.80,
    "d": 0.10,
    "f": 0.40,
    "x_cg": 1.20,
    "z_cg": 0.55,
    "mass": 500.0,
    "theta_deg": 45.0,
    "stroke_ratio": STROKE_RATIO_MAX,   # max L_max/L_min (also drives optimizer)
    "roof_clearance": 0.0,              # m the endpoint must stay below the roof
}

# Hydrate session state from URL query params (so reloads preserve values).
qp = st.query_params
for key, default in DEFAULTS.items():
    if key in st.session_state:
        continue
    raw = qp.get(key)
    if raw is None:
        st.session_state[key] = default
    else:
        try:
            st.session_state[key] = type(default)(raw)
        except (ValueError, TypeError):
            st.session_state[key] = default

# size_key is the one field with no numeric clamp to fall back on, so a bad
# value from the URL would crash the selectbox below. Validate membership.
if st.session_state["size_key"] not in CONTAINER_SIZES:
    st.session_state["size_key"] = DEFAULTS["size_key"]

# Mass has no other clamp; keep a URL-supplied value inside its slider range.
st.session_state["mass"] = float(min(max(st.session_state["mass"], 50.0), 20000.0))


def _clamp(key, lo, hi):
    """Clamp a persisted value into [lo, hi] so a container/unit change can't
    trip a 'value out of range' error on the widget that reads it."""
    st.session_state[key] = float(min(max(st.session_state[key], lo), hi))


def linked_input(label, key, lo, hi, step=0.01, fmt="%.2f", help=None,
                 lockable=False, disp_factor=1.0, disp_step=None, wkey=None):
    """A draggable slider AND a typeable number box bound to one value, rendered
    into the CURRENT container (call it inside a `with tab:`/sidebar block).

    `st.session_state[key]` is the single source of truth (URL-persisted). The
    two widgets get their own keys and are re-seeded from the canonical value
    each run, so they stay in sync and respect the current clamps. Either one
    edited writes back to the canonical value via its on_change callback.

    When `lockable`, a lock checkbox (transient state under `lock_<key>`) lets the
    user pin this value so the optimizer holds it fixed.

    `disp_factor` scales the canonical (stored) value for display: the widgets
    show `value * disp_factor` and `lo`/`hi * disp_factor`, and convert edits
    back by dividing. `lo`/`hi` and the returned value stay in canonical units.
    """
    # wkey lets the SAME value (key) be shown by a second set of widgets in
    # another place (distinct widget keys) — both stay in sync via `key`.
    wk = wkey or key
    skey, nkey = f"{wk}__sld", f"{wk}__num"
    U = disp_factor
    dstep = disp_step if disp_step is not None else step
    st.session_state[skey] = st.session_state[key] * U
    st.session_state[nkey] = st.session_state[key] * U

    def _from_sld():
        st.session_state[key] = st.session_state[skey] / U

    def _from_num():
        st.session_state[key] = float(min(max(st.session_state[nkey] / U, lo), hi))

    if lockable:
        st.session_state.setdefault(f"lock_{key}", False)
        c1, c2, c3 = st.columns([2, 1, 0.7])
    else:
        c1, c2 = st.columns([2, 1])
    c1.slider(label, lo * U, hi * U, step=dstep, key=skey,
              on_change=_from_sld, help=help)
    c2.number_input(label, min_value=lo * U, max_value=hi * U, step=dstep,
                    key=nkey, on_change=_from_num, format=fmt,
                    label_visibility="collapsed")
    if lockable:
        c3.checkbox("Lock", key=f"lock_{key}",
                    help="Hold this value fixed when you press Optimize.")
    return st.session_state[key]


MIN_SPAN = 0.01   # smallest allowed mounting range (m); tighter than this, lock the value


def range_input(label, key, full_lo, full_hi, disp_factor=1.0, disp_step=0.01,
                fmt="%.2f"):
    """A [min, max] sub-range control within [full_lo, full_hi]: a range slider
    (drag) plus min/max number boxes (type). Canonical (min, max) in METERS is
    our own state in session_state[key]; widgets show display units and track
    unit/container changes. A minimum span is enforced so a downstream value
    slider never gets a zero-width range.
    """
    U = disp_factor
    st.session_state.setdefault(key, (full_lo, full_hi))
    lo, hi = st.session_state[key]
    # If the container changed the full range (e.g. Standard -> High-Cube makes
    # the wall taller), grow any endpoint that was still pinned to the OLD full
    # extent -- i.e. an untouched limit -- out to the new one. This keeps an
    # untouched range spanning the whole container instead of freezing at the
    # previous container's size, while leaving user-narrowed ranges alone.
    full_key = f"{key}__full"
    prev_full = st.session_state.get(full_key)
    if prev_full is not None and prev_full != (full_lo, full_hi):
        prev_lo, prev_hi = prev_full
        if lo == prev_lo:
            lo = full_lo
        if hi == prev_hi:
            hi = full_hi
    st.session_state[full_key] = (full_lo, full_hi)
    lo = min(max(lo, full_lo), full_hi)
    hi = min(max(hi, full_lo), full_hi)
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo < MIN_SPAN:                        # never a zero-width range
        hi = min(lo + MIN_SPAN, full_hi)
        lo = max(hi - MIN_SPAN, full_lo)
    st.session_state[key] = (lo, hi)

    # All three widgets are keyed and re-seeded from the canonical range each run;
    # each writes back via its on_change (so typed input isn't clobbered by the
    # reseed). A tuple-seeded keyed slider renders as a range with no warning.
    rk, lo_w, hi_w = f"{key}__rng", f"{key}__lo", f"{key}__hi"
    st.session_state[rk] = (lo * U, hi * U)
    st.session_state[lo_w] = lo * U
    st.session_state[hi_w] = hi * U

    def _from_slider():
        wl, wh = st.session_state[rk]
        st.session_state[key] = (wl / U, wh / U)

    def _from_boxes():
        wl, wh = st.session_state[lo_w] / U, st.session_state[hi_w] / U
        st.session_state[key] = (min(wl, wh), max(wl, wh))

    st.markdown(f"**{label}**")
    st.slider(f"{key} range", full_lo * U, full_hi * U, step=disp_step, key=rk,
              on_change=_from_slider, label_visibility="collapsed")
    c1, c2 = st.columns(2)
    c1.number_input("min", min_value=full_lo * U, max_value=full_hi * U,
                    step=disp_step, format=fmt, key=lo_w, on_change=_from_boxes)
    c2.number_input("max", min_value=full_lo * U, max_value=full_hi * U,
                    step=disp_step, format=fmt, key=hi_w, on_change=_from_boxes)
    return st.session_state[key]


# --- Animation -----------------------------------------------------------
ANIM_STEP_DEG = 3.0     # degrees advanced per frame
FRAME_DELAY_S = 0.05    # pause between frames (~ steady frame rate)


def _advance_angle(angle, direction, step=ANIM_STEP_DEG):
    """Next sweep angle, bouncing back at the 0 and 90 degree limits.

    Returns (new_angle, new_direction) with direction in {+1, -1}.
    """
    nxt = angle + direction * step
    if nxt >= 90.0:
        return 90.0, -1
    if nxt <= 0.0:
        return 0.0, 1
    return nxt, direction


# =============================================================================
# LEFT PANEL — tabbed controls. Tabs render in code order, so the Optimize tab
# (whose button writes a/b/d/f) is executed before the Geometry tab that reads
# them, keeping the same-run "click optimize -> sliders update" behavior even
# though the tabs sit side by side.
# =============================================================================
tab_geometry, tab_setup, tab_optimize, tab_compare = st.sidebar.tabs(
    ["Geometry", "Setup", "Optimize", "Compare"])

with tab_setup:
    st.subheader("Container")
    size_key = st.selectbox("Container size", list(CONTAINER_SIZES.keys()),
                            key="size_key")
    container_width, container_height = CONTAINER_SIZES[size_key]
    st.caption("**These are internal (clear) dimensions** — the usable space *inside* "
               "the container, not the outer shell. The wall panel spans this clear "
               "opening and the moving parts must clear the internal roof.")

    # Half-container cap on the cylinder base position `a` (keep it in the near half of
    # the floor). The toggle WIDGET lives in the Geometry tab, next to the variable
    # ranges it governs; here we only read its state so GEOM_BOUNDS reflects it. Defaults
    # ON, so on first load `a` is capped at half the width.
    half_a = st.session_state.get("half_a_cap", True)

    # Bounds for the four geometry variables — single source of truth shared by
    # the slider widgets, the clamp-on-resize logic, and the optimize button's
    # clamp, so they can never drift apart and let an optimized value fall
    # outside a slider. `a`'s upper bound follows the half-container toggle above.
    _a_hi = container_width / 2 if half_a else container_width
    GEOM_BOUNDS = {
        "a": (0.05, _a_hi),
        "b": (0.05, container_height),
        "d": (0.00, _a_hi),          # bracket offset shares the half-container cap
        "f": (0.00, container_height),
    }
    for _k, (_lo, _hi) in GEOM_BOUNDS.items():
        _clamp(_k, _lo, _hi)
    _clamp("x_cg", 0.00, container_height)
    _clamp("z_cg", 0.00, 1.50)
    _clamp("theta_deg", 0.0, 90.0)
    _clamp("stroke_ratio", 1.0, 3.0)
    _clamp("roof_clearance", 0.0, 0.5)

    # --- Center of gravity: the load the actuator must hold ---
    st.subheader(f"Center of gravity ({UWORD})")
    x_cg = linked_input(f"x_cg — along wall from hinge [{ULABEL}]", "x_cg",
                        0.0, container_height, disp_factor=U, disp_step=LEN_STEP,
                        fmt=LEN_FMT)
    z_cg = linked_input(f"z_cg — perpendicular off wall [{ULABEL}]", "z_cg",
                        0.0, 1.5, disp_factor=U, disp_step=LEN_STEP, fmt=LEN_FMT)
    mass = linked_input(f"Wall + load mass ({MLABEL})", "mass", 50.0, 20000.0,
                        step=10.0, disp_factor=MU, disp_step=10.0, fmt="%.0f",
                        help="Total mass of the wall plus anything mounted on it. "
                             "Peak force per unit mass × this = the real cylinder force.")

    # --- Constraints (shared with the optimizer) ---
    st.subheader("Constraints")
    stroke_ratio = st.number_input(
        "Max stroke ratio (L_max / L_min)", min_value=1.0, max_value=3.0,
        step=0.05, key="stroke_ratio",
        help="Hydraulic cylinders extend at most ~1.8–2× their retracted length.")
    roof_clearance = linked_input(
        f"Roof clearance [{ULABEL}]", "roof_clearance", 0.0, 0.5,
        disp_factor=U, disp_step=LEN_STEP, fmt=LEN_FMT,
        help="Gap the actuator endpoint must keep below the ceiling.")

# Variable ranges (mounting limits) belong with the Geometry variables they
# bound. Rendered here — before the Optimize tab executes — so USER_BOUNDS is
# defined for both the optimizer and the value sliders (which appear just below
# it in the same Geometry tab).
with tab_geometry:
    st.subheader("Variable ranges")
    # Half-container cap on `a` (base along the floor) AND `d` (bracket offset): keep
    # both in the near half of the container — the base on the near-half floor, and the
    # attachment (which sits at x = -d when the wall is vertical) in the near half too.
    # Governs a's and d's range/slider below; on by default. tab_setup reads this key to
    # build GEOM_BOUNDS before this renders.
    st.checkbox("Keep base and bracket within half the container", value=True,
                key="half_a_cap",
                help="Caps both the base position **a** and the bracket offset **d** at "
                     "half the container width, so the base stays in the near half of "
                     "the floor and the attachment stays in the near half at full lift. "
                     "Uncheck to let a and d use the full width.")
    _half = container_width / 2 * U
    if half_a:
        st.caption(f"Active: **a ≤ {_half:.2f} {ULABEL}** and **d ≤ {_half:.2f} "
                   f"{ULABEL}** (half of the {container_width * U:.2f} {ULABEL} internal "
                   f"width).")
    else:
        st.caption(f"Off — **a** and **d** may use the full "
                   f"**{container_width * U:.2f} {ULABEL}** width.")
    with st.expander("Restrict where each dimension may sit (optimizer + slider)"):
        USER_BOUNDS = {
            v: range_input(f"{lbl} [{ULABEL}]", f"rng_{v}", *GEOM_BOUNDS[v],
                           disp_factor=U, disp_step=LEN_STEP, fmt=LEN_FMT)
            for v, lbl in (("a", "a — floor position"), ("b", "b — along wall"),
                           ("d", "d — bracket length"), ("f", "f — base height"))
        }
    # Keep each geometry value inside its (possibly narrowed) range before the
    # value sliders and the optimizer see it.
    for _k in ("a", "b", "d", "f"):
        _clamp(_k, *USER_BOUNDS[_k])

with tab_optimize:
    st.subheader("Optimize")
    st.session_state.setdefault("alt_pct", 15)
    alt_pct = st.slider(
        "Show alternatives within __% of the optimum", 0, 30, key="alt_pct",
        step=1,
        help="After optimizing, also list geometrically DIFFERENT designs whose "
             "peak force is within this percent of the optimum — fallbacks for "
             "when the optimum is awkward to build. 0 keeps only the optimum "
             "(and any exact ties). A sharp optimum may need ~10% before a "
             "different design appears.")

    st.session_state.setdefault("opt_mode", "Peak force")
    opt_mode = st.radio(
        "Optimize to minimize", ["Peak force", "Cylinder length"], key="opt_mode",
        horizontal=True,
        help="Peak force: the smallest piston force (best when force is the limit, "
             "e.g. a hydraulic cylinder where force is cheap). Cylinder length: the "
             "smallest actuator — shortest extended length — that still keeps peak "
             "force at or below a cap you set. Best when physical size is what costs, "
             "e.g. an electromechanical actuator.")
    force_cap_per_kg = None
    if opt_mode == "Cylinder length":
        # ONE slider: the biggest push your actuator can give (per cylinder). The
        # optimizer's real constraint is per-mass, so we divide by the Setup wall +
        # load mass to get it — the max force and the mass fold into a single limit,
        # and a heavier wall spends that force budget faster.
        st.session_state.setdefault("max_force_n", 200000.0)   # base newtons
        max_force_n = linked_input(
            f"Max cylinder force ({FLABEL})", "max_force_n", 1000.0, 1_000_000.0,
            step=1000.0, disp_factor=FU, disp_step=(100.0 if imperial else 1.0),
            fmt="%.0f",
            help="The largest force your actuator can push, per cylinder. The optimizer "
                 "finds the shortest cylinder whose peak force stays at or below this "
                 "for your Setup wall + load mass — so set the mass in Setup first.")
        force_cap_per_kg = max_force_n / mass if mass > 0 else float("inf")
        st.caption(
            f"= **{fmt_pk(force_cap_per_kg)}** at your {fmt_mass(mass)} wall — the "
            f"per-mass budget the optimizer actually holds the peak force under.")

    if st.button("Optimize geometry for current settings", type="primary",
                 use_container_width=True):
        try:
            # Locked variables held at their current value; the rest are searched.
            locked = {k: round(st.session_state[k], ROUND_DP)
                      for k in ("a", "b", "d", "f")
                      if st.session_state.get(f"lock_{k}", False)}
            with st.spinner("Searching for the global optimum (~5 s)…"):
                res = optimize_actuator(
                    container_width=container_width,
                    container_height=container_height,
                    x_cg=st.session_state["x_cg"], z_cg=st.session_state["z_cg"],
                    stroke_ratio_max=st.session_state["stroke_ratio"],
                    roof_clearance=st.session_state["roof_clearance"],
                    locked=locked, var_bounds=USER_BOUNDS,
                    alt_rel_tol=st.session_state["alt_pct"] / 100.0,
                    fast=True,
                    objective_mode=("length" if opt_mode == "Cylinder length"
                                    else "force"),
                    # The cap is entered per cylinder; the optimizer works in the
                    # intrinsic whole-wall force, so scale it up by the count.
                    force_cap=(force_cap_per_kg * n_cyl
                               if force_cap_per_kg is not None else None),
                )
            # Snap to the active slider precision AND clamp into the (possibly
            # narrowed) mounting-limit range, so the value can't exceed the
            # slider and error out. USER_BOUNDS is the same source the value
            # sliders use; ROUND_DP tracks the precision toggle.
            for k in ("a", "b", "d", "f"):
                lo, hi = USER_BOUNDS[k]
                st.session_state[k] = float(min(max(round(res[k], 4), lo), hi))
            held = f" (held: {', '.join(sorted(locked))})" if locked else ""
            action = "Evaluated" if len(locked) == 4 else "Optimized"
            geom_str = (f"a = {res['a'] * U:.2f}  b = {res['b'] * U:.2f}  "
                        f"d = {res['d'] * U:.2f}  f = {res['f'] * U:.2f} {ULABEL}")
            # Report forces PER CYLINDER (the banner states the count).
            _pk_pc = res["peak_force"] / n_cyl
            if opt_mode == "Cylinder length":
                # Lead with the geometry, then the extended length and the total
                # force per cylinder (peak per kg x mass).
                detail = (f"{geom_str} — extended length {res['L_max'] * U:.2f} {ULABEL}; "
                          f"total force {fmt_pk(_pk_pc)} × {fmt_mass(mass)} = "
                          f"{fmt_total(_pk_pc * mass)} per cylinder; "
                          f"stroke ratio {res['stroke_ratio']:.2f}")
            else:
                detail = (f"{geom_str} — peak {fmt_pk(_pk_pc)} per cylinder, "
                          f"stroke {(res['L_max'] - res['L_min']) * U:.2f} {ULABEL} "
                          f"(ratio {res['stroke_ratio']:.2f}), "
                          f"roof breach {res['ceiling_violation'] * U:.3f} {ULABEL}")
            # No st.rerun(): the geometry widgets (rendered in the Geometry tab,
            # which executes after this block) re-seed from these canonical
            # values in the same run, so they update immediately.
            if res.get("over_center", False):
                st.error(
                    f"{action}{held}: this geometry OVER-CENTERS — the cylinder "
                    "line crosses the hinge so the force diverges, and it can't "
                    "be built. Unlock a variable (or change the pinned values) "
                    "and re-optimize.")
            elif res["feasible"]:
                st.success(f"{action}{held} — buildable, all limits met: {detail}.")
            else:
                st.warning(
                    f"{action}{held} — best buildable design, but not all limits "
                    f"are met (usable; may need different hardware or looser "
                    f"settings): {detail}.")

            # Persist the diverse near-optimal alternatives so they render as
            # clickable buttons below — outside this click block, so they survive
            # later reruns and let you load any one into the sliders.
            st.session_state["_alts"] = res.get("alternatives", [])
        except TypeError as exc:  # e.g. new app.py calling an old optimize.py
            if "unexpected keyword argument" in str(exc):
                st.error(
                    f"This page is running an **out-of-date** copy of the code "
                    f"(build: {BUILD}). Reboot the app / restart the server to "
                    f"load the latest, then try again. ({exc})")
            else:
                st.error(f"Optimizer failed: {exc}")
        except Exception as exc:  # surface any other optimizer error in the UI
            st.error(f"Optimizer failed: {exc}")

    # Persistent geometry readout. The optimizer (force OR length mode) writes its
    # result into a/b/d/f, so this stays visible after the transient result banner
    # clears — you always see the current/optimized geometry here.
    st.caption(
        f"**Geometry (a, b, d, f):**  a = {st.session_state['a'] * U:.3f}  "
        f"b = {st.session_state['b'] * U:.3f}  d = {st.session_state['d'] * U:.3f}  "
        f"f = {st.session_state['f'] * U:.3f} {ULABEL}")

    # Clickable list of the last optimize's near-optimal alternatives. Rendered
    # here — before the Geometry tab executes — so a click loads the chosen
    # geometry into a/b/d/f and the sliders re-seed from it in the same run.
    _alts = st.session_state.get("_alts", [])
    if len(_alts) > 1:
        with st.expander(
                f"{len(_alts) - 1} near-optimal alternatives (click to load)"):
            for _i, _x in enumerate(_alts):
                _pen = _x.get("penalty_pct", 0.0)
                _tag = "optimum" if _pen < 1e-6 else f"+{_pen:.1f}%"
                _lmax = (f", ext. {_x['L_max'] * U:.2f} {ULABEL}"
                         if "L_max" in _x else "")
                _lbl = (f"a = {_x['a'] * U:.2f}  b = {_x['b'] * U:.2f}  "
                        f"d = {_x['d'] * U:.2f}  f = {_x['f'] * U:.2f} {ULABEL}  "
                        f"— {fmt_pk(_x['peak_force'] / n_cyl)}{_lmax} ({_tag})")
                if st.button(_lbl, key=f"alt_{_i}", use_container_width=True):
                    for _k in ("a", "b", "d", "f"):
                        _lo, _hi = USER_BOUNDS[_k]
                        st.session_state[_k] = float(
                            min(max(round(_x[_k], ROUND_DP), _lo), _hi))

with tab_geometry:
    st.subheader(f"Values ({UWORD})")
    _geom = dict(disp_factor=U, disp_step=LEN_STEP, fmt=LEN_FMT, lockable=True)
    _half_note = (f"Capped at half the container width "
                  f"({container_width / 2 * U:.2f} {ULABEL}) by the 'Keep base and "
                  f"bracket within half the container' toggle above."
                  if half_a else
                  f"Can use the full container width "
                  f"({container_width * U:.2f} {ULABEL}).")
    a = linked_input(f"a — hinge to cylinder base (along floor) [{ULABEL}]", "a",
                     *USER_BOUNDS["a"], **_geom, help=_half_note)
    b = linked_input(f"b — hinge to piston attachment (along wall) [{ULABEL}]", "b",
                     *USER_BOUNDS["b"], **_geom)
    d = linked_input(f"d — wall to piston attachment (perpendicular) [{ULABEL}]", "d",
                     *USER_BOUNDS["d"], **_geom, help=_half_note)
    f = linked_input(f"f — cylinder base height above floor [{ULABEL}]", "f",
                     *USER_BOUNDS["f"], **_geom)

    st.subheader("Wall angle")
    animating = st.toggle(
        "Sweep θ (0 → 90 → 0)", key="animating",
        help="Continuously animate the wall opening and closing. "
             "Toggle off to scrub the angle manually.")
    st.session_state.setdefault("anim_theta", float(st.session_state["theta_deg"]))
    st.session_state.setdefault("anim_dir", 1)
    if animating:
        # Drive the angle from the sweep state; the slider below follows along.
        st.session_state["theta_deg"] = st.session_state["anim_theta"]
    else:
        # Idle: keep the sweep ready to resume from the current manual angle.
        st.session_state["anim_theta"] = float(st.session_state["theta_deg"])
    theta_deg = linked_input("theta (degrees)", "theta_deg", 0.0, 90.0,
                             step=1.0, fmt="%.0f")
    theta = np.radians(theta_deg)


def _fmt_design(design):
    if not design:
        return "empty"
    return (f"a = {design['a'] * U:.2f} b = {design['b'] * U:.2f} "
            f"d = {design['d'] * U:.2f} f = {design['f'] * U:.2f} {ULABEL}")


with tab_compare:
    st.subheader("Compare designs")
    _current = dict(a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
    _save_a, _save_b = st.columns(2)
    if _save_a.button("Save as A", use_container_width=True):
        st.session_state["design_A"] = _current
    if _save_b.button("Save as B", use_container_width=True):
        st.session_state["design_B"] = _current
    _clear_a, _clear_b = st.columns(2)
    if _clear_a.button("Clear A", use_container_width=True):
        st.session_state.pop("design_A", None)
    if _clear_b.button("Clear B", use_container_width=True):
        st.session_state.pop("design_B", None)
    design_A = st.session_state.get("design_A")
    design_B = st.session_state.get("design_B")
    st.caption(f"**A** (green): {_fmt_design(design_A)}")
    st.caption(f"**B** (orange): {_fmt_design(design_B)}")
    st.toggle("Overlay A & B on plots", key="overlay",
              disabled=not (design_A and design_B),
              help="Needs both A and B saved. Draws each design's force and "
                   "length curve as a dashed line alongside the current one.")
# Only overlay when the toggle is on AND both snapshots still exist.
overlay = bool(st.session_state.get("overlay")) and bool(design_A) and bool(design_B)

# Push current values back into the URL so reloads / shared links restore them.
# Skip while animating: it reruns ~20x/sec, and browsers throttle history updates
# (Safari errors past ~100/30s). The frozen value is written once on stop.
if not animating:
    st.query_params.update({k: str(st.session_state[k]) for k in DEFAULTS})

# =============================================================================
# RIGHT PANEL — the visualization (main area).
# =============================================================================
st.title("Shipping container hinged-wall actuator")

# --- Computations ---
# Near-singular geometries make compute_F_piston divide by ~0; we mask those
# samples below, so silence the expected warning rather than spam the console.
theta_curve = np.linspace(0.0, np.pi / 2, 400)
with np.errstate(divide="ignore", invalid="ignore"):
    F_curve = compute_F_piston(theta_curve, a=a, b=b, d=d, f=f,
                               x_cg=x_cg, z_cg=z_cg)
    F_here = float(compute_F_piston(theta, a=a, b=b, d=d, f=f,
                                    x_cg=x_cg, z_cg=z_cg))
L_curve = compute_cylinder_length(theta_curve, a=a, b=b, d=d, f=f)
L_here = float(compute_cylinder_length(theta, a=a, b=b, d=d, f=f))
L_min, L_max = float(L_curve.min()), float(L_curve.max())
L_ratio = L_max / L_min if L_min > 0 else float("inf")

# Near a singularity the required force blows up toward +/-inf (and flips sign).
# Forces beyond this magnitude mean the geometry is effectively unusable there,
# so we treat them as "off the chart": exclude them from the reported extremes
# AND break the plotted line, so the numbers and the curve always agree.
F_CAP = 50.0  # N/kg
usable = np.isfinite(F_curve) & (np.abs(F_curve) <= F_CAP)
F_plot = np.where(usable, F_curve, np.nan)  # NaN breaks the line across poles
F_valid = F_curve[usable]
F_min = float(F_valid.min()) if F_valid.size else float("nan")
F_max = float(F_valid.max()) if F_valid.size else float("nan")
has_singularity = not bool(np.all(usable))

# Diagram coordinates — all scaled by U into the chosen display unit. (These are
# display-only; the physics above uses the canonical meter values directly.)
geom = compute_geometry(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
x_att, z_att = (float(v) * U for v in geom["attachment"])
x_cgw, z_cgw = (float(v) * U for v in geom["cg"])
xb, zb = (float(v) * U for v in geom["cylinder_base"])
x_tip_b, z_tip_b = (float(v) * U for v in geom["wall_axis_at_b"])
x_cgf, z_cgf = (float(v) * U for v in geom["wall_axis_at_xcg"])
x_door_tip = container_height * np.cos(theta) * U
z_door_tip = container_height * np.sin(theta) * U
cw, ch = container_width * U, container_height * U   # display-unit container dims
pad = 0.5 * U                                        # display-unit plot margin

# --- Key results at a glance (a bordered results card) ---
peak_mag = max(abs(F_min), abs(F_max)) if F_valid.size else float("nan")
# Per-cylinder force: with n_cyl cylinders sharing the load, each carries 1/n_cyl.
# The geometry/optimizer use the intrinsic (whole-wall) value; every displayed
# force is per cylinder so peak x mass stays consistent with the total-force bar.
peak_pc = peak_mag / n_cyl
F_here_pc = F_here / n_cyl
stroke_ok = L_ratio <= stroke_ratio + STROKE_TOL
st.info(cylinder_banner(n_cyl))
with st.container(border=True):
    # Geometry front and centre — the four numbers you're designing, shown large.
    g1, g2, g3, g4 = st.columns(4)
    g1.metric(f"a — base along floor", f"{a * U:.3f} {ULABEL}",
              help="Cylinder base position along the floor, from the hinge.")
    g2.metric(f"b — attach up wall", f"{b * U:.3f} {ULABEL}",
              help="Piston attachment point up the wall, from the hinge.")
    g3.metric(f"d — bracket offset", f"{d * U:.3f} {ULABEL}",
              help="How far the attachment bracket sticks off the wall.")
    g4.metric(f"f — base height", f"{f * U:.3f} {ULABEL}",
              help="Cylinder base height above the floor.")
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Peak force (worst case)", fmt_pk(peak_pc),
              help="Largest force over the full 0–90° swing, per cylinder — the "
                   "number to size the cylinder by.")
    m2.metric(f"Force at θ = {theta_deg:.0f}°", fmt_pk(F_here_pc),
              help="Force at the current wall angle (red marker on the plots), "
                   "per cylinder.")
    m3.metric("Stroke", f"{(L_max - L_min) * U:.2f} {ULABEL}",
              help="Rod travel you order a cylinder by (L_max − L_min).")
    m4.metric("Stroke ratio", f"{L_ratio:.2f}",
              delta=("within limit" if stroke_ok else "over limit"),
              delta_color=("off" if stroke_ok else "inverse"),
              help=f"Extended/retracted length ratio vs. your {stroke_ratio:g}× limit.")
    # The two cylinder lengths to order by — closed (retracted) and open (extended).
    st.divider()
    L1, L2 = st.columns(2)
    L1.metric("Retracted length (closed)", f"{L_min * U:.3f} {ULABEL}",
              help="Shortest the cylinder gets over the swing — the closed length you "
                   "order.")
    L2.metric("Extended length (open)", f"{L_max * U:.3f} {ULABEL}",
              help="Longest the cylinder gets over the swing — the open length. Order a "
                   "cylinder that spans closed → open (stroke = the difference).")
    total_kn, bar_fill, bar_color = force_bar(peak_pc, mass)
    st.caption(f"**Peak cylinder force at {fmt_mass(mass)}:**")
    st.markdown(force_bar_html(bar_fill, BAR_NEUTRAL, fmt_total(peak_pc * mass)),
                unsafe_allow_html=True)

# --- Cylinder sizing: turn the peak force into a bore + operating pressure ---
# Shared with the Browse inspector via cylinder_panel; returns the design pressure
# and bore standard so the PDF export below reports the same numbers.
pressure_bar, series = render_cylinder_sizing(peak_pc, mass, imperial=imperial)

# --- Side view large on top; force + length curves small below it. diag_area is
# created first so its slot sits above the curve row, even though the diagram
# code appears just below this. ---
diag_area = st.container()
col_force, col_len = st.columns(2)

with diag_area:
    fig_geom = go.Figure()

    # Ground (the door lies on it when open)
    fig_geom.add_trace(go.Scatter(
        x=[-cw - pad, ch + pad], y=[0, 0], mode="lines",
        line=dict(color="lightgray", dash="dash"), hoverinfo="skip", showlegend=False))

    # Container outline: floor + back wall + ceiling (internal clear dimensions)
    fig_geom.add_trace(go.Scatter(
        x=[0, -cw, -cw, 0],
        y=[0, 0, ch, ch],
        mode="lines", line=dict(color="darkgray", width=3),
        hoverinfo="skip", name="container"))

    # Effective ceiling the optimizer respects (roof minus clearance margin)
    if roof_clearance > 0:
        z_eff = (container_height - roof_clearance) * U
        fig_geom.add_trace(go.Scatter(
            x=[-cw, 0], y=[z_eff, z_eff], mode="lines",
            line=dict(color="firebrick", width=1, dash="dash"),
            hoverinfo="skip", name="effective ceiling"))

    # Hinged wall (door) — full length to container_height
    fig_geom.add_trace(go.Scatter(
        x=[0, x_door_tip], y=[0, z_door_tip], mode="lines",
        line=dict(color="black", width=6), name="door"))

    # Physical bracket from door to piston attachment point
    fig_geom.add_trace(go.Scatter(
        x=[x_tip_b, x_att], y=[z_tip_b, z_att], mode="lines",
        line=dict(color="black", width=4), name="bracket"))
    # Cg stand-off (visual aid, not a physical part)
    fig_geom.add_trace(go.Scatter(
        x=[x_cgf, x_cgw], y=[z_cgf, z_cgw], mode="lines",
        line=dict(color="gray", width=1, dash="dot"), hoverinfo="skip", showlegend=False))

    # Cylinder mounting post (floor to cylinder base)
    fig_geom.add_trace(go.Scatter(
        x=[xb, xb], y=[0, zb], mode="lines",
        line=dict(color="black", width=4), name="mounting post"))

    # Cylinder
    fig_geom.add_trace(go.Scatter(
        x=[xb, x_att], y=[zb, z_att], mode="lines",
        line=dict(color="orange", width=4), name="cylinder"))

    # Markers
    fig_geom.add_trace(go.Scatter(
        x=[0], y=[0], mode="markers",
        marker=dict(size=12, color="black"), name="hinge"))
    fig_geom.add_trace(go.Scatter(
        x=[xb], y=[zb], mode="markers",
        marker=dict(size=12, color="orange", symbol="square"), name="cylinder base"))
    fig_geom.add_trace(go.Scatter(
        x=[x_att], y=[z_att], mode="markers",
        marker=dict(size=10, color="red"), name="attachment"))
    fig_geom.add_trace(go.Scatter(
        x=[x_cgw], y=[z_cgw], mode="markers",
        marker=dict(size=14, color="blue", symbol="cross"), name="cg"))

    # Gravity arrow at cg
    fig_geom.add_annotation(
        x=x_cgw, y=z_cgw - 0.35 * U, ax=x_cgw, ay=z_cgw,
        xref="x", yref="y", axref="x", ayref="y",
        showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=2, arrowcolor="blue")

    fig_geom.update_layout(
        template=PLOT_TEMPLATE, font=PLOT_FONT,
        title=f"Side view (theta = {theta_deg:.0f} deg)",
        xaxis=dict(range=[-cw - pad, ch + pad],
                    title=f"x ({ULABEL})", zeroline=False),
        yaxis=dict(range=[-pad, ch + pad],
                    title=f"z ({ULABEL})", scaleanchor="x", scaleratio=1, zeroline=False),
        height=560,
        legend=dict(orientation="h", y=-0.15),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig_geom, width="stretch")

with col_force:
    # Force is shown PER CYLINDER (÷ n_cyl) to match the Peak-force metric, the
    # total-force bar, and the banner — with 2 cylinders each carries half.
    pc = PU / n_cyl                                     # whole-wall N/kg -> per-cyl display
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=np.degrees(theta_curve), y=F_plot * pc, mode="lines", name="F(theta)",
        line=dict(color=PRIMARY, width=2.5)))
    fig.add_trace(go.Scatter(
        x=[theta_deg], y=[F_here * pc], mode="markers",
        marker=dict(size=14, color="red"), name="current"))
    if overlay:
        for _lab, _dd, _col in (("A", design_A, "green"), ("B", design_B, "darkorange")):
            with np.errstate(divide="ignore", invalid="ignore"):
                _Fd = compute_F_piston(theta_curve, a=_dd["a"], b=_dd["b"],
                                       d=_dd["d"], f=_dd["f"],
                                       x_cg=_dd["x_cg"], z_cg=_dd["z_cg"])
            _Fd = np.where(np.isfinite(_Fd) & (np.abs(_Fd) <= F_CAP), _Fd, np.nan)
            fig.add_trace(go.Scatter(
                x=np.degrees(theta_curve), y=_Fd * pc, mode="lines",
                name=f"design {_lab}", line=dict(color=_col, dash="dash")))
    if F_valid.size:
        fig.add_hline(y=F_min * pc, line=dict(color="green", dash="dot"),
                       annotation_text=f"F_min = {fmt_pk(F_min / n_cyl)}",
                       annotation_position="bottom right")
        fig.add_hline(y=F_max * pc, line=dict(color="red", dash="dot"),
                       annotation_text=f"F_max = {fmt_pk(F_max / n_cyl)}",
                       annotation_position="top right")
        span = F_max - F_min if F_max > F_min else 1.0
        y_range = [(F_min - 0.1 * span) * pc, (F_max + 0.1 * span) * pc]
    else:
        y_range = [-F_CAP * pc, F_CAP * pc]
    fig.update_layout(
        template=PLOT_TEMPLATE, font=PLOT_FONT,
        title="Piston force vs. wall angle",
        xaxis_title="theta (degrees)",
        yaxis_title=f"Piston force ({PLABEL}{' per cyl' if n_cyl > 1 else ''})",
        xaxis=dict(range=[0, 90]),
        # Autoscale y when overlaying so A/B curves fit; otherwise frame the
        # current design's extremes.
        yaxis=dict(range=None if overlay else y_range),
        height=360,
        showlegend=overlay,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, width="stretch")
    if has_singularity:
        st.caption(
            f"Warning — part of the swing needs more than {fmt_pk(F_CAP / n_cyl)} "
            "(near-singular geometry) and is hidden — extremes shown are over "
            "the usable range only."
        )

# --- Top row, right: cylinder length plot (beside the force curve) ---
with col_len:
    fig_len = go.Figure()
    fig_len.add_trace(go.Scatter(
        x=np.degrees(theta_curve), y=L_curve * U, mode="lines", name="L(theta)",
        line=dict(color=PRIMARY, width=2.5)))
    fig_len.add_trace(go.Scatter(
        x=[theta_deg], y=[L_here * U], mode="markers",
        marker=dict(size=14, color="red"), name="current"))
    if overlay:
        for _lab, _dd, _col in (("A", design_A, "green"), ("B", design_B, "darkorange")):
            _Ld = compute_cylinder_length(theta_curve, a=_dd["a"], b=_dd["b"],
                                          d=_dd["d"], f=_dd["f"])
            fig_len.add_trace(go.Scatter(
                x=np.degrees(theta_curve), y=_Ld * U, mode="lines",
                name=f"design {_lab}", line=dict(color=_col, dash="dash")))
    fig_len.add_hline(y=L_min * U, line=dict(color="green", dash="dot"),
                       annotation_text=f"L_min = {L_min * U:.2f} {ULABEL}",
                       annotation_position="bottom right")
    fig_len.add_hline(y=stroke_ratio * L_min * U, line=dict(color="red", dash="dot"),
                       annotation_text=f"{stroke_ratio:g} x L_min = "
                                       f"{stroke_ratio * L_min * U:.2f} {ULABEL} (max stroke limit)",
                       annotation_position="top right")
    fig_len.update_layout(
        template=PLOT_TEMPLATE, font=PLOT_FONT,
        title="Cylinder length vs. wall angle",
        xaxis_title="theta (degrees)",
        yaxis_title=f"Cylinder length ({ULABEL})",
        xaxis=dict(range=[0, 90]),
        height=360,
        showlegend=overlay,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig_len, width="stretch")

# The stroke, ratio, L_min/L_max, and force-at-angle are already in the metrics
# row and on the plots, so no summary caption is repeated here.

if overlay:
    def _peak_force(design):
        with np.errstate(divide="ignore", invalid="ignore"):
            fd = compute_F_piston(theta_curve, a=design["a"], b=design["b"],
                                  d=design["d"], f=design["f"],
                                  x_cg=design["x_cg"], z_cg=design["z_cg"])
        fd = fd[np.isfinite(fd) & (np.abs(fd) <= F_CAP)]
        return float(np.max(np.abs(fd))) if fd.size else float("nan")
    st.caption(
        f"**Overlay** — A ({_fmt_design(design_A)}): peak "
        f"**{fmt_pk(_peak_force(design_A) / n_cyl)}**   ·   B ({_fmt_design(design_B)}): "
        f"peak **{fmt_pk(_peak_force(design_B) / n_cyl)}**.")

# --- Sensitivity: which dimension moves the force most, and WHERE in its range ---
# Shared with the Browse inspector via sensitivity_panel so the two stay identical.
sens_bar, sens_strip = render_sensitivity_panel(
    a, b, d, f, st.session_state["x_cg"], st.session_state["z_cg"], USER_BOUNDS,
    n_cyl=n_cyl, template=PLOT_TEMPLATE, font=PLOT_FONT,
    stroke_max=stroke_ratio, roof_clearance=roof_clearance,
    width=container_width, height=container_height)

# --- 2-D interaction map: pick two dimensions to vary together (also in Browse/Reverse) ---
render_interaction_map(
    a, b, d, f, st.session_state["x_cg"], st.session_state["z_cg"], USER_BOUNDS,
    n_cyl=n_cyl, template=PLOT_TEMPLATE, font=PLOT_FONT, stroke_max=stroke_ratio,
    roof_clearance=roof_clearance, width=container_width, height=container_height)

# --- Export the current design as a one-page PDF spec sheet ---
# Shared with Browse and Reverse via pdf_export so a spec sheet is available in
# every view; pressure_bar/series (from the cylinder-sizing card) add the bore row,
# and the sensitivity charts above are embedded too.
render_pdf_export(
    key="design", size_key=size_key, n_cyl=n_cyl, x_cg=x_cg, z_cg=z_cg, mass=mass,
    stroke_ratio_max=stroke_ratio, roof_clearance=roof_clearance,
    a=a, b=b, d=d, f=f, peak_pc=peak_pc, L_min=L_min, L_max=L_max,
    fig_geom=fig_geom, fig_force=fig, fig_len=fig_len,
    fig_sens_bar=sens_bar, fig_sens_strip=sens_strip,
    # All six interaction maps, built lazily (only when Generate is clicked).
    fig_interactions=lambda: build_interaction_matrix(
        a, b, d, f, st.session_state["x_cg"], st.session_state["z_cg"], USER_BOUNDS,
        stroke_max=stroke_ratio, roof_clearance=roof_clearance,
        width=container_width, height=container_height, template=PLOT_TEMPLATE,
        metric=selected_metric()),
    pressure_bar=pressure_bar, series=series, stroke_tol=STROKE_TOL,
    sens_metric=selected_metric())

# --- Animation driver -------------------------------------------------------
# Streamlit has no background loop, so we animate by advancing the sweep angle
# and re-running. This sits at the very end so every widget has already rendered
# this frame — an aborted (early) rerun would drop not-yet-rendered widget state
# (e.g. the lock checkboxes). Toggle the animation off to stop the loop.
if animating:
    st.session_state["anim_theta"], st.session_state["anim_dir"] = _advance_angle(
        st.session_state["anim_theta"], st.session_state["anim_dir"])
    time.sleep(FRAME_DELAY_S)
    st.rerun()
