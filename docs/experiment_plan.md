# Experiment / Test Plan — Container Wall Actuator Tool

**Purpose.** Confirm that the design tool produces *real, accurate* results — not
just that it runs. Everything here is meant to be **independently reproducible**
by a second person given the same math (physics) or the same implementation
(optimizer).

Two artifacts:

- **[`test_cases.csv`](test_cases.csv)** — the main table: each **point**, the
  **limiting factor you select** (and its setting), and the resulting
  **optimized peak force**. Open it, copy all, and paste into Google Sheets (if
  it lands in one column, use **Data → Split text to columns → Comma**). Each
  study varies one factor while the rest stay at the baseline (row `B0`), so a
  study's rows plot directly as force vs. that factor.
- **Section 6 below** — physics *anchor checks*: a handful of forces/lengths that
  are exact from the equations, so you can confirm the underlying math with a
  calculator, independent of any code.

---

## 1. Scope — three layers

| Layer | File | What it does | How results are reproduced |
|---|---|---|---|
| **Physics** | `wall.py` | Static piston force and cylinder length at a given angle. | **Analytically.** Anyone with the torque-balance equation and a calculator gets the same number. These are the ground-truth cases. |
| **Optimizer** | `optimize.py` | Searches geometry for minimum peak force under constraints. | **Deterministically.** Fixed random seeds (0…19) make every run identical *with this implementation*. See the reproducibility note below. |
| **UI / units** | `app.py` | Sliders, unit toggle, URL state, plots. | **By construction** — unit factors and state round-trips; covered by the automated `pytest` suite (README §7). |

The CSV holds the **optimizer** points; the **physics** anchors are §6 below; the
**UI** layer is exercised by the automated tests rather than this hand table.

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

## 4. How to run the points (`test_cases.csv`)

Each row is one optimizer run: set the limiting factor to its setting, keep
everything else at the baseline (`B0`), and read the optimized peak force.

- **CLI (scriptable)** covers the rows whose factor is a plain flag:
  `python3 optimize.py` with `--stroke-ratio 2.0` (S-rows), `--container highcube`
  (C2), `--x-cg 1.2 --z-cg 1.0` (G-rows), or `--lock f=0.40` (L1).
- **Mounting-limit rows (F- and R-rows)** cap the base height `f`, which the CLI
  does not expose. Use the app's **Mounting limits** (F-rows: set the `f` range,
  e.g. `[0, 0.5]`; R-rows: set `f` to `[0, 1.0]` *and* the **Roof clearance**
  slider), or call the function directly, e.g.
  `optimize_actuator(2.438, 2.591, 1.2, 0.55, var_bounds={'f': (0.0, 1.0)}, roof_clearance=0.05)`.
- **App (any row):** dial the same setting in the sidebar and press **Optimize**;
  read the peak off the result banner or the force plot.
- **All at once (regression):** `pytest` runs an automated mirror of these
  (`pytest -m slow` for the exhaustive ones). See README §7.

## 5. Pass criteria

A point **passes** if the optimized peak force matches the table within about
**±0.1 N/kg** (optimizer tolerance for solver/version variation), and the
qualitative flags (feasible / over-center / which factor is binding) match. The
physics anchors (§6) are formula-exact and use a much tighter tolerance. Record
any mismatch so it can be traced — as we did when the "14.30 vs 14.58" gap
turned out to be a roof-clearance difference (rows R1 vs R2).

## 6. Physics anchor checks (analytic ground truth)

These do **not** involve the optimizer — they check the force/length math
directly, and are reproducible from the equations in §3 with a calculator.
Fixed geometry `a=0.5, b=1.0, d=0.1, f=0.5` unless noted; `mass = 1 kg`.

| # | Check | Inputs | Expected | Tolerance |
|---|---|---|---|---|
| A1 | CG on the hinge → no moment | x_cg=0, z_cg=0, θ=37° | F = 0.000 N/kg | 1e-9 |
| A2 | Vertical wall, cg on the wall line → above hinge | x_cg=1.2, z_cg=0, θ=90° | F = 0.000 N/kg | 1e-9 |
| A3 | Reference force, flat | x_cg=1.2, z_cg=0.55, θ=0° | F = −33.2274 N/kg (pushes) | 1e-3 |
| A4 | Reference force, mid-swing | x_cg=1.2, z_cg=0.55, θ=45° | F = −7.4596 N/kg | 1e-3 |
| A5 | Reference force, closed (sign flips) | x_cg=1.2, z_cg=0.55, θ=90° | F = +7.6773 N/kg (pulls) | 1e-3 |
| A6 | Force is linear in mass | as A4 but mass=2 | F = −14.9193 N/kg (= 2 × A4) | 1e-3 |
| A7 | Cylinder length, flat (hand-check) | θ=0° → √(1.5² + 0.4²) | L = 1.552417 m = √2.41 | 1e-4 |
| A8 | Cylinder length, closed (hand-check) | θ=90° → √(0.4² + 0.5²) | L = 0.640312 m = √0.41 | 1e-4 |
| A9 | Over-center blow-up | a=0.2, b=0.3, d=0.3, f=0.3, sweep θ | max \|F\| > 1000 N/kg (diverges at the pole) | qualitative |

Run one directly, e.g.:
`python3 -c "import math, wall; print(wall.compute_F_piston(math.radians(45), a=0.5,b=1.0,d=0.1,f=0.5,x_cg=1.2,z_cg=0.55))"`
