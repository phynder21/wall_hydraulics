# Container Wall Actuator — Quick Guide

A tool for sizing the **hydraulic cylinder that raises and lowers a hinged
shipping-container sidewall**. You describe the wall and where the cylinder can
mount; the tool finds the geometry that needs the **least piston force** — so you
can spec a smaller, cheaper cylinder.

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
2. Drag or type the four geometry values (a, b, d, f). The **diagram** — looking
   down the container's long axis, the wall swinging up from flat — shows the
   layout, and the **plots** show force and cylinder length across the full swing.
3. Watch the **metrics**: *Peak force* is the worst-case push the cylinder must
   provide (per kg) — the number you want to make small. Set the **Wall + load
   mass** slider and the **total-force bar** below the metrics shows the real
   cylinder force in kN.
4. Press **Optimize** and the tool finds the a, b, d, f that minimize peak force
   for your setup, and lists a few near-optimal alternatives you can click to load.

**Optimize to minimize — force or length.** In the Optimize tab you choose what
to minimize:
- **Peak force** (default) — the smallest piston force. Best when force is the
  binding constraint, e.g. a hydraulic cylinder, where force is cheap to buy.
- **Cylinder length** — the *shortest actuator* (smallest extended length) that
  still keeps peak force at or below a **Max piston force (N/kg)** cap you set.
  The cap is in N/kg — the same unit as the Peak force metric — so it depends only
  on geometry, not mass. A **Wall + load mass** slider (kept in sync with Setup)
  sits alongside it and shows the cap as a real force in **kN**. Best when physical
  size is what costs — e.g. an **electromechanical actuator**, where you pay most
  for force/size.

These pull toward different geometries because the work to raise the wall is
fixed: **lower force ⇒ longer stroke, and a shorter cylinder ⇒ more force.** If no
geometry meets the force cap, the result is flagged not-buildable — raise the cap
until one qualifies.

Extras: switch **units** (m / in), turn on **Fine precision** for smaller steps,
**lock** any value so Optimize holds it fixed, and use **Compare** to save two
designs (A/B) and overlay them on the plots. **Export design (PDF)** downloads a
one-page spec sheet for the current design — inputs, geometry, forces, bore &
pressure, the diagram, and the curves. The Designer's URL captures your setup, so
you can copy the link to share an exact configuration.

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
   **total cylinder force** in kN.
4. The database is a grid, so its best row is only *near*-optimal. Press
   **Get the exact optimum** to run the optimizer once for your settings and get
   the true best geometry (and see how far the grid was off).

---

## Size from a cylinder — the reverse

Have a specific hydraulic cylinder in mind? This works backwards: you enter the
cylinder, and it finds the best geometry and the **biggest wall it can raise**.

1. Pick your **units** (Imperial or Metric) with the toggle at the top — it
   converts the cylinder inputs in place, so you can enter specs in whichever the
   datasheet uses. The wall geometry itself always stays in metres.
2. Enter the cylinder's **force** — either bore + rod diameter + max pressure
   (psi / bar), or a rated push force (lbf / kN) — plus a **safety factor**.
3. Enter the cylinder's **length** — closed (retracted) length + stroke (in / mm).
   It shows the extended length. This is a **hard constraint** — the geometry's
   cylinder length must stay inside [closed, extended] the whole way up.
4. Set the **wall** (container, cg) and, optionally, **restrict the output
   geometry** (a, b, d, f ranges) — e.g. keep the base height f low.
5. It reports two mass numbers — the **safe max wall mass** (your force ÷ safety
   factor) and the **absolute cylinder max** (flat-out, no margin) — plus the
   best-fitting geometry and the setup diagram + plots. Use the safe one.

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
- **Cylinder sizing — bore & pressure** (Designer) — turns the total force into an
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
