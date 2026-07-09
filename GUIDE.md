# Container Wall Actuator — Quick Guide

A tool for sizing the **hydraulic cylinder that raises and lowers a hinged
shipping-container sidewall**. You describe the wall and where the cylinder can
mount; the tool finds the geometry that needs the **least piston force** — so you
can spec a smaller, cheaper cylinder.

There are two apps with the same engine: a Streamlit version and a NiceGUI
version (deployed on Render). Both have the same two views.

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

---

## 🛠 Designer — try a geometry, see what it needs

1. Pick the **container** (Standard or High-Cube) and set the weight (x_cg, z_cg).
2. Drag or type the four geometry values (a, b, d, f). The **diagram** shows the
   layout and the **plots** show force and cylinder length across the full swing.
3. Watch the **metrics**: *Peak force* is the worst-case push the cylinder must
   provide (per kg) — the number you want to make small. Set the **Wall + load
   mass** slider and the **total-force bar** below the metrics shows the real
   cylinder force in kN.
4. Press **Optimize** and the tool finds the a, b, d, f that minimize peak force
   for your setup, and lists a few near-optimal alternatives you can click to load.

Extras: switch **units** (m / in), turn on **Fine precision** for smaller steps,
🔒 **lock** any value so Optimize holds it fixed, and use **Compare** to save two
designs (A/B) and overlay them on the plots. The Designer's URL captures your
setup, so you can copy the link to share an exact configuration.

---

## 🔎 Browse configurations — search a ready-made database

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
     together. **Max rows per sorted value** caps how many of each value appear
     (default 20), so one value (like f = 0) can't flood the list — you see the
     best few at each value and a wide spread of values instead.
3. Click a row's **rank** to inspect it: its exact diagram (scrub the view angle),
   force curve, length curve, and — from the **Wall + load mass** slider — its
   **total cylinder force** in kN.
4. The database is a grid, so its best row is only *near*-optimal. Press
   **Get the exact optimum** to run the optimizer once for your settings and get
   the true best geometry (and see how far the grid was off).

---

## Reading the results

- **Peak force (N/kg)** — piston force per kg of wall+load. **Lower is better.**
- **Wall + load mass (kg)** — set this (drag or type) and the **total-force bar**
  does the multiplication for you: the real cylinder force in **kN**. It's in
  both the Designer and Browse.
- **Stroke / stroke ratio** — how much the cylinder extends; keep the ratio under
  your limit so a real cylinder can do it.
- **Green→red shading** (Browse) — relative to the results shown: greenest is the
  lowest force in the list, reddest the highest. Nearly-equal forces get
  nearly-identical colors.

---

## Where to run it

- **Streamlit:** `streamlit run app.py` (or the Streamlit Community Cloud deploy).
- **NiceGUI / Render:** `python nicegui_app.py` locally, or the public Render URL.

Both read the same physics core, so results match. For the engineering details
and deployment specifics, see the main `README.md`.
