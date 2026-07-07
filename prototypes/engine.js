/* Shared physics + rendering engine for the UI prototypes.
   Each HTML shell provides elements with these ids and styles the SVG classes:
   inputs  : #container #a #b #d #f #xcg #zcg #theta
   labels  : #va #vb #vd #vf #vxcg #vzcg #vtheta
   metrics : #mPeak #mHere #mStroke #mRatio #mRatioTag
   svgs    : #diagram #spark        button: #optimize   (optional #optmsg)
   svg classes: ground cont door brkt post cyl hinge cbase att cg grav fline mk */
(function () {
  const G = 9.81, F_CAP = 50;
  const CON = { "Standard": [2.438, 2.591], "High-Cube": [2.438, 2.896] };
  const S = { container: "Standard", a: 0.60, b: 1.80, d: 0.10, f: 0.40,
              xcg: 1.20, zcg: 0.55, theta: 45 };
  const $ = id => document.getElementById(id);

  function force(th, a, b, d, f, xcg, zcg) {
    const c = Math.cos(th), s = Math.sin(th);
    const xatt = b * c - d * s, zatt = b * s + d * c, xcgw = xcg * c - zcg * s;
    const ratt = Math.hypot(b, d);
    const beta = Math.atan2(zatt, xatt), phi = Math.atan2(zatt - f, xatt + a);
    return -(G * xcgw) / (ratt * Math.sin(beta - phi));       // per kg of load
  }
  function clen(th, a, b, d, f) {
    const c = Math.cos(th), s = Math.sin(th);
    return Math.hypot(b * c - d * s + a, b * s + d * c - f);
  }
  function metrics(a, b, d, f, xcg, zcg) {
    const N = 121, Fs = [], Ls = [];
    for (let i = 0; i < N; i++) {
      const th = Math.PI / 2 * i / (N - 1);
      Fs.push(force(th, a, b, d, f, xcg, zcg));
      Ls.push(clen(th, a, b, d, f));
    }
    const fin = Fs.filter(v => isFinite(v) && Math.abs(v) <= F_CAP);
    const Lmin = Math.min(...Ls), Lmax = Math.max(...Ls);
    return {
      peak: fin.length ? Math.max(...fin.map(Math.abs)) : NaN,
      here: force(S.theta * Math.PI / 180, a, b, d, f, xcg, zcg),
      stroke: Lmax - Lmin, ratio: Lmax / Lmin, Fs, N,
      singular: fin.length < Fs.length
    };
  }

  function diagram() {
    const [W, H] = CON[S.container], PW = 560, PH = 440, pad = 18;
    const xmin = -W - 0.4, xmax = H + 0.4, zmin = -0.4, zmax = H + 0.4;
    const sc = Math.min((PW - 2 * pad) / (xmax - xmin), (PH - 2 * pad) / (zmax - zmin));
    const M = (x, z) => [(pad + (x - xmin) * sc).toFixed(1), (PH - pad - (z - zmin) * sc).toFixed(1)];
    const th = S.theta * Math.PI / 180, { a, b, d, f, xcg, zcg } = S;
    const c = Math.cos(th), s = Math.sin(th);
    const att = [b * c - d * s, b * s + d * c], cgw = [xcg * c - zcg * s, xcg * s + zcg * c];
    const base = [-a, f], tip = [b * c, b * s], door = [H * c, H * s];
    const L = (p, q, cls) => `<line x1="${M(...p)[0]}" y1="${M(...p)[1]}" x2="${M(...q)[0]}" y2="${M(...q)[1]}" class="${cls}"/>`;
    const C = (p, r, cls) => `<circle cx="${M(...p)[0]}" cy="${M(...p)[1]}" r="${r}" class="${cls}"/>`;
    let g = "";
    g += L([-W - 0.4, 0], [H + 0.4, 0], "ground");
    g += `<polyline points="${M(0, 0)} ${M(-W, 0)} ${M(-W, H)} ${M(0, H)}" class="cont"/>`;
    g += L([0, 0], door, "door");
    g += L(tip, att, "brkt");
    g += L([base[0], 0], base, "post");
    g += L(base, att, "cyl");
    const a1 = M(cgw[0], cgw[1]), a2 = M(cgw[0], cgw[1] - 0.4);
    g += `<line x1="${a1[0]}" y1="${a1[1]}" x2="${a2[0]}" y2="${a2[1]}" class="grav" marker-end="url(#arw)"/>`;
    g += C([0, 0], 5, "hinge") + C(base, 5, "cbase") + C(att, 4, "att") + C(cgw, 6, "cg");
    const svg = $("diagram");
    svg.setAttribute("viewBox", `0 0 ${PW} ${PH}`);
    svg.innerHTML = `<defs><marker id="arw" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" class="grav-h"/></marker></defs>` + g;
  }

  function spark(m) {
    const PW = 560, PH = 120, pad = 8;
    const Fs = m.Fs.map(v => (isFinite(v) && Math.abs(v) <= F_CAP) ? v : null);
    const vals = Fs.filter(v => v !== null);
    const svg = $("spark");
    if (!vals.length) { svg.innerHTML = ""; return; }
    const lo = Math.min(...vals), hi = Math.max(...vals), rng = (hi - lo) || 1;
    const X = i => pad + (PW - 2 * pad) * i / (m.N - 1);
    const Y = v => PH - pad - (PH - 2 * pad) * (v - lo) / rng;
    let dd = "", pen = true;
    Fs.forEach((v, i) => { if (v === null) { pen = true; return; } dd += (pen ? "M" : "L") + X(i).toFixed(1) + " " + Y(v).toFixed(1) + " "; pen = false; });
    const ti = Math.round(S.theta / 90 * (m.N - 1)), tv = m.Fs[ti];
    const mk = isFinite(tv) ? `<circle cx="${X(ti).toFixed(1)}" cy="${Y(Math.max(lo, Math.min(hi, tv))).toFixed(1)}" r="4" class="mk"/>` : "";
    svg.setAttribute("viewBox", `0 0 ${PW} ${PH}`);
    svg.innerHTML = `<path d="${dd}" class="fline"/>${mk}`;
  }

  function set(id, txt) { const e = $(id); if (e) e.textContent = txt; }

  function render() {
    const { a, b, d, f, xcg, zcg } = S, m = metrics(a, b, d, f, xcg, zcg);
    set("va", a.toFixed(2)); set("vb", b.toFixed(2)); set("vd", d.toFixed(2));
    set("vf", f.toFixed(2)); set("vxcg", xcg.toFixed(2)); set("vzcg", zcg.toFixed(2));
    set("vtheta", S.theta.toFixed(0) + "°");
    set("mPeak", isFinite(m.peak) ? m.peak.toFixed(2) : "—");
    set("mHere", isFinite(m.here) ? m.here.toFixed(2) : "—");
    set("mStroke", m.stroke.toFixed(2)); set("mRatio", m.ratio.toFixed(2));
    set("mRatioTag", m.ratio <= 1.8 ? "within 1.8× limit" : "over 1.8× limit");
    const tag = $("mRatioTag"); if (tag) tag.dataset.ok = (m.ratio <= 1.8);
    diagram(); spark(m);
  }

  function optimize() {
    const [W, H] = CON[S.container];
    const lin = (lo, hi, n) => Array.from({ length: n }, (_, i) => lo + (hi - lo) * i / (n - 1));
    const As = lin(0.05, W / 2, 8), Bs = lin(0.05, H, 9), Ds = lin(0, 1, 6), Fz = lin(0, H, 9);
    let best = null, feas = null;
    for (const a of As) for (const b of Bs) for (const d of Ds) for (const f of Fz) {
      let Lmin = 1e9, Lmax = 0, sing = false, peak = 0, ok = true;
      for (let i = 0; i <= 40; i++) {
        const th = Math.PI / 2 * i / 40, v = force(th, a, b, d, f, S.xcg, S.zcg), l = clen(th, a, b, d, f);
        if (l < Lmin) Lmin = l; if (l > Lmax) Lmax = l;
        if (isFinite(v) && Math.abs(v) <= F_CAP) peak = Math.max(peak, Math.abs(v)); else sing = true;
      }
      if (sing) continue;
      const ratio = Lmax / Lmin;
      if (!best || peak < best.peak) best = { a, b, d, f, peak };
      if (ratio <= 1.8 && (!feas || peak < feas.peak)) feas = { a, b, d, f, peak };
    }
    const p = feas || best; if (!p) return;
    S.a = +p.a.toFixed(2); S.b = +p.b.toFixed(2); S.d = +p.d.toFixed(2); S.f = +p.f.toFixed(2);
    ["a", "b", "d", "f"].forEach(k => { const el = $(k); if (el) el.value = S[k]; });
    set("optmsg", `Optimized — peak ${p.peak.toFixed(2)} N/kg`);
    render();
  }

  function wire() {
    const sel = $("container");
    if (sel) { sel.value = S.container; sel.onchange = e => { S.container = e.target.value; render(); }; }
    [["a", "a"], ["b", "b"], ["d", "d"], ["f", "f"], ["xcg", "xcg"], ["zcg", "zcg"], ["theta", "theta"]]
      .forEach(([id, k]) => { const el = $(id); if (!el) return; el.value = S[k]; el.oninput = e => { S[k] = parseFloat(e.target.value); render(); }; });
    const ob = $("optimize"); if (ob) ob.onclick = optimize;
    render();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
  else wire();
})();
