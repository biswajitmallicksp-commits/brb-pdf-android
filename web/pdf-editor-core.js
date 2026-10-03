/*
 * PDF editor core: page geometry and writing the edited PDF with pdf-lib.
 * Runs in the browser (window.PdfEditCore) and in Node (require) for tests.
 * Everything happens locally; no network, no API.
 *
 * Edits are stored in each page's PDF user space (points, origin bottom-left),
 * so they stay put when the page is zoomed or rotated.
 *
 *   source: { name, bytes: Uint8Array }
 *   page:   { src: number|null, index, rotate (extra, 0/90/180/270), size: [w,h] (blank pages), annots: [] }
 *   annot:  { type: "rect", x, y, w, h, color: [r,g,b] 0..1, opacity, highlight }
 *           { type: "text", x, y (first baseline), size, font: "Helvetica"|"Times"|"Courier", bold, color, text, rot }
 *           { type: "ink", points: [[x,y]...], width, color }
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PdfEditCore = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const norm = (r) => ((Math.round(r / 90) * 90) % 360 + 360) % 360;

  /** Same math as pdf.js PageViewport: PDF user space -> CSS pixels. */
  function viewport(view, scale, rotation) {
    const [x0, y0, x1, y1] = view;
    const cx = (x1 + x0) / 2, cy = (y1 + y0) / 2;
    let a, b, c, d;
    switch (norm(rotation)) {
      case 180: a = -1; b = 0; c = 0; d = 1; break;
      case 90: a = 0; b = 1; c = 1; d = 0; break;
      case 270: a = 0; b = -1; c = -1; d = 0; break;
      default: a = 1; b = 0; c = 0; d = -1;
    }
    let ox, oy, width, height;
    if (a === 0) {
      ox = Math.abs(cy - y0) * scale; oy = Math.abs(cx - x0) * scale;
      width = (y1 - y0) * scale; height = (x1 - x0) * scale;
    } else {
      ox = Math.abs(cx - x0) * scale; oy = Math.abs(cy - y0) * scale;
      width = (x1 - x0) * scale; height = (y1 - y0) * scale;
    }
    const t = [a * scale, b * scale, c * scale, d * scale, ox - a * scale * cx - c * scale * cy, oy - b * scale * cx - d * scale * cy];
    const det = t[0] * t[3] - t[1] * t[2];
    return {
      width, height, scale, rotation: norm(rotation), transform: t,
      toView: (x, y) => [t[0] * x + t[2] * y + t[4], t[1] * x + t[3] * y + t[5]],
      toPdf: (vx, vy) => {
        const px = vx - t[4], py = vy - t[5];
        return [(t[3] * px - t[2] * py) / det, (-t[1] * px + t[0] * py) / det];
      },
      /** CSS rect {left, top, width, height} of a PDF-space rect. */
      rectToView: (x, y, w, h) => {
        const p = [t[0] * x + t[2] * y + t[4], t[1] * x + t[3] * y + t[5]];
        const q = [t[0] * (x + w) + t[2] * (y + h) + t[4], t[1] * (x + w) + t[3] * (y + h) + t[5]];
        return { left: Math.min(p[0], q[0]), top: Math.min(p[1], q[1]), width: Math.abs(q[0] - p[0]), height: Math.abs(q[1] - p[1]) };
      },
      /** PDF-space rect {x, y, w, h} of a CSS rect given by two corners. */
      rectToPdf: (vx0, vy0, vx1, vy1) => {
        const p = [(t[3] * (vx0 - t[4]) - t[2] * (vy0 - t[5])) / det, (-t[1] * (vx0 - t[4]) + t[0] * (vy0 - t[5])) / det];
        const q = [(t[3] * (vx1 - t[4]) - t[2] * (vy1 - t[5])) / det, (-t[1] * (vx1 - t[4]) + t[0] * (vy1 - t[5])) / det];
        return { x: Math.min(p[0], q[0]), y: Math.min(p[1], q[1]), w: Math.abs(q[0] - p[0]), h: Math.abs(q[1] - p[1]) };
      },
    };
  }

  const FONT_KEYS = {
    Helvetica: ["Helvetica", "HelveticaBold"],
    Times: ["TimesRoman", "TimesRomanBold"],
    Courier: ["Courier", "CourierBold"],
  };
  const CSS_FONTS = {
    Helvetica: "Helvetica, Arial, 'Liberation Sans', Roboto, sans-serif",
    Times: "'Times New Roman', Times, 'Liberation Serif', 'Noto Serif', serif",
    Courier: "'Courier New', Courier, 'Liberation Mono', monospace",
  };
  const REPLACE = { "₹": "Rs.", "−": "-", " ": " ", " ": " ", "​": "" };

  /** The 14 standard PDF fonts only cover Latin text (WinAnsi); swap anything else. */
  function encodable(font, text) {
    let out = "";
    for (const ch of String(text).replace(/\r\n?/g, "\n")) {
      if (ch === "\n") { out += ch; continue; }
      const c = REPLACE[ch] != null ? REPLACE[ch] : ch;
      try { font.encodeText(c); out += c; } catch { out += "?"; }
    }
    return out;
  }

  /**
   * A private copy of PDF bytes. pdf.js takes ownership of (detaches) the buffer it is given,
   * so the app never hands it bytes it still needs.
   */
  function copyBytes(b) {
    const src = b instanceof Uint8Array ? b : new Uint8Array(b);
    if (!src.byteLength) throw new Error("The file arrived empty. Please open it again.");
    const out = new Uint8Array(src.byteLength);
    out.set(src);
    return out;
  }

  /** Bytes of a picked File, or of { name, bytes } from the Android app. Works on older WebViews too. */
  async function fileBytes(f) {
    if (f.bytes) return copyBytes(f.bytes);
    if (typeof f.arrayBuffer === "function") return new Uint8Array(await f.arrayBuffer());
    return new Uint8Array(await new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(r.result);
      r.onerror = () => reject(r.error || new Error("Could not read the file"));
      r.readAsArrayBuffer(f);
    }));
  }

  async function bytesOf(maybePromise) {
    const v = await maybePromise;
    return v instanceof Uint8Array ? v : new Uint8Array(v);
  }

  /**
   * Builds the edited PDF and returns its bytes.
   * rasterize(src, index) is used for pages pdf-lib can't copy (password-protected or broken files):
   * it must return { bytes (PNG or JPEG), type: "png"|"jpg", view: [x0,y0,x1,y1], rotate }.
   */
  async function buildPdf(PDFLib, sources, pages, rasterize, info = {}) {
    const { PDFDocument, StandardFonts, rgb, degrees, LineCapStyle, BlendMode } = PDFLib;
    const out = await PDFDocument.create();
    if (info.title) out.setTitle(info.title);
    out.setProducer("BRB PDF (offline)");
    out.setCreator("BRB PDF (offline)");

    // Copy each source's pages in one go so shared fonts and images are copied once.
    const copied = new Map(); // "src:index" -> PDFPage
    const rasterOnly = new Set();
    const wanted = new Map();
    for (const p of pages) if (p.src != null) (wanted.get(p.src) || wanted.set(p.src, new Set()).get(p.src)).add(p.index);
    for (const [src, set] of wanted) {
      const idx = [...set];
      try {
        const doc = await PDFDocument.load(sources[src].bytes, { updateMetadata: false });
        const got = await out.copyPages(doc, idx);
        idx.forEach((i, k) => copied.set(src + ":" + i, got[k]));
      } catch (e) {
        if (!rasterize) throw e;
        rasterOnly.add(src);
      }
    }

    const fonts = {};
    const font = async (name, bold) => {
      const key = (FONT_KEYS[name] || FONT_KEYS.Helvetica)[bold ? 1 : 0];
      return fonts[key] || (fonts[key] = await out.embedFont(StandardFonts[key]));
    };
    const used = new Set();
    const rasterized = [];

    for (const p of pages) {
      let page, dx = 0, dy = 0, base = 0;
      if (p.src == null) {
        page = out.addPage(p.size || [595.28, 841.89]);
      } else if (!rasterOnly.has(p.src)) {
        const key = p.src + ":" + p.index;
        page = copied.get(key);
        // The same page added twice needs its own copy.
        if (used.has(key)) {
          const doc = await PDFDocument.load(sources[p.src].bytes, { updateMetadata: false });
          [page] = await out.copyPages(doc, [p.index]);
        }
        used.add(key);
        out.addPage(page);
        base = page.getRotation().angle;
      } else {
        const r = await rasterize(p.src, p.index);
        const img = r.type === "png" ? await out.embedPng(await bytesOf(r.bytes)) : await out.embedJpg(await bytesOf(r.bytes));
        const [x0, y0, x1, y1] = r.view;
        page = out.addPage([x1 - x0, y1 - y0]);
        page.drawImage(img, { x: 0, y: 0, width: x1 - x0, height: y1 - y0 });
        dx = -x0; dy = -y0; base = r.rotate || 0;
        rasterized.push(pages.indexOf(p) + 1);
      }
      page.setRotation(degrees(norm(base + (p.rotate || 0))));

      for (const a of p.annots || []) {
        const color = rgb(...(a.color || [0, 0, 0]));
        if (a.type === "rect") {
          page.drawRectangle({ x: a.x + dx, y: a.y + dy, width: a.w, height: a.h, color, opacity: a.opacity ?? 1,
            ...(a.highlight && BlendMode ? { blendMode: BlendMode.Multiply } : {}) });
        } else if (a.type === "ink") {
          const pts = a.points || [];
          const opts = { thickness: a.width || 2, color, opacity: a.opacity ?? 1, lineCap: LineCapStyle && LineCapStyle.Round };
          if (pts.length === 1) page.drawCircle({ x: pts[0][0] + dx, y: pts[0][1] + dy, size: (a.width || 2) / 2, color });
          for (let i = 1; i < pts.length; i++) {
            page.drawLine({ start: { x: pts[i - 1][0] + dx, y: pts[i - 1][1] + dy }, end: { x: pts[i][0] + dx, y: pts[i][1] + dy }, ...opts });
          }
        } else if (a.type === "text" && String(a.text || "").trim()) {
          const f = await font(a.font, a.bold);
          page.drawText(encodable(f, a.text), { x: a.x + dx, y: a.y + dy, size: a.size, font: f, color,
            lineHeight: a.size * 1.2, rotate: degrees(norm(a.rot || 0)) });
        }
      }
    }
    const bytes = await out.save();
    return { bytes, rasterized };
  }

  return { viewport, buildPdf, encodable, norm, copyBytes, fileBytes, CSS_FONTS };
});
