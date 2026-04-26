import os
import io
import re
import base64
import resend
from flask import Flask, request, jsonify
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT

app = Flask(__name__)

ALMOST_BLACK = colors.HexColor('#0F0F0F')
DARK         = colors.HexColor('#1A1A1A')
MID          = colors.HexColor('#3A3A3A')
SUBTLE       = colors.HexColor('#888888')
LIGHT_GREY   = colors.HexColor('#E8E8E8')
WARM_WHITE   = colors.HexColor('#F9F7F4')
GOLD         = colors.HexColor('#C4A97D')
WHITE        = colors.white

PAGE_W, PAGE_H = letter
MARGIN = 0.85 * inch
W = PAGE_W - 2 * MARGIN


def cover_page_canvas(canvas, doc):
    canvas.saveState()
    if doc.page == 1:
        band_h = 3.2 * inch
        canvas.setFillColor(ALMOST_BLACK)
        canvas.rect(0, PAGE_H - band_h, PAGE_W, band_h, fill=1, stroke=0)
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(0.8)
        canvas.line(MARGIN, PAGE_H - band_h, PAGE_W - MARGIN, PAGE_H - band_h)
    canvas.setFont('Times-Italic', 8)
    canvas.setFillColor(SUBTLE)
    footer_y = 0.45 * inch
    canvas.drawString(MARGIN, footer_y, doc._studio)
    canvas.drawRightString(PAGE_W - MARGIN, footer_y,
                           f"Private & Confidential · Prepared for {doc._client}")
    canvas.drawCentredString(PAGE_W / 2, footer_y, f"— {doc.page} —")
    canvas.restoreState()


def make_styles():
    s = getSampleStyleSheet()

    def add(name, **kw):
        s.add(ParagraphStyle(name=name, **kw))

    add('CoverStudio',
        fontName='Times-Roman', fontSize=9,
        textColor=GOLD, alignment=TA_CENTER, spaceAfter=6, leading=12)
    add('CoverTitle',
        fontName='Times-Bold', fontSize=28,
        textColor=WHITE, alignment=TA_CENTER, spaceAfter=8, leading=34)
    add('CoverSubtitle',
        fontName='Times-Italic', fontSize=13,
        textColor=colors.HexColor('#CCCCCC'), alignment=TA_CENTER,
        spaceAfter=4, leading=18)
    add('CoverYear',
        fontName='Times-Roman', fontSize=9,
        textColor=GOLD, alignment=TA_CENTER, spaceAfter=0, leading=12)
    add('SectionNum',
        fontName='Times-Roman', fontSize=22,
        textColor=LIGHT_GREY, alignment=TA_LEFT,
        spaceBefore=28, spaceAfter=0, leading=26)
    add('SectionTitle',
        fontName='Times-Bold', fontSize=13,
        textColor=DARK, alignment=TA_LEFT,
        spaceBefore=2, spaceAfter=10, leading=17)
    add('SubHead',
        fontName='Times-Bold', fontSize=10.5,
        textColor=MID, alignment=TA_LEFT,
        spaceBefore=12, spaceAfter=4, leading=14)
    add('Body',
        fontName='Times-Roman', fontSize=10.5,
        textColor=DARK, alignment=TA_JUSTIFY,
        leading=16.5, spaceAfter=8)
    add('BulletItem',
        fontName='Times-Roman', fontSize=10.5,
        textColor=DARK, alignment=TA_LEFT,
        leading=16, spaceAfter=4, leftIndent=16, firstLineIndent=-12)
    add('Signature',
        fontName='Times-Italic', fontSize=12,
        textColor=MID, alignment=TA_CENTER,
        leading=19, spaceBefore=16, spaceAfter=16)
    add('SignatureAttr',
        fontName='Times-Roman', fontSize=9,
        textColor=SUBTLE, alignment=TA_CENTER, spaceAfter=4)
    add('MetaLine',
        fontName='Times-Roman', fontSize=8.5,
        textColor=SUBTLE, alignment=TA_LEFT, spaceAfter=2, leading=12)
    add('FooterCity',
        fontName='Times-Roman', fontSize=9,
        textColor=SUBTLE, alignment=TA_CENTER, spaceAfter=0)
    return s


def thin_rule(color=None, width='100%', thickness=0.5):
    c = color if color else LIGHT_GREY
    return HRFlowable(width=width, thickness=thickness,
                      color=c, spaceAfter=6, spaceBefore=4)


def gold_rule():
    return HRFlowable(width='100%', thickness=0.8,
                      color=GOLD, spaceAfter=8, spaceBefore=8)


def parse_section_header(line):
    line = line.strip().lstrip('#').strip().strip('*').strip()
    m = re.match(r'^(\d+)[.)]\s+(.+)$', line)
    if m:
        num = int(m.group(1))
        title = m.group(2).strip()
        # Only treat as section header if 1-9 and short title (not a next-step item)
        if 1 <= num <= 9 and len(title) < 60:
            return m.group(1), title.title()
    return None, None


def is_table_separator(line):
    return bool(re.match(r'^[\s|:\-]+$', line))


def try_parse_budget_line(line):
    """Detect plain-text budget lines like 'Design Services: $8,000–$24,000'
    and convert them to a two-element list for table rendering."""
    # Match: Label: $X,XXX–$Y,YYY or $X,XXX - $Y,YYY or $X,XXX – $Y,YYY
    m = re.match(r'^(.{3,80}):\s+(\$[\d,]+\s*[\u2013\u2014-]+\s*\$[\d,]+.*)$', line)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    # Match total/single dollar lines: Label: $XX,XXX
    m2 = re.match(r'^(.{3,80}):\s+(\$[\d,]+.{0,30})$', line)
    if m2 and not m2.group(1).strip().startswith('http'):
        return [m2.group(1).strip(), m2.group(2).strip()]
    return None


def parse_table_row(line):
    parts = [c.strip() for c in line.strip().strip('|').split('|')]
    return [p for p in parts if p]


def build_investment_table(rows):
    if not rows:
        return None
    data = []
    for row in rows:
        if len(row) == 1:
            data.append([row[0], ''])
        else:
            data.append(row[:2])
    col_w = [W * 0.62, W * 0.38]
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), ALMOST_BLACK),
        ('TEXTCOLOR',     (0, 0), (-1, 0), WHITE),
        ('FONTNAME',      (0, 0), (-1, 0), 'Times-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0), 9),
        ('ALIGN',         (1, 0), (1, 0),  'RIGHT'),
        ('TOPPADDING',    (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('FONTNAME',      (0, 1), (-1, -1), 'Times-Roman'),
        ('FONTSIZE',      (0, 1), (-1, -1), 10),
        ('TEXTCOLOR',     (0, 1), (-1, -1), DARK),
        ('ALIGN',         (1, 1), (1, -1),  'RIGHT'),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [WHITE, WARM_WHITE]),
        ('FONTNAME',      (0, -1), (-1, -1), 'Times-Bold'),
        ('TEXTCOLOR',     (0, -1), (-1, -1), ALMOST_BLACK),
        ('LINEABOVE',     (0, -1), (-1, -1), 0.8, GOLD),
        ('GRID',          (0, 0), (-1, -1), 0.3, LIGHT_GREY),
        ('LINEBELOW',     (0, 0), (-1, 0),  1,   GOLD),
        ('TOPPADDING',    (0, 1), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 7),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
    ]))
    return t


def build_pdf(proposal_text, designer_name, client_name, city, designer_email=''):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=MARGIN, leftMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=0.85 * inch,
    )
    doc._studio = f"{designer_name} Studio"
    doc._client = client_name

    S = make_styles()
    story = []

    # Cover band content
    story.append(Spacer(1, 0.35 * inch))
    story.append(Paragraph(designer_name.upper(), S['CoverStudio']))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Interior Design", S['CoverSubtitle']))
    story.append(Paragraph("Proposal", S['CoverTitle']))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Prepared exclusively for {client_name}", S['CoverSubtitle']))
    story.append(Paragraph(f"{city} Residence", S['CoverSubtitle']))
    story.append(Spacer(1, 6))
    story.append(Paragraph("2026", S['CoverYear']))
    story.append(Spacer(1, 1.6 * inch))

    story.append(Paragraph(
        f"{designer_name} Studio &nbsp;·&nbsp; Private &amp; Confidential &nbsp;·&nbsp; "
        f"Prepared for {client_name}", S['MetaLine']))
    story.append(thin_rule())
    story.append(Spacer(1, 16))

    lines = proposal_text.splitlines()
    i = 0
    table_rows = []
    section_counter = 0
    in_investment_section = False

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1

        if not line:
            if table_rows:
                t = build_investment_table(table_rows)
                if t:
                    story.append(t)
                    story.append(Spacer(1, 12))
                table_rows = []
            continue

        num, title = parse_section_header(line)
        if num:
            if table_rows:
                t = build_investment_table(table_rows)
                if t:
                    story.append(t)
                    story.append(Spacer(1, 12))
                table_rows = []
            section_counter += 1
            num_str = str(section_counter).zfill(2)
            # Track when we enter the investment section
            in_investment_section = ('investment' in title.lower() or
                                     'budget' in title.lower())
            story.append(Spacer(1, 6))
            story.append(thin_rule())
            story.append(Paragraph(num_str, S['SectionNum']))
            story.append(Paragraph(title, S['SectionTitle']))
            # Add table header row automatically for investment section
            if in_investment_section:
                table_rows = [['Category', 'Estimated Range']]
            continue

        if line.startswith('**') and line.endswith('**'):
            story.append(Paragraph(line.strip('*').strip().title(), S['SubHead']))
            continue

        if line.isupper() and 2 < len(line) < 60 and '|' not in line:
            story.append(Paragraph(line.title(), S['SubHead']))
            continue

        if re.match(r'^[-=]{3,}$', line):
            continue

        if '|' in line:
            if not is_table_separator(line):
                row = parse_table_row(line)
                if row:
                    table_rows.append(row)
            continue

        if table_rows:
            t = build_investment_table(table_rows)
            if t:
                story.append(t)
                story.append(Spacer(1, 12))
            table_rows = []

        if line.startswith('*') and line.endswith('*') and not line.startswith('**'):
            story.append(Spacer(1, 8))
            story.append(thin_rule(width='60%'))
            story.append(Paragraph(line.strip('*').strip(), S['Signature']))
            story.append(Paragraph(f"— {designer_name}", S['SignatureAttr']))
            story.append(thin_rule(width='60%'))
            continue

        if line.startswith(('- ', '• ', '* ')):
            story.append(Paragraph('— &nbsp;' + line[2:], S['BulletItem']))
            continue

        # Auto-detect plain budget lines in investment section
        if in_investment_section:
            # Skip the recommendation sentence
            if 'recommend positioning' in line.lower():
                story.append(Paragraph(line, S['Body']))
                continue
            # Skip lines that look like table headers (Category / Estimated Range)
            if re.match(r'^category\s+estimated', line.lower()):
                continue
            # Skip pure description lines that follow a budget row (no $ sign, short)
            budget_row = try_parse_budget_line(line)
            if budget_row:
                table_rows.append(budget_row)
                continue
            # If it's a short descriptor line after a budget line, skip it
            if table_rows and len(table_rows) > 1 and '$' not in line and len(line) < 120:
                continue

        story.append(Paragraph(line, S['Body']))

    if table_rows:
        t = build_investment_table(table_rows)
        if t:
            story.append(t)
            story.append(Spacer(1, 12))

    story.append(Spacer(1, 24))
    story.append(gold_rule())
    story.append(Paragraph(
        f"{designer_name} Studio &nbsp;·&nbsp; {city}", S['FooterCity']))
    if designer_email:
        story.append(Paragraph(designer_email, S['FooterCity']))

    doc.build(story, onFirstPage=cover_page_canvas, onLaterPages=cover_page_canvas)
    buffer.seek(0)
    return buffer.read()


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No JSON body"}), 400

        proposal_text   = data.get('proposal_text', '')
        designer        = data.get('designer', 'Your Designer')
        client          = data.get('client', 'Valued Client')
        city            = data.get('city', '')
        recipient_email = data.get('recipient_email', '')

        if not recipient_email:
            return jsonify({"error": "recipient_email required"}), 400

        designer_email = recipient_email

        pdf_bytes = build_pdf(proposal_text, designer, client, city, designer_email)
        pdf_b64   = base64.b64encode(pdf_bytes).decode('utf-8')

        resend.api_key = os.environ.get('RESEND_API_KEY', '')
        from_email     = os.environ.get('FROM_EMAIL', 'onboarding@resend.dev')

        filename = (f"Proposal_{client.replace(' ', '_')}"
                    f"_{city.replace(' ', '_')}.pdf")

        params = {
            "from": from_email,
            "to":   ["vanshgupta0004@gmail.com"],
            "subject": (f"Your Interior Design Proposal — "
                        f"{client}, {city} | {designer_email}"),
            "html": f"""
<div style="font-family:Georgia,serif;max-width:600px;margin:0 auto;color:#1a1a1a;line-height:1.7;">
  <div style="background:#0F0F0F;padding:32px 36px 28px;margin-bottom:24px;">
    <p style="color:#C4A97D;font-size:10px;letter-spacing:3px;margin:0 0 8px;text-transform:uppercase;">{designer.upper()} STUDIO</p>
    <h1 style="color:#ffffff;font-size:22px;margin:0 0 6px;font-weight:normal;font-style:italic;">Your proposal is ready.</h1>
    <p style="color:#AAAAAA;font-size:13px;margin:0;">Prepared for <strong style="color:#fff;">{client}</strong> · {city}</p>
  </div>
  <p style="padding:0 4px;">Please find attached your bespoke interior design proposal. This document outlines the full design vision, room-by-room direction, investment breakdown, and project timeline.</p>
  <p style="color:#555;font-size:13px;padding:0 4px;">If you have any questions, simply reply to this email.</p>
  <hr style="border:none;border-top:1px solid #C4A97D;margin:24px 0;"/>
  <p style="font-style:italic;color:#999;font-size:12px;padding:0 4px;">{designer} Studio · Powered by Vansh Craft</p>
</div>""",
            "attachments": [{
                "filename": filename,
                "content":  pdf_b64,
            }],
        }

        resend.Emails.send(params)
        return jsonify({"status": "sent", "to": "vanshgupta0004@gmail.com",
                        "designer": designer_email}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
