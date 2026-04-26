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
                                 TableStyle, HRFlowable, KeepTogether)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT

app = Flask(__name__)

# ── Colour palette ──────────────────────────────────────────────
GOLD        = colors.HexColor('#B8960C')
GOLD_LIGHT  = colors.HexColor('#F5E6A3')
GOLD_ROW    = colors.HexColor('#FAF7EE')
DARK        = colors.HexColor('#1A1A1A')
MID         = colors.HexColor('#444444')
SUBTLE      = colors.HexColor('#777777')
RULE        = colors.HexColor('#D4B86A')
WHITE       = colors.white

W = letter[0] - 1.7 * inch   # usable text width


def make_styles():
    s = getSampleStyleSheet()

    def add(name, **kw):
        s.add(ParagraphStyle(name=name, **kw))

    add('StudioName',
        fontName='Times-BoldItalic', fontSize=10,
        textColor=GOLD, alignment=TA_CENTER, spaceAfter=6)

    add('DocTitle',
        fontName='Times-Bold', fontSize=26,
        textColor=DARK, alignment=TA_CENTER, spaceAfter=6)

    add('ClientLine',
        fontName='Times-Italic', fontSize=12,
        textColor=MID, alignment=TA_CENTER, spaceAfter=4)

    add('CityLine',
        fontName='Times-Roman', fontSize=10,
        textColor=SUBTLE, alignment=TA_CENTER, spaceAfter=20)

    add('SectionNum',
        fontName='Times-Bold', fontSize=8,
        textColor=GOLD, alignment=TA_LEFT, spaceBefore=22, spaceAfter=2,
        leading=10)

    add('SectionTitle',
        fontName='Times-Bold', fontSize=14,
        textColor=DARK, alignment=TA_LEFT, spaceBefore=2, spaceAfter=8,
        leading=18)

    add('SubHead',
        fontName='Times-Bold', fontSize=10.5,
        textColor=GOLD, alignment=TA_LEFT, spaceBefore=10, spaceAfter=4,
        leading=14)

    add('Body',
        fontName='Times-Roman', fontSize=10,
        textColor=DARK, alignment=TA_JUSTIFY,
        leading=15.5, spaceAfter=6)

    add('BulletItem',
        fontName='Times-Roman', fontSize=10,
        textColor=DARK, alignment=TA_LEFT,
        leading=15, spaceAfter=3, leftIndent=14, firstLineIndent=-10)

    add('Signature',
        fontName='Times-Italic', fontSize=11.5,
        textColor=MID, alignment=TA_CENTER,
        leading=18, spaceBefore=14, spaceAfter=14)

    add('PreparedBy',
        fontName='Times-Roman', fontSize=9,
        textColor=SUBTLE, alignment=TA_LEFT, spaceAfter=2)

    return s


def gold_rule(full=True):
    w = '100%' if full else '35%'
    return HRFlowable(width=w, thickness=0.8, color=RULE, spaceAfter=6, spaceBefore=2)


def section_rule():
    return HRFlowable(width='100%', thickness=0.4,
                      color=colors.HexColor('#E8E0CC'),
                      spaceAfter=4, spaceBefore=0)


def parse_section_header(line):
    """
    Accepts lines like:
      '1. DESIGN VISION'
      '**1. Design Vision**'
      '## 1. Design Vision'
    Returns (number_str, title_str) or (None, None).
    """
    line = line.strip().lstrip('#').strip()
    line = line.strip('*').strip()
    m = re.match(r'^(\d+)[.)]\s+(.+)$', line)
    if m:
        return m.group(1), m.group(2).title()
    return None, None


def is_table_separator(line):
    return bool(re.match(r'^[\s|:\-]+$', line))


def parse_table_row(line):
    parts = [c.strip() for c in line.strip().strip('|').split('|')]
    return [p for p in parts if p]


def build_investment_table(rows):
    """Render the investment breakdown as a styled two-column table."""
    data = []
    for row in rows:
        if len(row) == 1:
            data.append([row[0], ''])
        else:
            data.append(row[:2])

    if not data:
        return None

    col_w = [W * 0.65, W * 0.35]
    t = Table(data, colWidths=col_w, repeatRows=1)

    style = [
        # header row
        ('BACKGROUND',   (0, 0), (-1, 0), GOLD),
        ('TEXTCOLOR',    (0, 0), (-1, 0), WHITE),
        ('FONTNAME',     (0, 0), (-1, 0), 'Times-Bold'),
        ('FONTSIZE',     (0, 0), (-1, 0), 10),
        ('ALIGN',        (1, 0), (1, 0),  'RIGHT'),
        # body rows
        ('FONTNAME',     (0, 1), (-1, -1), 'Times-Roman'),
        ('FONTSIZE',     (0, 1), (-1, -1), 9.5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, GOLD_ROW]),
        ('ALIGN',        (1, 1), (1, -1),  'RIGHT'),
        ('TEXTCOLOR',    (0, 1), (-1, -1), DARK),
        # grid
        ('GRID',         (0, 0), (-1, -1), 0.4, colors.HexColor('#DDDDDD')),
        ('LINEBELOW',    (0, 0), (-1, 0),  1.2, GOLD),
        # padding
        ('TOPPADDING',   (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 6),
        ('LEFTPADDING',  (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
    ]
    t.setStyle(TableStyle(style))
    return t


def build_pdf(proposal_text, designer_name, client_name, city):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.85 * inch,
        leftMargin=0.85 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
    )
    S = make_styles()
    story = []

    # ── Cover header ────────────────────────────────────────────
    story.append(Paragraph(f"{designer_name} Studio", S['StudioName']))
    story.append(gold_rule(full=True))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Interior Design Proposal", S['DocTitle']))
    story.append(Spacer(1, 4))
    story.append(Paragraph(client_name, S['ClientLine']))
    story.append(Paragraph(city, S['CityLine']))
    story.append(gold_rule(full=True))
    story.append(Spacer(1, 6))

    # Prepared-by line
    story.append(Paragraph(
        f"Prepared by: <b>{designer_name} Studio</b>&nbsp;&nbsp;·&nbsp;&nbsp;"
        f"Client: <b>{client_name}</b>&nbsp;&nbsp;·&nbsp;&nbsp;City: <b>{city}</b>",
        S['PreparedBy']))
    story.append(section_rule())
    story.append(Spacer(1, 10))

    # ── Body parsing ────────────────────────────────────────────
    lines = proposal_text.splitlines()
    i = 0
    current_section_block = []   # accumulate a section's flowables for KeepTogether

    def flush_block():
        if current_section_block:
            story.extend(current_section_block)
            current_section_block.clear()

    table_rows = []

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1

        if not line:
            # blank line = paragraph break; flush any pending table
            if table_rows:
                t = build_investment_table(table_rows)
                if t:
                    story.append(t)
                    story.append(Spacer(1, 8))
                table_rows = []
            continue

        # ── Section header ──
        num, title = parse_section_header(line)
        if num:
            if table_rows:
                t = build_investment_table(table_rows)
                if t:
                    story.append(t)
                    story.append(Spacer(1, 8))
                table_rows = []
            story.append(Spacer(1, 8))
            story.append(section_rule())
            story.append(Paragraph(f"— {num} —", S['SectionNum']))
            story.append(Paragraph(title, S['SectionTitle']))
            continue

        # ── Markdown-style bold header (all-caps sub-heading) ──
        if line.startswith('**') and line.endswith('**'):
            text = line.strip('*').strip()
            story.append(Paragraph(text.title(), S['SubHead']))
            continue

        # ── ALL-CAPS sub-heading (room names etc.) ──
        if line.isupper() and len(line) > 2 and '|' not in line:
            story.append(Paragraph(line.title(), S['SubHead']))
            continue

        # ── Separator dashes (----, ====) → ignore ──
        if re.match(r'^[-=]{3,}$', line):
            continue

        # ── Table row ──
        if '|' in line:
            if not is_table_separator(line):
                row = parse_table_row(line)
                if row:
                    table_rows.append(row)
            continue

        # ── Flush table before non-table content ──
        if table_rows:
            t = build_investment_table(table_rows)
            if t:
                story.append(t)
                story.append(Spacer(1, 8))
            table_rows = []

        # ── Italic signature line (*text*) ──
        if line.startswith('*') and line.endswith('*') and not line.startswith('**'):
            story.append(Paragraph(line.strip('*').strip(), S['Signature']))
            continue

        # ── Bullet point ──
        if line.startswith(('- ', '• ', '* ')):
            story.append(Paragraph('• ' + line[2:], S['BulletItem']))
            continue

        # ── Regular body paragraph ──
        story.append(Paragraph(line, S['Body']))

    # flush any trailing table
    if table_rows:
        t = build_investment_table(table_rows)
        if t:
            story.append(t)
            story.append(Spacer(1, 8))

    # ── Footer rule ──
    story.append(Spacer(1, 20))
    story.append(gold_rule(full=True))
    story.append(Paragraph(
        f"{designer_name} Studio &nbsp;·&nbsp; Confidential Proposal &nbsp;·&nbsp; {city}",
        S['CityLine']))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


# ── Routes ──────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No JSON body"}), 400

        proposal_text  = data.get('proposal_text', '')
        designer       = data.get('designer', 'Your Designer')
        client         = data.get('client', 'Valued Client')
        city           = data.get('city', '')
        recipient_email = data.get('recipient_email', '')

        if not recipient_email:
            return jsonify({"error": "recipient_email required"}), 400

        pdf_bytes = build_pdf(proposal_text, designer, client, city)
        pdf_b64   = base64.b64encode(pdf_bytes).decode('utf-8')

        resend.api_key = os.environ.get('RESEND_API_KEY', '')
        from_email     = os.environ.get('FROM_EMAIL', 'onboarding@resend.dev')

        filename = (f"Proposal_{client.replace(' ','_')}"
                    f"_{city.replace(' ','_')}.pdf")

        params = {
            "from": from_email,
            "to":   [recipient_email],
            "subject": f"Your Interior Design Proposal — {client}, {city}"| Designer: {designer_email}",
            "html": f"""
<div style="font-family:Georgia,serif;max-width:600px;margin:0 auto;
            color:#1a1a1a;line-height:1.7;">
  <p style="color:#B8960C;font-style:italic;margin-bottom:4px;">
    From the studio of {designer}</p>
  <h2 style="font-size:22px;margin-bottom:8px;">Your proposal is ready.</h2>
  <p>Please find attached your bespoke interior design proposal for
     <strong>{client}</strong> in {city}.</p>
  <p>This document outlines your full design vision, room-by-room direction,
     investment breakdown, and project timeline.</p>
  <p style="color:#555;font-size:13px;">
     If you have any questions, simply reply to this email.</p>
  <hr style="border:none;border-top:1px solid #B8960C;margin:24px 0;"/>
  <p style="font-style:italic;color:#999;font-size:12px;">
     {designer} Studio · Powered by Vansh Craft</p>
</div>""",
            "attachments": [{
                "filename": filename,
                "content":  pdf_b64,
            }],
        }

        resend.Emails.send(params)
        return jsonify({"status": "sent", "to": recipient_email}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
