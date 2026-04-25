import os
import io
import resend
from flask import Flask, request, jsonify
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

app = Flask(__name__)

GOLD = colors.HexColor('#B8960C')
DARK = colors.HexColor('#1a1a1a')
LIGHT_GOLD = colors.HexColor('#F5E6A3')

def build_pdf(proposal_text, designer_name, client_name, city):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.85*inch,
        leftMargin=0.85*inch,
        topMargin=1*inch,
        bottomMargin=1*inch
    )

    styles = getSampleStyleSheet()
    
    style_studio = ParagraphStyle('Studio', fontName='Times-BoldItalic', fontSize=11,
        textColor=GOLD, alignment=TA_CENTER, spaceAfter=2)
    style_title = ParagraphStyle('Title', fontName='Times-Bold', fontSize=22,
        textColor=DARK, alignment=TA_CENTER, spaceAfter=4)
    style_subtitle = ParagraphStyle('Subtitle', fontName='Times-Italic', fontSize=11,
        textColor=colors.HexColor('#555555'), alignment=TA_CENTER, spaceAfter=20)
    style_h2 = ParagraphStyle('H2', fontName='Times-Bold', fontSize=13,
        textColor=GOLD, spaceBefore=18, spaceAfter=6)
    style_body = ParagraphStyle('Body', fontName='Times-Roman', fontSize=10.5,
        leading=16, textColor=DARK, alignment=TA_JUSTIFY, spaceAfter=6)
    style_italic = ParagraphStyle('Italic', fontName='Times-Italic', fontSize=11,
        leading=17, textColor=colors.HexColor('#333333'), alignment=TA_CENTER,
        spaceBefore=10, spaceAfter=10)

    story = []

    # Header
    story.append(Paragraph(f"{designer_name} Studio", style_studio))
    story.append(HRFlowable(width="100%", thickness=1.2, color=GOLD, spaceAfter=8))
    story.append(Paragraph(f"Interior Design Proposal", style_title))
    story.append(Paragraph(f"{client_name} &nbsp;·&nbsp; {city}", style_subtitle))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GOLD, spaceAfter=20))

    # Parse and render proposal sections
    lines = proposal_text.split('\n')
    in_table = False
    table_data = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Section headers (numbered like "1." or "**Title**")
        if line.startswith('**') and line.endswith('**'):
            text = line.replace('**', '')
            story.append(Paragraph(text, style_h2))
            story.append(HRFlowable(width="40%", thickness=0.5, color=GOLD, spaceAfter=4))

        elif line[0].isdigit() and '. ' in line[:4]:
            story.append(Paragraph(line, style_h2))
            story.append(HRFlowable(width="40%", thickness=0.5, color=GOLD, spaceAfter=4))

        # Table rows (pipe-separated)
        elif '|' in line:
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if cells and not all(set(c) <= set('-') for c in cells):
                table_data.append(cells)
        
        # Italic signature moment lines
        elif line.startswith('*') and line.endswith('*') and not line.startswith('**'):
            text = line.strip('*')
            story.append(Paragraph(text, style_italic))

        # Regular body
        else:
            # Flush any pending table
            if table_data:
                col_widths = [2.2*inch, 1.5*inch, 2.0*inch]
                if len(table_data[0]) == 2:
                    col_widths = [3*inch, 2.5*inch]
                t = Table(table_data, colWidths=col_widths[:len(table_data[0])])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), GOLD),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                    ('FONTNAME', (0,0), (-1,0), 'Times-Bold'),
                    ('FONTSIZE', (0,0), (-1,-1), 10),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#FAF7EE')]),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#DDDDDD')),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                    ('LEFTPADDING', (0,0), (-1,-1), 8),
                ]))
                story.append(t)
                story.append(Spacer(1, 10))
                table_data = []
            story.append(Paragraph(line, style_body))

    # Flush any remaining table
    if table_data:
        t = Table(table_data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), GOLD),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Times-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#DDDDDD')),
        ]))
        story.append(t)

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON body received"}), 400

        proposal_text = data.get('proposal_text', '')
        designer = data.get('designer', 'Designer')
        client = data.get('client', 'Client')
        city = data.get('city', '')
        recipient_email = data.get('recipient_email', '')

        if not recipient_email:
            return jsonify({"error": "recipient_email is required"}), 400

        pdf_bytes = build_pdf(proposal_text, designer, client, city)

        resend.api_key = os.environ.get('RESEND_API_KEY')
        from_email = os.environ.get('FROM_EMAIL', 'onboarding@resend.dev')

        import base64
        pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')

        params = {
            "from": from_email,
            "to": [recipient_email],
            "subject": f"Your Interior Design Proposal — {client}, {city}",
            "html": f"""
                <div style="font-family: Georgia, serif; max-width: 600px; margin: 0 auto; color: #1a1a1a;">
                    <p style="color: #B8960C; font-style: italic;">From the studio of {designer}</p>
                    <h2>Your proposal is ready.</h2>
                    <p>Please find attached your bespoke interior design proposal for <strong>{client}</strong> in {city}.</p>
                    <p>This document outlines our full design vision, room-by-room direction, investment breakdown, and project timeline.</p>
                    <p style="color: #555; font-size: 13px;">If you have any questions, simply reply to this email.</p>
                    <hr style="border-color: #B8960C; margin: 24px 0;" />
                    <p style="font-style: italic; color: #888; font-size: 12px;">{designer} Studio · Powered by Vansh Craft</p>
                </div>
            """,
            "attachments": [{
                "filename": f"Proposal_{client.replace(' ','_')}_{city.replace(' ','_')}.pdf",
                "content": pdf_b64
            }]
        }

        resend.Emails.send(params)
        return jsonify({"status": "sent", "to": recipient_email}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
