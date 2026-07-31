# Container Wall Actuator — Quick Guide

A tool for sizing the **hydraulic cylinder that raises and lowers a hinged
shipping-container sidewall**. You describe the wall and where the cylinder can
mount; the tool finds the geometry that needs the **least piston force** — or the
**shortest cylinder** — so you can spec a smaller, cheaper actuator.

There are two apps with the same engine: a Streamlit version and a NiceGUI
version (deployed on Render). Both have the same three views.

---

## What the numbers mean

The wall pivots on a hinge and swings from **flat (0°)** to **fully upright
(90°)**. A cylinder pushes on it. Four numbers describe the setup:

| Symbol | Meaning |
|--------|---------|
| **a** | cylinder base position along the floor (from the hinge) |
| **b** | attachment point up the wall (from the hinge) |
| **d** | bracket offset — how far the attachment sticks out from the wall |
| **f** | height of the cylinder base above the floor |
| **x_cg**, **z_cg** | where the wall's weight acts (center of gravity), along and off the wall |

Two limits keep designs realistic:
- **Max stroke ratio** — the cylinder's extended ÷ retracted length. Real
  hydraulic cylinders are ~1.8–2×. This is a hard cap: results never exceed it.
- **Roof clearance** — how far the moving parts must stay below the ceiling.

**Cylinders sharing the load (1 or 2).** A sidebar switch (visible in every view)
sets how many cylinders share the wall equally — a normal setup uses **2**, one
near each end. The geometry is identical either way; with 2 cylinders each carries
**half**, so **every force and bore size shown becomes per cylinder** (the reverse
view's max wall mass doubles instead). A banner at the top of each view states the
count. This keeps things consistent: peak force (N/kg) × mass = the per-cylinder
total force.

---

## Designer — try a geometry, see what it needs

1. Pick the **container** (Standard or High-Cube) and set the weight (x_cg, z_cg).
   Container sizes are the **internal (clear) dimensions** — the usable space *inside*
   the shell (Standard ≈ 2.35 × 2.39 m, High-Cube ≈ 2.35 × 2.70 m), not the outer ISO
   box — because the wall panel spans the clear opening and the moving parts must clear
   the *internal* roof. The diagram draws the steel shell (grey) around this clear
   interior so you can see the wall thickness. A **Keep base and bracket within half
   the container** toggle (on by default, in every view; in the Designer it lives in the
   Geometry tab) caps both the cylinder base `a` **and** the bracket offset `d` at half
   the width — so the base stays in the near half of the floor and the attachment stays
   in the near half at full lift (the usual layout with a cylinder near each end); a
   caption shows the exact active limits. Uncheck it to let `a` and `d` use the full
   width. (Browse's precomputed table only covers up to half-width, so unlock wider
   layouts in the Designer.)
2. Drag or type the four geometry values (a, b, d, f). The **diagram** — looking
   down the container's long axis, the wall swinging up from flat — shows the
   layout, and the **plots** show force and cylinder length across the full swing.
3. Watch the **metrics**: *Peak force* is the worst-case push the cylinder must
   provide (per kg) — the number you want to make small. Set the **Wall + load
   mass** slider and the **total-force bar** below the metrics shows the real
   cylinder force in kN.
4. Press **Optimize** and the tool finds the a, b, d, f that minimize peak force
   for your setup, and lists a few near-optimal alternatives you can click to load.

**Sensitivity — which dimension moves the result most, and how much better or worse
each spot is.** Two aligned charts below the plots, for your *current* design. A
**Color by** toggle at the top switches every part of the sensitivity — these charts,
the interaction map, and the PDF — between **peak force** and **cylinder length**, so
you can chase whichever the optimizer is minimizing (lower is better for both, so
**blue = better** either way). **Top (tornado bars):** how much the peak force (or
cylinder length) swings as each of `a, b, d, f` sweeps its allowed range (others
fixed) — longer / redder = more impact overall (e.g. base height `f` usually
dominates). **Bottom (strip):** move that dimension to any position and the color is
the peak force (or length) *there* as a **percent of your current value** — so **200%
means double, 50% means half**. **White (100%) = same
as now** (the **white dot** is your current value), **red = higher (worse)**,
**blue = lower (better)**, **black = a spot the optimizer would reject** (over-center,
over your stroke ratio, through the roof, or — in Reverse — outside the cylinder's
length window). Because the black includes every rule-breaking spot, **after you
optimize there is no blue left**: nothing feasible beats where you are. So you read
straight off it *which* knob matters and exactly *how much* you'd gain or lose by
moving it — e.g. "sliding `f` to the top takes the force to ~50% of now." It's a
*local, one-at-a-time* read — each variable
swept with the others fixed at your current values (so it doesn't capture
interactions), which is why it updates as you move. Reflects your cg and mounting
limits. The same panel appears in the Browse and Reverse inspectors, for whichever
geometry you're looking at there.

**Interaction map — vary two dimensions at once.** Below the strip, two dropdowns
let you pick *two* of `a, b, d, f` to sweep together (the other two stay at your
current design), drawn as a 2-D heatmap in the same colours — % of your current
force, **black = a spot the optimizer would reject**, white dot = now. Because it
moves two knobs together it shows their **interaction**: a diagonal blue pocket is
a combined move that lowers the force in a way the one-at-a-time strip can't see
(e.g. raising `b` and `d` together). It appears in all three views, each with that
view's rules: in **Reverse** the black region is where the cylinder length falls
outside the one you entered, so the coloured band is the "ring" of geometries that
cylinder can actually drive (the length constraint is a distance, so it reads as
arcs rather than boxes).

**Optimize to minimize — force or length.** In the Optimize tab you choose what
to minimize:
- **Peak force** (default) — the smallest piston force. Best when force is the
  binding constraint, e.g. a hydraulic cylinder, where force is cheap to buy.
- **Cylinder length** — the *shortest actuator* (smallest extended length) that
  still keeps peak force at or below a limit you set. You give it as a single
  **Max cylinder force** (the biggest push your actuator can provide, per cylinder,
  in kN / lbf); the optimizer divides that by your **Setup wall + load mass** to get
  the per-kg budget it holds the peak force under (shown as a caption). So the max
  force and the mass fold into one limit, and a heavier wall spends that budget
  faster. Best when physical size is what costs — e.g. an **electromechanical
  actuator**, where you pay most for force/size.

These pull toward different geometries because the work to raise the wall is
fixed: **lower force ⇒ longer stroke, and a shorter cylinder ⇒ more force.** If no
geometry meets the force cap, the result is flagged not-buildable — raise the cap
until one qualifies.

Extras: switch **units** (Imperial / Metric) — one toggle flips *every* readout
together (lengths, mass, force, the peak-force metric, pressure, and bore), turn on
**Fine precision** for smaller steps,
**lock** any value so Optimize holds it fixed, and use **Compare** to save two
designs (A/B) and overlay them on the plots. **Export design (PDF)** downloads a
one-page spec sheet for the current design — inputs, geometry, forces, bore &
pressure, the diagram, the curves, the two sensitivity charts, and (Designer only)
the full **interaction matrix** — all six variable pairs at once, so the sheet is
self-contained rather than tied to whichever pair was selected on screen. The
Designer's URL captures your setup, so you can copy the link to share an exact
configuration.

---

## Browse configurations — search a ready-made database

Instead of optimizing, this searches a **precomputed database** of geometries —
instant results, no waiting.

1. Set your **Problem** (container, x_cg, z_cg, stroke ratio, roof clearance) and
   the **Mounting limits** (the min–max range each of a, b, d, f may occupy).
2. The table lists every matching geometry, **best (lowest peak force) first**.
   The **Peak force** column is shaded **green (low / good) → red (high / bad)**
   so you can eyeball quality at a glance. The count above the table shows how
   many configurations match — it responds to every filter you change.
   - **Sort by any column** and, within each group of equal values (e.g. all the
     rows with a = 0.05), the lowest-force design is listed first — and the column
     you sorted by jumps to just right of Peak force so you can read the pair
     together (it's added automatically even if you hadn't ticked it in *Columns to
     show*). **Max rows per sorted value** caps how many of each value appear
     (default 20), so one value (like f = 0) can't flood the list — you see the
     best few at each value and a wide spread of values instead.
3. Click a row's **rank** to inspect it: its exact diagram (scrub the view angle),
   force curve, length curve, and — from the **Wall + load mass** slider — its
   **total cylinder force** in kN. The inspector carries the same tools as the
   Designer: the **cylinder sizing (bore & pressure)** card, the **sensitivity**
   panel (which dimension moves the force most, and where), and **Export design
   (PDF)** for a one-page spec sheet of that configuration.
4. The database is a grid, so its best row is only *near*-optimal. Press
   **Get the exact optimum** to run the optimizer once for your settings and get
   the true best geometry (and see how far the grid was off).

---

## Size from a cylinder — the reverse

Have a specific hydraulic cylinder in mind? This works backwards: you enter the
cylinder, and it finds the best geometry and the **biggest wall it can raise**.

1. Pick your **units** (Imperial or Metric) with the toggle at the top — it
   converts the cylinder inputs in place, so you can enter specs in whichever the
   datasheet uses. The wall geometry itself always stays in meters.
2. Enter the cylinder's **force** — either bore + rod diameter + max pressure
   (psi / bar), or a rated push force (lbf / kN) — plus a **safety factor**.
3. Enter the cylinder's **length** — closed (retracted) length + stroke (in / mm).
   It shows the extended length. This is a **hard constraint** — the geometry's
   cylinder length must stay inside [closed, extended] the whole way up.
4. Set the **wall** (container, cg) and, optionally, **restrict the output
   geometry** (a, b, d, f ranges) — e.g. keep the base height f low.
5. It reports two mass numbers — the **safe max wall mass** (your force ÷ safety
   factor) and the **absolute cylinder max** (flat-out, no margin) — plus the
   best-fitting geometry and the setup diagram + plots. Use the safe one. Below the
   plots it also shows the **sensitivity** panel for that geometry and an **Export
   design (PDF)** — a one-page sizing sheet pairing the cylinder you entered with
   the geometry it sized. (There's no bore-sizing card here: the cylinder is the
   input, not an output.)

Because the length window and geometry limits are hard constraints, **some
cylinders simply won't fit any wall** — when that happens it says so and tells
you the length range that *would* work (so you know whether to pick a longer
stroke, a different retracted length, or a bigger container).

---

## Reading the results

- **Peak force (N/kg)** — piston force per kg of wall+load. **Lower is better.**
- **Wall + load mass (kg)** — set this (drag or type) and the **total-force bar**
  does the multiplication for you: the real cylinder force in **kN**. It's in
  both the Designer and Browse.
- **Stroke / stroke ratio** — how much the cylinder extends; keep the ratio under
  your limit so a real cylinder can do it.
- **Cylinder sizing — bore & pressure** (Designer & Browse inspector) — turns the total force into an
  actual cylinder. Pick a **bore standard** (ISO metric, NFPA inch, or exact) and
  a **design pressure**; it shows the **required bore** — the barrel's inner
  diameter (`bore = √(4·force / π·pressure)`,
  full-bore *push* area, since raising the wall extends the cylinder), rounds up to
  the **next standard size**, and reports the **pressure that size actually needs**
  and how far that sits below your design pressure (headroom). If the force needs a
  bore bigger than the largest standard, it says so — raise the pressure or split
  the load across two cylinders.
- **Green→red shading** (Browse) — relative to the results shown: greenest is the
  lowest force in the list, reddest the highest. Nearly-equal forces get
  nearly-identical colors.

---

## Where to run it

- **Streamlit:** `streamlit run app.py` (or the Streamlit Community Cloud deploy).
- **NiceGUI / Render:** `python nicegui_app.py` locally, or the public Render URL.

Both read the same physics core, so results match. For the engineering details
and deployment specifics, see the main `README.md`.
