import math
import numpy as np

# Geometric parameters, in meters. Looking down the long axis of a shipping
# container; the hinged wall is one of the long sidewalls, swinging down to lie
# flat outside the container.
#
#   a    distance along floor from hinge to cylinder mounting base
#   b    distance along wall from hinge to piston attachment point (body frame)
#   d    distance from wall to piston attachment point (body frame)
#   f    height of cylinder mounting base above the floor
#   x_cg distance along wall from hinge to cg of wall + equipment (body frame)
#   z_cg distance from wall to cg of wall + equipment (body frame)
#   m_cg mass of wall + equipment (use 1.0 for per-unit-mass results)
#
# theta is angle of wall from floor, in radians (0 = lying flat, pi/2 = closed).

g = 9.81  # m/s^2


def compute_geometry(theta, a=0.5, b=1.0, d=0.1, f=0.5, x_cg=1.2, z_cg=0.55):
    """World-frame positions of the key points at angle theta."""
    theta = np.asarray(theta, dtype=float)
    x_attachment = b * np.cos(theta) - d * np.sin(theta)
    z_attachment = b * np.sin(theta) + d * np.cos(theta)
    x_cg_world = x_cg * np.cos(theta) - z_cg * np.sin(theta)
    z_cg_world = x_cg * np.sin(theta) + z_cg * np.cos(theta)
    return {
        "attachment": (x_attachment, z_attachment),
        "cg": (x_cg_world, z_cg_world),
        "cylinder_base": (-a, f),
        "wall_axis_at_b": (b * np.cos(theta), b * np.sin(theta)),
        "wall_axis_at_xcg": (x_cg * np.cos(theta), x_cg * np.sin(theta)),
    }


def compute_cylinder_length(theta, a=0.5, b=1.0, d=0.1, f=0.5):
    """Distance between cylinder base (-a, f) and the piston attachment point."""
    theta = np.asarray(theta, dtype=float)
    x_attachment = b * np.cos(theta) - d * np.sin(theta)
    z_attachment = b * np.sin(theta) + d * np.cos(theta)
    return np.sqrt((x_attachment + a) ** 2 + (z_attachment - f) ** 2)


def compute_F_piston(theta, a=0.5, b=1.0, d=0.1, f=0.5,
                     x_cg=1.2, z_cg=0.55, m_cg=1.0):
    """Piston force needed to hold the wall at angle theta. Accepts a scalar
    or numpy array for theta."""
    geom = compute_geometry(theta, a=a, b=b, d=d, f=f, x_cg=x_cg, z_cg=z_cg)
    x_attachment, z_attachment = geom["attachment"]
    x_cg_world, z_cg_world = geom["cg"]

    r_attachment = np.sqrt(b**2 + d**2)
    beta = np.arctan2(z_attachment, x_attachment)
    r_cg = np.sqrt(x_cg**2 + z_cg**2)
    alpha = np.arctan2(z_cg_world, x_cg_world)
    phi = np.arctan2(z_attachment - f, x_attachment + a)

    torque_gravity = -(m_cg * g * r_cg * np.cos(alpha))
    return torque_gravity / (r_attachment * np.sin(beta - phi))


if __name__ == "__main__":
    print(compute_F_piston(math.radians(45)))
