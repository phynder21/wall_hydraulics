import numpy as np
import plotly.graph_objects as go
import streamlit as st

from wall import compute_F_piston, compute_geometry, compute_cylinder_length

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

# Clamp persisted values into the bounds the current container allows, so
# changing container size doesn't trip a "value out of range" error on widgets.
def _clamp(key, lo, hi):
    st.session_state[key] = float(min(max(st.session_state[key], lo), hi))

_clamp("a", 0.05, container_width / 2)
_clamp("b", 0.05, container_height)
_clamp("d", 0.00, 1.00)
_clamp("f", 0.00, container_height)
_clamp("x_cg", 0.00, container_height)
_clamp("z_cg", 0.00, 1.50)
_clamp("theta_deg", 0.0, 90.0)

st.sidebar.header("Geometry (meters)")
a = st.sidebar.slider(
    "a — hinge to cylinder base (along floor)",
    0.05, container_width / 2, step=0.01, key="a",
    help=f"Limited to half the floor width ({container_width/2:.2f} m).",
)
b = st.sidebar.slider(
    "b — hinge to piston attachment (along wall)",
    0.05, container_height, step=0.01, key="b",
)
d = st.sidebar.slider(
    "d — wall to piston attachment (perpendicular)",
    0.00, 1.00, step=0.01, key="d",
)
f = st.sidebar.slider(
    "f — cylinder base height above floor",
    0.00, container_height, step=0.01, key="f",
)

st.sidebar.header("Wall angle")
theta_deg = st.sidebar.slider("theta (degrees)", 0.0, 90.0, step=1.0, key="theta_deg")
theta = np.radians(theta_deg)

st.sidebar.header("Center of gravity (meters)")
x_cg = st.sidebar.slider("x_cg — along wall from hinge",
                          0.0, container_height, step=0.01, key="x_cg")
z_cg = st.sidebar.slider("z_cg — perpendicular off wall",
                          0.0, 1.5, step=0.01, key="z_cg")

# Push current values back into the URL so reloads / shared links restore them.
st.query_params.update({k: str(st.session_state[k]) for k in DEFAULTS})

# --- Computations ---
theta_curve = np.linspace(0.0, np.pi / 2, 400)
F_curve = compute_F_piston(theta_curve, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
L_curve = compute_cylinder_length(theta_curve, a=a, b=b, d=d, f=f)

F_here = float(compute_F_piston(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg))
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

geom = compute_geometry(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
x_att, z_att = (float(v) for v in geom["attachment"])
x_cgw, z_cgw = (float(v) for v in geom["cg"])
xb, zb = geom["cylinder_base"]
x_tip_b, z_tip_b = (float(v) for v in geom["wall_axis_at_b"])
x_cgf, z_cgf = (float(v) for v in geom["wall_axis_at_xcg"])
x_door_tip = container_height * np.cos(theta)
z_door_tip = container_height * np.sin(theta)

# --- Top row: diagram + force ---
col_diag, col_force = st.columns(2)

with col_diag:
    fig_geom = go.Figure()

    # Ground (the door lies on it when open)
    fig_geom.add_trace(go.Scatter(
        x=[-container_width - 0.3, container_height + 0.3], y=[0, 0], mode="lines",
        line=dict(color="lightgray", dash="dash"), hoverinfo="skip", showlegend=False))

    # Container outline: floor + back wall + ceiling
    fig_geom.add_trace(go.Scatter(
        x=[0, -container_width, -container_width, 0],
        y=[0, 0, container_height, container_height],
        mode="lines", line=dict(color="darkgray", width=3),
        hoverinfo="skip", name="container"))

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
        x=x_cgw, y=z_cgw - 0.35, ax=x_cgw, ay=z_cgw,
        xref="x", yref="y", axref="x", ayref="y",
        showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=2, arrowcolor="blue")

    pad = 0.5
    fig_geom.update_layout(
        title=f"Side view (theta = {theta_deg:.0f} deg)",
        xaxis=dict(range=[-container_width - pad, container_height + pad],
                    title="x (m)", zeroline=False),
        yaxis=dict(range=[-pad, container_height + pad],
                    title="z (m)", scaleanchor="x", scaleratio=1, zeroline=False),
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
    fig.add_hline(y=F_min, line=dict(color="green", dash="dot"),
                   annotation_text=f"F_min = {F_min:.2f} N/kg",
                   annotation_position="bottom right")
    fig.add_hline(y=F_max, line=dict(color="red", dash="dot"),
                   annotation_text=f"F_max = {F_max:.2f} N/kg",
                   annotation_position="top right")
    if F_valid.size:
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
    x=np.degrees(theta_curve), y=L_curve, mode="lines", name="L(theta)"))
fig_len.add_trace(go.Scatter(
    x=[theta_deg], y=[L_here], mode="markers",
    marker=dict(size=14, color="red"), name="current"))
fig_len.add_hline(y=L_min, line=dict(color="green", dash="dot"),
                   annotation_text=f"L_min = {L_min:.2f} m",
                   annotation_position="bottom right")
fig_len.add_hline(y=2 * L_min, line=dict(color="red", dash="dot"),
                   annotation_text=f"2 x L_min = {2 * L_min:.2f} m (max stroke limit)",
                   annotation_position="top right")
fig_len.update_layout(
    title="Cylinder length vs. wall angle",
    xaxis_title="theta (degrees)",
    yaxis_title="Cylinder length (m)",
    xaxis=dict(range=[0, 90]),
    height=350,
    showlegend=False,
    margin=dict(l=10, r=10, t=40, b=10),
)
st.plotly_chart(fig_len, width="stretch")

stroke_ok = L_ratio <= 2.0
stroke_status = "within 2x limit" if stroke_ok else "EXCEEDS 2x stroke limit"
st.caption(
    f"At theta = {theta_deg:.0f} deg: piston force = **{F_here:.2f} N/kg**, "
    f"cylinder length = **{L_here:.2f} m**.  "
    f"Across 0-90 deg: L_min = {L_min:.2f} m, L_max = {L_max:.2f} m "
    f"(ratio = **{L_ratio:.2f}**, {stroke_status})."
)
