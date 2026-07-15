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
from lookup import (force_bar, force_bar_html, BAR_NEUTRAL,
                    required_bore_mm, next_standard_bore_mm, pressure_for_bore_bar)

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

# Left rail: view switch + a build marker, above the tabbed control panel.
st.sidebar.markdown("### Wall actuator")
_view = st.sidebar.radio(
    "View", ["Designer", "Browse configurations", "Size from a cylinder"],
    key="view", label_visibility="collapsed")
st.sidebar.caption(f"build: {BUILD}")
if _view == "Browse configurations":
    render_browse()
    st.stop()
if _view == "Size from a cylinder":
    render_reverse()
    st.stop()

# ISO container dimensions (external)
CONTAINER_SIZES = {
    "Standard (8'6\") — 2.44 m W x 2.59 m H": (2.438, 2.591),
    "High-Cube (9'6\") — 2.44 m W x 2.90 m H": (2.438, 2.896),
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

    # Bounds for the four geometry variables — single source of truth shared by
    # the slider widgets, the clamp-on-resize logic, and the optimize button's
    # clamp, so they can never drift apart and let an optimized value fall
    # outside a slider.
    GEOM_BOUNDS = {
        "a": (0.05, container_width / 2),
        "b": (0.05, container_height),
        "d": (0.00, 1.00),
        "f": (0.00, container_height),
    }
    for _k, (_lo, _hi) in GEOM_BOUNDS.items():
        _clamp(_k, _lo, _hi)
    _clamp("x_cg", 0.00, container_height)
    _clamp("z_cg", 0.00, 1.50)
    _clamp("theta_deg", 0.0, 90.0)
    _clamp("stroke_ratio", 1.0, 3.0)
    _clamp("roof_clearance", 0.0, 0.5)

    # --- Display units ---
    # All values are stored and computed in METERS internally (so the physics,
    # the optimizer, and shared URLs stay consistent). This toggle only changes
    # how lengths are *displayed*: widgets, plots, and captions multiply by `U`.
    st.subheader("Display units")
    units = st.radio("Length units", ["meters", "inches"], key="units",
                     horizontal=True, label_visibility="collapsed")
    fine = st.toggle(
        "Fine precision", key="fine",
        help="Finer slider/number steps for exact values (0.001 m / 0.01 in), "
             "and the optimizer rounds to that precision — so the plotted force "
             "matches the reported one more closely.")
    inches = units == "inches"
    U = 39.3700787 if inches else 1.0    # meters -> display-unit factor
    ULABEL = "in" if inches else "m"      # short unit label
    UWORD = "inches" if inches else "meters"
    if inches:
        LEN_STEP, LEN_FMT = (0.01, "%.3f") if fine else (0.1, "%.2f")
    else:
        LEN_STEP, LEN_FMT = (0.001, "%.3f") if fine else (0.01, "%.2f")
    ROUND_DP = 3 if fine else 2           # meters precision the optimize snaps to

    # --- Center of gravity: the load the actuator must hold ---
    st.subheader(f"Center of gravity ({UWORD})")
    x_cg = linked_input(f"x_cg — along wall from hinge [{ULABEL}]", "x_cg",
                        0.0, container_height, disp_factor=U, disp_step=LEN_STEP,
                        fmt=LEN_FMT)
    z_cg = linked_input(f"z_cg — perpendicular off wall [{ULABEL}]", "z_cg",
                        0.0, 1.5, disp_factor=U, disp_step=LEN_STEP, fmt=LEN_FMT)
    mass = linked_input("Wall + load mass (kg)", "mass", 50.0, 20000.0, step=10.0,
                        fmt="%.0f",
                        help="Total mass of the wall plus anything mounted on it. "
                             "Peak force per kg × this = the real cylinder force.")

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
        st.session_state.setdefault("force_cap_nkg", 40.0)
        force_cap_per_kg = linked_input(
            "Max piston force (N/kg)", "force_cap_nkg", 1.0, 200.0, step=1.0, fmt="%.0f",
            help="The optimizer returns the shortest cylinder whose PEAK force per kg "
                 "stays at or below this. Same unit as the Peak force metric; it does "
                 "not depend on the wall mass.")
        opt_mass = linked_input(
            "Wall + load mass (kg)", "mass", 50.0, 20000.0, step=10.0, fmt="%.0f",
            wkey="mass_opt",
            help="Same value as the Setup tab (kept in sync). Only translates the cap "
                 "into a real force in kN — it does not change the optimization.")
        st.metric(
            f"Total force ({force_cap_per_kg:.0f} N/kg × {opt_mass:,.0f} kg)",
            f"{force_cap_per_kg * opt_mass / 1000:.1f} kN",
            help="The force limit in real units: the N/kg cap multiplied by the wall "
                 "+ load mass. The optimizer finds the shortest cylinder whose peak "
                 "force stays within it.")

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
                    force_cap=force_cap_per_kg,
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
            if opt_mode == "Cylinder length":
                # Lead with the geometry, then the extended length and the total
                # force (peak per kg x mass).
                detail = (f"{geom_str} — extended length {res['L_max'] * U:.2f} {ULABEL}; "
                          f"total force {res['peak_force']:.2f} N/kg × {mass:,.0f} kg = "
                          f"{res['peak_force'] * mass / 1000:.1f} kN; "
                          f"stroke ratio {res['stroke_ratio']:.2f}")
            else:
                detail = (f"{geom_str} — peak {res['peak_force']:.2f} N/kg, "
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
                        f"— {_x['peak_force']:.2f} N/kg{_lmax} ({_tag})")
                if st.button(_lbl, key=f"alt_{_i}", use_container_width=True):
                    for _k in ("a", "b", "d", "f"):
                        _lo, _hi = USER_BOUNDS[_k]
                        st.session_state[_k] = float(
                            min(max(round(_x[_k], ROUND_DP), _lo), _hi))

with tab_geometry:
    st.subheader(f"Values ({UWORD})")
    _geom = dict(disp_factor=U, disp_step=LEN_STEP, fmt=LEN_FMT, lockable=True)
    a = linked_input(f"a — hinge to cylinder base (along floor) [{ULABEL}]", "a",
                     *USER_BOUNDS["a"], **_geom,
                     help=f"Limited to half the floor width "
                          f"({container_width / 2 * U:.2f} {ULABEL}).")
    b = linked_input(f"b — hinge to piston attachment (along wall) [{ULABEL}]", "b",
                     *USER_BOUNDS["b"], **_geom)
    d = linked_input(f"d — wall to piston attachment (perpendicular) [{ULABEL}]", "d",
                     *USER_BOUNDS["d"], **_geom)
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
# display-only; the physics above uses the canonical metre values directly.)
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
stroke_ok = L_ratio <= stroke_ratio + STROKE_TOL
with st.container(border=True):
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Peak force (worst case)", f"{peak_mag:.2f} N/kg",
              help="Largest force over the full 0–90° swing — the number to size "
                   "the cylinder by.")
    m2.metric(f"Force at θ = {theta_deg:.0f}°", f"{F_here:.2f} N/kg",
              help="Force at the current wall angle (red marker on the plots).")
    m3.metric("Stroke", f"{(L_max - L_min) * U:.2f} {ULABEL}",
              help="Rod travel you order a cylinder by (L_max − L_min).")
    m4.metric("Stroke ratio", f"{L_ratio:.2f}",
              delta=("within limit" if stroke_ok else "over limit"),
              delta_color=("off" if stroke_ok else "inverse"),
              help=f"Extended/retracted length ratio vs. your {stroke_ratio:g}× limit.")
    total_kn, bar_fill, bar_color = force_bar(peak_mag, mass)
    st.caption(f"**Peak cylinder force at {mass:,.0f} kg:**")
    st.markdown(force_bar_html(bar_fill, BAR_NEUTRAL, f"{total_kn:.1f} kN"),
                unsafe_allow_html=True)

# --- Cylinder sizing: turn the peak force into a bore + operating pressure ---
with st.container(border=True):
    st.markdown("**Cylinder sizing — bore & pressure**")
    st.caption("Bore = the cylinder barrel's inner **diameter**.")
    cs1, cs2 = st.columns([1, 1])
    series = cs1.selectbox(
        "Bore standard", ["ISO metric", "NFPA (inch)", "Exact (no rounding)"],
        key="bore_series",
        help="Round the required bore up to a real catalogue size, or show the "
             "exact number.")
    if series == "NFPA (inch)":
        st.session_state.setdefault("des_psi", 3000.0)
        press_psi = cs2.number_input("Design pressure (psi)", 200.0, 10000.0,
                                     step=50.0, key="des_psi")
        pressure_bar = press_psi * 0.0689476
        press_label = f"{press_psi:,.0f} psi"
    else:
        st.session_state.setdefault("des_bar", 210.0)
        pressure_bar = cs2.number_input("Design pressure (bar)", 20.0, 700.0,
                                        step=5.0, key="des_bar")
        press_label = f"{pressure_bar:,.0f} bar"

    if np.isfinite(peak_mag) and mass > 0 and pressure_bar > 0:
        force_n = peak_mag * mass                       # total peak push, newtons
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

    # Container outline: floor + back wall + ceiling
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
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=np.degrees(theta_curve), y=F_plot, mode="lines", name="F(theta)",
        line=dict(color=PRIMARY, width=2.5)))
    fig.add_trace(go.Scatter(
        x=[theta_deg], y=[F_here], mode="markers",
        marker=dict(size=14, color="red"), name="current"))
    if overlay:
        for _lab, _dd, _col in (("A", design_A, "green"), ("B", design_B, "darkorange")):
            with np.errstate(divide="ignore", invalid="ignore"):
                _Fd = compute_F_piston(theta_curve, a=_dd["a"], b=_dd["b"],
                                       d=_dd["d"], f=_dd["f"],
                                       x_cg=_dd["x_cg"], z_cg=_dd["z_cg"])
            _Fd = np.where(np.isfinite(_Fd) & (np.abs(_Fd) <= F_CAP), _Fd, np.nan)
            fig.add_trace(go.Scatter(
                x=np.degrees(theta_curve), y=_Fd, mode="lines",
                name=f"design {_lab}", line=dict(color=_col, dash="dash")))
    if F_valid.size:
        fig.add_hline(y=F_min, line=dict(color="green", dash="dot"),
                       annotation_text=f"F_min = {F_min:.2f} N/kg",
                       annotation_position="bottom right")
        fig.add_hline(y=F_max, line=dict(color="red", dash="dot"),
                       annotation_text=f"F_max = {F_max:.2f} N/kg",
                       annotation_position="top right")
        span = F_max - F_min if F_max > F_min else 1.0
        y_range = [F_min - 0.1 * span, F_max + 0.1 * span]
    else:
        y_range = [-F_CAP, F_CAP]
    fig.update_layout(
        template=PLOT_TEMPLATE, font=PLOT_FONT,
        title="Piston force vs. wall angle",
        xaxis_title="theta (degrees)",
        yaxis_title="Piston force (N per kg of wall + equipment mass)",
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
            f"Warning — part of the swing needs more than {F_CAP:.0f} N/kg "
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
        f"**{_peak_force(design_A):.2f} N/kg**   ·   B ({_fmt_design(design_B)}): "
        f"peak **{_peak_force(design_B):.2f} N/kg**.")

# --- Export the current design as a one-page PDF spec sheet ---
with st.expander("Export design (PDF)"):
    st.caption("A one-page spec sheet for the current geometry — inputs, forces, "
               "bore & pressure, the diagram, and the curves. Click Generate to "
               "capture the design as it stands now.")
    if st.button("Generate PDF"):
        import datetime
        import report
        with st.spinner("Rendering the PDF…"):
            # The PDF shows BOTH unit systems for every value (see report.dual_*),
            # regardless of the app's display toggle.
            _len, _force = report.dual_len, report.dual_force
            _press, _bore = report.dual_pressure, report.dual_bore

            force_n = peak_mag * mass if np.isfinite(peak_mag) else float("nan")
            _pk = (f"{peak_mag:.2f} N/kg" if np.isfinite(peak_mag)
                   else "n/a (singular geometry)")
            _tot = _force(force_n) if np.isfinite(force_n) else "n/a"
            cyl_rows = [("Peak force", _pk),
                        (f"Total force at {mass:,.0f} kg", _tot)]
            if np.isfinite(peak_mag) and pressure_bar > 0:
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
            tables = [
                ("Setup", [
                    ("Container", size_key),
                    ("Center of gravity x_cg", _len(x_cg)),
                    ("Center of gravity z_cg", _len(z_cg)),
                    ("Wall + load mass", report.dual_mass(mass)),
                    ("Max stroke ratio", f"{stroke_ratio:g}x"),
                    ("Roof clearance", _len(roof_clearance)),
                ]),
                ("Geometry (a, b, d, f)", [
                    ("a - base along floor", _len(a)),
                    ("b - attachment up wall", _len(b)),
                    ("d - bracket offset", _len(d)),
                    ("f - base height", _len(f)),
                ]),
                ("Cylinder", cyl_rows),
            ]
            notes = [
                "All forces and the bore above are for ONE cylinder carrying the "
                "whole wall.",
                "Real installs often use two cylinders (one near each end); then each "
                "carries about half this force, so each can use a smaller bore.",
                "Forces are static holding forces (no inertia, friction, wind, or flex).",
                "Apply a factor of safety (>=1.5x is a common start).",
                "Bore is the barrel inner diameter; it uses the full-bore push area "
                "(raising the wall extends the cylinder).",
            ]
            # Rendering figures to PNG needs an image backend (kaleido); if it is
            # unavailable, still produce a numbers-only PDF rather than crash.
            images = []
            try:
                images = [
                    ("Side view", fig_geom.to_image(format="png", width=900, height=560, scale=2)),
                    ("Piston force vs. wall angle",
                     fig.to_image(format="png", width=900, height=380, scale=2)),
                    ("Cylinder length vs. wall angle",
                     fig_len.to_image(format="png", width=900, height=380, scale=2)),
                ]
            except Exception:
                notes.append("Diagrams omitted (image rendering unavailable here).")
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            st.session_state["design_pdf"] = report.build_spec_pdf(
                "Container Wall Actuator - Design Report",
                f"{size_key} - generated {ts}", tables, images=images, notes=notes)
    if st.session_state.get("design_pdf"):
        st.download_button("Download PDF", st.session_state["design_pdf"],
                           file_name="wall_actuator_design.pdf",
                           mime="application/pdf")

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
