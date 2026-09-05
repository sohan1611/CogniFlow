"""Shared ReportLab styling for the two recording documents.

    pip install reportlab
    python scripts/docs_pdf/build.py

Not a project dependency: reportlab is needed only to regenerate the PDFs in docs/,
never at runtime, so it stays out of requirements.txt.

Two hard-won constraints live here rather than at the call sites, because both fail
silently and are only visible once someone opens the finished page:

  * No Unicode arrows, ticks or emoji. The built-in fonts are WinAnsi, and any glyph
    outside that encoding renders as a solid black box.
  * Every table cell must be a Paragraph. ReportLab wraps Paragraphs and does NOT wrap
    bare strings -- a long string runs past its column, over the next one, and off the
    page edge, with no warning.
"""

from __future__ import annotations

import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

INK = colors.HexColor("#10213A")
DEEP = colors.HexColor("#065A82")
TEAL = colors.HexColor("#1C7293")
MUTE = colors.HexColor("#4A5A6B")
WASH = colors.HexColor("#EEF4F8")
WARN = colors.HexColor("#B85042")
GOOD = colors.HexColor("#1F7A5C")
RULE = colors.HexColor("#D5E0E8")
SCRIPTBG = colors.HexColor("#F7FAFC")

FRAME_W = A4[0] - 40 * mm


def S(name, **kw):
    base = dict(fontName="Helvetica", fontSize=10, leading=14.5, textColor=INK,
                alignment=TA_LEFT, spaceAfter=6)
    base.update(kw)
    return ParagraphStyle(name, **base)


H1 = S("H1", fontName="Helvetica-Bold", fontSize=19, leading=23, spaceAfter=10)
H2 = S("H2", fontName="Helvetica-Bold", fontSize=13.5, leading=17, textColor=DEEP,
       spaceBefore=14, spaceAfter=6)
H3 = S("H3", fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=9,
       spaceAfter=3)
BODY = S("BODY")
SMALL = S("SMALL", fontSize=9, leading=12.5, textColor=MUTE)
LEAD = S("LEAD", fontSize=11, leading=16, textColor=MUTE, spaceAfter=9)
BULLET = S("BULLET", leftIndent=11, bulletIndent=2, spaceAfter=3.5)
SAY = S("SAY", fontName="Helvetica-Oblique", fontSize=10, leading=14.5, textColor=DEEP,
        leftIndent=10, spaceAfter=5)
CODE = S("CODE", fontName="Courier", fontSize=8.6, leading=11.6, leftIndent=6,
         spaceAfter=4)
SPEAK = S("SPEAK", fontSize=12, leading=18.5, spaceAfter=9)
DO = S("DO", fontName="Helvetica-Bold", fontSize=9.5, leading=13, textColor=WARN,
       spaceAfter=4)

_TAG = re.compile(r"</?(?:b|i|br|font|sub|super)\b[^>]*/?>", re.IGNORECASE)
_ENTITY = re.compile(r"&(?:amp|lt|gt|nbsp|#\d+);")


def markup_safe(text: str) -> str:
    """Escape ampersands and stray angle brackets without breaking real tags.

    Cell text mixes prose with intentional markup. A bare '&' -- as in 'Q&A' -- makes
    the parser drop the whole paragraph, and a stray '<' swallows everything after it.
    """
    spans = [m.span() for m in _TAG.finditer(text)]
    spans += [m.span() for m in _ENTITY.finditer(text)]
    out, i = [], 0
    for start, end in sorted(spans):
        if start < i:
            continue
        out.append(text[i:start].replace("&", "&amp;").replace("<", "&lt;"))
        out.append(text[start:end])
        i = end
    out.append(text[i:].replace("&", "&amp;").replace("<", "&lt;"))
    return "".join(out)


class Doc:
    def __init__(self, path, title, footer_text):
        self.story = []
        self.path = path
        self.title = title
        self.footer_text = footer_text

    def p(self, t, s=BODY):
        self.story.append(Paragraph(t, s))

    def h1(self, t):
        self.story.append(Paragraph(t, H1))

    def h2(self, t):
        self.story.append(Paragraph(t, H2))

    def h3(self, t):
        self.story.append(Paragraph(t, H3))

    def gap(self, h=5):
        self.story.append(Spacer(1, h))

    def pagebreak(self):
        self.story.append(PageBreak())

    def bullets(self, items, style=BULLET):
        for it in items:
            self.story.append(Paragraph(it, style, bulletText="•"))

    def table(self, rows, widths, header=True, fill=WASH, fontsize=9):
        cell = S("cell", fontSize=fontsize, leading=fontsize * 1.32, spaceAfter=0)
        head = S("cellhead", fontName="Helvetica-Bold", fontSize=fontsize,
                 leading=fontsize * 1.32, spaceAfter=0)
        wrapped = [
            [c if hasattr(c, "wrap")
             else Paragraph(markup_safe(str(c)), head if (header and r == 0) else cell)
             for c in row]
            for r, row in enumerate(rows)
        ]
        t = Table(wrapped, colWidths=widths, hAlign="LEFT")
        style = [
            ("TEXTCOLOR", (0, 0), (-1, -1), INK),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, RULE),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), fill))
        t.setStyle(TableStyle(style))
        self.story.append(t)
        self.gap(7)

    def callout(self, title, text, colour=TEAL, bg=WASH):
        inner = [[Paragraph(f"<b>{title}</b><br/><br/>{text}",
                            S("cal", fontSize=9.5, leading=13.5))]]
        t = Table(inner, colWidths=[165 * mm], hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX", (0, 0), (-1, -1), 0.8, colour),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        self.story.append(KeepTogether([t, Spacer(1, 8)]))

    def code(self, lines):
        for ln in lines:
            self.p(ln.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                     .replace(" ", "&nbsp;"), CODE)
        self.gap(4)

    def speech(self, paragraphs):
        """The words read aloud: tinted, boxed, and larger than everything around them."""
        cells = [[Paragraph(t, SPEAK)] for t in paragraphs]
        t = Table(cells, colWidths=[165 * mm], hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SCRIPTBG),
            ("BOX", (0, 0), (-1, -1), 1.0, DEEP),
            ("LEFTPADDING", (0, 0), (-1, -1), 11),
            ("RIGHTPADDING", (0, 0), (-1, -1), 11),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
        self.story.append(t)
        self.gap(8)

    def check_layout(self) -> list[str]:
        """Measure instead of looking: there is no renderer on the build machine.

        Catches the two faults a text-extraction check cannot see -- a table wider than
        the printable frame, and a single unbreakable token too wide for its column
        (wrapping cannot rescue a token that does not fit alone).
        """
        from reportlab.pdfbase.pdfmetrics import stringWidth

        problems: list[str] = []
        for idx, item in enumerate(self.story):
            if not isinstance(item, Table):
                continue
            width, _ = item.wrap(FRAME_W, A4[1])
            if width > FRAME_W + 0.75:
                problems.append(
                    f"table #{idx}: {width:.1f}pt wide, frame is {FRAME_W:.1f}pt")
            cols = item._colWidths or []
            for r, row in enumerate(item._cellvalues):
                for c, cellv in enumerate(row):
                    if not isinstance(cellv, Paragraph) or c >= len(cols):
                        continue
                    avail = (cols[c] or 0) - 12
                    plain = re.sub(r"<[^>]+>", "", cellv.text or "")
                    for tok in plain.split():
                        w = stringWidth(tok, cellv.style.fontName, cellv.style.fontSize)
                        if w > avail + 0.75:
                            problems.append(
                                f"table #{idx} cell ({r},{c}): token {tok!r} is "
                                f"{w:.1f}pt in a {avail:.1f}pt column")
        return problems

    def build(self):
        problems = self.check_layout()
        for prob in problems:
            print(f"  OVERFLOW  {prob}")
        if not problems:
            print("  layout: PASS")

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(MUTE)
            canvas.drawString(20 * mm, 12 * mm, self.footer_text)
            canvas.drawRightString(190 * mm, 12 * mm, f"Page {doc.page}")
            canvas.setStrokeColor(RULE)
            canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
            canvas.restoreState()

        doc = BaseDocTemplate(
            self.path, pagesize=A4, title=self.title, author="Team BloodCoded",
            leftMargin=20 * mm, rightMargin=20 * mm,
            topMargin=18 * mm, bottomMargin=20 * mm,
        )
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
        doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=footer)])
        doc.build(self.story)
        print(f"  wrote {self.path}")
