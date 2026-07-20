"""Sensitivity map for the actuator geometry.

Peak piston force depends on four geometry variables (a, b, d, f) plus the
wall's center of gravity (x_cg, z_cg). Fixing the cg, this sweeps a dense 4-D
grid over the geometry, computes the peak |force| over the full 0-90 deg swing
for every layout (marking over-center layouts as unbuildable), and renders a
PAIRWISE SENSITIVITY MATRIX:

  * 6 lower-triangle heatmaps  -- each variable pair on the axes, color = the
    BEST achievable peak force at that combination (minimised over the other
    two variables). Green = low force (good), red = high (bad). A steep color
    gradient means that pair strongly drives the force (sensitive); a flat
    field means it barely matters.
  * 4 diagonal profiles        -- peak force vs a single variable (best case
    over the other three): the pure one-variable sensitivity.
  * blank cells                -- over-center / unbuildable regions.

It also prints a TORNADO RANKING: holding the others at the grid-optimum, how
much each variable alone swings the force -- the one-line "which knob matters
most" answer.

Outputs (standalone, no app changes):
  sensitivity_matrix.png   -- static image for a report
  sensitivity_matrix.html  -- interactive (hover for exact values, zoom)

Usage:
  python sensitivity.py                      # defaults: cg 1.2/0.55, res 34
  python sensitivity.py --x-cg 1.45 --z-cg 0.6 --res 40
"""
import argparse
import warnings

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import wall
from optimize import CONTAINER_PRESETS

VARS = ["a", "b", "d", "f"]
LABELS = {"a": "a — base along floor",
          "b": "b — attach up wall",
          "d": "d — bracket offset",
          "f": "f — base height"}


def geometry_ranges():
    """Full physical slider ranges, using High-Cube extents like the app."""
    w, h = CONTAINER_PRESETS["highcube"]
    return {"a": (0.05, w / 2), "b": (0.05, h), "d": (0.0, 1.0), "f": (0.0, h)}


def peak_force_grid(res, x_cg, z_cg, n_theta=121):
    """4-D array peak[a,b,d,f] of peak |force| (N/kg) over the 0-90 deg swing.

    Layouts that over-center (the cylinder line crosses the hinge, so the force
    diverges) are set to NaN -- they can't be built and shouldn't color the map.
    """
    rng = geometry_ranges()
    grids = {v: np.linspace(*rng[v], res) for v in VARS}
    A, B, D, F = np.meshgrid(grids["a"], grids["b"], grids["d"], grids["f"],
                             indexing="ij")

    r_att = np.sqrt(B**2 + D**2)                 # theta-independent
    r_cg = float(np.hypot(x_cg, z_cg))
    theta = np.linspace(0.0, np.pi / 2, n_theta)

    peak = np.zeros_like(A)                       # running max |F|
    s_min = np.full_like(A, np.inf)               # track sign of sin(beta-phi)
    s_max = np.full_like(A, -np.inf)

    for th in theta:
        c, s = np.cos(th), np.sin(th)
        x_att = B * c - D * s
        z_att = B * s + D * c
        x_cgw = x_cg * c - z_cg * s
        z_cgw = x_cg * s + z_cg * c
        beta = np.arctan2(z_att, x_att)
        alpha = np.arctan2(z_cgw, x_cgw)
        phi = np.arctan2(z_att - F, x_att + A)
        sin_bp = np.sin(beta - phi)
        s_min = np.minimum(s_min, sin_bp)
        s_max = np.maximum(s_max, sin_bp)
        with np.errstate(divide="ignore", invalid="ignore"):
            fval = -(r_cg * np.cos(alpha)) * wall.g / (r_att * sin_bp)
        np.maximum(peak, np.abs(fval), out=peak)

    over_center = (s_min < 0.0) & (s_max > 0.0)   # sign flip in range -> pole
    peak[over_center] = np.nan
    return grids, peak


def reduce_pair(peak, i, j):
    """min peak over the two variables that are NOT i, j -> 2-D (var_i, var_j)."""
    others = tuple(k for k in range(4) if k not in (i, j))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN slices -> NaN
        m = np.nanmin(peak, axis=others)
    return m.T if i > j else m                             # rows = var_i


def reduce_single(peak, i, how="min"):
    """Collapse the three variables that are NOT i -> 1-D vs var_i.
    how='min' = best achievable force; how='median' = typical force."""
    others = tuple(k for k in range(4) if k != i)
    fn = np.nanmin if how == "min" else np.nanmedian
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return fn(peak, axis=others)


def main_effects(peak, cap):
    """First-order (Sobol-style) sensitivity: the share of force variation each
    variable explains on its own = Var(E[force | var]) / Var(force), over the
    buildable region with force clipped to `cap` so over-center spikes don't
    dominate. Robust to where the optimum sits. Returns [(var, share)] ranked."""
    pc = np.clip(peak, 0.0, cap)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        total = float(np.nanvar(pc))
        rows = []
        for k, v in enumerate(VARS):
            others = tuple(j for j in range(4) if j != k)
            cond_mean = np.nanmean(pc, axis=others)      # E[force | var_k]
            share = float(np.nanvar(cond_mean)) / total if total > 0 else 0.0
            rows.append((v, share))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows


def grid_optimum(grids, peak):
    idx = np.unravel_index(np.nanargmin(peak), peak.shape)
    base = {v: float(grids[v][idx[k]]) for k, v in enumerate(VARS)}
    return base, float(peak[idx])


def build_figure(grids, peak, cap, x_cg, z_cg, effects):
    titles = []
    for i in range(4):
        for j in range(4):
            vi, vj = VARS[i], VARS[j]
            if i == j:
                titles.append(f"{vi} — force vs {vi}")
            elif i > j:
                titles.append(f"{vi} × {vj}")
            else:
                titles.append("")
    fig = make_subplots(rows=4, cols=4, subplot_titles=titles,
                        horizontal_spacing=0.06, vertical_spacing=0.08)

    for i in range(4):
        for j in range(4):
            r, c = i + 1, j + 1
            vi, vj = VARS[i], VARS[j]
            if i == j:
                # Two lines: best achievable (min over others) and typical (median).
                # Flat 'best' + sloping 'typical' = matters only if you tune the rest.
                fig.add_trace(go.Scatter(
                    x=grids[vi], y=reduce_single(peak, i, "median"), mode="lines",
                    line=dict(color="#c0752a", width=2, dash="dot"),
                    name="typical", legendgroup="typical", showlegend=(i == 0),
                    hovertemplate=f"{vi}=%{{x:.3f}}<br>typical=%{{y:.1f}} N/kg<extra></extra>"),
                    row=r, col=c)
                fig.add_trace(go.Scatter(
                    x=grids[vi], y=reduce_single(peak, i, "min"), mode="lines",
                    line=dict(color="#1f3b57", width=2),
                    name="best achievable", legendgroup="best", showlegend=(i == 0),
                    hovertemplate=f"{vi}=%{{x:.3f}}<br>best=%{{y:.1f}} N/kg<extra></extra>"),
                    row=r, col=c)
                fig.update_yaxes(range=[0, cap], row=r, col=c)
            elif i > j:
                z = reduce_pair(peak, i, j)
                fig.add_trace(go.Heatmap(
                    x=grids[vj], y=grids[vi], z=z, coloraxis="coloraxis",
                    hovertemplate=f"{vj}=%{{x:.3f}}<br>{vi}=%{{y:.3f}}<br>"
                                  "best force=%{z:.1f} N/kg<extra></extra>"),
                    row=r, col=c)
            fig.update_xaxes(title_text=vj if i >= j else "", row=r, col=c,
                             title_standoff=2)
            fig.update_yaxes(title_text=vi if (i > j or i == j) else "", row=r, col=c,
                             title_standoff=2)

    rank = " · ".join(f"{v} {sh*100:.0f}%" for v, sh in effects)
    fig.update_layout(
        coloraxis=dict(colorscale="RdYlGn", reversescale=True, cmin=0, cmax=cap,
                       colorbar=dict(title="peak force<br>N/kg", len=0.5, y=0.78)),
        title=dict(text=(f"Geometry sensitivity — peak piston force (N/kg), "
                         f"cg at x={x_cg}, z={z_cg} m<br>"
                         f"<sup>heatmaps: green=low force (good), red=high, blank=over-center; "
                         f"color = BEST force over the two hidden variables · "
                         f"share of force variation: {rank}</sup>"),
                   x=0.5, xanchor="center"),
        legend=dict(orientation="h", x=0.62, y=0.97, xanchor="left"),
        width=1180, height=1080, template="plotly_white",
        margin=dict(t=110, l=60, r=40, b=50))
    return fig


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--x-cg", type=float, default=1.20, help="cg along wall (m)")
    p.add_argument("--z-cg", type=float, default=0.55, help="cg off wall (m)")
    p.add_argument("--res", type=int, default=34, help="grid points per variable")
    p.add_argument("--cap", type=float, default=60.0,
                   help="color-scale max (N/kg); forces above clamp to red")
    p.add_argument("--prefix", default="sensitivity_matrix", help="output filename prefix")
    args = p.parse_args()

    print(f"Sweeping {args.res}^4 = {args.res**4:,} geometries "
          f"(cg x={args.x_cg}, z={args.z_cg})…")
    grids, peak = peak_force_grid(args.res, args.x_cg, args.z_cg)
    buildable = np.isfinite(peak).sum()
    print(f"  {buildable:,} buildable ({100*buildable/peak.size:.0f}%); "
          f"{peak.size - buildable:,} over-center.")

    base, base_force = grid_optimum(grids, peak)
    print(f"\nGrid optimum: {base_force:.2f} N/kg at "
          + ", ".join(f"{v}={base[v]:.3f}" for v in VARS))
    effects = main_effects(peak, args.cap)
    print("\nSensitivity — share of force variation each variable explains alone:")
    for v, sh in effects:
        print(f"  {v}: {sh*100:5.1f}%   " + "#" * int(round(40 * sh / effects[0][1])))

    fig = build_figure(grids, peak, args.cap, args.x_cg, args.z_cg, effects)
    fig.write_html(f"{args.prefix}.html")
    fig.write_image(f"{args.prefix}.png", scale=2)
    print(f"\nWrote {args.prefix}.png and {args.prefix}.html")


if __name__ == "__main__":
    main()
