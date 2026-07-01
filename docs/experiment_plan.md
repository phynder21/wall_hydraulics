# Experiment / Test Plan — Container Wall Actuator Tool

**Purpose.** Confirm that the design tool produces *real, accurate* results — not
just that it runs. Each case below has inputs, a procedure, and an **expected
result a second person can independently reproduce** given the same math (for
physics) or the same implementation (for the optimizer). Record your observed
value in the "Pass/Fail" column.

The machine-readable case list is [`test_cases.csv`](test_cases.csv) — open it,
copy all, and paste into Google Sheets (if it lands in one column, use
**Data → Split text to columns → Comma**).

---

## 1. Scope — three layers

| Layer | File | What it does | How results are reproduced |
|---|---|---|---|
| **Physics** | `wall.py` | Static piston force and cylinder length at a given angle. | **Analytically.** Anyone with the torque-balance equation and a calculator gets the same number. These are the ground-truth cases. |
| **Optimizer** | `optimize.py` | Searches geometry for minimum peak force under constraints. | **Deterministically.** Fixed random seeds (0…19) make every run identical *with this implementation*. See the reproducibility note below. |
| **UI / units** | `app.py` | Sliders, unit toggle, URL state, plots. | **By construction** — unit factors and state round-trips. |

## 2. Environment (record yours)

The reference numbers below were produced with:

- Python **3.14.5**, NumPy **2.4.6**, SciPy **1.18.0**
- `g = 9.81 m/s²`, container presets: Standard **2.438 × 2.591 m**, High-Cube **2.438 × 2.896 m**
- Optimizer defaults: `N_STARTS = 20`, `n_theta = 200`, `maxiter = 300`, `seed = 0`, stroke-ratio limit `1.8`

**Reproducibility note.** *Physics* cases are exact from the equations and are
version-independent. *Optimizer* cases are deterministic for a given SciPy
version because the seeds are fixed; a **different SciPy version may shift a
local basin slightly**, so compare optimizer values within the stated tolerance,
not bit-for-bit. The **global** optimum (e.g. 12.94 N/kg on the standard
container) is robust across versions; the exact *alternatives* are the most
version-sensitive. Always report the versions you used.

## 3. The core math (so a reviewer can recompute the physics)

Piston force to hold the wall at angle `θ` (per kg of wall+equipment mass):

```
F(θ) = −[ m·g·r_cg·cos(α) ] / [ r_att·sin(β − φ) ]
```

- Attachment (world): `x_att = b·cosθ − d·sinθ`, `z_att = b·sinθ + d·cosθ`
- cg (world): `x_cgw = x_cg·cosθ − z_cg·sinθ`, `z_cgw = x_cg·sinθ + z_cg·cosθ`
- `r_cg = √(x_cg² + z_cg²)`, `α = atan2(z_cgw, x_cgw)` — world angle hinge→cg
- `r_att = √(b² + d²)`, `β = atan2(z_att, x_att)` — world angle hinge→attachment
- `φ = atan2(z_att − f, x_att + a)` — angle of the cylinder line, base→attachment
- Cylinder base is fixed at `(−a, f)`; cylinder length `L(θ) = √((x_att + a)² + (z_att − f)²)`
- **Sign:** `F > 0` = cylinder pulls (retracts), `F < 0` = pushes (extends). For sizing, the peak **magnitude** is what matters.
- **Over-center:** when `sin(β − φ)` changes sign across the 0–90° swing, the cylinder line crosses the hinge, the lever arm passes through zero, and `F` diverges — a physically impossible geometry. The optimizer rejects these; the physics simply returns a blow-up.

See the [README](../README.md) §4 and §6 for the full derivation.

## 4. How to run each case

- **Physics (P-*):** call the function directly, e.g.
  `python3 -c "import math, wall; print(wall.compute_F_piston(math.radians(45), a=0.5,b=1.0,d=0.1,f=0.5,x_cg=1.2,z_cg=0.55))"`
  — or set the geometry/angle sliders in the app and read the caption/plot marker.
- **Optimizer (O-*):** use the CLI so the run is scriptable, e.g.
  `python3 optimize.py --stroke-ratio 2.0` (add `--lock f=0.4`, `--clearance 0.05`, `--alt-tol 0.15` as the case requires). Or press **Optimize** in the app with the same settings.
- **UI (U-*):** perform the action in the app and read the widget/URL.
- **All at once (regression):** `pytest` runs the automated mirror of these cases
  (`pytest -m slow` for the exhaustive ones). See README §7.

## 5. Pass criteria

A case **passes** if the observed value equals the expected value within the
stated tolerance, *and* the qualitative flags (feasible / over_center / binding)
match. Physics tolerances are tight (formula-exact); optimizer tolerances allow
for solver/version variation. Any mismatch outside tolerance is a **fail** —
record the observed number so the discrepancy can be traced (as we did when the
"14.30 vs 14.58" gap turned out to be a roof-clearance difference — see O9).
