/*
 * PDF editor UI: open, read, find, edit existing text, add text, draw, highlight,
 * white-out, rotate / reorder / delete / add pages, and save a new PDF.
 * pdf.js renders the pages and pdf-lib writes the result; both are bundled in vendor/.
 */
(function () {
  "use strict";
  const C = window.PdfEditCore;
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const SVGNS = "http://www.w3.org/2000/svg";
  const BASELINE = { Helvetica: 0.95, Times: 0.94, Courier: 0.87 }; // CSS baseline offset at line-height 1.2
  const hexToRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const rgbToHex = (c) => "#" + c.map((v) => Math.round(v * 255).toString(16).padStart(2, "0")).join("");
  const css = (c, o = 1) => `rgb(${c.map((v) => Math.round(v * 255)).join(" ")} / ${o})`;

  const TOOLS = [
    ["read", "Read", "Scroll and read. Nothing changes."],
    ["edit", "Edit text", "Tap a line of text to rewrite it."],
    ["text", "Add text", "Tap where the new text should go."],
    ["draw", "Draw / sign", "Draw with your finger."],
    ["highlight", "Highlight", "Tap a line or drag over an area."],
    ["whiteout", "White-out", "Drag over anything to cover it."],
    ["erase", "Erase edit", "Tap one of your edits to remove it."],
  ];

  const E = {
    deps: null,
    root: null,
    sources: [], // { name, bytes, pdf (pdf.js doc), pageCache: [] }
    pages: [],
    name: "",
    dirty: false,
    tool: "read",
    zoom: 1,
    history: [],
    future: [],
    selected: null, // { pi, ai }
    editing: null, // { pi, ai, ta }
    style: { font: "Helvetica", size: 12, bold: false, color: "#000000" },
    pen: { color: "#1a3fd6", width: 2 },
    find: { q: "", hits: [], i: -1 },
    textCache: new Map(), // "src:index" -> textContent
    sheets: [], // per page { el, sheet, canvas, svg, layer, vp, rendered, task }
    observer: null,
    lastFinish: 0,
    findOpen: false,
    renderToken: 0,
  };

  // ------------------------------------------------------------ loading
  async function loadSource(name, bytes) {
    const task = pdfjsLib.getDocument({ data: bytes.slice(), isEvalSupported: false });
    let skipped = false;
    task.onPassword = async (update, reason) => {
      const pw = await E.deps.askPassword(name, reason === pdfjsLib.PasswordResponses.INCORRECT_PASSWORD);
      if (pw == null) { skipped = true; task.destroy(); } else update(pw);
    };
    try {
      const pdf = await task.promise;
      return { name, bytes, pdf, pageCache: [] };
    } catch (e) {
      if (skipped) return null;
      throw e;
    }
  }

  function pdfPage(src, index) {
    const s = E.sources[src];
    return s.pageCache[index] || (s.pageCache[index] = s.pdf.getPage(index + 1));
  }

  async function geometry(p) {
    if (p.src == null) return { view: [0, 0, p.size[0], p.size[1]], base: 0 };
    const pg = await pdfPage(p.src, p.index);
    return { view: pg.view, base: pg.rotate, pg };
  }

  async function openFiles(files) {
    if (!files.length) return;
    if (E.dirty && !(await E.deps.confirm("Open another PDF? Your unsaved changes to this one will be lost.", "Open"))) return;
    const f = files[0];
    E.deps.busy(`Opening <b>${esc(f.name)}</b>…`);
    try {
      const bytes = f.bytes || new Uint8Array(await f.arrayBuffer());
      const src = await loadSource(f.name, bytes);
      if (!src) { E.deps.busy(""); return; }
      closeDoc(true);
      E.sources = [src];
      E.name = f.name.replace(/\.pdf$/i, "");
      E.pages = Array.from({ length: src.pdf.numPages }, (_, i) => ({ src: 0, index: i, rotate: 0, annots: [] }));
      E.deps.busy("");
      render();
      if (files.length > 1) await addPdfPages(files.slice(1), true);
    } catch (e) {
      E.deps.busy(`Couldn't open <b>${esc(f.name)}</b>: ${esc(e && e.message ? e.message : e)}`, "err");
    }
  }

  async function addPdfPages(files, quiet) {
    for (const f of files) {
      try {
        const bytes = f.bytes || new Uint8Array(await f.arrayBuffer());
        const src = await loadSource(f.name, bytes);
        if (!src) continue;
        pushHistory();
        const n = E.sources.push(src) - 1;
        for (let i = 0; i < src.pdf.numPages; i++) E.pages.push({ src: n, index: i, rotate: 0, annots: [] });
        if (!quiet) E.deps.toast(`Added ${src.pdf.numPages} page(s) from ${f.name}`);
      } catch (e) {
        E.deps.toast(`Couldn't add ${f.name}: ${e.message}`);
      }
    }
    render();
  }

  function closeDoc(silent) {
    for (const s of E.sources) { try { s.pdf.destroy(); } catch {} }
    E.sources = []; E.pages = []; E.history = []; E.future = []; E.dirty = false;
    E.selected = null; E.editing = null; E.find = { q: "", hits: [], i: -1 }; E.textCache.clear();
    if (!silent) render();
  }

  // ------------------------------------------------------------ history
  function pushHistory() {
    E.history.push(JSON.stringify(E.pages));
    if (E.history.length > 100) E.history.shift();
    E.future = [];
    E.dirty = true;
  }
  const structure = () => E.pages.map((p) => `${p.src}:${p.index}:${p.rotate}`).join("|");
  function restore(json) {
    const before = structure();
    E.pages = JSON.parse(json);
    E.selected = null;
    E.dirty = true;
    if (structure() !== before) renderPages(); else E.pages.forEach((_, i) => drawOverlay(i));
    renderBar();
  }
  function undo() { if (!E.history.length) return; finishEditing(); E.future.push(JSON.stringify(E.pages)); restore(E.history.pop()); }
  function redo() { if (!E.future.length) return; finishEditing(); E.history.push(JSON.stringify(E.pages)); restore(E.future.pop()); }

  // ------------------------------------------------------------ layout
  function render() {
    const root = E.root;
    if (!E.pages.length) {
      E.observer && E.observer.disconnect();
      E.sheets = [];
      root.innerHTML = `
        <div class="ed-empty">
          <svg width="44" height="44" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2h8l5 5v15H6z M14 2v5h5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M9 13h7M9 16h7M9 19h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <h2>Open a PDF to read or edit</h2>
          <p class="muted">Read any PDF, rewrite its text, add text, sign, highlight, cover up details, rotate, reorder,
            delete or add pages, then save it as a new PDF. Everything happens on this device.</p>
          <label class="btn primary file-btn" for="ed-open-empty">Open PDF<input id="ed-open-empty" type="file" accept="application/pdf,.pdf" multiple></label>
          <ul class="help small">
            <li>On Android, choose <b>Open with → BRB PDF</b> from Files, Drive or Gmail to open a PDF straight here.</li>
            <li>Password-protected PDFs ask for their password.</li>
            <li>Editing changes a copy: tap <b>Save PDF</b> to keep it.</li>
          </ul>
        </div>`;
      $("#ed-open-empty").onchange = (e) => { const f = [...e.target.files]; e.target.value = ""; openFiles(f); };
      return;
    }
    root.innerHTML = `
      <div class="ed-bar" id="ed-bar"></div>
      <div class="ed-pages" id="ed-pages"></div>
      <input id="ed-open" type="file" accept="application/pdf,.pdf" multiple hidden>
      <input id="ed-add" type="file" accept="application/pdf,.pdf" multiple hidden>`;
    $("#ed-open").onchange = (e) => { const f = [...e.target.files]; e.target.value = ""; openFiles(f); };
    $("#ed-add").onchange = (e) => { const f = [...e.target.files]; e.target.value = ""; addPdfPages(f); };
    renderBar();
    renderPages();
  }

  function renderBar() {
    const bar = $("#ed-bar");
    if (!bar) return;
    const sel = selectedAnnot();
    const textCtx = E.tool === "text" || E.tool === "edit" || (sel && sel.type === "text");
    const st = sel && sel.type === "text" ? { font: sel.font, size: sel.size, bold: sel.bold, color: rgbToHex(sel.color) } : E.style;
    const tip = TOOLS.find((t) => t[0] === E.tool)[2];
    bar.innerHTML = `
      <div class="ed-row">
        <input class="ed-name" id="ed-name" value="${esc(E.name)}" aria-label="File name" spellcheck="false">
        <button class="btn quiet ed-icon" id="ed-undo" ${E.history.length ? "" : "disabled"} title="Undo" aria-label="Undo">↶</button>
        <button class="btn quiet ed-icon" id="ed-redo" ${E.future.length ? "" : "disabled"} title="Redo" aria-label="Redo">↷</button>
        <button class="btn quiet ed-icon" id="ed-find-t" aria-pressed="${E.findOpen}" title="Find text" aria-label="Find text">
          <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M13 13l5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        </button>
        <button class="btn primary" id="ed-save">Save PDF</button>
        <details class="ed-menu">
          <summary class="btn ed-icon" aria-label="More actions">⋯</summary>
          <div class="ed-menu-list">
            <p class="small muted" style="padding:4px 8px">${E.pages.length} page${E.pages.length === 1 ? "" : "s"}${E.dirty ? " · not saved yet" : ""}</p>
            <button class="btn quiet" data-m="open">Open another PDF</button>
            <button class="btn quiet" data-m="add">Add pages from a PDF</button>
            <button class="btn quiet" data-m="blank">Add a blank page</button>
            <button class="btn quiet" data-m="analyze">Read as bank statement</button>
            <button class="btn quiet danger" data-m="close">Close PDF</button>
          </div>
        </details>
      </div>
      ${E.findOpen ? `
      <form class="ed-row ed-find" id="ed-find">
        <input id="ed-find-q" type="search" placeholder="Find text" value="${esc(E.find.q)}" aria-label="Find text" enterkeyhint="search">
        <span class="small muted num" id="ed-find-n">${E.find.q ? (E.find.hits.length ? `${E.find.i + 1}/${E.find.hits.length}` : "0") : ""}</span>
        <button class="btn quiet ed-icon" type="button" id="ed-find-prev" aria-label="Previous match" ${E.find.hits.length ? "" : "disabled"}>↑</button>
        <button class="btn quiet ed-icon" type="submit" aria-label="Next match">↓</button>
      </form>` : ""}
      <div class="ed-row ed-tools" role="toolbar" aria-label="Tools">
        ${TOOLS.map(([k, label]) => `<button class="ed-tool" data-tool="${k}" aria-pressed="${E.tool === k}">${label}</button>`).join("")}
      </div>
      ${textCtx ? `
      <div class="ed-row ed-props">
        <select id="ed-font" aria-label="Font">${["Helvetica", "Times", "Courier"].map((f) => `<option ${st.font === f ? "selected" : ""}>${f}</option>`).join("")}</select>
        <input id="ed-size" type="number" min="4" max="96" step="0.5" value="${+st.size.toFixed(1)}" aria-label="Font size">
        <button class="ed-tool" id="ed-bold" aria-pressed="${!!st.bold}" aria-label="Bold"><b>B</b></button>
        <input id="ed-color" type="color" value="${st.color}" aria-label="Text colour">
        ${sel ? `<button class="btn quiet danger" id="ed-del">Delete</button>` : ""}
      </div>` : ""}
      ${E.tool === "draw" ? `
      <div class="ed-row ed-props">
        <input id="ed-pen" type="color" value="${E.pen.color}" aria-label="Pen colour">
        <label class="small">Width <input id="ed-penw" type="range" min="0.5" max="8" step="0.5" value="${E.pen.width}"></label>
      </div>` : ""}
      ${E.tool !== "read" ? `<p class="small muted ed-tip">${tip}</p>` : ""}`;
    let zoom = $("#ed-zoombox");
    if (!zoom) {
      zoom = document.createElement("div");
      zoom.className = "ed-zoom";
      zoom.id = "ed-zoombox";
      zoom.innerHTML = `<button class="btn quiet" id="ed-zout" aria-label="Zoom out">−</button>
        <button class="btn quiet num" id="ed-zfit" title="Fit width"></button>
        <button class="btn quiet" id="ed-zin" aria-label="Zoom in">+</button>`;
      E.root.appendChild(zoom);
      $("#ed-zin").onclick = () => setZoom(E.zoom * 1.25);
      $("#ed-zout").onclick = () => setZoom(E.zoom / 1.25);
      $("#ed-zfit").onclick = () => setZoom(1);
    }
    $("#ed-zfit").textContent = Math.round(E.zoom * 100) + "%";

    $("#ed-name").onchange = (e) => { E.name = e.target.value.trim() || "document"; };
    $("#ed-undo").onclick = undo;
    $("#ed-redo").onclick = redo;
    $("#ed-save").onclick = save;
    bar.querySelectorAll("[data-tool]").forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
    bar.querySelectorAll("[data-m]").forEach((b) => (b.onclick = () => { b.closest("details").open = false; menu(b.dataset.m); }));
    $("#ed-find-t").onclick = () => {
      E.findOpen = !E.findOpen;
      if (!E.findOpen) { const h = E.find.hits[E.find.i]; E.find = { q: "", hits: [], i: -1 }; if (h) drawOverlay(h.pi); }
      renderBar();
      if (E.findOpen) $("#ed-find-q").focus();
    };
    if (E.findOpen) {
      $("#ed-find").onsubmit = (e) => { e.preventDefault(); find(1); };
      $("#ed-find-prev").onclick = () => find(-1);
    }
    if (textCtx) {
      const apply = (k, v) => {
        E.style[k] = v;
        const a = selectedAnnot();
        if (a && a.type === "text") {
          pushHistory();
          if (k === "color") a.color = hexToRgb(v); else a[k] = v;
          if (E.editing && E.editing.ta) {
            styleInput(E.editing.ta, a, E.sheets[E.editing.pi].vp);
            E.editing.fit();
            E.editing.before = JSON.stringify(a);
          } else drawOverlay(E.selected.pi);
        }
      };
      $("#ed-font").onchange = (e) => apply("font", e.target.value);
      $("#ed-size").onchange = (e) => { const v = Math.min(96, Math.max(4, Number(e.target.value) || 12)); apply("size", v); };
      $("#ed-bold").onclick = (e) => { const next = e.currentTarget.getAttribute("aria-pressed") !== "true"; apply("bold", next); e.currentTarget.setAttribute("aria-pressed", String(next)); };
      $("#ed-color").onchange = (e) => apply("color", e.target.value);
      const del = $("#ed-del");
      if (del) del.onclick = () => { const { pi, ai } = E.selected; pushHistory(); E.pages[pi].annots.splice(ai, 1); E.selected = null; drawOverlay(pi); renderBar(); };
    }
    if (E.tool === "draw") {
      $("#ed-pen").onchange = (e) => (E.pen.color = e.target.value);
      $("#ed-penw").onchange = (e) => (E.pen.width = Number(e.target.value));
    }
  }

  function setTool(t) {
    finishEditing();
    E.tool = t;
    E.selected = null;
    E.root.dataset.tool = t;
    renderBar();
    E.pages.forEach((_, i) => drawOverlay(i));
  }

  function setZoom(z) {
    finishEditing();
    E.zoom = Math.min(4, Math.max(0.4, z));
    // Keep the page you are looking at in view.
    const box = $("#ed-pages");
    const atPage = currentPageIndex();
    renderPages();
    renderBar();
    const s = E.sheets[atPage];
    if (s && box) s.el.scrollIntoView({ block: "start" });
  }

  function currentPageIndex() {
    let best = 0;
    for (let i = 0; i < E.sheets.length; i++) {
      const r = E.sheets[i].el.getBoundingClientRect();
      if (r.top < window.innerHeight / 2) best = i;
    }
    return best;
  }

  async function renderPages() {
    const box = $("#ed-pages");
    if (!box) return;
    const token = ++E.renderToken;
    E.observer && E.observer.disconnect();
    for (const s of E.sheets) { try { s.task && s.task.cancel(); } catch {} }
    E.sheets = [];
    box.innerHTML = "";
    E.root.dataset.tool = E.tool;
    const avail = Math.max(240, (box.clientWidth || E.root.clientWidth || 360) - 2);
    E.observer = new IntersectionObserver((entries) => {
      for (const en of entries) if (en.isIntersecting) paint(Number(en.target.dataset.pi));
    }, { rootMargin: "600px 0px" });

    const geos = await Promise.all(E.pages.map(geometry));
    if (token !== E.renderToken || box !== $("#ed-pages")) return;
    E.pages.forEach((p, pi) => {
      const g = geos[pi];
      const unit = C.viewport(g.view, 1, g.base + p.rotate);
      const vp = C.viewport(g.view, (avail / unit.width) * E.zoom, g.base + p.rotate);
      const el = document.createElement("div");
      el.className = "ed-page";
      el.innerHTML = `
        <div class="ed-page-head">
          <span class="num small">Page ${pi + 1} of ${E.pages.length}</span>
          <span style="flex:1"></span>
          <button class="btn quiet" data-a="copy" title="Copy this page's text">Copy text</button>
          <button class="btn quiet" data-a="up" ${pi ? "" : "disabled"} aria-label="Move page up">↑</button>
          <button class="btn quiet" data-a="down" ${pi < E.pages.length - 1 ? "" : "disabled"} aria-label="Move page down">↓</button>
          <button class="btn quiet" data-a="rot" aria-label="Rotate page">⟳</button>
          <button class="btn quiet danger" data-a="del" ${E.pages.length > 1 ? "" : "disabled"} aria-label="Delete page">✕</button>
        </div>
        <div class="ed-sheet" data-pi="${pi}" style="width:${vp.width}px;height:${vp.height}px">
          <canvas></canvas>
          <svg class="ed-svg" width="${vp.width}" height="${vp.height}"></svg>
          <div class="ed-layer"></div>
        </div>`;
      box.appendChild(el);
      const sheet = $(".ed-sheet", el);
      E.sheets[pi] = { el, sheet, canvas: $("canvas", el), svg: $("svg", el), layer: $(".ed-layer", el), vp, g, rendered: false, task: null };
      el.querySelectorAll("[data-a]").forEach((b) => (b.onclick = () => pageAction(pi, b.dataset.a)));
      bindSheet(pi);
      drawOverlay(pi);
      sheet.dataset.pi = pi;
      E.observer.observe(sheet);
    });
  }

  async function paint(pi) {
    const s = E.sheets[pi];
    if (!s || s.rendered) return;
    s.rendered = true;
    const p = E.pages[pi];
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    // Cap the canvas so large zooms don't run out of memory on phones.
    const k = Math.min(dpr, Math.sqrt(16e6 / (s.vp.width * s.vp.height)));
    const cv = s.canvas;
    cv.width = Math.floor(s.vp.width * k);
    cv.height = Math.floor(s.vp.height * k);
    cv.style.width = s.vp.width + "px";
    cv.style.height = s.vp.height + "px";
    const ctx = cv.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, cv.width, cv.height);
    if (p.src == null) return;
    const pg = s.g.pg;
    const view = pg.getViewport({ scale: s.vp.scale * k, rotation: (s.g.base + p.rotate) % 360 });
    try {
      s.task = pg.render({ canvasContext: ctx, viewport: view });
      await s.task.promise;
    } catch (e) {
      if (e && e.name === "RenderingCancelledException") s.rendered = false;
    }
  }

  // ------------------------------------------------------------ overlay (your edits)
  function selectedAnnot() {
    if (!E.selected) return null;
    const p = E.pages[E.selected.pi];
    return (p && p.annots[E.selected.ai]) || null;
  }

  function drawOverlay(pi) {
    const s = E.sheets[pi];
    if (!s) return;
    const p = E.pages[pi];
    const vp = s.vp;
    const sc = vp.scale;
    let svg = "";
    let html = "";
    p.annots.forEach((a, ai) => {
      const sel = E.selected && E.selected.pi === pi && E.selected.ai === ai;
      if (a.type === "rect") {
        const r = vp.rectToView(a.x, a.y, a.w, a.h);
        svg += `<rect data-ai="${ai}" x="${r.left}" y="${r.top}" width="${r.width}" height="${r.height}" fill="${css(a.color)}" fill-opacity="${a.opacity ?? 1}"${a.highlight ? ' style="mix-blend-mode:multiply"' : ""}/>`;
      } else if (a.type === "ink") {
        const d = a.points.map((pt, i) => { const v = vp.toView(pt[0], pt[1]); return (i ? "L" : "M") + v[0].toFixed(1) + " " + v[1].toFixed(1); }).join("");
        svg += `<path data-ai="${ai}" d="${d}${a.points.length === 1 ? "l0.01 0" : ""}" fill="none" stroke="${css(a.color)}" stroke-width="${(a.width || 2) * sc}" stroke-linecap="round" stroke-linejoin="round"/>`;
      } else if (a.type === "text") {
        if (E.editing && E.editing.pi === pi && E.editing.ai === ai) return;
        const v = vp.toView(a.x, a.y);
        const fs = a.size * sc;
        const off = BASELINE[a.font] || 0.95;
        const turn = C.norm(vp.rotation - (a.rot || 0));
        html += `<div class="ed-text${sel ? " sel" : ""}" data-ai="${ai}" style="left:${v[0]}px;top:${v[1] - off * fs}px;font-size:${fs}px;` +
          `font-family:${C.CSS_FONTS[a.font] || C.CSS_FONTS.Helvetica};font-weight:${a.bold ? 700 : 400};color:${css(a.color)};` +
          `transform-origin:0 ${off * fs}px;${turn ? `transform:rotate(${turn}deg);` : ""}">${esc(a.text) || "&#8203;"}</div>`;
      }
    });
    const hit = E.find.hits[E.find.i];
    if (hit && hit.pi === pi) {
      const r = itemRect(hit.item, vp);
      svg += `<rect class="ed-hit" x="${r.left - 2}" y="${r.top - 2}" width="${r.width + 4}" height="${r.height + 4}" rx="2"/>`;
    }
    s.svg.innerHTML = svg;
    s.layer.innerHTML = html;
    s.layer.querySelectorAll(".ed-text").forEach((el) => bindTextAnnot(pi, Number(el.dataset.ai), el));
  }

  // ------------------------------------------------------------ text items of the original page
  async function textItems(p) {
    if (p.src == null) return { items: [], styles: {} };
    const key = p.src + ":" + p.index;
    if (!E.textCache.has(key)) E.textCache.set(key, (await pdfPage(p.src, p.index)).getTextContent());
    return E.textCache.get(key);
  }

  function mul(m, n) {
    return [m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1], m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
      m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5]];
  }

  /** Screen rect of a pdf.js text item. */
  function itemRect(item, vp) {
    const t = mul(vp.transform, item.transform);
    const h = Math.hypot(t[2], t[3]);
    const len = Math.hypot(t[0], t[1]) || 1;
    const u = [t[0] / len, t[1] / len];
    const up = [t[2] / (h || 1), t[3] / (h || 1)];
    const w = item.width * vp.scale;
    const p0 = [t[4] - up[0] * h * 0.25, t[5] - up[1] * h * 0.25];
    const pts = [p0, [p0[0] + u[0] * w, p0[1] + u[1] * w], [p0[0] + up[0] * h * 1.2, p0[1] + up[1] * h * 1.2]];
    pts.push([pts[1][0] + up[0] * h * 1.2, pts[1][1] + up[1] * h * 1.2]);
    const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
    return { left: Math.min(...xs), top: Math.min(...ys), width: Math.max(...xs) - Math.min(...xs), height: Math.max(...ys) - Math.min(...ys) };
  }

  async function hitText(pi, vx, vy) {
    const { items } = await textItems(E.pages[pi]);
    const vp = E.sheets[pi].vp;
    let best = null;
    for (const it of items) {
      if (!it.str || !it.str.trim()) continue;
      const r = itemRect(it, vp);
      if (vx >= r.left - 3 && vx <= r.left + r.width + 3 && vy >= r.top - 3 && vy <= r.top + r.height + 3) {
        const area = r.width * r.height;
        if (!best || area < best.area) best = { it, r, area };
      }
    }
    return best;
  }

  /** Background and ink colours read from the rendered page around/inside a screen rect. */
  function sampleColors(pi, r) {
    const s = E.sheets[pi];
    const out = { bg: [1, 1, 1], ink: [0, 0, 0] };
    if (!s.rendered || !s.canvas.width) return out;
    try {
      const k = s.canvas.width / s.vp.width;
      const ctx = s.canvas.getContext("2d", { willReadFrequently: true });
      const px = (x, y) => Array.from(ctx.getImageData(Math.max(0, Math.round(x * k)), Math.max(0, Math.round(y * k)), 1, 1).data.slice(0, 3));
      const around = [px(r.left - 3, r.top + r.height / 2), px(r.left + r.width + 3, r.top + r.height / 2), px(r.left + r.width / 2, r.top - 2), px(r.left + r.width / 2, r.top + r.height + 2)];
      const bright = (c) => c[0] + c[1] + c[2];
      around.sort((a, b) => bright(b) - bright(a));
      const bg = around[1];
      out.bg = bg.map((v) => v / 255);
      const x0 = Math.max(0, Math.floor(r.left * k)), y0 = Math.max(0, Math.floor(r.top * k));
      const w = Math.max(1, Math.min(s.canvas.width - x0, Math.ceil(r.width * k))), h = Math.max(1, Math.min(s.canvas.height - y0, Math.ceil(r.height * k)));
      const d = ctx.getImageData(x0, y0, w, h).data;
      let far = -1, ink = null;
      for (let i = 0; i < d.length; i += 4 * 3) {
        const dist = Math.abs(d[i] - bg[0]) + Math.abs(d[i + 1] - bg[1]) + Math.abs(d[i + 2] - bg[2]);
        if (dist > far) { far = dist; ink = [d[i], d[i + 1], d[i + 2]]; }
      }
      if (ink && far > 120) out.ink = ink.map((v) => (v < 60 ? 0 : v / 255));
    } catch {}
    return out;
  }

  async function rewriteItem(pi, hit) {
    const p = E.pages[pi];
    const it = hit.it;
    const [a, b, c, d, e, f] = it.transform;
    const size = Math.hypot(c, d) || 12;
    const len = Math.hypot(a, b) || 1;
    const u = [a / len, b / len];
    const up = [c / size, d / size];
    // Cover box in PDF space (axis-aligned), slightly larger than the glyphs.
    const p0 = [e - up[0] * size * 0.28, f - up[1] * size * 0.28];
    const pts = [p0, [p0[0] + u[0] * it.width, p0[1] + u[1] * it.width]];
    pts.push([p0[0] + up[0] * size * 1.18, p0[1] + up[1] * size * 1.18], [pts[1][0] + up[0] * size * 1.18, pts[1][1] + up[1] * size * 1.18]);
    const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
    const pad = size * 0.06;
    const colors = sampleColors(pi, hit.r);
    let font = "Helvetica", bold = false;
    const { styles } = await textItems(p);
    const fam = (styles[it.fontName] && styles[it.fontName].fontFamily) || "";
    let real = "";
    try {
      const pg = await pdfPage(p.src, p.index);
      if (pg.commonObjs.has(it.fontName)) { const fo = pg.commonObjs.get(it.fontName); real = fo.name || ""; bold = !!fo.bold; }
    } catch {}
    if (/serif/i.test(fam) && !/sans/i.test(fam) || /times|georgia|cambria|garamond|book/i.test(real)) font = "Times";
    if (/mono/i.test(fam) || /courier|mono|consol/i.test(real)) font = "Courier";
    if (/bold|black|heavy|semibold/i.test(real)) bold = true;

    pushHistory();
    p.annots.push({ type: "rect", x: Math.min(...xs) - pad, y: Math.min(...ys) - pad, w: Math.max(...xs) - Math.min(...xs) + 2 * pad,
      h: Math.max(...ys) - Math.min(...ys) + 2 * pad, color: colors.bg, opacity: 1, cover: true });
    p.annots.push({ type: "text", x: e, y: f, size: +size.toFixed(2), font, bold, color: colors.ink, text: it.str,
      rot: C.norm((Math.atan2(b, a) * 180) / Math.PI) });
    E.selected = { pi, ai: p.annots.length - 1 };
    E.style = { font, size: +size.toFixed(1), bold, color: rgbToHex(colors.ink) };
    renderBar();
    startEditing(pi, p.annots.length - 1);
  }

  // ------------------------------------------------------------ editing text
  function startEditing(pi, ai) {
    finishEditing();
    const s = E.sheets[pi];
    const a = E.pages[pi].annots[ai];
    if (!s || !a || a.type !== "text") return;
    E.selected = { pi, ai };
    E.editing = { pi, ai, before: JSON.stringify(a) };
    drawOverlay(pi);
    const vp = s.vp;
    const ta = document.createElement("textarea");
    ta.className = "ed-input";
    ta.value = a.text;
    ta.spellcheck = false;
    styleInput(ta, a, vp);
    const fit = () => {
      const fs = a.size * vp.scale;
      ta.style.width = "0px"; ta.style.height = "0px";
      ta.style.width = Math.max(fs * 2, ta.scrollWidth + fs * 0.6) + "px";
      ta.style.height = ta.scrollHeight + "px";
    };
    ta.oninput = () => { a.text = ta.value; fit(); };
    ta.onblur = (ev) => {
      if (ev.relatedTarget && ev.relatedTarget.closest("#ed-bar")) return; // font/size/colour controls
      E.lastFinish = Date.now();
      setTimeout(() => { if (E.editing && E.editing.ta === ta) finishEditing(); }, 0);
    };
    E.editing.fit = fit;
    ta.onkeydown = (ev) => { if (ev.key === "Escape") { ev.preventDefault(); ta.blur(); } };
    s.layer.appendChild(ta);
    E.editing.ta = ta;
    fit();
    ta.focus();
    ta.select();
    renderBar();
  }

  function styleInput(ta, a, vp) {
    const v = vp.toView(a.x, a.y);
    const fs = a.size * vp.scale;
    const off = BASELINE[a.font] || 0.95;
    const turn = C.norm(vp.rotation - (a.rot || 0));
    Object.assign(ta.style, {
      left: v[0] + "px", top: v[1] - off * fs + "px", fontSize: fs + "px", fontFamily: C.CSS_FONTS[a.font] || C.CSS_FONTS.Helvetica,
      fontWeight: a.bold ? 700 : 400, color: css(a.color), transformOrigin: `0 ${off * fs}px`, transform: turn ? `rotate(${turn}deg)` : "",
    });
  }

  function finishEditing() {
    const ed = E.editing;
    if (!ed) return;
    E.editing = null;
    const p = E.pages[ed.pi];
    const a = p && p.annots[ed.ai];
    if (a) {
      if (JSON.stringify(a) !== ed.before) {
        // Record the state before typing started.
        const now = a.text;
        a.text = JSON.parse(ed.before).text;
        pushHistory();
        a.text = now;
      }
      if (!String(a.text).trim()) { p.annots.splice(ed.ai, 1); E.selected = null; }
    }
    if (ed.ta) ed.ta.remove();
    drawOverlay(ed.pi);
    renderBar();
  }

  function bindTextAnnot(pi, ai, el) {
    el.addEventListener("pointerdown", (ev) => {
      if (E.tool === "read") return;
      ev.stopPropagation();
      if (E.tool === "erase") return;
      const a = E.pages[pi].annots[ai];
      const start = [ev.clientX, ev.clientY];
      let moved = false;
      el.setPointerCapture(ev.pointerId);
      const left0 = parseFloat(el.style.left), top0 = parseFloat(el.style.top);
      const move = (m) => {
        const dx = m.clientX - start[0], dy = m.clientY - start[1];
        if (!moved && Math.hypot(dx, dy) < 6) return;
        moved = true;
        el.style.left = left0 + dx + "px";
        el.style.top = top0 + dy + "px";
      };
      const up = (m) => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up);
        el.removeEventListener("pointercancel", up);
        if (moved) {
          const vp = E.sheets[pi].vp;
          const v = vp.toView(a.x, a.y);
          const q = vp.toPdf(v[0] + m.clientX - start[0], v[1] + m.clientY - start[1]);
          pushHistory();
          a.x = q[0]; a.y = q[1];
          E.selected = { pi, ai };
          drawOverlay(pi);
          renderBar();
        } else {
          E.style = { font: a.font, size: a.size, bold: a.bold, color: rgbToHex(a.color) };
          startEditing(pi, ai);
        }
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
      el.addEventListener("pointercancel", up);
    });
  }

  // ------------------------------------------------------------ tools on the page
  function local(pi, ev) {
    const r = E.sheets[pi].sheet.getBoundingClientRect();
    return [ev.clientX - r.left, ev.clientY - r.top];
  }

  function bindSheet(pi) {
    const s = E.sheets[pi];
    const sheet = s.sheet;
    let drag = null;

    sheet.addEventListener("click", async (ev) => {
      if (drag && drag.used) return;
      const tool = E.tool;
      const p = E.pages[pi];
      if (tool === "erase") {
        const t = ev.target.closest("[data-ai]");
        const idx = t ? Number(t.dataset.ai) : NaN;
        if (!Number.isNaN(idx)) {
          pushHistory();
          p.annots.splice(idx, 1);
          drawOverlay(pi);
          renderBar();
        } else E.deps.toast("Tap one of your edits (text, drawing, highlight or white-out) to remove it.");
        return;
      }
      if (ev.target.closest(".ed-input") || ev.target.closest(".ed-text")) return;
      if (E.editing) { finishEditing(); return; }
      if (Date.now() - E.lastFinish < 400) return; // this tap only closed the text box
      const [x, y] = local(pi, ev);
      const vp = E.sheets[pi].vp;
      if (tool === "edit") {
        const hit = await hitText(pi, x, y);
        if (hit) rewriteItem(pi, hit);
        else if (!(await textItems(p)).items.length) E.deps.toast("This page has no editable text (it may be a scan). Use White-out and Add text instead.");
        else E.deps.toast("Tap directly on a line of text.");
      } else if (tool === "text") {
        const st = E.style;
        const q = vp.toPdf(x, y + (BASELINE[st.font] || 0.95) * st.size * vp.scale);
        pushHistory();
        p.annots.push({ type: "text", x: q[0], y: q[1], size: st.size, font: st.font, bold: st.bold, color: hexToRgb(st.color), text: "", rot: vp.rotation });
        startEditing(pi, p.annots.length - 1);
      }
    });

    sheet.addEventListener("pointerdown", (ev) => {
      const tool = E.tool;
      if (!["draw", "highlight", "whiteout"].includes(tool)) return;
      if (ev.button > 0) return;
      finishEditing();
      sheet.setPointerCapture(ev.pointerId);
      const p0 = local(pi, ev);
      drag = { tool, p0, pts: [p0], used: false, el: null };
      const el = document.createElementNS(SVGNS, tool === "draw" ? "path" : "rect");
      if (tool === "draw") {
        el.setAttribute("fill", "none");
        el.setAttribute("stroke", E.pen.color);
        el.setAttribute("stroke-width", E.pen.width * s.vp.scale);
        el.setAttribute("stroke-linecap", "round");
        el.setAttribute("stroke-linejoin", "round");
      } else {
        el.setAttribute("fill", tool === "highlight" ? "rgb(255 221 0 / 0.4)" : "#fff");
        el.setAttribute("stroke", "rgb(0 0 0 / 0.35)");
        el.setAttribute("stroke-dasharray", "4 3");
      }
      s.svg.appendChild(el);
      drag.el = el;
      ev.preventDefault();
    });
    sheet.addEventListener("pointermove", (ev) => {
      if (!drag || !drag.el) return;
      const q = local(pi, ev);
      if (Math.hypot(q[0] - drag.p0[0], q[1] - drag.p0[1]) > 4) drag.used = true;
      if (drag.tool === "draw") {
        drag.pts.push(q);
        drag.el.setAttribute("d", drag.pts.map((pt, i) => (i ? "L" : "M") + pt[0].toFixed(1) + " " + pt[1].toFixed(1)).join(""));
      } else {
        drag.p1 = q;
        drag.el.setAttribute("x", Math.min(q[0], drag.p0[0]));
        drag.el.setAttribute("y", Math.min(q[1], drag.p0[1]));
        drag.el.setAttribute("width", Math.abs(q[0] - drag.p0[0]));
        drag.el.setAttribute("height", Math.abs(q[1] - drag.p0[1]));
      }
    });
    const end = async () => {
      if (!drag) return;
      const d = drag;
      setTimeout(() => { if (drag === d) drag = null; }, 0);
      const vp = s.vp;
      const p = E.pages[pi];
      if (d.tool === "draw") {
        if (d.pts.length < 2 && !d.used) { d.pts.push([d.p0[0] + 0.01, d.p0[1]]); }
        pushHistory();
        p.annots.push({ type: "ink", points: simplify(d.pts, 0.6).map((q) => vp.toPdf(q[0], q[1]).map((n) => +n.toFixed(2))), width: E.pen.width, color: hexToRgb(E.pen.color) });
      } else if (d.used && d.p1) {
        const r = vp.rectToPdf(d.p0[0], d.p0[1], d.p1[0], d.p1[1]);
        pushHistory();
        p.annots.push(d.tool === "highlight"
          ? { type: "rect", ...r, color: [1, 0.87, 0], opacity: 0.4, highlight: true }
          : { type: "rect", ...r, color: [1, 1, 1], opacity: 1 });
      } else if (d.tool === "highlight") {
        // A tap highlights the line of text under the finger.
        const hit = await hitText(pi, d.p0[0], d.p0[1]);
        if (hit) {
          const r = vp.rectToPdf(hit.r.left, hit.r.top + hit.r.height * 0.08, hit.r.left + hit.r.width, hit.r.top + hit.r.height * 0.92);
          pushHistory();
          p.annots.push({ type: "rect", ...r, color: [1, 0.87, 0], opacity: 0.4, highlight: true });
        }
      }
      drawOverlay(pi);
      renderBar();
    };
    sheet.addEventListener("pointerup", end);
    sheet.addEventListener("pointercancel", end);
  }

  /** Drops points closer than tol px to keep drawings small. */
  function simplify(pts, tol) {
    const out = [pts[0]];
    for (let i = 1; i < pts.length; i++) {
      const l = out[out.length - 1];
      if (Math.hypot(pts[i][0] - l[0], pts[i][1] - l[1]) >= tol || i === pts.length - 1) out.push(pts[i]);
    }
    return out;
  }

  // ------------------------------------------------------------ page & menu actions
  async function pageAction(pi, a) {
    finishEditing();
    const p = E.pages[pi];
    if (a === "copy") {
      const { items } = await textItems(p);
      const text = items.map((it) => it.str + (it.hasEOL ? "\n" : " ")).join("").replace(/[ \t]+\n/g, "\n").trim();
      if (!text) { E.deps.toast("This page has no text to copy (it may be a scan)."); return; }
      try { await navigator.clipboard.writeText(text); E.deps.toast(`Copied the text of page ${pi + 1}`); }
      catch { E.deps.toast("Copying isn't allowed here."); }
      return;
    }
    pushHistory();
    if (a === "up" && pi > 0) [E.pages[pi - 1], E.pages[pi]] = [E.pages[pi], E.pages[pi - 1]];
    if (a === "down" && pi < E.pages.length - 1) [E.pages[pi + 1], E.pages[pi]] = [E.pages[pi], E.pages[pi + 1]];
    if (a === "rot") p.rotate = (p.rotate + 90) % 360;
    if (a === "del") E.pages.splice(pi, 1);
    E.selected = null;
    E.find = { q: "", hits: [], i: -1 };
    await renderPages();
    renderBar();
    const target = a === "up" ? pi - 1 : a === "down" ? pi + 1 : Math.min(pi, E.pages.length - 1);
    if (E.sheets[target]) E.sheets[target].el.scrollIntoView({ block: "nearest" });
  }

  async function menu(m) {
    finishEditing();
    if (m === "open") $("#ed-open").click();
    else if (m === "add") $("#ed-add").click();
    else if (m === "blank") {
      pushHistory();
      const last = E.pages[E.pages.length - 1];
      const g = last ? await geometry(last) : { view: [0, 0, 595.28, 841.89] };
      E.pages.push({ src: null, index: 0, rotate: 0, size: [g.view[2] - g.view[0], g.view[3] - g.view[1]], annots: [] });
      await renderPages();
      renderBar();
      E.sheets[E.sheets.length - 1].el.scrollIntoView({ block: "start" });
    } else if (m === "analyze") {
      const s = E.sources[0];
      if (s) E.deps.analyze(s.name, s.bytes);
    } else if (m === "close") {
      if (E.dirty && !(await E.deps.confirm("Close this PDF? Your unsaved changes will be lost.", "Close without saving"))) return;
      closeDoc();
    }
  }

  async function find(dir) {
    const q = ($("#ed-find-q").value || "").trim().toLowerCase();
    if (!q) return;
    if (q !== E.find.q) {
      E.find = { q, hits: [], i: -1 };
      for (let pi = 0; pi < E.pages.length; pi++) {
        const { items } = await textItems(E.pages[pi]);
        for (const item of items) if (item.str && item.str.toLowerCase().includes(q)) E.find.hits.push({ pi, item });
      }
    }
    const f = E.find;
    const prev = f.hits[f.i];
    if (f.hits.length) f.i = (f.i + dir + f.hits.length) % f.hits.length;
    renderBar();
    if (prev) drawOverlay(prev.pi);
    const hit = f.hits[f.i];
    if (!hit) { E.deps.toast(`“${q}” not found`); return; }
    drawOverlay(hit.pi);
    const s = E.sheets[hit.pi];
    const r = itemRect(hit.item, s.vp);
    const box = s.sheet.getBoundingClientRect();
    window.scrollTo({ top: window.scrollY + box.top + r.top - window.innerHeight / 3, behavior: "smooth" });
  }

  // ------------------------------------------------------------ saving
  async function rasterize(src, index) {
    const pg = await pdfPage(src, index);
    const vp = pg.getViewport({ scale: 2.5, rotation: 0 });
    const cv = document.createElement("canvas");
    cv.width = Math.ceil(vp.width); cv.height = Math.ceil(vp.height);
    const ctx = cv.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, cv.width, cv.height);
    await pg.render({ canvasContext: ctx, viewport: vp }).promise;
    const blob = await new Promise((r) => cv.toBlob(r, "image/jpeg", 0.9));
    return { bytes: new Uint8Array(await blob.arrayBuffer()), type: "jpg", view: pg.view, rotate: pg.rotate };
  }

  async function save() {
    finishEditing();
    const name = (E.name || "document").replace(/[\\/:*?"<>|]+/g, "_") + ".pdf";
    E.deps.busy(`Saving <b>${esc(name)}</b>…`);
    try {
      const pages = E.pages.map((p) => ({ ...p, annots: p.annots.map(({ cover, ...a }) => a) }));
      const { bytes, rasterized } = await C.buildPdf(window.PDFLib, E.sources, pages, rasterize, { title: E.name });
      E.deps.busy("");
      await E.deps.saveBinary(name, bytes, "application/pdf");
      E.dirty = false;
      renderBar();
      if (rasterized.length) {
        E.deps.toast(`Saved. Page${rasterized.length > 1 ? "s" : ""} ${rasterized.join(", ")} came from a protected PDF and were saved as images.`);
      }
    } catch (e) {
      E.deps.busy(`Couldn't save: ${esc(e && e.message ? e.message : e)}`, "err");
    }
  }

  // ------------------------------------------------------------ public
  window.PdfEditor = {
    init(root, deps) {
      E.root = root;
      E.deps = deps;
      render();
      let w = window.innerWidth;
      window.addEventListener("resize", () => {
        if (Math.abs(window.innerWidth - w) < 40 || !E.pages.length || E.editing) return;
        w = window.innerWidth;
        renderPages();
      });
      window.addEventListener("beforeunload", (ev) => { if (E.dirty) { ev.preventDefault(); ev.returnValue = ""; } });
    },
    open: openFiles,
    get dirty() { return E.dirty; },
    get hasDocument() { return E.pages.length > 0; },
    /** Android back button: true if the editor handled it. */
    async back() {
      if (E.editing) { finishEditing(); return true; }
      if (E.tool !== "read") { setTool("read"); return true; }
      if (E.pages.length) { await menu("close"); return true; }
      return false;
    },
  };
})();
