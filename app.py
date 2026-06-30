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
from optimize import optimize_actuator

st.set_page_config(page_title="Container Wall Actuator", layout="wide")
st.title("Shipping container hinged-wall actuator")
st.caption("Looking down the long axis of the container. The hinged sidewall swings down to lie flat outside.")

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

st.sidebar.header("Container")
size_key = st.sidebar.selectbox("Container size", list(CONTAINER_SIZES.keys()), key="size_key")
container_width, container_height = CONTAINER_SIZES[size_key]

# Bounds for the four geometry variables — single source of truth shared by the
# slider widgets, the clamp-on-resize logic, and the optimize button's clamp, so
# they can never drift apart and let an optimized value fall outside a slider.
GEOM_BOUNDS = {
    "a": (0.05, container_width / 2),
    "b": (0.05, container_height),
    "d": (0.00, 1.00),
    "f": (0.00, container_height),
}

# Clamp persisted values into the bounds the current container allows, so
# changing container size doesn't trip a "value out of range" error on widgets.
def _clamp(key, lo, hi):
    st.session_state[key] = float(min(max(st.session_state[key], lo), hi))

for _k, (_lo, _hi) in GEOM_BOUNDS.items():
    _clamp(_k, _lo, _hi)
_clamp("x_cg", 0.00, container_height)
_clamp("z_cg", 0.00, 1.50)
_clamp("theta_deg", 0.0, 90.0)
_clamp("stroke_ratio", 1.0, 3.0)
_clamp("roof_clearance", 0.0, 0.5)

# --- Display units -----------------------------------------------------------
# All values are stored and computed in METERS internally (so the physics, the
# optimizer, and shared URLs stay consistent). This toggle only changes how
# lengths are *displayed*: widgets, plots, and captions multiply by `U`. Angles
# (degrees) and force (N/kg) are not lengths and are unaffected.
st.sidebar.header("Display units")
units = st.sidebar.radio("Length units", ["meters", "inches"], key="units",
                         horizontal=True, label_visibility="collapsed")
inches = units == "inches"
U = 39.3700787 if inches else 1.0    # meters -> display-unit factor
ULABEL = "in" if inches else "m"      # short unit label
UWORD = "inches" if inches else "meters"
LEN_STEP = 0.1 if inches else 0.01    # slider/number step in display units


def linked_input(label, key, lo, hi, step=0.01, fmt="%.2f", help=None,
                 lockable=False, disp_factor=1.0, disp_step=None):
    """A draggable slider AND a typeable number box bound to one value.

    `st.session_state[key]` is the single source of truth (URL-persisted). The
    two widgets get their own keys and are re-seeded from the canonical value
    each run, so they stay in sync and respect the current clamps. Either one
    edited writes back to the canonical value via its on_change callback.

    When `lockable`, a 🔒 checkbox (transient state under `lock_<key>`) lets the
    user pin this value so the optimizer holds it fixed.

    `disp_factor` scales the canonical (stored) value for display: the widgets
    show `value * disp_factor` and `lo`/`hi * disp_factor`, and convert edits
    back by dividing. `lo`/`hi` and the returned value stay in canonical units.
    """
    skey, nkey = f"{key}__sld", f"{key}__num"
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
        c1, c2, c3 = st.sidebar.columns([2, 1, 0.7])
    else:
        c1, c2 = st.sidebar.columns([2, 1])
    c1.slider(label, lo * U, hi * U, step=dstep, key=skey,
              on_change=_from_sld, help=help)
    c2.number_input(label, min_value=lo * U, max_value=hi * U, step=dstep,
                    key=nkey, on_change=_from_num, format=fmt,
                    label_visibility="collapsed")
    if lockable:
        c3.checkbox("🔒", key=f"lock_{key}",
                    help="Hold this value fixed when you press Optimize.")
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


# --- Constraints (shared with the optimizer) ---
st.sidebar.header("Constraints")
stroke_ratio = st.sidebar.number_input(
    "Max stroke ratio (L_max / L_min)", min_value=1.0, max_value=3.0,
    step=0.05, key="stroke_ratio",
    help="Hydraulic cylinders extend at most ~1.8–2× their retracted length.")
roof_clearance = linked_input(
    f"Roof clearance [{ULABEL}]", "roof_clearance", 0.0, 0.5,
    disp_factor=U, disp_step=LEN_STEP,
    help="Gap the actuator endpoint must keep below the ceiling.")

# --- Optimize: fill the geometry with the force-minimizing design ---
st.sidebar.header("Optimize")
if st.sidebar.button("Optimize geometry for current settings"):
    try:
        # Locked variables are held at their current value; the rest are searched.
        locked = {k: round(st.session_state[k], 2)
                  for k in ("a", "b", "d", "f")
                  if st.session_state.get(f"lock_{k}", False)}
        with st.spinner("Searching for the force-minimizing geometry…"):
            res = optimize_actuator(
                container_width=container_width,
                container_height=container_height,
                x_cg=st.session_state["x_cg"], z_cg=st.session_state["z_cg"],
                stroke_ratio_max=st.session_state["stroke_ratio"],
                roof_clearance=st.session_state["roof_clearance"],
                locked=locked,
            )
        # Snap to slider precision AND clamp into the widget bounds, so a value
        # the optimizer lands at the very top of a range (e.g. b ≈ container
        # height on High-Cube, which rounds just above the max) can't exceed the
        # slider and error out. GEOM_BOUNDS is the same source the sliders use.
        for k in ("a", "b", "d", "f"):
            lo, hi = GEOM_BOUNDS[k]
            st.session_state[k] = float(min(max(round(res[k], 2), lo), hi))
        held = f" (held: {', '.join(sorted(locked))})" if locked else ""
        action = "Evaluated" if len(locked) == 4 else "Optimized"
        detail = (f"peak {res['peak_force']:.2f} N/kg, "
                  f"stroke {res['stroke_ratio']:.2f}, "
                  f"roof breach {res['ceiling_violation'] * U:.3f} {ULABEL}")
        # No st.rerun(): the geometry widgets below re-seed from these canonical
        # values in this same run, so they update immediately. Skipping the
        # rerun also keeps the lock checkboxes (rendered later) from being reset,
        # since an aborted run would drop their not-yet-rendered widget state.
        # .get() guards against a stale optimize.py that predates these keys.
        if res.get("over_center", False):
            # Reached only when the geometry is forced to over-center — in
            # practice the all-four-locked "evaluate" case (pinned to an
            # impossible geometry), since the search hard-rejects crossings.
            st.sidebar.error(
                f"{action}{held}: this geometry OVER-CENTERS — the cylinder line "
                "crosses the hinge so the force diverges, and it can't be built. "
                "Unlock a variable (or change the pinned values) and re-optimize.")
        elif res["feasible"]:
            st.sidebar.success(f"{action}{held} — buildable, all limits met: {detail}.")
        else:
            st.sidebar.warning(
                f"{action}{held} — best buildable design, but not all limits are met "
                f"(usable; may need different hardware or looser settings): {detail}.")
    except Exception as exc:  # surface any optimizer error in the UI
        st.sidebar.error(f"Optimizer failed: {exc}")

st.sidebar.header(f"Geometry ({UWORD})")
st.sidebar.caption("🔒 a value to hold it fixed while the others are optimized.")
_geom = dict(disp_factor=U, disp_step=LEN_STEP, lockable=True)
a = linked_input(f"a — hinge to cylinder base (along floor) [{ULABEL}]", "a",
                 *GEOM_BOUNDS["a"], **_geom,
                 help=f"Limited to half the floor width "
                      f"({container_width / 2 * U:.2f} {ULABEL}).")
b = linked_input(f"b — hinge to piston attachment (along wall) [{ULABEL}]", "b",
                 *GEOM_BOUNDS["b"], **_geom)
d = linked_input(f"d — wall to piston attachment (perpendicular) [{ULABEL}]", "d",
                 *GEOM_BOUNDS["d"], **_geom)
f = linked_input(f"f — cylinder base height above floor [{ULABEL}]", "f",
                 *GEOM_BOUNDS["f"], **_geom)

st.sidebar.header("Wall angle")
animating = st.sidebar.toggle(
    "▶ Sweep θ (0 → 90 → 0)", key="animating",
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

st.sidebar.header(f"Center of gravity ({UWORD})")
x_cg = linked_input(f"x_cg — along wall from hinge [{ULABEL}]", "x_cg",
                    0.0, container_height, disp_factor=U, disp_step=LEN_STEP)
z_cg = linked_input(f"z_cg — perpendicular off wall [{ULABEL}]", "z_cg",
                    0.0, 1.5, disp_factor=U, disp_step=LEN_STEP)

# Push current values back into the URL so reloads / shared links restore them.
# Skip while animating: it reruns ~20x/sec, and browsers throttle history updates
# (Safari errors past ~100/30s). The frozen value is written once on stop.
if not animating:
    st.query_params.update({k: str(st.session_state[k]) for k in DEFAULTS})

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

# --- Top row: diagram + force ---
col_diag, col_force = st.columns(2)

with col_diag:
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
        title=f"Side view (theta = {theta_deg:.0f} deg)",
        xaxis=dict(range=[-cw - pad, ch + pad],
                    title=f"x ({ULABEL})", zeroline=False),
        yaxis=dict(range=[-pad, ch + pad],
                    title=f"z ({ULABEL})", scaleanchor="x", scaleratio=1, zeroline=False),
        height=500,
        legend=dict(orientation="h", y=-0.15),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig_geom, width="stretch")

with col_force:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=np.degrees(theta_curve), y=F_plot, mode="lines", name="F(theta)"))
    fig.add_trace(go.Scatter(
        x=[theta_deg], y=[F_here], mode="markers",
        marker=dict(size=14, color="red"), name="current"))
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
        title="Piston force vs. wall angle",
        xaxis_title="theta (degrees)",
        yaxis_title="Piston force (N per kg of wall + equipment mass)",
        xaxis=dict(range=[0, 90]),
        yaxis=dict(range=y_range),
        height=500,
        showlegend=False,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, width="stretch")
    if has_singularity:
        st.caption(
            f"⚠️ Part of the swing needs more than {F_CAP:.0f} N/kg "
            "(near-singular geometry) and is hidden — extremes shown are over "
            "the usable range only."
        )

# --- Bottom row: cylinder length plot (full width) ---
fig_len = go.Figure()
fig_len.add_trace(go.Scatter(
    x=np.degrees(theta_curve), y=L_curve * U, mode="lines", name="L(theta)"))
fig_len.add_trace(go.Scatter(
    x=[theta_deg], y=[L_here * U], mode="markers",
    marker=dict(size=14, color="red"), name="current"))
fig_len.add_hline(y=L_min * U, line=dict(color="green", dash="dot"),
                   annotation_text=f"L_min = {L_min * U:.2f} {ULABEL}",
                   annotation_position="bottom right")
fig_len.add_hline(y=stroke_ratio * L_min * U, line=dict(color="red", dash="dot"),
                   annotation_text=f"{stroke_ratio:g} x L_min = "
                                   f"{stroke_ratio * L_min * U:.2f} {ULABEL} (max stroke limit)",
                   annotation_position="top right")
fig_len.update_layout(
    title="Cylinder length vs. wall angle",
    xaxis_title="theta (degrees)",
    yaxis_title=f"Cylinder length ({ULABEL})",
    xaxis=dict(range=[0, 90]),
    height=350,
    showlegend=False,
    margin=dict(l=10, r=10, t=40, b=10),
)
st.plotly_chart(fig_len, width="stretch")

stroke_ok = L_ratio <= stroke_ratio
stroke_status = (f"within {stroke_ratio:g}x limit" if stroke_ok
                 else f"EXCEEDS {stroke_ratio:g}x stroke limit")
st.caption(
    f"At theta = {theta_deg:.0f} deg: piston force = **{F_here:.2f} N/kg**, "
    f"cylinder length = **{L_here * U:.2f} {ULABEL}**.  "
    f"Across 0-90 deg: L_min = {L_min * U:.2f} {ULABEL}, "
    f"L_max = {L_max * U:.2f} {ULABEL} "
    f"(ratio = **{L_ratio:.2f}**, {stroke_status})."
)

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
