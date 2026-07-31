"""Draw a shipping container's steel shell (back wall, floor understructure, roof)
as filled rectangles AROUND the internal clear space, so the diagrams make clear that
the mechanism works in the INTERNAL envelope, not the outer ISO box.

Shared by the Designer diagram (app.py), the quick-guide schematic (app.py) and the
Browse/Reverse inspector diagram (browse._diagram_figure) so every view — and the PDF
that embeds these figures — shows the wall thickness the same way.
"""
from optimize import SHELL_T_SIDE, SHELL_T_ROOF, SHELL_T_FLOOR


def add_container_shell(fig, width, height, scale=1.0,
                        fill="#e5e7eb", line_color="#9ca3af", line_width=1):
    """Draw the container shell around the internal clear space on a plotly figure.

    `width`/`height` are the INTERNAL clear dimensions (meters); the clear space is
    x in (-width, 0), z in (0, height), with the hinge at (0, 0). `scale` converts to
    the figure's display units (e.g. meters->inches). The shell is drawn as three
    filled rectangles UNDER the mechanism: floor understructure below z=0, roof above
    z=height, and the back wall left of x=-width — each a shell-thickness thick.

    Returns (x_left, z_bottom, z_top) — the outer extents in the figure's units — so
    the caller can widen the axis ranges to include the shell.
    """
    ts, tr, tf = SHELL_T_SIDE * scale, SHELL_T_ROOF * scale, SHELL_T_FLOOR * scale
    w, h = width * scale, height * scale
    x_left, z_bottom, z_top = -w - ts, -tf, h + tr
    for x0, y0, x1, y1 in (
        (x_left, z_bottom, 0.0, 0.0),     # floor understructure (below the clear floor)
        (x_left, h, 0.0, z_top),          # roof (above the clear ceiling)
        (x_left, 0.0, -w, h),             # back wall (left of the clear width)
    ):
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1, layer="below",
                      fillcolor=fill, line=dict(color=line_color, width=line_width))
    return x_left, z_bottom, z_top
