const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const pdfjs = require("pdfjs-dist/legacy/build/pdf.js");
const PDFLib = require("../web/vendor/pdf-lib.min.js");
const C = require("../web/pdf-editor-core.js");

const fixture = (name) => new Uint8Array(fs.readFileSync(path.join(__dirname, "fixtures", name + ".pdf")));
const open = (data, password) => pdfjs.getDocument({ data: data.slice(), password, isEvalSupported: false, verbosity: 0 }).promise;
async function pageText(pdf, n) {
  const tc = await (await pdf.getPage(n)).getTextContent();
  return tc.items.map((i) => i.str).join(" ");
}

test("viewport matches pdf.js for every rotation", async () => {
  const pdf = await open(fixture("sbi_style"));
  const page = await pdf.getPage(1);
  for (const rotation of [0, 90, 180, 270]) {
    for (const scale of [1, 1.7]) {
      const ref = page.getViewport({ scale, rotation });
      const vp = C.viewport(page.view, scale, rotation);
      assert.deepEqual(vp.transform.map((v) => +v.toFixed(6)), ref.transform.map((v) => +v.toFixed(6)));
      assert.equal(vp.width, ref.width);
      assert.equal(vp.height, ref.height);
      const [x, y] = vp.toPdf(...vp.toView(100, 200));
      assert.ok(Math.abs(x - 100) < 1e-9 && Math.abs(y - 200) < 1e-9);
      const r = vp.rectToPdf(...Object.values((({ left, top, width, height }) => [left, top, left + width, top + height])(vp.rectToView(50, 60, 70, 80))));
      assert.deepEqual([r.x, r.y, r.w, r.h].map((v) => +v.toFixed(6)), [50, 60, 70, 80]);
    }
  }
});

test("writes edits, page order, rotation, blank pages and merged files", async () => {
  const a = fixture("sbi_style");
  const b = fixture("hdfc_style");
  const srcA = await open(a);
  const srcB = await open(b);
  const textA1 = await pageText(srcA, 1);
  const pages = [
    { src: 1, index: 0, rotate: 0, annots: [] },
    {
      src: 0, index: 0, rotate: 90, annots: [
        { type: "rect", x: 40, y: 700, w: 200, h: 20, color: [1, 1, 1], opacity: 1 },
        { type: "text", x: 42, y: 705, size: 11, font: "Times", bold: true, color: [0.1, 0.2, 0.7], text: "Rewritten line ₹ 5,000\nsecond line", rot: 0 },
        { type: "rect", x: 40, y: 600, w: 100, h: 12, color: [1, 0.87, 0], opacity: 0.4, highlight: true },
        { type: "ink", points: [[100, 100], [120, 130], [140, 110]], width: 2, color: [0, 0, 1] },
        { type: "ink", points: [[300, 300]], width: 3, color: [0, 0, 0] },
        { type: "text", x: 10, y: 10, size: 10, font: "Courier", color: [0, 0, 0], text: "   ", rot: 0 },
      ],
    },
    { src: null, index: 0, rotate: 0, size: [400, 500], annots: [{ type: "text", x: 50, y: 400, size: 14, font: "Helvetica", color: [0, 0, 0], text: "Notes page", rot: 0 }] },
  ];
  const { bytes, rasterized } = await C.buildPdf(PDFLib, [{ name: "a", bytes: a }, { name: "b", bytes: b }], pages, null, { title: "Edited" });
  assert.deepEqual(rasterized, []);
  const out = await open(bytes);
  assert.equal(out.numPages, 3);
  assert.equal(await pageText(out, 1), await pageText(srcB, 1));
  const p2 = await out.getPage(2);
  assert.equal(p2.rotate, 90);
  const t2 = await pageText(out, 2);
  assert.ok(t2.startsWith(textA1), "original text kept");
  assert.match(t2, /Rewritten line Rs\. 5,000/);
  assert.match(t2, /second line/);
  const p3 = await out.getPage(3);
  assert.deepEqual(p3.view, [0, 0, 400, 500]);
  assert.match(await pageText(out, 3), /Notes page/);
  const meta = await out.getMetadata();
  assert.equal(meta.info.Title, "Edited");
});

test("locked PDFs are saved as images with the edits on top", async () => {
  const locked = fixture("sbi_style_locked");
  const pdf = await open(locked, "mallick123");
  let calls = 0;
  // A 1x1 PNG stands in for the rendered page (rendering needs a canvas).
  const png = Uint8Array.from(Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==", "base64"));
  const rasterize = async (src, index) => {
    calls++;
    const pg = await pdf.getPage(index + 1);
    return { bytes: png, type: "png", view: pg.view, rotate: pg.rotate };
  };
  const pages = [{ src: 0, index: 0, rotate: 0, annots: [{ type: "text", x: 60, y: 60, size: 12, font: "Helvetica", color: [0, 0, 0], text: "Signed", rot: 0 }] }];
  const { bytes, rasterized } = await C.buildPdf(PDFLib, [{ name: "locked", bytes: locked }], pages, rasterize);
  assert.equal(calls, 1);
  assert.deepEqual(rasterized, [1]);
  const out = await open(bytes);
  assert.equal(out.numPages, 1);
  assert.equal(await pageText(out, 1), "Signed");
});

test("text outside the standard fonts is replaced instead of failing", async () => {
  const doc = await PDFLib.PDFDocument.create();
  const font = await doc.embedFont(PDFLib.StandardFonts.Helvetica);
  assert.equal(C.encodable(font, "Café ₹10 − ok\r\nनमस्ते"), "Café Rs.10 - ok\n??????");
});
