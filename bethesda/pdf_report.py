"""PDF lab report: actual values vs reference (safe) limits, with a visual range bar."""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Flowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from .ranges import FLAG_LABEL, _num, range_text

BRAND = colors.HexColor("#0b5e7e")
LIGHT = colors.HexColor("#e8f3f7")
RED = colors.HexColor("#c0392b")
BLUE = colors.HexColor("#1f6fb2")
OK_GREEN = colors.HexColor("#5cb85c")
ZONE = colors.HexColor("#f3d6d2")

ss = getSampleStyleSheet()
S_CELL = ParagraphStyle("cell", parent=ss["Normal"], fontSize=8.5, leading=10.5)
S_CELL_B = ParagraphStyle("cellb", parent=S_CELL, fontName="Helvetica-Bold")
S_SMALL = ParagraphStyle("small", parent=S_CELL, fontSize=7.5, leading=9, textColor=colors.HexColor("#555555"))
S_HEAD = ParagraphStyle("head", parent=S_CELL, fontName="Helvetica-Bold", textColor=colors.white)
S_TEST = ParagraphStyle("test", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=10.5,
                        textColor=BRAND, spaceBefore=8, spaceAfter=3)
S_TITLE = ParagraphStyle("title", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=12,
                         alignment=TA_CENTER, spaceBefore=4, spaceAfter=6)
S_SIGN = ParagraphStyle("sign", parent=S_CELL, alignment=TA_CENTER)
S_RIGHT = ParagraphStyle("right", parent=S_CELL, alignment=TA_RIGHT)


def P(text, style=S_CELL):
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


class RangeBar(Flowable):
    """Horizontal bar: red zones = outside limits, green = within, black marker = patient value."""

    def __init__(self, value, low, high, flag, width=4.4 * cm, height=0.42 * cm):
        super().__init__()
        self.value, self.low, self.high, self.flag = value, low, high, flag
        self.width, self.height = width, height

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        v, lo, hi = self.value, self.low, self.high
        if v is None or (lo is None and hi is None):
            return
        c = self.canv
        # Build a display scale that always shows the normal band in the middle.
        if lo is not None and hi is not None:
            span = (hi - lo) or abs(hi) or 1
            dmin, dmax = lo - span * 0.5, hi + span * 0.5
        elif hi is not None:  # only an upper limit, e.g. "< 200"
            lo_eff = 0.0 if hi > 0 else hi - abs(hi or 1)
            dmin, dmax = lo_eff, hi * 1.6 if hi > 0 else hi + abs(hi or 1)
        else:  # only a lower limit, e.g. "> 40"
            dmin, dmax = 0.0 if lo > 0 else lo - abs(lo or 1), lo * 2.2 if lo > 0 else lo + abs(lo or 1)
        dmin = min(dmin, v)
        dmax = max(dmax, v)
        if dmax == dmin:
            dmax = dmin + 1
        w, h = self.width, self.height
        bar_y, bar_h = h * 0.3, h * 0.4

        def x(val):
            return (val - dmin) / (dmax - dmin) * w

        c.setStrokeColor(colors.white)
        c.setFillColor(ZONE)
        c.rect(0, bar_y, w, bar_h, stroke=0, fill=1)
        nlo = x(lo) if lo is not None else 0
        nhi = x(hi) if hi is not None else w
        c.setFillColor(OK_GREEN)
        c.rect(nlo, bar_y, max(nhi - nlo, 1), bar_h, stroke=0, fill=1)
        # marker
        mx = x(v)
        c.setFillColor(RED if self.flag else colors.black)
        c.setStrokeColor(colors.white)
        p = c.beginPath()
        p.moveTo(mx, bar_y - 1)
        p.lineTo(mx - 3, 0)
        p.lineTo(mx + 3, 0)
        p.close()
        c.drawPath(p, stroke=0, fill=1)
        c.rect(mx - 0.8, bar_y - 1, 1.6, bar_h + 2.5, stroke=0, fill=1)


def _header_footer(settings, patient, visit, logo_path=None):
    logo = ImageReader(logo_path) if logo_path else None

    def draw(canvas, doc):
        canvas.saveState()
        w, h = A4
        # Header band
        canvas.setFillColor(BRAND)
        canvas.rect(0, h - 2.6 * cm, w, 2.6 * cm, stroke=0, fill=1)
        x = 1.5 * cm
        if logo:
            iw, ih = logo.getSize()
            box_h = 2.0 * cm
            box_w = min(box_h * iw / ih + 0.3 * cm, 5.0 * cm)
            canvas.setFillColor(colors.white)
            canvas.roundRect(x - 0.15 * cm, h - 2.3 * cm, box_w, box_h, 4, stroke=0, fill=1)
            canvas.drawImage(logo, x, h - 2.2 * cm, width=box_w - 0.3 * cm, height=box_h - 0.2 * cm,
                             preserveAspectRatio=True, anchor="c", mask="auto")
            x += box_w + 0.3 * cm
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 20)
        canvas.drawString(x, h - 1.35 * cm, settings["lab_name"])
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, h - 1.9 * cm, settings.get("lab_tagline", ""))
        canvas.drawRightString(w - 1.5 * cm, h - 1.15 * cm, settings.get("lab_address", ""))
        canvas.drawRightString(w - 1.5 * cm, h - 1.6 * cm,
                               f"Ph: {settings.get('lab_phone', '')}   {settings.get('lab_email', '')}")
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawRightString(w - 1.5 * cm, h - 2.15 * cm,
                               f"{patient['name']}  |  {visit['visit_no']}")
        # Footer
        canvas.setStrokeColor(colors.HexColor("#bbbbbb"))
        canvas.line(1.5 * cm, 1.55 * cm, w - 1.5 * cm, 1.55 * cm)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(1.5 * cm, 1.15 * cm, settings.get("report_footer", "")[:150])
        canvas.drawRightString(w - 1.5 * cm, 0.8 * cm, f"Page {doc.page}")
        canvas.drawString(1.5 * cm, 0.8 * cm, "This is a computer generated report.")
        canvas.restoreState()
    return draw


def build_report(settings, visit, patient, referred_by, sections, draft=False, approval=None,
                 logo_path=None, signature_path=None):
    """
    sections: list of dicts {name, sample_type, rows:[{name, value, unit, low, high,
                                                        ref_text, normal_value, flag}]}
    Returns PDF bytes.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=3.0 * cm, bottomMargin=2.0 * cm,
                            title=f"Lab Report {visit['visit_no']}", author=settings["lab_name"])
    story = []

    age = f"{patient['age']} {patient['age_unit']}" if patient["age"] is not None else "-"
    info = [
        [P("Patient Name", S_CELL_B), P(patient["name"]), P("Visit / Sample No.", S_CELL_B), P(visit["visit_no"])],
        [P("Age / Gender", S_CELL_B), P(f"{age} / {patient['gender'] or '-'}"),
         P("Patient ID", S_CELL_B), P(patient["patient_no"])],
        [P("Referred By", S_CELL_B), P(referred_by), P("Registered On", S_CELL_B), P(visit["visit_date"])],
        [P("Phone", S_CELL_B), P(patient["phone"] or "-"), P("Collected On", S_CELL_B),
         P(visit["sample_collected_at"] or visit["visit_date"])],
        [P("", S_CELL_B), P(""), P("Reported On", S_CELL_B), P(visit["reported_at"] or "-")],
    ]
    t = Table(info, colWidths=[3.0 * cm, 6.0 * cm, 3.4 * cm, 5.6 * cm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BRAND),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    title = "LABORATORY TEST REPORT"
    if draft:
        title += " - DRAFT (NOT APPROVED)"
    elif approval and approval["version"] > 1:
        title = f"AMENDED LABORATORY TEST REPORT (Version {approval['version']})"
    story += [t, Paragraph(title, S_TITLE)]
    if approval and approval.get("superseded"):
        story.append(Paragraph("<font color='#c0392b'><b>This version has been superseded by a later amended "
                               "report. Do not use for clinical decisions.</b></font>", S_CELL))
    if approval and approval.get("amend_reason"):
        story.append(Paragraph(f"<b>Reason for amendment:</b> {escape(approval['amend_reason'])}", S_CELL))
        story.append(Spacer(1, 4))

    # Summary of out-of-range values
    abnormal = [(s["name"], r) for s in sections for r in s["rows"] if r["flag"]]
    total = sum(1 for s in sections for r in s["rows"] if str(r["value"] or "").strip())
    if total:
        if abnormal:
            items = ", ".join(f"{escape(r['name'])} ({FLAG_LABEL[r['flag']]})" for _, r in abnormal)
            summary = (f"<b>Summary:</b> <font color='#c0392b'><b>{len(abnormal)}</b></font> of {total} "
                       f"parameters are outside the reference range: {items}.")
        else:
            summary = f"<b>Summary:</b> All {total} reported parameters are within the reference range."
        story += [Paragraph(summary, S_CELL), Spacer(1, 4)]

    col_w = [5.0 * cm, 2.3 * cm, 2.1 * cm, 3.8 * cm, 4.8 * cm]
    for s in sections:
        rows = [r for r in s["rows"] if str(r["value"] or "").strip()]
        if not rows:
            continue
        data = [[P("Investigation", S_HEAD), P("Result", S_HEAD), P("Unit", S_HEAD),
                 P("Reference Range", S_HEAD), P("Result vs Range", S_HEAD)]]
        styles = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i, r in enumerate(rows, start=1):
            flag = r["flag"]
            val = escape(str(r["value"]))
            if flag:
                color = "#1f6fb2" if flag == "L" else "#c0392b"
                val_p = Paragraph(f"<font color='{color}'><b>{val} {flag}</b></font>", S_CELL)
                styles.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fdf1ef")))
            else:
                val_p = Paragraph(val, S_CELL)
            data.append([
                P(r["name"]), val_p, P(r["unit"]),
                P(range_text(r["low"], r["high"], r["ref_text"], r["normal_value"]), S_SMALL),
                RangeBar(_num(r["value"]), r["low"], r["high"], flag),
            ])
        tbl = Table(data, colWidths=col_w, repeatRows=1)
        tbl.setStyle(TableStyle(styles))
        title = f"{escape(s['name'])}"
        if s.get("sample_type"):
            title += f" <font size=8 color='#777777'>(Sample: {escape(s['sample_type'])})</font>"
        story.append(KeepTogether([Paragraph(title, S_TEST), tbl]) if len(rows) < 18
                     else Table([[Paragraph(title, S_TEST)], [tbl]]))

    remarks = approval["remarks"] if approval else visit["remarks"]
    if remarks:
        story += [Spacer(1, 8), Paragraph(f"<b>Remarks:</b> {escape(remarks)}", S_CELL)]

    story += [Spacer(1, 6), Paragraph(
        "<font color='#555555'>Legend: <b>H</b> = above reference range, <b>L</b> = below, "
        "<b>A</b> = abnormal finding. Bar: green = reference range, red = outside, marker = your result."
        "</font>", S_SMALL)]
    story.append(Paragraph("<para alignment='center'>*** End of Report ***</para>", S_SMALL))

    path_cell = [P(f"{settings.get('pathologist_name', '')}\n{settings.get('pathologist_qualification', '')}\n"
                   f"Consultant Pathologist", S_SIGN)]
    if signature_path and not draft:
        ir = ImageReader(signature_path)
        iw, ih = ir.getSize()
        sh = 1.3 * cm
        path_cell.insert(0, Image(signature_path, width=min(sh * iw / ih, 6 * cm), height=sh))
    sign = Table([[P(f"{settings.get('technician_name', '')}\nLab Technician", S_SIGN), path_cell]],
                 colWidths=[9 * cm, 9 * cm])
    sign.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 4 if signature_path and not draft else 30),
                              ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    block = [Spacer(1, 10), sign]
    if approval:
        block.append(Paragraph(f"<para alignment='center'>Electronically approved by {escape(approval['approved_by'])}"
                               f" on {escape(approval['approved_at'])}</para>", S_SMALL))
    story.append(KeepTogether(block))

    hf = _header_footer(settings, patient, visit, logo_path)
    if draft:
        def watermark():  # drawn after the page content, so it shows over table backgrounds
            c = doc.canv
            c.saveState()
            c.setFillColor(colors.Color(0.75, 0.2, 0.15, alpha=0.18))
            c.setFont("Helvetica-Bold", 90)
            c.translate(A4[0] / 2, A4[1] / 2)
            c.rotate(35)
            c.drawCentredString(0, 0, "DRAFT")
            c.restoreState()
        doc.afterPage = watermark
    doc.build(story, onFirstPage=hf, onLaterPages=hf)
    return buf.getvalue()


def build_receipt(settings, visit, patient, referred_by, lines, logo_path=None):
    """Simple payment receipt / invoice. lines: list of (description, amount)."""
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=3.0 * cm, bottomMargin=2.0 * cm,
                            title=f"Receipt {visit['visit_no']}")
    cur = settings.get("currency", "Rs.")
    story = [Paragraph("PAYMENT RECEIPT", S_TITLE)]
    info = [
        [P("Patient", S_CELL_B), P(patient["name"]), P("Receipt / Visit No.", S_CELL_B), P(visit["visit_no"])],
        [P("Patient ID", S_CELL_B), P(patient["patient_no"]), P("Date", S_CELL_B), P(visit["visit_date"])],
        [P("Referred By", S_CELL_B), P(referred_by), P("Payment Mode", S_CELL_B), P(visit["payment_mode"] or "-")],
    ]
    t = Table(info, colWidths=[3.0 * cm, 6.0 * cm, 3.4 * cm, 5.6 * cm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, BRAND), ("BACKGROUND", (0, 0), (-1, -1), LIGHT)]))
    story += [t, Spacer(1, 10)]
    data = [[P("#", S_HEAD), P("Description", S_HEAD), P(f"Amount ({cur})", S_HEAD)]]
    for i, (desc, amt) in enumerate(lines, 1):
        data.append([P(i), P(desc), P(f"{amt:,.2f}", S_RIGHT)])
    for label, amt in [("Gross Total", visit["gross_amount"]), ("Discount", -visit["discount"]),
                       ("Net Payable", visit["net_amount"]), ("Paid", visit["paid_amount"]),
                       ("Balance Due", visit["net_amount"] - visit["paid_amount"])]:
        data.append(["", P(label, S_CELL_B), P(f"{amt:,.2f}", S_RIGHT)])
    tbl = Table(data, colWidths=[1.2 * cm, 12.3 * cm, 4.5 * cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ("LINEABOVE", (1, len(lines) + 1), (-1, len(lines) + 1), 0.8, BRAND),
    ]))
    story.append(tbl)
    hf = _header_footer(settings, patient, visit, logo_path)
    doc.build(story, onFirstPage=hf, onLaterPages=hf)
    return buf.getvalue()
