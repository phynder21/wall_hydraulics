# Container Wall Actuator Sizing

Interactive tool for sizing the hydraulic cylinder that raises and lowers
a hinged sidewall on a shipping container. Drag or type the mounting
dimensions, watch the geometry update in real time, and read off the
required piston force, cylinder length range, and the **bore + operating
pressure** to buy — or let the built-in optimizer find the geometry for you.

Three views share one physics core:

- **Designer** — set a geometry (or optimize it), read the force, stroke, and a
  **bore & pressure** sizing panel. The optimizer minimizes **peak force**, or
  minimizes the **cylinder's length** under a force cap you set.
- **Browse configurations** — instant search over a precomputed database of
  geometries (no optimizer wait).
- **Size from a cylinder** — the reverse: enter a real cylinder's force and
  length window and it finds the geometry and the biggest wall it can raise.

---

## 1. Use the tool

> **Live app:** https://wall-hydraulics.streamlit.app

Open the link in any browser — phone, tablet, or computer. Nothing to
install.

Every numeric input is both a **slider** (drag) and a **number box** (type
an exact value) — use whichever you prefer.

Your input values are saved into the page URL as you change them. That
means:

- Reloading the page restores your last setup.
- Copy the address bar and send it to a colleague to drop them into the
  exact configuration you're looking at.
- Bookmark a URL to save a candidate design.

---

## 2. The setup we're modeling

Looking down the long axis of a shipping container, we see a 2-D
cross-section. One of the long sidewalls is hinged at the bottom and
swings down to lie flat on the ground outside — like a fold-down loading
ramp or a hinged equipment cover. A hydraulic cylinder mounted inside
the container holds it at any angle and drives it open or closed.

`theta` is the wall angle from the floor: `0` is fully open (flat on the
ground), `pi/2` is fully closed (upright against the container).

The tool answers two design questions:

1. **What force** must the cylinder deliver across the full angle range?
   (Drives bore and operating pressure.)
2. **What cylinder length range** is swept out from open to closed?
   (Drives stroke. Off-the-shelf hydraulic cylinders typically extend to
   at most ~1.8–2× their retracted length; the tool uses 1.8 by default
   and lets you change it.)

---

## 3. Parameters

The hinge is the origin; the floor extends left into the container; the
wall opens to the right. Every numeric parameter below can be **dragged on
its slider or typed into its number box** — whichever is handier. A
**Display units** toggle in the sidebar switches every length between
**meters and inches** (angles and force are unaffected); values are stored
in meters internally, so shared links are identical regardless of unit.

### Container

| Parameter          | Meaning                                                                    |
| ------------------ | -------------------------------------------------------------------------- |
| Container size     | Dropdown: Standard (2.44 m × 2.59 m) or High-Cube (2.44 m × 2.90 m). Sets `container_width` and `container_height`, which bound the other sliders. |

The left panel groups the controls into tabs that follow the workflow:
**Setup** (container, units, center of gravity, constraints), **Geometry**
(the variable *ranges* that bound each dimension, the `a, b, d, f` *values*
with locks, and the wall angle), **Optimize** (run the search, pick an
alternative), and **Compare** (overlay two designs). The visualization is on
the right.

### Center of gravity

| Parameter | Meaning                                                                  |
| --------- | ------------------------------------------------------------------------ |
| `x_cg`    | Distance along the wall from the hinge to the cg of wall + equipment.    |
| `z_cg`    | Perpendicular stand-off from the wall surface to the cg.                 |

The wall mass is fixed at 1 kg, so the force readout is **newtons per kg
of wall + equipment mass**. Multiply by your actual mass for the real
cylinder force.

### Constraints

These bound what counts as a valid design and feed the optimizer (below).

| Parameter          | Meaning                                                                    |
| ------------------ | -------------------------------------------------------------------------- |
| Max stroke ratio   | Largest allowed `L_max / L_min` over the swing. Draws the red limit line on the length plot. Default `1.8`. |
| Roof clearance     | How far below the ceiling the linkage endpoint must stay (in the active length unit). When > 0, a dashed red **effective ceiling** line appears on the diagram. Default `0`. |

### Mounting limits

Real installs constrain a dimension to a *window*, not a single value (a
bracket that can go anywhere from 0.3 to 0.8 m up, say). The **Mounting
limits** expander has, for each of `a, b, d, f`, a range slider **and**
min/max number boxes — drag or type the `[min, max]`. Narrow a variable's
range and both the **value slider** and the **optimizer's search** are
restricted to that window — so you get the best design *you can
actually build*, not an optimal-but-unmountable one (e.g. the base pinned at
the ceiling). Leave a range at full for no restriction; to pin an exact value
use the lock instead. Tighter ranges = less freedom, so the best
achievable force can only rise.

### Optimize

| Control | Meaning |
| ------- | ------- |
| **Optimize to minimize** | *Peak force* (default) — the geometry with the lowest worst-case piston force. *Cylinder length* — the **shortest** cylinder (smallest extended length) whose peak force stays at or below a **Max piston force (N/kg)** cap; a synced wall-mass slider shows that cap as a real force in kN. The two pull toward different geometries because the work to raise the wall is fixed: **lower force ⇒ longer stroke**. Use *force* for a hydraulic (force is cheap), *length* for an electromechanical actuator (size/force is what you pay for). |
| **Optimize geometry** button | Searches for the `a, b, d, f` that minimize the chosen objective for the current container, cg, and constraints, then fills them in. The result banner leads with the found `a, b, d, f`. See [section 6](#6-optimizing-the-geometry-optimizepy). |
| lock (beside `a`, `b`, `d`, `f`) | Hold that dimension at its current value so the optimizer searches only the unlocked ones. Lock all four to just evaluate that exact geometry. |
| Show alternatives within __% | How far above the optimum's force a listed alternative may sit. The true optimum is often awkward to build (on the standard container it wants the cylinder base right at the ceiling); a design a few percent worse can be far easier. A **sharp** optimum sits alone, so you may need ~10% before a genuinely different design appears. `0` keeps just the optimum (and exact ties). |
| Result banner | The optimizer **never returns an impossible (over-center) geometry**. After it runs, a banner reports the design: **green** = buildable and all limits met; **yellow** = best buildable design, but a stroke/roof limit can't be met (still usable — you'd just need different hardware); **red** = the (locked) geometry over-centers and can't be built, so unlock something. |
| Near-optimal alternatives | A **geometrically diverse** set of designs within your tolerance of the optimum appears in an expander below the button, each tagged with its force penalty (e.g. `+10.5%`). **Click any one to load it into the geometry and diagrams.** The first is the optimum itself. |

### Geometry

The optimizer writes its result here; you can also edit any value by hand.

| Parameter | Meaning                                                                                                |
| --------- | ------------------------------------------------------------------------------------------------------ |
| `a`       | Distance along the floor from the hinge to the cylinder mounting base. Capped at half the floor width. |
| `b`       | Distance along the wall from the hinge to the piston attachment point. Stays fixed on the wall as it rotates. |
| `d`       | Perpendicular stand-off from the wall surface to the piston attachment (the length of the bracket).    |
| `f`       | Height of the cylinder mounting base above the floor.                                                  |

### Wall angle

| Parameter   | Meaning                              |
| ----------- | ------------------------------------ |
| `theta_deg` | Current angle for the side-view diagram. Slide it to scrub through the motion; both plots mark the current angle in red. |
| Sweep θ   | Toggle to **continuously animate** the wall opening and closing (0 → 90 → 0°). The angle slider sweeps along; toggle off to freeze and scrub manually. |

### Compare designs

Weigh two designs side by side — typically the optimum against a near-optimal
alternative you clicked in. **Save as A** / **Save as B** snapshot the
current geometry; **Overlay A & B on plots** (enabled once both are saved) draws
each design's force and length curve as a dashed line (A, B) alongside the
current one, with a caption reporting each design's peak force. **Clear A/B**
removes a snapshot.

### Export design (PDF)

The **Export design (PDF)** panel downloads a one-page spec sheet for the current
configuration — setup (container, cg, mass, constraints), the `a, b, d, f`
geometry, the cylinder spec (peak/total force, required bore, standard size and
its pressure, stroke, retracted/extended length, stroke ratio), the side-view
diagram, both curves, the two **sensitivity** charts (tornado + within-range
strip), and the standard sizing caveats. Click **Generate PDF** to capture the
design as it stands, then **Download PDF**.

The same export lives in the **Browse** inspector (for the configuration you're
viewing) and in **Reverse** (a cylinder-sizing sheet: the cylinder you entered
plus the geometry it sized and the safe max wall mass). All three share one
implementation (`pdf_export.py`), as do the **sensitivity** panel
(`sensitivity_panel.py`) and the **bore & pressure** card (`cylinder_panel.py`,
Designer + Browse), so a design carries the same tools wherever you land on it.

---

## 4. How the math works

Static torque balance about the hinge at every angle:

```
F_piston(theta) = - m_cg * g * r_cg * cos(alpha)
                  ────────────────────────────────
                   r_attachment * sin(beta - phi)
```

- `r_cg`, `alpha` — distance and world angle from hinge to the cg.
- `r_attachment`, `beta` — distance and world angle from hinge to the
  piston attachment point on the wall.
- `phi` — angle of the cylinder line (base to attachment).
- `sin(beta - phi)` is the **mechanical advantage** of the cylinder
  about the hinge. When it crosses zero, the cylinder pulls straight
  through the hinge and the required force diverges (an *over-center*).
  A good design keeps this term well away from zero across the full
  0–π/2 sweep — the optimizer enforces exactly this (constraint 3 in
  [section 6](#6-optimizing-the-geometry-optimizepy)).

Cylinder length is just the distance from base `(-a, f)` to the
attachment point:

```
L_cyl(theta) = sqrt((x_attachment + a)^2 + (z_attachment - f)^2)
```

**Sign convention.** Positive `F_piston` = cylinder pulls (retracts);
negative = cylinder pushes (extends). For sizing, what matters is the
peak **magnitude**, not the sign.

---

## 5. Reading the plots and using the numbers

- **Force plot** marks `F_min` (most negative) and `F_max` (most
  positive). The worst-case magnitude is whichever has the larger
  absolute value.
- **Length plot** marks `L_min` (green) and `STROKE_RATIO_MAX × L_min`
  (red, the practical stroke ceiling — `1.8 ×` by default). If the curve
  crosses the red line you can't buy a standard cylinder for this
  geometry.
- **Caption under the length plot** reports `L_min`, `L_max`, and the
  **stroke** (`L_max − L_min`) — the rod travel you actually order a
  cylinder by — plus the `L_max / L_min` ratio. All follow the units toggle.
- **A spike or asymptote** in the force curve means the geometry passes
  through the `sin(beta - phi) = 0` singularity. Change `a`, `b`, `d`,
  or `f` until the curve is smooth and finite everywhere.
- **Side-view diagram** shows the container outline and the linkage. With
  *Roof clearance* > 0, a dashed red line marks the effective ceiling the
  linkage must stay below.

### Cylinder sizing — bore & pressure

The **Cylinder sizing** card (below the metrics) turns the total force into a
buyable cylinder. **Bore** here means the barrel's inner **diameter**. A hydraulic
cylinder makes `force = pressure × piston area`, so for a chosen system pressure
the required bore diameter is `bore = √(4·force / π·P)`
— using the full-bore **push** area, since raising the wall *extends* the
cylinder. Pick a **bore standard** — *ISO metric* (40, 50, 63 mm…), *NFPA inch*
(1.5, 2, 2.5 in…), or *Exact* (no rounding) — and a **design pressure**. It
reports:

- the **exact required bore**,
- the **next standard bore** up (a real catalog size),
- the **pressure that standard bore actually needs** for your force, and how far
  that sits **below your design pressure** (headroom).

If the force needs a bore bigger than the largest standard size, it says so —
raise the pressure, or split the load across two cylinders.

### Before sizing real hardware

- **Multiply by real mass.** Plot values are per kg; wall + equipment is
  probably 100–500 kg.
- **Apply a factor of safety.** 1.5× the static peak is a common
  starting point; more if motion is fast, the door slams, or wind
  matters.
- **The model is static.** No inertia, no friction, no flow dynamics,
  no wind loads, no flex.
- **2-D only.** Real installations usually use two cylinders (one near
  each end of the wall) to prevent twist. The sidebar's **Cylinders sharing
  the load** switch (1 or 2, in every view) handles this: with 2, the load is
  split equally and **every force and bore size shown becomes per cylinder**
  (and the reverse view's max wall mass doubles). The geometry is unchanged.

---

## 6. Optimizing the geometry (`optimize.py`)

The app is a *viewer* — you move the sliders and read off the force.
`optimize.py` is the inverse: it *searches* for the four mounting
dimensions (`a`, `b`, `d`, `f`) that **minimize the worst-case piston
force** over the full 0–90° swing, subject to physical constraints. The
center of gravity and container size are fixed inputs (the door you are
lifting), not design variables.

Run it (standard container is the default):

```bash
python3 optimize.py                                   # standard container
python3 optimize.py --container highcube --x-cg 1.4   # high-cube, custom cg
python3 optimize.py --stroke-ratio 2.0                # override the limit
python3 optimize.py --lock f=0.5                      # hold f, optimize a, b, d
python3 optimize.py --help                            # all options
```

It prints the optimal `a, b, d, f`, the resulting peak force, the cylinder
stroke and stroke ratio, the roof and over-center clearances, whether the
design is feasible, and a paste-ready line for the app's sliders.

**Locking variables.** Real installs often fix some dimensions (a bracket
height, an existing floor mount). Pass `--lock VAR=VALUE` (repeatable) to
hold those fixed and search only the rest — e.g. `--lock f=0.5 --lock a=0.6`.
In the app, tick the box next to `a`, `b`, `d`, or `f` to do the same.
Locking removes design freedom, so the best achievable peak force can only
stay equal or rise, and tight locks may make the constraints infeasible
(reported as such). Locking all four just evaluates that fixed geometry.

**Restricting a range.** To search only a *sub-range* of a variable rather
than pin it, pass `var_bounds={"f": (0.0, 1.0)}` to `optimize_actuator` (this
is what the app's **Mounting limits** range sliders do). A zero-width range is
treated as a lock. The CLI currently exposes locking but not ranges.

### How it works

This is a constrained **min–max** problem. For one candidate geometry we
sweep `theta` across the whole swing and reduce the force curve to a
single number — its peak magnitude. A global, gradient-free optimizer
(SciPy's `differential_evolution`) then searches the geometry space for
the candidate with the smallest peak.

### Multi-start (finding the *global* optimum)

A single `differential_evolution` run can settle into a good-but-not-best
valley — its answer depends on the random seed. For some geometries the best
design sits in a **narrow basin that most seeds miss**: on the standard
container, the default seed lands on 14.30 N/kg while the true optimum is
**12.94 N/kg (~10% lower)**. So `optimize_actuator` runs **`N_STARTS`
(default 20) independent starts from fixed seeds and keeps the best** — at a
~28% per-seed hit rate, 20 starts finds the global basin ~99.9% of the time,
and *fixed* seeds keep the result reproducible (so shared URLs stay stable).
Bigger per-seed populations and corner-seeded starts were both tested and
gave **no** reliability gain — only independent restarts help — so they
aren't used. The trade-off: the Optimize button takes ~20 s; `n_starts` is
tunable (`--starts` on the CLI).

**Near-optimal alternatives.** The true optimum is often the *least* buildable
design — on the standard container it wants the cylinder base right at the
ceiling (`f` at its max). So alongside the optimum, `optimize_actuator` returns
`alternatives`: a geometrically **diverse** set of near-optimal designs, each
within `alt_rel_tol` of the optimum's peak force (default 15%; a slider in the
app, `--alt-tol` on the CLI) and tagged with its `penalty_pct`.

Because a sharp optimum sits alone in a narrow basin, jittering around it finds
nothing new — the nearest genuinely different design can be ~10% worse. So each
extra design is found by **re-optimizing with a repulsion penalty** that pushes
the search away from the designs already chosen: the result is the lowest-force
geometry that is meaningfully different from them, kept only if it stays within
tolerance. Feasible multi-start winners seed the set first (they're free). The
optimum is always `alternatives[0]`; the app shows them as **clickable buttons**
(click to load into the geometry and diagrams), so you can trade a few percent
of force for a design that is far easier to mount.

### How the constraints are added (penalty method)

Rather than derive Lagrange/KKT multipliers by hand, each inequality
constraint is folded into the objective as a **penalty** — a cost that is
zero when the constraint holds and grows quadratically as it is violated.
The optimizer then minimizes a single unconstrained sum and is naturally
pushed to the feasible boundary:

```
objective(a,b,d,f) = peak_force
                   + STROKE_PENALTY     * max(0, stroke_ratio - STROKE_RATIO_MAX)^2
                   + CEILING_PENALTY    * roof_overshoot^2
                   + OVERCENTER_PENALTY * max(0, MIN_MOMENT_ARM - moment_arm)^2
                   + OVERCENTER_HARD    if moment_arm < 0   (crossing: impossible)
```

Three constraints are enforced this way:

1. **Stroke limit.** A hydraulic cylinder can only extend so far, so we
   require `L_max / L_min ≤ STROKE_RATIO_MAX` across the swing.

2. **Roof clearance.** The attachment endpoint sweeps an arc of radius
   `r_att = √(b² + d²)` about the hinge. Wherever that endpoint is
   horizontally inside the container footprint (`−W ≤ x ≤ 0`), it must
   stay below the **effective ceiling** `H − ROOF_CLEARANCE`; otherwise
   the bracket would pass through the roof. `ROOF_CLEARANCE` is a
   mechanical safety margin (meters) — `0` lets the endpoint just touch
   the roof, larger values keep more air underneath. `roof_overshoot` is
   the worst `max(0, z − (H − ROOF_CLEARANCE))` over the swing.
   Geometrically this caps the swing radius at `r_att ≤ H − ROOF_CLEARANCE`,
   and the optimum sits right on that cap.

3. **No over-center.** The cylinder's moment arm about the hinge is
   `r_att · sin(β − φ)`, where `β` points hinge→attachment and `φ` points
   base→attachment. It vanishes when the base, hinge, and attachment go
   **collinear** — the line of action passes through the hinge, the lever
   arm is zero, and the required force **diverges to infinity**. We track
   `sin(β − φ)` over the swing; if it changes sign the geometry
   *over-centers* (physically impossible to build). `moment_arm` is the
   signed worst-case clearance — the closest approach of `|sin(β − φ)|` to
   zero, made negative if it crosses — and we require it to stay
   `≥ MIN_MOMENT_ARM`. This both forbids the crossing and keeps a real,
   build-tolerant margin away from it. (Catching this needs the *sign*, not
   the force magnitude: near the crossing the force spike can be so narrow
   it slips between samples and reads as deceptively low.)

The over-center penalty is **hard** (`OVERCENTER_HARD`, far larger than the
others): a crossing is physically impossible, not merely costly, so the
optimizer always returns the best **buildable** (non-over-center) geometry —
it will give up the stroke and roof limits before it ever hands back an
impossible design. A result is reported **feasible** only when *all three*
constraints hold within tolerance; when they can't all be met, you still get
the best buildable geometry, flagged as not-all-limits-met rather than a
failure.

### The global constants

| Constant | Where | Default | Meaning |
|---|---|---|---|
| `STROKE_RATIO_MAX` | `wall.py` | `1.8` | Max extended/retracted cylinder length ratio. **Shared** by the app's length plot and the optimizer so the two never disagree — change it in one place. |
| `N_STARTS` | `optimize.py` | `20` | Independent optimizer restarts (multi-start); the best is kept. More = more reliably global, but slower. |
| `ALT_REL_TOL` | `optimize.py` | `0.15` | Default force tolerance for near-optimal `alternatives` (within 15% of the optimum). Overridable per call (`alt_rel_tol`), by the app's slider, or `--alt-tol`. |
| `N_ALTERNATIVES` | `optimize.py` | `6` | Most designs returned in `alternatives` (including the optimum). |
| `ALT_TARGET_SEP` / `ALT_MIN_SEP` | `optimize.py` | `0.20` / `0.08` | Normalized geometry separation each new alternative *aims for* / must *at least* reach to count as genuinely distinct. |
| `ROOF_CLEARANCE` | `optimize.py` | `0.0` m | Mechanical margin: how far below the ceiling the endpoint must stay. Effective ceiling = `height − ROOF_CLEARANCE`. |
| `MIN_MOMENT_ARM` | `optimize.py` | `0.05` | Smallest allowed `|sin(β − φ)|` over the swing — the over-center floor. Larger = more clearance from the singularity (and a lower force ceiling), at the cost of a smaller feasible set. |
| `STROKE_PENALTY` | `optimize.py` | `1e6` | Weight on the stroke-limit penalty. |
| `CEILING_PENALTY` | `optimize.py` | `1e6` | Weight on the roof-clearance penalty. |
| `OVERCENTER_PENALTY` | `optimize.py` | `1e6` | Weight on the (soft) over-center margin penalty. |
| `OVERCENTER_HARD` | `optimize.py` | `1e12` | Hard floor added when the moment arm actually crosses zero, so a buildable geometry always beats an impossible one. |
| `STROKE_TOL` | `optimize.py` | `1e-3` | Solver slack for declaring the stroke limit "met" (not a design margin). |
| `CEILING_TOL` | `optimize.py` | `1e-3` m | Solver slack for declaring roof clearance "met" (not a design margin). |
| `MOMENT_ARM_TOL` | `optimize.py` | `1e-3` | Solver slack for declaring the over-center constraint "met". |

Two values can also be overridden per run without touching the
constants: `--stroke-ratio` and `--clearance`. The penalty weights are
deliberately large so the optimum sits essentially *on* each limit rather
than past it; the `*_TOL` values are pure numerical slack that absorb the
tiny residual violation penalty methods leave behind. `optimize.py`
requires SciPy (already in `requirements.txt`).

### Browse mode: a precomputed lookup (instant, no optimizer)

The optimizer takes ~20 s per run. The **Browse configurations** view (the
sidebar view switch at the top) trades that for *instant* search over a
**precomputed database** of geometries. Set your problem (container, cg, stroke
limit, roof clearance) and mounting limits, then filter and sort by any
attribute — peak force, base height `f`, bracket length `d`, stroke — to find a
buildable design, not just the single force-optimal one.

How it stays small and fast, from the physics:

- The force factorizes as `F(θ) = (z_cg·sinθ − x_cg·cosθ) · G(θ)`, where the
  gain curve `G = g/D` depends **only on geometry**. So the table is indexed by
  the 4-D geometry grid `(a, b, d, f)` alone; the cg is reconstructed at query
  time (force is *linear* in the cg), never a table dimension.
- Stroke ratio and the over-center margin are geometry-only, and roof clearance
  is a threshold on a stored value — so every constraint and mounting limit is a
  plain row filter, not a table dimension.
- `lookup_build.py` sweeps the grid once (~15 s, cached in memory on first use —
  the table is **not** committed, it's regenerated), pruning over-center and
  over-stroke geometries. `lookup.py` filters + ranks a query in ~40 ms.

Because a grid can't land exactly on the stroke-limit boundary (where the
optimum usually sits), a hard cutoff would hide every near-optimal design — the
closest grid points are a step *over* the limit (e.g. ratio 1.81 for a 1.80
limit). So the stroke filter allows a small grid tolerance (`STROKE_GRID_TOL`)
and the real stroke ratio is shown in the results, so the ~12.9 N/kg designs
appear (at ratio ~1.85, not exactly 1.80). Plots for any selected config are
recomputed **exactly** from `wall.py`, and **Refine** runs the real optimizer
for the exact-limit optimum.

### Size from a cylinder: the reverse

The **Size from a cylinder** view (the third sidebar view) works backwards from a
real cylinder. Enter its **force** (bore + rod + pressure, or a rated force) and
its **length window** (retracted length + stroke) in whichever units you like (an
Imperial/Metric toggle converts in place), plus a safety factor. It searches the
same precomputed table for geometries whose cylinder length stays entirely inside
[retracted, extended] the whole way up, and reports the **biggest wall mass** that
cylinder can raise — both a *safe* figure (force ÷ safety factor) and the
*absolute* cylinder maximum. Because the length window is a hard constraint, some
cylinders won't fit any geometry; when that happens it says so and gives the
length range that *would* work. **Refine** runs the exact optimizer with the
length window as a constraint.

---

## 7. Run it locally (for developers)

End users don't need this section — they just open the live app URL
above. This is only for someone who wants to modify the code.

**What you need first:**

- **Python 3.10+** — install from [python.org](https://www.python.org/downloads/)
  (on Windows make sure to check "Add Python to PATH"; on macOS
  `brew install python` also works).
- **Git** — install from [git-scm.com](https://git-scm.com/downloads),
  or skip git and use the "Download ZIP" button on the GitHub repo page
  instead.

**Get the code:**

```bash
git clone https://github.com/phynder21/wall_hydraulics.git
cd wall_hydraulics
```

Or, without git: on the [repo
page](https://github.com/phynder21/wall_hydraulics), click the green
**Code** button → **Download ZIP**, then unzip and `cd` into the folder.

**Set up an isolated environment and install dependencies:**

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The `.venv` step keeps Streamlit and its dependencies out of your
system Python.

**Run the app:**

```bash
streamlit run app.py
```

A browser tab opens at `http://localhost:8501`. Stop with `Ctrl+C`.

**Run the tests:**

The repo ships a [`pytest`](https://docs.pytest.org/) suite under `tests/`
that guards the three layers — the physics (`wall.py`), the optimizer
(`optimize.py`), and the Streamlit UI (`app.py`). Run it after any change:

```bash
pytest                 # fast suite (~1 min) — run this routinely
pytest -m slow         # exhaustive sweeps too (several minutes; before a release)
pytest tests/test_physics.py -v   # one file, verbose
```

(If `pytest` isn't found, use `python3 -m pytest`.) What it covers:

- **`test_physics.py`** — cross-checks `compute_F_piston` against an
  independent torque-balance derivation over thousands of random geometries,
  plus array/scalar consistency, swing endpoints, and degenerate inputs.
- **`test_optimize.py`** — result-shape and constraint *invariants* across
  varied cg, stroke ratios, clearances, locks, and mounting limits;
  determinism; and that multi-start still reaches the known global optimum.
- **`test_lookup.py`** — the Browse-mode table and query layer: build-time
  pruning invariants, the stored gain curve matching exact physics, that
  filters/mounting-limits/sorting behave, and that the grid best is a valid
  upper bound on the optimizer's answer.
- **`test_app.py`** — renders the app headlessly (Streamlit's `AppTest`) in
  both unit systems and the fine-precision mode, with extreme geometries, cg,
  constraints, container switches, malformed URL params, the
  clickable-alternatives flow, and the Browse view. The animation bounce logic
  is unit-tested directly (it can't be driven through `AppTest`'s rerun loop).

The heavier sweeps are marked `slow` and skipped by default, so the routine
`pytest` run stays fast.

For a **human-readable, reproducible test plan** — a spreadsheet of optimizer
points (each limiting factor and the optimized force it produces) plus physics
anchor checks you can verify by hand from the equations — see
[`docs/experiment_plan.md`](docs/experiment_plan.md) and the
paste-into-a-spreadsheet [`docs/test_cases.csv`](docs/test_cases.csv).

### Troubleshooting

| Symptom                                          | Fix                                                                          |
| ------------------------------------------------ | ---------------------------------------------------------------------------- |
| `python: command not found` (macOS/Linux)        | Use `python3` instead.                                                       |
| `pip: command not found`                         | Use `python3 -m pip install -r requirements.txt`.                            |
| `streamlit: command not found` after install     | The venv probably isn't activated. Re-run the `activate` line, or use `python3 -m streamlit run app.py`. |
| Browser doesn't open automatically               | Visit `http://localhost:8501` manually.                                      |
| PowerShell blocks `Activate.ps1`                 | Run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then retry. |

---

## 8. Modify the code

**Two front-ends, one core.** The physics (`wall.py`), optimizer
(`optimize.py`), and lookup table (`lookup.py` / `lookup_build.py`) are plain
Python with **no UI**. Two interfaces import that same core:

- **`app.py` — Streamlit** (the original; deploys to Streamlit Cloud).
- **`nicegui_app.py` — NiceGUI** (a parallel, snappier UI with the same
  features; deploys to Render — see [`NICEGUI.md`](NICEGUI.md)).

Because the numerics live in the shared core, a change there (e.g. a faster
optimizer) benefits **both** front-ends automatically; only UI-specific tweaks
are done in both `app.py` and `nicegui_app.py`.

```
.
│  # --- shared core (no UI; imported by everything, and by the tests) ---
├── wall.py            # Physics + shared constants (e.g. STROKE_RATIO_MAX).
├── optimize.py        # Geometry optimizer (CLI + importable function). Needs SciPy.
├── lookup.py          # Fast filter + rank query over the precomputed table.
├── lookup_build.py    # Builds the precomputed geometry table (Browse mode).
│  # --- front-end 1: Streamlit ---
├── app.py             # Streamlit UI (Designer + view switch).
├── browse.py          # Streamlit "Browse configurations" view.
├── reverse.py         # Streamlit "Size from a cylinder" (reverse) view.
├── sensitivity_panel.py # Shared in-app sensitivity panel (Designer + Browse + Reverse).
├── cylinder_panel.py  # Shared bore & pressure sizing card (Designer + Browse).
├── pdf_export.py      # Shared one-page PDF spec sheet (Designer + Browse + Reverse).
├── sensitivity.py     # Standalone: geometry sensitivity heatmap (PNG/HTML). See GUIDE.
├── .streamlit/config.toml   # Streamlit theme.
├── requirements.txt   # Streamlit deps (streamlit, numpy, plotly, scipy, pytest, kaleido).
│  # --- front-end 2: NiceGUI ---
├── nicegui_app.py     # NiceGUI UI (same features; /browse, /reverse routes). See NICEGUI.md.
├── requirements-nicegui.txt # NiceGUI deps (separate, so the two deploys never mix).
├── render.yaml        # Render.com blueprint for the NiceGUI deploy.
├── NICEGUI.md         # How to run + deploy the NiceGUI front-end.
│  # --- tests & docs ---
├── tests/             # pytest suite (physics, optimizer, lookup, both UIs). Section 7.
├── docs/              # Reproducible test plan (experiment_plan.md + test_cases.csv).
├── GUIDE.md           # Short user guide to the three views.
├── manual_qa_test_cases.csv  # Ground-truth inputs/outputs for manual QA across the app.
├── prototypes/        # Static HTML UI mockups — open in a browser; not part of either app.
├── pytest.ini
└── README.md
```

The split is intentional: `wall.py` knows nothing about any UI and
can be imported into a Jupyter notebook, a test, or a CSV-generating
script without dragging in Streamlit or NiceGUI.

**Hot reload.** Streamlit watches `app.py` and the modules it imports at
the top (`wall.py`, `optimize.py`) and re-runs on save. If a change ever
doesn't seem to take effect — Streamlit's watcher can miss edits to
imported modules in some cases — stop the server (`Ctrl+C`) and run
`streamlit run app.py` again; a full restart always reloads everything.
You also need a restart when you edit `requirements.txt` or
`.streamlit/config.toml`.

**To add a new parameter:**

1. Add it as a keyword argument to the relevant function(s) in
   `wall.py`.
2. Add an input in `app.py` — use the `linked_input(...)` helper for a
   drag-and-type geometry value, or `st.sidebar.number_input(..., key=...)`
   for a plain one.
3. Add an entry to the `DEFAULTS` dict in `app.py` so the URL
   persistence picks it up.
4. Pass it through to the `compute_*` calls in `app.py`.

---

## 9. Deploy your own copy

There are **two independent deployments** from the same GitHub repo (`main`
branch) — each builds a different front-end, so they don't interfere (separate
requirements files, separate entry points). Both auto-redeploy on push to
`main`, so one `git push` can update both.

**Streamlit app (`app.py`) → [Streamlit Community Cloud](https://share.streamlit.io)** (free)
1. Push this repo to your GitHub.
2. Sign in at share.streamlit.io, **New app**, set the main file to `app.py`
   (it installs `requirements.txt`), deploy.
3. You get a public `…streamlit.app` URL.

**NiceGUI app (`nicegui_app.py`) → [Render](https://render.com)** (free tier)
1. Sign in at render.com, **New + → Blueprint**, pick this repo. Render reads
   `render.yaml` (installs `requirements-nicegui.txt`, runs `python nicegui_app.py`).
2. You get a public `https://<name>.onrender.com` URL. If a push doesn't
   redeploy automatically, use **Manual Deploy → Deploy latest commit**.

Streamlit Cloud can only host the Streamlit app (it's Streamlit-specific), which
is why NiceGUI goes on Render. Full NiceGUI run/deploy notes — including the
free-tier "sleeps when idle" caveat — are in [`NICEGUI.md`](NICEGUI.md).

---

## Built with

[Python](https://www.python.org/) ·
[NumPy](https://numpy.org/) ·
[SciPy](https://scipy.org/) ·
[Streamlit](https://streamlit.io/) ·
[NiceGUI](https://nicegui.io/) ·
[Plotly](https://plotly.com/python/)

The browser doesn't execute Python directly. Streamlit runs your script
in a small local web server; slider changes are sent over a WebSocket,
the script reruns, and new chart data is shipped as JSON for Plotly.js
to render in the browser.
