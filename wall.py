import math

# Geometric parameters from spreadsheet, in meters
a = 0.5 # distance along floor from hinge to cylinder mounting base
b = 1.0 # distance along wall from hinge to piston attachment point, body coordinate
d = 0.1 # distance from wall to piston attachment point, body coordinate
f = 0.5 # distance of cylinder mounting base from floor

# Location of cg of wall + equipment mounted to wall
x_cg = 0.5 # distance along wall from hinge to cg of wall + equipment, body coordinate
z_cg = 0.5 # distance from wall to cg of wall + equipment, body coordinate

# Use a unit mass, so we can do percentages
m_cg = 1.0 # mass of wall + equipment mounted to wall
g = 9.81 # acceleration due to gravity, m/s^2

# theta is angle from wall to floor, in radians
# alpha is angle from floor to cg
# beta is angle from floor to piston attachment point
# phi is cylinder angle from horizontal

# We need to figure out the world coordinates of attachment point and cg point
# as a function of theta.
theta = math.radians(45)# angle of wall from floor, in radians
r_attachment = math.sqrt(b**2 + d**2)
x_attachment = (b * math.cos(theta) - d * math.sin(theta))
z_attachment = (b * math.sin(theta) + d * math.cos(theta))
beta = math.atan2(z_attachment, x_attachment)

r_cg = math.sqrt(x_cg**2 + z_cg**2)
x_cg_world = x_cg * math.cos(theta) - z_cg * math.sin(theta)
z_cg_world = x_cg * math.sin(theta) + z_cg * math.cos(theta)
alpha = math.atan2(z_cg_world, x_cg_world)

# Cylinder angle. Piston attaches at x_attachement, z_attachment, and cylinder 
# mounts at (-a,f)
phi = math.atan2((z_attachment - f), (x_attachment + a))

# Torque on wall from gravity, negative because wall is being pulled clockwise when wall is on floor
torque_gravity = -(m_cg * g * r_cg * math.cos(alpha))

# Torque due to piston force, positive because piston is pulling counterclockwise when wall is on floor
# torque_piston = F_piston * r_attachment * math.sin(beta - phi)
# Torque from piston must balance gravity torque
F_piston = torque_gravity / (r_attachment * math.sin(beta - phi))

print(F_piston)
