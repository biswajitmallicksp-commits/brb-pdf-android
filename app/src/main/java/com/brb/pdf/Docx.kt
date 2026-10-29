package com.brb.pdf

import org.w3c.dom.Element
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.util.Base64
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream
import javax.xml.parsers.DocumentBuilderFactory

/**
 * Word (.docx) files without Microsoft Word, all on the phone.
 *
 *  - [read]  .docx -> HTML for the editor (text, fonts, sizes, bold / italic / underline / strike, colours,
 *            highlight, Title / Heading styles, alignment, indents, spacing, line spacing, bulleted and
 *            numbered lists, tables with merged cells and column widths, pictures, page breaks, page size
 *            and margins).
 *  - [write] the editor's document (JSON from the editor page) -> .docx.
 *
 * Pure Java/Kotlin (no Android classes), so it is also tested on a PC.
 */
object Docx {
    const val MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    private const val W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    private const val R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    private const val A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    private const val WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    private const val EMU_PER_PT = 12700f

    data class Page(var w: Float = 595.3f, var h: Float = 841.9f,
                    var ml: Float = 72f, var mt: Float = 72f, var mr: Float = 72f, var mb: Float = 72f)

    class Loaded(val html: String, val page: Page, val baseFont: String, val baseSize: Float)

    private val HIGHLIGHT = mapOf(
        "yellow" to "FFFF00", "green" to "00FF00", "cyan" to "00FFFF", "magenta" to "FF00FF", "blue" to "0000FF",
        "red" to "FF0000", "darkBlue" to "000080", "darkCyan" to "008080", "darkGreen" to "008000",
        "darkMagenta" to "800080", "darkRed" to "800000", "darkYellow" to "808000", "darkGray" to "808080",
        "lightGray" to "C0C0C0", "black" to "000000", "white" to "FFFFFF")

    // ================================================================ read
    private class RP(var b: Boolean? = null, var i: Boolean? = null, var u: Boolean? = null, var s: Boolean? = null,
                     var color: String? = null, var bg: String? = null, var size: Float? = null,
                     var font: String? = null, var va: String? = null) {
        fun over(o: RP?): RP {
            if (o == null) return this
            return RP(o.b ?: b, o.i ?: i, o.u ?: u, o.s ?: s, o.color ?: color, o.bg ?: bg, o.size ?: size,
                o.font ?: font, o.va ?: va)
        }
    }

    private class PP(var align: String? = null, var left: Float? = null, var right: Float? = null,
                     var first: Float? = null, var before: Float? = null, var after: Float? = null,
                     var line: Float? = null, var lineExact: Float? = null, var numId: String? = null,
                     var ilvl: Int? = null, var pageBreak: Boolean? = null) {
        fun over(o: PP?): PP {
            if (o == null) return this
            return PP(o.align ?: align, o.left ?: left, o.right ?: right, o.first ?: first, o.before ?: before,
                o.after ?: after, if (o.line != null || o.lineExact != null) o.line else line,
                if (o.line != null || o.lineExact != null) o.lineExact else lineExact,
                o.numId ?: numId, o.ilvl ?: ilvl, o.pageBreak ?: pageBreak)
        }
    }

    private class Style(val id: String, val name: String, val basedOn: String?, val r: RP, val p: PP)

    private fun Element.w(local: String): String? = getAttributeNS(W, local).takeIf { it.isNotEmpty() }
    private fun Element.kids(local: String? = null, ns: String = W): List<Element> {
        val out = ArrayList<Element>()
        var n = firstChild
        while (n != null) {
            if (n is Element && n.namespaceURI == ns && (local == null || n.localName == local)) out.add(n)
            n = n.nextSibling
        }
        return out
    }
    private fun Element.kid(local: String, ns: String = W): Element? = kids(local, ns).firstOrNull()
    private fun Element.all(local: String, ns: String): List<Element> {
        val nl = getElementsByTagNameNS(ns, local)
        return (0 until nl.length).map { nl.item(it) as Element }
    }
    private fun toggle(e: Element?): Boolean? = when {
        e == null -> null
        else -> e.w("val")?.lowercase(Locale.US) !in setOf("0", "false", "off", "none")
    }
    private fun twip(v: String?): Float? = v?.toFloatOrNull()?.div(20f)

    private fun readRP(rPr: Element?): RP {
        val r = RP()
        if (rPr == null) return r
        r.b = toggle(rPr.kid("b"))
        r.i = toggle(rPr.kid("i"))
        rPr.kid("u")?.let { r.u = it.w("val") != "none" }
        r.s = toggle(rPr.kid("strike")) ?: toggle(rPr.kid("dstrike"))
        rPr.kid("color")?.w("val")?.takeIf { it.length == 6 && it != "auto" }?.let { r.color = it.uppercase(Locale.US) }
        rPr.kid("highlight")?.w("val")?.let { HIGHLIGHT[it] }?.let { r.bg = it }
        if (r.bg == null) rPr.kid("shd")?.w("fill")?.takeIf { it.length == 6 && it != "auto" }
            ?.let { r.bg = it.uppercase(Locale.US) }
        rPr.kid("sz")?.w("val")?.toFloatOrNull()?.let { r.size = it / 2f }
        rPr.kid("rFonts")?.let { f -> r.font = f.w("ascii") ?: f.w("hAnsi") ?: f.w("cs") }
        rPr.kid("vertAlign")?.w("val")?.let { r.va = it }
        return r
    }

    private fun readPP(pPr: Element?): PP {
        val p = PP()
        if (pPr == null) return p
        pPr.kid("jc")?.w("val")?.let {
            p.align = when (it) { "center" -> "center"; "right", "end" -> "right"; "both", "distribute" -> "justify"; else -> "left" }
        }
        pPr.kid("ind")?.let { ind ->
            p.left = twip(ind.w("left") ?: ind.w("start"))
            p.right = twip(ind.w("right") ?: ind.w("end"))
            p.first = twip(ind.w("firstLine")) ?: twip(ind.w("hanging"))?.let { -it }
        }
        pPr.kid("spacing")?.let { sp ->
            p.before = twip(sp.w("before"))
            p.after = twip(sp.w("after"))
            val line = sp.w("line")?.toFloatOrNull()
            if (line != null) {
                if (sp.w("lineRule") == null || sp.w("lineRule") == "auto") p.line = line / 240f
                else p.lineExact = line / 20f
            }
        }
        pPr.kid("numPr")?.let { n ->
            p.numId = n.kid("numId")?.w("val")
            p.ilvl = n.kid("ilvl")?.w("val")?.toIntOrNull()
        }
        p.pageBreak = toggle(pPr.kid("pageBreakBefore"))
        return p
    }

    private fun unzip(input: InputStream): Map<String, ByteArray> {
        val out = HashMap<String, ByteArray>()
        ZipInputStream(input).use { z ->
            var e: ZipEntry? = z.nextEntry
            var total = 0L
            while (e != null) {
                if (!e.isDirectory) {
                    val bytes = z.readBytes()
                    total += bytes.size
                    if (total > 400L * 1024 * 1024) throw UserError("This Word file is too large to open.")
                    out[e.name.trimStart('/')] = bytes
                }
                e = z.nextEntry
            }
        }
        return out
    }

    private fun parse(bytes: ByteArray): Element {
        val f = DocumentBuilderFactory.newInstance()
        f.isNamespaceAware = true
        try { f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true) } catch (_: Exception) { }
        try { f.isExpandEntityReferences = false } catch (_: Exception) { }
        return f.newDocumentBuilder().parse(bytes.inputStream()).documentElement
    }

    fun read(input: InputStream, name: String = "document.docx"): Loaded {
        if (name.lowercase(Locale.US).endsWith(".doc"))
            throw UserError("Old Word files (.doc) cannot be opened. Save it as .docx in Word first.")
        val parts = try { unzip(input) } catch (e: UserError) { throw e } catch (e: Exception) {
            throw UserError("$name could not be read as a Word document.")
        }
        val docXml = parts["word/document.xml"] ?: throw UserError("$name is not a Word (.docx) document.")
        return Reader(parts, parse(docXml)).run()
    }

    private class ListState(val tag: String, val level: Int)

    private class Reader(val parts: Map<String, ByteArray>, val root: Element) {
        val styles = HashMap<String, Style>()
        var defR = RP()
        var defP = PP()
        var defaultPara: String? = null
        val numFmt = HashMap<String, String>()            // "numId/ilvl" -> numFmt
        val rels = HashMap<String, String>()               // rId -> target path
        val html = StringBuilder()
        val page = Page()
        var pendingBreak = false
        val openLists = ArrayList<ListState>()
        var baseSize = 11f
        var baseFont = "Calibri"

        init {
            parts["word/styles.xml"]?.let { readStyles(Docx.parse(it)) }
            parts["word/numbering.xml"]?.let { readNumbering(Docx.parse(it)) }
            parts["word/_rels/document.xml.rels"]?.let { relsXml ->
                val e = Docx.parse(relsXml)
                val nl = e.getElementsByTagName("Relationship")
                for (k in 0 until nl.length) {
                    val r = nl.item(k) as Element
                    val t = r.getAttribute("Target")
                    rels[r.getAttribute("Id")] = if (t.startsWith("/")) t.trimStart('/') else "word/$t"
                }
            }
        }

        fun readStyles(e: Element) {
            e.kid("docDefaults")?.let { dd ->
                defR = readRP(dd.kid("rPrDefault")?.kid("rPr"))
                defP = readPP(dd.kid("pPrDefault")?.kid("pPr"))
            }
            for (s in e.kids("style")) {
                val id = s.w("styleId") ?: continue
                val st = Style(id, s.kid("name")?.w("val") ?: id, s.kid("basedOn")?.w("val"),
                    readRP(s.kid("rPr")), readPP(s.kid("pPr")))
                styles[id] = st
                if (s.w("type") == "paragraph" && s.w("default") == "1") defaultPara = id
            }
        }

        fun readNumbering(e: Element) {
            val abstract = HashMap<String, Map<Int, String>>()
            for (an in e.kids("abstractNum")) {
                val m = HashMap<Int, String>()
                for (lvl in an.kids("lvl")) m[lvl.w("ilvl")?.toIntOrNull() ?: 0] = lvl.kid("numFmt")?.w("val") ?: "bullet"
                abstract[an.w("abstractNumId") ?: continue] = m
            }
            for (n in e.kids("num")) {
                val id = n.w("numId") ?: continue
                val m = abstract[n.kid("abstractNumId")?.w("val")] ?: continue
                for ((lvl, fmt) in m) numFmt["$id/$lvl"] = fmt
            }
        }

        fun styleR(id: String?, depth: Int = 0): RP {
            val s = styles[id ?: return RP()] ?: return RP()
            return if (depth < 10) styleR(s.basedOn, depth + 1).over(s.r) else s.r
        }

        fun styleP(id: String?, depth: Int = 0): PP {
            val s = styles[id ?: return PP()] ?: return PP()
            return if (depth < 10) styleP(s.basedOn, depth + 1).over(s.p) else s.p
        }

        fun run(): Loaded {
            val body = root.kid("body") ?: throw UserError("This Word document has no body.")
            val normal = defR.over(styleR(defaultPara))
            baseSize = normal.size ?: 11f
            baseFont = normal.font ?: "Calibri"
            body.kids("sectPr").lastOrNull()?.let { readSection(it) }
            blocks(body, html, top = true)
            closeLists(html, -1)
            if (pendingBreak) html.append("<hr class=\"pb\">")
            if (html.isEmpty()) html.append("<p><br></p>")
            return Loaded(html.toString(), page, baseFont, baseSize)
        }

        fun readSection(s: Element) {
            s.kid("pgSz")?.let { sz ->
                twip(sz.w("w"))?.let { page.w = it }
                twip(sz.w("h"))?.let { page.h = it }
            }
            s.kid("pgMar")?.let { m ->
                twip(m.w("left"))?.let { page.ml = it }
                twip(m.w("top"))?.let { page.mt = maxOf(0f, it) }
                twip(m.w("right"))?.let { page.mr = it }
                twip(m.w("bottom"))?.let { page.mb = maxOf(0f, it) }
            }
        }

        fun blocks(container: Element, out: StringBuilder, top: Boolean) {
            for (child in container.kids()) {
                when (child.localName) {
                    "p" -> paragraph(child, out, top)
                    "tbl" -> { if (top) closeLists(out, -1); table(child, out) }
                    "sdt" -> child.kid("sdtContent")?.let { blocks(it, out, top) }
                }
            }
        }

        fun closeLists(out: StringBuilder, keepLevel: Int) {
            while (openLists.size > keepLevel + 1) out.append("</${openLists.removeAt(openLists.size - 1).tag}>")
        }

        fun paragraph(p: Element, out: StringBuilder, top: Boolean) {
            val pPr = p.kid("pPr")
            val styleId = pPr?.kid("pStyle")?.w("val") ?: defaultPara
            val styleName = styles[styleId]?.name ?: ""
            val pp = defP.over(styleP(styleId)).over(readPP(pPr))
            val paraR = defR.over(styleR(styleId))
            // content: runs, with page breaks splitting the paragraph
            val pieces = ArrayList<StringBuilder>()
            val breaksAfter = ArrayList<Boolean>()
            var cur = StringBuilder()
            fun runs(parent: Element) {
                for (c in parent.kids()) {
                    when (c.localName) {
                        "r" -> run(c, paraR, cur) { pieces.add(cur); breaksAfter.add(true); cur = StringBuilder() }
                        "hyperlink", "smartTag", "ins", "fldSimple" -> runs(c)
                        "sdt" -> c.kid("sdtContent")?.let { runs(it) }
                    }
                }
            }
            runs(p)
            pieces.add(cur); breaksAfter.add(false)

            val lname = styleName.lowercase(Locale.US)
            val tag = when {
                lname == "title" -> "h1"
                lname == "heading 1" -> "h2"
                lname == "heading 2" -> "h3"
                lname.startsWith("heading ") -> "h4"
                else -> "p"
            }
            val numId = pp.numId?.takeIf { it != "0" }
            val level = pp.ilvl ?: 0
            for ((k, content) in pieces.withIndex()) {
                val onlyBreak = content.isEmpty() && breaksAfter[k] && k == 0
                if (onlyBreak) { if (top) closeLists(out, -1); pendingBreak = true; continue }
                if (content.isEmpty() && k > 0 && k == pieces.size - 1) continue
                val style = StringBuilder()
                pp.align?.takeIf { it != "left" }?.let { style.append("text-align:$it;") }
                if (numId == null) pp.left?.takeIf { it > 0.5f }?.let { style.append("margin-left:${f(it)}pt;") }
                pp.right?.takeIf { it > 0.5f }?.let { style.append("margin-right:${f(it)}pt;") }
                if (numId == null) pp.first?.takeIf { it != 0f }?.let { style.append("text-indent:${f(it)}pt;") }
                style.append("margin-top:${f(pp.before ?: 0f)}pt;margin-bottom:${f(pp.after ?: 0f)}pt;")
                pp.line?.let { style.append("line-height:${f(maxOf(0.8f, it) * 1.15f)};") }
                pp.lineExact?.let { style.append("line-height:${f(it)}pt;") }
                if (pendingBreak || (k == 0 && pp.pageBreak == true)) {
                    if (top) closeLists(out, -1)
                    out.append("<hr class=\"pb\">")
                    pendingBreak = false
                }
                val inner = if (content.isEmpty()) "<br>" else content.toString()
                if (numId != null && top) {
                    val fmt = numFmt["$numId/$level"] ?: if ("number" in lname) "decimal" else "bullet"
                    val ltag = if (fmt == "bullet" || fmt == "none") "ul" else "ol"
                    closeLists(out, level)
                    if (openLists.size == level + 1 && openLists.last().tag != ltag) closeLists(out, level - 1)
                    while (openLists.size < level + 1) {
                        out.append("<$ltag>")
                        openLists.add(ListState(ltag, openLists.size))
                    }
                    out.append("<li style=\"$style\">").append(inner).append("</li>")
                } else {
                    if (top) closeLists(out, -1)
                    out.append("<$tag style=\"$style\">").append(inner).append("</$tag>")
                }
                if (breaksAfter[k]) pendingBreak = true
            }
        }

        fun run(r: Element, paraR: RP, out: StringBuilder, pageBreak: () -> Unit) {
            val rStyle = r.kid("rPr")?.kid("rStyle")?.w("val")
            val rp = paraR.over(styleR(rStyle)).over(readRP(r.kid("rPr")))
            val css = StringBuilder()
            css.append("font-size:${f(rp.size ?: baseSize)}pt;")
            (rp.font ?: baseFont).let { css.append("font-family:'${it.replace("'", "")}';") }
            if (rp.b == true) css.append("font-weight:bold;")
            if (rp.i == true) css.append("font-style:italic;")
            val deco = listOfNotNull(if (rp.u == true) "underline" else null, if (rp.s == true) "line-through" else null)
            if (deco.isNotEmpty()) css.append("text-decoration:${deco.joinToString(" ")};")
            rp.color?.takeIf { it != "000000" }?.let { css.append("color:#$it;") }
            rp.bg?.let { css.append("background-color:#$it;") }
            when (rp.va) {
                "superscript" -> css.append("vertical-align:super;font-size:${f((rp.size ?: baseSize) * 0.66f)}pt;")
                "subscript" -> css.append("vertical-align:sub;font-size:${f((rp.size ?: baseSize) * 0.66f)}pt;")
            }
            val text = StringBuilder()
            fun flush() {
                if (text.isNotEmpty()) {
                    out.append("<span style=\"").append(css).append("\">").append(esc(text.toString())).append("</span>")
                    text.setLength(0)
                }
            }
            for (c in r.kids()) {
                when (c.localName) {
                    "t" -> text.append(c.textContent ?: "")
                    "tab", "ptab" -> text.append('\t')
                    "noBreakHyphen" -> text.append('-')
                    "softHyphen" -> {}
                    "br", "cr" -> {
                        if (c.w("type") == "page") { flush(); pageBreak() }
                        else { flush(); out.append("<br>") }
                    }
                    "lastRenderedPageBreak" -> {}
                    "drawing" -> { flush(); picture(c, out) }
                    "sym" -> c.w("char")?.toIntOrNull(16)?.let { text.append(it.toChar()) }
                }
            }
            flush()
        }

        fun picture(d: Element, out: StringBuilder) {
            val blip = d.all("blip", A).firstOrNull() ?: return
            val rid = blip.getAttributeNS(R, "embed").takeIf { it.isNotEmpty() } ?: return
            val path = rels[rid] ?: return
            val bytes = parts[path.replace("/./", "/")] ?: return
            val ext = path.substringAfterLast('.').lowercase(Locale.US)
            val mime = when (ext) { "jpg", "jpeg" -> "image/jpeg"; "gif" -> "image/gif"; "bmp" -> "image/bmp"
                "webp" -> "image/webp"; "emf" -> "image/x-emf"; "wmf" -> "image/x-wmf"; "tif", "tiff" -> "image/tiff"
                else -> "image/png" }
            val extent = d.all("extent", WP).firstOrNull()
            var w = extent?.getAttribute("cx")?.toFloatOrNull()?.div(EMU_PER_PT) ?: 200f
            var h = extent?.getAttribute("cy")?.toFloatOrNull()?.div(EMU_PER_PT) ?: 150f
            val maxW = page.w - page.ml - page.mr
            if (w > maxW && maxW > 50) { h *= maxW / w; w = maxW }
            out.append("<img src=\"data:$mime;base64,").append(Base64.getEncoder().encodeToString(bytes))
                .append("\" style=\"width:${f(w)}pt;height:${f(h)}pt\">")
        }

        fun table(t: Element, out: StringBuilder) {
            val grid = t.kid("tblGrid")?.kids("gridCol")?.map { twip(it.w("w")) ?: 0f } ?: emptyList()
            data class C(val tc: Element, val col: Int, val span: Int, val vm: String?)
            val rows = t.kids("tr").map { tr ->
                var col = 0
                tr.kids("tc").map { tc ->
                    val pr = tc.kid("tcPr")
                    val span = pr?.kid("gridSpan")?.w("val")?.toIntOrNull() ?: 1
                    val vm = pr?.kid("vMerge")?.let { it.w("val") ?: "continue" }
                    C(tc, col, span, vm).also { col += span }
                }
            }
            val bordered = t.kid("tblPr")?.kid("tblBorders") != null ||
                t.kid("tblPr")?.kid("tblStyle")?.w("val")?.contains("Grid", true) == true ||
                t.kid("tblPr")?.kid("tblStyle") == null
            out.append("<table class=\"t${if (bordered) "" else " nb"}\">")
            if (grid.isNotEmpty() && grid.sum() > 0) {
                out.append("<colgroup>")
                for (g in grid) out.append("<col style=\"width:${f(g)}pt\">")
                out.append("</colgroup>")
            }
            for ((ri, row) in rows.withIndex()) {
                out.append("<tr>")
                for (c in row) {
                    if (c.vm == "continue") continue
                    var rowspan = 1
                    if (c.vm == "restart") {
                        var k = ri + 1
                        while (k < rows.size && rows[k].any { it.col == c.col && it.vm == "continue" }) { rowspan++; k++ }
                    }
                    out.append("<td")
                    if (c.span > 1) out.append(" colspan=\"${c.span}\"")
                    if (rowspan > 1) out.append(" rowspan=\"$rowspan\"")
                    c.tc.kid("tcPr")?.kid("shd")?.w("fill")?.takeIf { it.length == 6 && it != "auto" }
                        ?.let { out.append(" style=\"background-color:#$it\"") }
                    out.append(">")
                    val saveLists = ArrayList(openLists)
                    openLists.clear()
                    val cell = StringBuilder()
                    blocks(c.tc, cell, top = false)
                    out.append(if (cell.isEmpty()) "<p><br></p>" else cell)
                    openLists.clear(); openLists.addAll(saveLists)
                    out.append("</td>")
                }
                out.append("</tr>")
            }
            out.append("</table>")
        }
    }

    private fun f(v: Float): String = if (v == Math.round(v).toFloat()) Math.round(v).toString()
        else String.format(Locale.US, "%.2f", v).trimEnd('0').trimEnd('.')

    fun esc(s: String): String {
        val sb = StringBuilder(s.length + 16)
        for (ch in s) when (ch) {
            '&' -> sb.append("&amp;"); '<' -> sb.append("&lt;"); '>' -> sb.append("&gt;"); '"' -> sb.append("&quot;")
            else -> sb.append(ch)
        }
        return sb.toString()
    }

    // ================================================================ write
    /** Write the editor's document (the JSON made by serialize() in the editor page) as a .docx. */
    @Suppress("UNCHECKED_CAST")
    fun write(json: String, out: OutputStream) {
        val doc = Json.parse(json) as Map<String, Any?>
        Writer(doc).write(out)
    }

    private class Writer(val doc: Map<String, Any?>) {
        val body = StringBuilder()
        val media = ArrayList<Triple<String, String, ByteArray>>()   // rId, file name, bytes
        val lists = LinkedHashMap<String, Boolean>()                  // list id -> numbered
        var pics = 0
        val page: Map<String, Any?> = map(doc["page"])
        val textWidth = num(page["w"], 595.3f) - num(page["ml"], 72f) - num(page["mr"], 72f)

        @Suppress("UNCHECKED_CAST")
        fun map(v: Any?): Map<String, Any?> = (v as? Map<String, Any?>) ?: emptyMap()
        @Suppress("UNCHECKED_CAST")
        fun list(v: Any?): List<Any?> = (v as? List<Any?>) ?: emptyList()
        fun num(v: Any?, def: Float = 0f): Float = (v as? Number)?.toFloat() ?: def
        fun str(v: Any?): String? = (v as? String)?.takeIf { it.isNotEmpty() }
        fun bool(v: Any?): Boolean = v == true

        fun write(out: OutputStream) {
            val blocks = list(doc["blocks"])
            blocks(blocks, body)
            if (blocks.isEmpty() || map(blocks.last())["t"] == "table") body.append("<w:p/>")
            val pw = num(page["w"], 595.3f); val ph = num(page["h"], 841.9f)
            body.append("<w:sectPr><w:pgSz w:w=\"${tw(pw)}\" w:h=\"${tw(ph)}\"")
            if (pw > ph) body.append(" w:orient=\"landscape\"")
            body.append("/><w:pgMar w:top=\"${tw(num(page["mt"], 72f))}\" w:right=\"${tw(num(page["mr"], 72f))}\" " +
                "w:bottom=\"${tw(num(page["mb"], 72f))}\" w:left=\"${tw(num(page["ml"], 72f))}\" w:header=\"708\" " +
                "w:footer=\"708\" w:gutter=\"0\"/></w:sectPr>")
            ZipOutputStream(out).use { z ->
                fun put(name: String, text: String) { z.putNextEntry(ZipEntry(name)); z.write(text.toByteArray(Charsets.UTF_8)); z.closeEntry() }
                put("[Content_Types].xml", contentTypes())
                put("_rels/.rels", "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                    "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
                    "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>" +
                    "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties\" Target=\"docProps/core.xml\"/>" +
                    "</Relationships>")
                put("docProps/core.xml", "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                    "<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" " +
                    "xmlns:dc=\"http://purl.org/dc/elements/1.1/\"><dc:creator>BRB PDF</dc:creator></cp:coreProperties>")
                put("word/document.xml", "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                    "<w:document xmlns:w=\"$W\" xmlns:r=\"$R\" xmlns:wp=\"$WP\" xmlns:a=\"$A\" " +
                    "xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\"><w:body>$body</w:body></w:document>")
                put("word/styles.xml", styles())
                put("word/numbering.xml", numbering())
                val rels = StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                    "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
                    "<Relationship Id=\"rIdStyles\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>" +
                    "<Relationship Id=\"rIdNumbering\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering\" Target=\"numbering.xml\"/>")
                for ((rid, name, bytes) in media) {
                    rels.append("<Relationship Id=\"$rid\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/image\" Target=\"media/$name\"/>")
                    z.putNextEntry(ZipEntry("word/media/$name")); z.write(bytes); z.closeEntry()
                }
                rels.append("</Relationships>")
                put("word/_rels/document.xml.rels", rels.toString())
            }
        }

        fun contentTypes(): String = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
            "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">" +
            "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>" +
            "<Default Extension=\"xml\" ContentType=\"application/xml\"/>" +
            "<Default Extension=\"png\" ContentType=\"image/png\"/><Default Extension=\"jpeg\" ContentType=\"image/jpeg\"/>" +
            "<Default Extension=\"gif\" ContentType=\"image/gif\"/><Default Extension=\"bmp\" ContentType=\"image/bmp\"/>" +
            "<Default Extension=\"tiff\" ContentType=\"image/tiff\"/><Default Extension=\"emf\" ContentType=\"image/x-emf\"/>" +
            "<Default Extension=\"wmf\" ContentType=\"image/x-wmf\"/><Default Extension=\"webp\" ContentType=\"image/webp\"/>" +
            "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>" +
            "<Override PartName=\"/word/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml\"/>" +
            "<Override PartName=\"/word/numbering.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml\"/>" +
            "<Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/>" +
            "</Types>"

        fun blocks(items: List<Any?>, out: StringBuilder) {
            for (b in items) {
                val m = map(b)
                when (m["t"]) {
                    "table" -> table(m, out)
                    else -> para(m, out)
                }
            }
        }

        fun para(p: Map<String, Any?>, out: StringBuilder) {
            out.append("<w:p><w:pPr>")
            when (str(p["style"])) {
                "Title" -> out.append("<w:pStyle w:val=\"Title\"/>")
                "Heading1" -> out.append("<w:pStyle w:val=\"Heading1\"/>")
                "Heading2" -> out.append("<w:pStyle w:val=\"Heading2\"/>")
                "Heading3" -> out.append("<w:pStyle w:val=\"Heading3\"/>")
                else -> if (p["list"] != null) out.append("<w:pStyle w:val=\"ListParagraph\"/>")
            }
            if (bool(p["pb"])) out.append("<w:pageBreakBefore/>")
            val lst = map(p["list"])
            if (lst.isNotEmpty()) {
                val numbered = lst["type"] == "number"
                val id = (str(lst["id"]) ?: "x") + (if (numbered) "n" else "b")
                if (id !in lists) lists[id] = numbered
                val numId = lists.keys.indexOf(id) + 1
                out.append("<w:numPr><w:ilvl w:val=\"${num(lst["level"]).toInt().coerceIn(0, 8)}\"/><w:numId w:val=\"$numId\"/></w:numPr>")
            }
            out.append("<w:spacing w:before=\"${tw(num(p["before"]))}\" w:after=\"${tw(num(p["after"]))}\"")
            p["line"]?.let { out.append(" w:line=\"${Math.round(num(it, 1f) * 240)}\" w:lineRule=\"auto\"") }
            out.append("/>")
            val left = num(p["left"]); val right = num(p["right"]); val first = num(p["first"])
            if (lst.isEmpty() && (left != 0f || right != 0f || first != 0f)) {
                out.append("<w:ind w:left=\"${tw(left)}\" w:right=\"${tw(right)}\"")
                if (first > 0) out.append(" w:firstLine=\"${tw(first)}\"") else if (first < 0) out.append(" w:hanging=\"${tw(-first)}\"")
                out.append("/>")
            }
            when (p["align"]) {
                "center" -> out.append("<w:jc w:val=\"center\"/>")
                "right" -> out.append("<w:jc w:val=\"right\"/>")
                "justify" -> out.append("<w:jc w:val=\"both\"/>")
            }
            out.append("</w:pPr>")
            for (r in list(p["runs"])) run(map(r), out)
            out.append("</w:p>")
        }

        fun run(r: Map<String, Any?>, out: StringBuilder) {
            if (bool(r["br"])) { out.append("<w:r><w:br/></w:r>"); return }
            str(r["img"])?.let { picture(r, it, out); return }
            val text = str(r["text"]) ?: return
            val pr = StringBuilder()
            str(r["font"])?.let { val f = xa(it); pr.append("<w:rFonts w:ascii=\"$f\" w:hAnsi=\"$f\" w:cs=\"$f\"/>") }
            if (bool(r["b"])) pr.append("<w:b/><w:bCs/>")
            if (bool(r["i"])) pr.append("<w:i/><w:iCs/>")
            if (bool(r["s"])) pr.append("<w:strike/>")
            str(r["color"])?.takeIf { it.length == 6 && it != "000000" }?.let { pr.append("<w:color w:val=\"$it\"/>") }
            r["size"]?.let { val hp = Math.round(num(it, 11f) * 2).coerceIn(2, 3276); pr.append("<w:sz w:val=\"$hp\"/><w:szCs w:val=\"$hp\"/>") }
            if (bool(r["u"])) pr.append("<w:u w:val=\"single\"/>")
            str(r["bg"])?.takeIf { it.length == 6 && it != "FFFFFF" }?.let { pr.append("<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"$it\"/>") }
            if (bool(r["sup"])) pr.append("<w:vertAlign w:val=\"superscript\"/>")
            else if (bool(r["sub"])) pr.append("<w:vertAlign w:val=\"subscript\"/>")
            out.append("<w:r>")
            if (pr.isNotEmpty()) out.append("<w:rPr>").append(pr).append("</w:rPr>")
            val buf = StringBuilder()
            fun flush() { if (buf.isNotEmpty()) { out.append("<w:t xml:space=\"preserve\">").append(xt(buf.toString())).append("</w:t>"); buf.setLength(0) } }
            for (ch in text) when (ch) {
                '\t' -> { flush(); out.append("<w:tab/>") }
                '\n' -> { flush(); out.append("<w:br/>") }
                '\r' -> {}
                else -> buf.append(ch)
            }
            flush()
            out.append("</w:r>")
        }

        fun picture(r: Map<String, Any?>, data: String, out: StringBuilder) {
            val comma = data.indexOf(',')
            if (!data.startsWith("data:") || comma < 0) return
            val mime = data.substring(5, data.indexOf(';').takeIf { it in 0 until comma } ?: comma)
            val bytes = try { Base64.getDecoder().decode(data.substring(comma + 1)) } catch (_: Exception) { return }
            val ext = when (mime) { "image/jpeg", "image/jpg" -> "jpeg"; "image/gif" -> "gif"; "image/bmp" -> "bmp"
                "image/x-emf" -> "emf"; "image/x-wmf" -> "wmf"; "image/tiff" -> "tiff"; "image/webp" -> "webp"; else -> "png" }
            pics++
            val rid = "rIdImg$pics"
            media.add(Triple(rid, "image$pics.$ext", bytes))
            var w = num(r["w"], 100f); var h = num(r["h"], 75f)
            if (w > textWidth && textWidth > 20) { h *= textWidth / w; w = textWidth }
            val cx = Math.round(w * EMU_PER_PT); val cy = Math.round(h * EMU_PER_PT)
            out.append("<w:r><w:drawing><wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">" +
                "<wp:extent cx=\"$cx\" cy=\"$cy\"/><wp:docPr id=\"$pics\" name=\"Picture $pics\"/>" +
                "<a:graphic><a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">" +
                "<pic:pic><pic:nvPicPr><pic:cNvPr id=\"$pics\" name=\"image$pics.$ext\"/><pic:cNvPicPr/></pic:nvPicPr>" +
                "<pic:blipFill><a:blip r:embed=\"$rid\"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>" +
                "<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"$cx\" cy=\"$cy\"/></a:xfrm>" +
                "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>" +
                "</wp:inline></w:drawing></w:r>")
        }

        fun table(t: Map<String, Any?>, out: StringBuilder) {
            val rows = list(t["rows"]).map { row -> list(row).map { map(it) } }
            if (rows.isEmpty()) return
            // lay the cells on a grid (rowspan / colspan) to know the column count and continuation cells
            val occupied = HashMap<Int, MutableMap<Int, Int>>()     // row -> (col -> colspan) taken from above
            val placed = ArrayList<List<Triple<Int, Map<String, Any?>, Int>>>() // per row: (col, cell, colspan)
            var ncols = 0
            for ((ri, row) in rows.withIndex()) {
                var col = 0
                val here = ArrayList<Triple<Int, Map<String, Any?>, Int>>()
                for (cell in row) {
                    while (occupied[ri]?.containsKey(col) == true) col += occupied[ri]!![col]!!
                    val cs = num(cell["colspan"], 1f).toInt().coerceAtLeast(1)
                    val rs = num(cell["rowspan"], 1f).toInt().coerceAtLeast(1)
                    here.add(Triple(col, cell, cs))
                    for (k in 1 until rs) occupied.getOrPut(ri + k) { HashMap() }[col] = cs
                    col += cs
                }
                ncols = maxOf(ncols, col, (occupied[ri]?.keys?.maxOrNull() ?: -1) + 1)
                placed.add(here)
            }
            if (ncols == 0) return
            val given = list(t["widths"]).map { num(it) }
            val widths = if (given.size == ncols && given.all { it > 0 }) given else List(ncols) { textWidth / ncols }
            out.append("<w:tbl><w:tblPr><w:tblStyle w:val=\"TableGrid\"/><w:tblW w:w=\"0\" w:type=\"auto\"/>")
            if (t["borders"] == false) out.append("<w:tblBorders><w:top w:val=\"nil\"/><w:left w:val=\"nil\"/><w:bottom w:val=\"nil\"/>" +
                "<w:right w:val=\"nil\"/><w:insideH w:val=\"nil\"/><w:insideV w:val=\"nil\"/></w:tblBorders>")
            out.append("<w:tblLook w:val=\"04A0\" w:firstRow=\"1\" w:lastRow=\"0\" w:firstColumn=\"1\" w:lastColumn=\"0\" w:noHBand=\"0\" w:noVBand=\"1\"/></w:tblPr><w:tblGrid>")
            for (wd in widths) out.append("<w:gridCol w:w=\"${tw(wd)}\"/>")
            out.append("</w:tblGrid>")
            for ((ri, here) in placed.withIndex()) {
                out.append("<w:tr>")
                val cont = occupied[ri] ?: emptyMap<Int, Int>()
                var col = 0
                val byCol = here.associateBy { it.first }
                while (col < ncols) {
                    val c = byCol[col]
                    val span = c?.third ?: cont[col] ?: 1
                    val w = widths.subList(col, minOf(ncols, col + span)).sum()
                    out.append("<w:tc><w:tcPr><w:tcW w:w=\"${tw(w)}\" w:type=\"dxa\"/>")
                    if (span > 1) out.append("<w:gridSpan w:val=\"$span\"/>")
                    when {
                        c == null && cont.containsKey(col) -> out.append("<w:vMerge/>")
                        c != null && num(c.second["rowspan"], 1f) > 1 -> out.append("<w:vMerge w:val=\"restart\"/>")
                    }
                    str(c?.second?.get("bg"))?.takeIf { it.length == 6 }?.let { out.append("<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"$it\"/>") }
                    out.append("</w:tcPr>")
                    val inner = StringBuilder()
                    if (c != null) blocks(list(c.second["blocks"]), inner)
                    if (inner.isEmpty() || inner.endsWith("</w:tbl>")) inner.append("<w:p/>")
                    out.append(inner).append("</w:tc>")
                    col += span
                }
                out.append("</w:tr>")
            }
            out.append("</w:tbl>")
        }

        fun styles(): String {
            val base = str(doc["font"]) ?: "Calibri"
            val size = Math.round(num(doc["size"], 11f) * 2)
            fun heading(id: String, name: String, sz: Int, color: String, bold: Boolean, before: Int, after: Int, lvl: Int) =
                "<w:style w:type=\"paragraph\" w:styleId=\"$id\"><w:name w:val=\"$name\"/><w:basedOn w:val=\"Normal\"/>" +
                    "<w:next w:val=\"Normal\"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before=\"$before\" w:after=\"$after\"/>" +
                    (if (lvl >= 0) "<w:outlineLvl w:val=\"$lvl\"/>" else "") + "</w:pPr><w:rPr>" +
                    (if (bold) "<w:b/><w:bCs/>" else "") + "<w:color w:val=\"$color\"/><w:sz w:val=\"$sz\"/><w:szCs w:val=\"$sz\"/></w:rPr></w:style>"
            val fx = xa(base)
            return "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><w:styles xmlns:w=\"$W\">" +
                "<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii=\"$fx\" w:hAnsi=\"$fx\" w:cs=\"$fx\" w:eastAsia=\"$fx\"/>" +
                "<w:sz w:val=\"$size\"/><w:szCs w:val=\"$size\"/><w:lang w:val=\"en-IN\"/></w:rPr></w:rPrDefault>" +
                "<w:pPrDefault><w:pPr><w:spacing w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/></w:pPr></w:pPrDefault></w:docDefaults>" +
                "<w:style w:type=\"paragraph\" w:default=\"1\" w:styleId=\"Normal\"><w:name w:val=\"Normal\"/><w:qFormat/></w:style>" +
                "<w:style w:type=\"character\" w:default=\"1\" w:styleId=\"DefaultParagraphFont\"><w:name w:val=\"Default Paragraph Font\"/><w:uiPriority w:val=\"1\"/><w:semiHidden/></w:style>" +
                heading("Title", "Title", 52, "17365D", false, 0, 240, -1) +
                heading("Heading1", "heading 1", 32, "365F91", true, 360, 120, 0) +
                heading("Heading2", "heading 2", 26, "4F81BD", true, 200, 80, 1) +
                heading("Heading3", "heading 3", 24, "4F81BD", true, 200, 80, 2) +
                "<w:style w:type=\"paragraph\" w:styleId=\"ListParagraph\"><w:name w:val=\"List Paragraph\"/><w:basedOn w:val=\"Normal\"/><w:qFormat/><w:pPr><w:ind w:left=\"720\"/></w:pPr></w:style>" +
                "<w:style w:type=\"table\" w:default=\"1\" w:styleId=\"TableNormal\"><w:name w:val=\"Normal Table\"/><w:semiHidden/>" +
                "<w:tblPr><w:tblInd w:w=\"0\" w:type=\"dxa\"/><w:tblCellMar><w:top w:w=\"0\" w:type=\"dxa\"/><w:left w:w=\"108\" w:type=\"dxa\"/>" +
                "<w:bottom w:w=\"0\" w:type=\"dxa\"/><w:right w:w=\"108\" w:type=\"dxa\"/></w:tblCellMar></w:tblPr></w:style>" +
                "<w:style w:type=\"table\" w:styleId=\"TableGrid\"><w:name w:val=\"Table Grid\"/><w:basedOn w:val=\"TableNormal\"/>" +
                "<w:tblPr><w:tblBorders><w:top w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>" +
                "<w:left w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/><w:bottom w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>" +
                "<w:right w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/><w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>" +
                "<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/></w:tblBorders></w:tblPr></w:style>" +
                "</w:styles>"
        }

        fun numbering(): String {
            val sb = StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><w:numbering xmlns:w=\"$W\">")
            val bullets = listOf("•", "◦", "▪")
            val formats = listOf("decimal", "lowerLetter", "lowerRoman")
            for ((aid, numbered) in listOf(0 to false, 1 to true)) {
                sb.append("<w:abstractNum w:abstractNumId=\"$aid\"><w:multiLevelType w:val=\"hybridMultilevel\"/>")
                for (l in 0..8) {
                    sb.append("<w:lvl w:ilvl=\"$l\"><w:start w:val=\"1\"/>")
                    if (numbered) sb.append("<w:numFmt w:val=\"${formats[l % 3]}\"/><w:lvlText w:val=\"%${l + 1}.\"/>")
                    else sb.append("<w:numFmt w:val=\"bullet\"/><w:lvlText w:val=\"${bullets[l % 3]}\"/>")
                    sb.append("<w:lvlJc w:val=\"left\"/><w:pPr><w:ind w:left=\"${720 * (l + 1)}\" w:hanging=\"360\"/></w:pPr>")
                    if (!numbered) sb.append("<w:rPr><w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\"/></w:rPr>")
                    sb.append("</w:lvl>")
                }
                sb.append("</w:abstractNum>")
            }
            for ((k, numbered) in lists.values.withIndex()) {
                sb.append("<w:num w:numId=\"${k + 1}\"><w:abstractNumId w:val=\"${if (numbered) 1 else 0}\"/>")
                if (numbered) for (l in 0..8) sb.append("<w:lvlOverride w:ilvl=\"$l\"><w:startOverride w:val=\"1\"/></w:lvlOverride>")
                sb.append("</w:num>")
            }
            if (lists.isEmpty()) sb.append("<w:num w:numId=\"1\"><w:abstractNumId w:val=\"0\"/></w:num>")
            sb.append("</w:numbering>")
            return sb.toString()
        }

        fun tw(pt: Float): Int = Math.round(pt * 20)
    }

    /** XML text: escape and drop characters XML does not allow. */
    private fun xt(s: String): String {
        val sb = StringBuilder(s.length)
        for (ch in s) when {
            ch == '&' -> sb.append("&amp;"); ch == '<' -> sb.append("&lt;"); ch == '>' -> sb.append("&gt;")
            ch < ' ' && ch != '\t' && ch != '\n' && ch != '\r' -> {}
            ch == '￾' || ch == '￿' -> {}
            else -> sb.append(ch)
        }
        return sb.toString()
    }
    private fun xa(s: String): String = xt(s).replace("\"", "&quot;")

    /** For tests and the PC: read a .docx file's bytes. */
    fun readBytes(bytes: ByteArray, name: String = "document.docx"): Loaded = read(bytes.inputStream(), name)

    fun writeBytes(json: String): ByteArray = ByteArrayOutputStream().also { write(json, it) }.toByteArray()

    /** The editor page (assets/word/editor.html) filled with a document. */
    fun editorPage(template: String, content: String, page: Page, font: String, size: Float): String {
        val pageJson = String.format(Locale.US, "{\"w\":%.2f,\"h\":%.2f,\"ml\":%.2f,\"mt\":%.2f,\"mr\":%.2f,\"mb\":%.2f}",
            page.w, page.h, page.ml, page.mt, page.mr, page.mb)
        val base = "{\"font\":\"" + font.replace("\\", "").replace("\"", "") + "\",\"size\":" + f(size) + "}"
        return template.replace("__VIEWPORT__", Math.round(page.w * 96 / 72 + 24).toString())
            .replace("__PAGE__", pageJson).replace("__BASE__", base).replace("__CONTENT__", content)
    }
}

/** A very small JSON reader (objects, arrays, strings, numbers, true/false/null). */
object Json {
    fun parse(s: String): Any? {
        val p = P(s)
        p.ws()
        val v = p.value()
        return v
    }

    private class P(val s: String) {
        var i = 0
        fun ws() { while (i < s.length && s[i].isWhitespace()) i++ }
        fun value(): Any? {
            ws()
            if (i >= s.length) throw IllegalArgumentException("JSON ended early")
            return when (val c = s[i]) {
                '{' -> obj()
                '[' -> arr()
                '"' -> str()
                't' -> { i += 4; true }
                'f' -> { i += 5; false }
                'n' -> { i += 4; null }
                else -> if (c == '-' || c.isDigit()) number() else throw IllegalArgumentException("Bad JSON at $i")
            }
        }
        fun obj(): Map<String, Any?> {
            val m = LinkedHashMap<String, Any?>()
            i++; ws()
            if (s[i] == '}') { i++; return m }
            while (true) {
                ws(); val k = str(); ws()
                if (s[i] != ':') throw IllegalArgumentException("Bad JSON at $i")
                i++
                m[k] = value(); ws()
                when (s[i++]) { ',' -> continue; '}' -> return m; else -> throw IllegalArgumentException("Bad JSON at $i") }
            }
        }
        fun arr(): List<Any?> {
            val l = ArrayList<Any?>()
            i++; ws()
            if (s[i] == ']') { i++; return l }
            while (true) {
                l.add(value()); ws()
                when (s[i++]) { ',' -> continue; ']' -> return l; else -> throw IllegalArgumentException("Bad JSON at $i") }
            }
        }
        fun str(): String {
            if (s[i] != '"') throw IllegalArgumentException("Bad JSON at $i")
            i++
            val sb = StringBuilder()
            while (true) {
                val c = s[i++]
                when (c) {
                    '"' -> return sb.toString()
                    '\\' -> when (val e = s[i++]) {
                        'n' -> sb.append('\n'); 't' -> sb.append('\t'); 'r' -> sb.append('\r'); 'b' -> sb.append('\b')
                        'f' -> sb.append('\u000C'); 'u' -> { sb.append(s.substring(i, i + 4).toInt(16).toChar()); i += 4 }
                        else -> sb.append(e)
                    }
                    else -> sb.append(c)
                }
            }
        }
        fun number(): Double {
            val start = i
            while (i < s.length && (s[i].isDigit() || s[i] in "+-.eE")) i++
            return s.substring(start, i).toDouble()
        }
    }
}
