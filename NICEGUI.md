# NiceGUI front-end

A parallel, snappier UI (`nicegui_app.py`) for the actuator tool. Same physics
and optimizer as the Streamlit app — it imports the shared `wall.py` /
`optimize.py` — just a different interface. **The Streamlit app is untouched**;
this has its own dependency file (`requirements-nicegui.txt`).

---

## Run it locally

```bash
pip install -r requirements-nicegui.txt
python nicegui_app.py
```

Then open **http://localhost:8080** in your browser. Stop with `Ctrl+C`.

(If port 8080 is busy: `PORT=8090 python nicegui_app.py`, then use that port.)

---

## Put it online (public URL anyone can open)

NiceGUI is a normal web server, so — unlike Streamlit Community Cloud — you host
it yourself. The easiest free option is **Render.com**; a `render.yaml` in this
repo makes it near one-click.

1. Make sure this repo is on GitHub (it is: `phynder21/wall_hydraulics`).
2. Create a free account at **https://render.com** and connect your GitHub.
3. **New +  →  Blueprint**, pick this repo. Render reads `render.yaml`, builds
   with `requirements-nicegui.txt`, and starts `python nicegui_app.py`.
   *(Or **New + → Web Service** and set Build = `pip install -r requirements-nicegui.txt`,
   Start = `python nicegui_app.py`, Plan = Free.)*
4. Click **Deploy**. In ~2–3 minutes you get a **public HTTPS URL** like
   **`https://wall-actuator.onrender.com`** — share it with anyone; no login
   needed to view.

**Notes**
- The app binds to `0.0.0.0` and reads Render's `PORT` env var automatically.
- The **free** plan **sleeps when idle**, so the first visit after a quiet spell
  takes ~30–60 s to wake (same behavior as Streamlit's free tier). A paid plan
  ($7/mo) stays always-on.
- Other hosts work the same way (Railway, Fly.io, a VPS, Docker) — any place that
  can run `python nicegui_app.py` and expose a port.

### Quick temporary share (no hosting)
For a throwaway link that tunnels to your own machine while it runs, change the
last line of `nicegui_app.py` to `ui.run(..., on_air=True)` and run it — NiceGUI
prints a temporary `https://…on-air.nicegui.io` URL. Good for a quick demo; your
machine must stay on, so it's not a substitute for hosting.

---

## Keeping the two UIs in sync

The core (`wall.py`, `optimize.py`, `lookup.py`, `lookup_build.py`) is shared and
UI-agnostic, so **logic changes land in one place and both UIs get them**. Only
UI-specific changes (a new control, a layout tweak) are done in both `app.py`
(Streamlit) and `nicegui_app.py`. The pure figure/metric builders in
`nicegui_app.py` are covered by `tests/test_nicegui.py`.
