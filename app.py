import os
import io
import re
import base64
import resend
import requests
import replicate
from flask import Flask, request, jsonify
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, KeepTogether, Image as RLImage)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT

app = Flask(__name__)

ALMOST_BLACK = colors.HexColor('#0F0F0F')
DARK         = colors.HexColor('#1A1A1A')
MID          = colors.HexColor('#3A3A3A')
SUBTLE       = colors.HexColor('#888888')
LIGHT_GREY   = colors.HexColor('#DEDEDE')
WARM_WHITE   = colors.HexColor('#F9F7F4')
GOLD         = colors.HexColor('#C4A97D')
GOLD_DARK    = colors.HexColor('#9A7D52')
WHITE        = colors.white

PAGE_W, PAGE_H = letter
MARGIN = 0.85 * inch
W = PAGE_W - 2 * MARGIN


# ── IMAGE GENERATION ────────────────────────────────────────────────────────

def run_flux(prompt):
    """Run a single FLUX image generation and return BytesIO buffer."""
    try:
        replicate_key = os.environ.get('REPLICATE_API_TOKEN', '')
        if not replicate_key:
            return None
        os.environ['REPLICATE_API_TOKEN'] = replicate_key

        output = replicate.run(
            "black-forest-labs/flux-schnell",
            input={
                "prompt": prompt,
                "width": 768,
                "height": 432,
                "num_outputs": 1,
                "num_inference_steps": 4,
                "guidance_scale": 3.5,
                "output_format": "jpg",
            }
        )
        if output and len(output) > 0:
            response = requests.get(output[0], timeout=30)
            if response.status_code == 200:
                return io.BytesIO(response.content)
    except Exception as e:
        print(f"Image generation failed: {e}")
    return None


def generate_all_images(style, mood, city, rooms, property_type=''):
    """Generate 3 images in parallel: mood, rooms, closing."""
    import concurrent.futures

    room_list = rooms if isinstance(rooms, str) else ', '.join(rooms)
    style_l = style.lower()
    mood_l = mood.lower()

    prompts = [
        # Image 1 — after Design Vision: overall mood
        (
            f"Luxury {style_l} interior design, {mood_l} atmosphere, "
            f"{city} residence, professional architectural photography, "
            f"soft natural lighting, editorial magazine style, "
            f"high-end finishes, no people, warm tones, photorealistic, 8k quality"
        ),
        # Image 2 — after Room-By-Room: specific rooms
        (
            f"Luxury {style_l} {room_list} interior, {mood_l} mood, "
            f"detailed room design, high-end materials, natural light, "
            f"no people, editorial photography, photorealistic, 8k quality"
        ),
        # Image 3 — before Signature Moment: elegant closing detail
        (
            f"Luxury {style_l} interior design detail, {mood_l} atmosphere, "
            f"close-up of premium materials and finishes, decorative accents, "
            f"soft bokeh, editorial style, no people, photorealistic, 8k quality"
        ),
    ]

    images = [None, None, None]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(run_flux, p): i for i, p in enumerate(prompts)}
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            try:
                images[idx] = future.result()
            except Exception as e:
                print(f"Image {idx} failed: {e}")

    return images  # [mood_img, rooms_img, closing_img]


def image_flowable(img_buffer, width=None, caption=None):
    try:
        if width is None:
            width = W
        img = RLImage(img_buffer, width=width, height=width * 9/16)
        return img
    except Exception as e:
        print(f"Image flowable failed: {e}")
        return None


# ── SPACED CAPS ──────────────────────────────────────────────────────────────

def spaced_caps(text):
    words = text.upper().split()
    spaced_words = [' &nbsp;'.join(list(word)) for word in words]
    return ' &nbsp;&nbsp; '.join(spaced_words)


def draw_spaced_caps(canvas, text, x, y, font='Times-Roman', size=7.5, color=None, letter_spacing=4, word_spacing=14):
    if color:
        canvas.setFillColor(color)
    canvas.setFont(font, size)
    words = text.upper().split()
    total_width = 0
    for wi, word in enumerate(words):
        for li, letter in enumerate(word):
            total_width += canvas.stringWidth(letter, font, size)
            if li < len(word) - 1:
                total_width += letter_spacing
        if wi < len(words) - 1:
            total_width += word_spacing
    cx = x - total_width / 2
    for wi, word in enumerate(words):
        for li, letter in enumerate(word):
            canvas.drawString(cx, y, letter)
            cx += canvas.stringWidth(letter, font, size) + letter_spacing
        if wi < len(words) - 1:
            cx += word_spacing - letter_spacing


def cover_page_canvas(canvas, doc):
    canvas.saveState()
    if doc.page == 1:
        band_h = 3.4 * inch
        canvas.setFillColor(ALMOST_BLACK)
        canvas.rect(0, PAGE_H - band_h, PAGE_W, band_h, fill=1, stroke=0)
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, PAGE_H - band_h + 0.01*inch,
                    PAGE_W - MARGIN, PAGE_H - band_h + 0.01*inch)
        draw_spaced_caps(canvas, doc._studio,
                         x=PAGE_W / 2,
                         y=PAGE_H - 0.72 * inch,
                         size=7.5, color=GOLD,
                         letter_spacing=3.5, word_spacing=13)
    canvas.setFont('Times-Roman', 8)
    canvas.setFillColor(SUBTLE)
    footer_y = 0.42 * inch
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
        fontName='Times-Roman', fontSize=7.5,
        textColor=GOLD, alignment=TA_CENTER, spaceAfter=10, leading=12,
        wordWrap='CJK')
    add('CoverTitle',
        fontName='Times-Bold', fontSize=30,
        textColor=WHITE, alignment=TA_CENTER, spaceAfter=6, leading=36)
    add('CoverSubtitle',
        fontName='Times-Italic', fontSize=12,
        textColor=colors.HexColor('#BBBBBB'), alignment=TA_CENTER,
        spaceAfter=4, leading=17)
    add('CoverYear',
        fontName='Times-Roman', fontSize=9,
        textColor=GOLD, alignment=TA_CENTER, spaceAfter=0, leading=12)
    add('SectionNum',
        fontName='Times-Roman', fontSize=36,
        textColor=LIGHT_GREY, alignment=TA_LEFT,
        spaceBefore=32, spaceAfter=2, leading=40)
    add('SectionTitle',
        fontName='Times-Bold', fontSize=12,
        textColor=DARK, alignment=TA_LEFT,
        spaceBefore=0, spaceAfter=12, leading=16,
        tracking=1)
    add('SubHead',
        fontName='Times-Bold', fontSize=10.5,
        textColor=MID, alignment=TA_LEFT,
        spaceBefore=14, spaceAfter=4, leading=14)
    add('Body',
        fontName='Times-Roman', fontSize=10.5,
        textColor=DARK, alignment=TA_JUSTIFY,
        leading=17, spaceAfter=9)
    add('BulletItem',
        fontName='Times-Roman', fontSize=10.5,
        textColor=DARK, alignment=TA_LEFT,
        leading=16, spaceAfter=5, leftIndent=18, firstLineIndent=-14)
    add('SignatureText',
        fontName='Times-Italic', fontSize=12.5,
        textColor=MID, alignment=TA_CENTER,
        leading=20, spaceBefore=8, spaceAfter=6)
    add('SignatureAttr',
        fontName='Times-Roman', fontSize=9,
        textColor=SUBTLE, alignment=TA_CENTER, spaceAfter=4, leading=13)
    add('MetaLine',
        fontName='Times-Roman', fontSize=8.5,
        textColor=SUBTLE, alignment=TA_LEFT, spaceAfter=2, leading=12)
    add('FooterCity',
        fontName='Times-Roman', fontSize=9,
        textColor=SUBTLE, alignment=TA_CENTER, spaceAfter=0)
    add('InvHeading',
        fontName='Times-Bold', fontSize=10.5,
        textColor=MID, spaceBefore=10, spaceAfter=4, leading=14)
    add('ImageCaption',
        fontName='Times-Italic', fontSize=8.5,
        textColor=SUBTLE, alignment=TA_CENTER,
        spaceAfter=12, leading=12)

    return s


def thin_rule(color=None, width='100%', thickness=0.4, before=4, after=6):
    c = color or LIGHT_GREY
    return HRFlowable(width=width, thickness=thickness,
                      color=c, spaceBefore=before, spaceAfter=after)


def gold_rule(width='100%'):
    return HRFlowable(width=width, thickness=0.8,
                      color=GOLD, spaceBefore=8, spaceAfter=8)


def parse_section_header(line):
    line = line.strip().lstrip('#').strip().strip('*').strip()
    m = re.match(r'^(\d+)[.)]\s+(.+)$', line)
    if m:
        num = int(m.group(1))
        title = m.group(2).strip()
        if 1 <= num <= 9 and len(title) < 80:
            return m.group(1), title.title()
    return None, None


def is_table_separator(line):
    return bool(re.match(r'^[\s|:\-]+$', line))


def try_parse_budget_line(line):
    line = re.sub(r'^[\-–—\•]\s+', '', line.strip())
    m = re.match(
        r'^(.{3,80}):\s+(\$[\d,]+\s*[\u2013\u2014-]+\s*\$[\d,]+.*?)(?:\s*\(.*\))?$',
        line)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    m2 = re.match(
        r'^((?:[A-Za-z&,/()\s]+))\s+(\$[\d,]+\s*[\u2013\u2014-]+\s*\$[\d,]+)',
        line)
    if m2 and len(m2.group(1).strip()) > 3:
        return [m2.group(1).strip(), m2.group(2).strip()]
    m3 = re.match(r'^(.{3,80}):\s+(\$[\d,\s]+?)(?:\s*\(.*\))?$', line)
    if m3 and '$' in m3.group(2):
        return [m3.group(1).strip(), m3.group(2).strip()]
    return None


def parse_table_row(line):
    parts = [c.strip() for c in line.strip().strip('|').split('|')]
    return [p for p in parts if p]


def is_duplicate_header(row):
    if not row:
        return False
    row_lower = [c.lower().strip() for c in row]
    header_combos = [
        ['category', 'estimated range'],
        ['phase', 'date range'],
        ['phase', 'key activities'],
        ['phase', 'dates'],
        ['phase', 'activities'],
        ['category', 'range'],
    ]
    if row_lower in header_combos:
        return True
    if (len(row_lower) == 2
            and row_lower[0] in ('category', 'phase', 'item')
            and row_lower[1] in ('estimated range', 'date range', 'key activities',
                                  'dates', 'activities', 'range', 'cost', 'amount')):
        return True
    return False


def build_investment_flowables(rows, S):
    if not rows:
        return []

    col_w = [W * 0.62, W * 0.38]

    def make_mini_table(data_rows, include_header):
        table_data = []
        if include_header:
            table_data.append(['CATEGORY', 'ESTIMATED RANGE'])
        for row in data_rows:
            if len(row) == 1:
                table_data.append([row[0], ''])
            else:
                table_data.append(row[:2])

        if not table_data:
            return None

        t = Table(table_data, colWidths=col_w)
        offset = 1 if include_header else 0
        cmds = [
            ('TEXTCOLOR',      (0, 0), (-1, -1), DARK),
            ('FONTNAME',       (0, 0), (-1, -1), 'Times-Roman'),
            ('FONTSIZE',       (0, 0), (-1, -1), 10),
            ('TOPPADDING',     (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 8),
            ('LEFTPADDING',    (0, 0), (-1, -1), 10),
            ('RIGHTPADDING',   (0, 0), (-1, -1), 10),
            ('GRID',           (0, 0), (-1, -1), 0.3, LIGHT_GREY),
            ('ROWBACKGROUNDS', (0, offset), (-1, -1), [WHITE, WARM_WHITE]),
            ('ALIGN',          (1, 0), (1, -1), 'RIGHT'),
        ]
        if include_header:
            cmds += [
                ('BACKGROUND',  (0, 0), (-1, 0), ALMOST_BLACK),
                ('TEXTCOLOR',   (0, 0), (-1, 0), GOLD),
                ('FONTNAME',    (0, 0), (-1, 0), 'Times-Roman'),
                ('FONTSIZE',    (0, 0), (-1, 0), 8),
                ('LINEBELOW',   (0, 0), (-1, 0), 0.8, GOLD),
            ]
        last = len(table_data) - 1
        if last >= offset and table_data[last][1]:
            cmds += [
                ('FONTNAME',  (0, last), (-1, last), 'Times-Bold'),
                ('LINEABOVE', (0, last), (-1, last), 1.0, GOLD_DARK),
            ]
        t.setStyle(TableStyle(cmds))
        return t

    data_rows = rows[1:] if rows and rows[0] == ['CATEGORY', 'ESTIMATED RANGE'] else rows
    data_rows = [r for r in data_rows if not is_duplicate_header(r)]

    blocks = []
    current_heading = None
    current_rows = []

    for row in data_rows:
        no_price = len(row) == 1 or (len(row) >= 2 and not row[1].strip())
        is_heading = no_price and '$' not in row[0]
        if is_heading:
            if current_heading is not None or current_rows:
                blocks.append((current_heading, current_rows))
            current_heading = row[0]
            current_rows = []
        else:
            current_rows.append(row)

    if current_heading is not None or current_rows:
        blocks.append((current_heading, current_rows))

    flowables = []
    first = True
    for heading, brows in blocks:
        group = []
        if heading:
            group.append(Paragraph(heading, S['InvHeading']))
        if brows:
            mini = make_mini_table(brows, include_header=first)
            if mini:
                group.append(mini)
                first = False
        if group:
            flowables.append(KeepTogether(group))
            flowables.append(Spacer(1, 6))

    return flowables


def build_timeline_table(rows):
    if not rows:
        return None

    rows = [r for r in rows if not is_duplicate_header(r)]
    if not rows:
        return None

    phase_style = ParagraphStyle('TLPhase', fontName='Times-Roman',
                                  fontSize=9.5, textColor=DARK, leading=14,
                                  spaceAfter=0)
    activity_style = ParagraphStyle('TLActivity', fontName='Times-Roman',
                                     fontSize=9.5, textColor=MID, leading=14,
                                     spaceAfter=0)

    wrapped = []
    for idx, row in enumerate(rows):
        if idx == 0:
            wrapped.append(row)
        else:
            phase_text    = row[0] if len(row) > 0 else ''
            activity_text = row[1] if len(row) > 1 else ''
            wrapped.append([
                Paragraph(phase_text.replace('\n', '<br/>'), phase_style),
                Paragraph(activity_text.replace('\n', '<br/>'), activity_style),
            ])

    col_w = [W * 0.35, W * 0.65]
    t = Table(wrapped, colWidths=col_w)
    cmds = [
        ('TEXTCOLOR',     (0, 0), (-1, -1), DARK),
        ('FONTNAME',      (0, 0), (-1, -1), 'Times-Roman'),
        ('FONTSIZE',      (0, 0), (-1, -1), 9.5),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('GRID',          (0, 0), (-1, -1), 0.3, LIGHT_GREY),
        ('BACKGROUND',    (0, 0), (-1, 0), ALMOST_BLACK),
        ('TEXTCOLOR',     (0, 0), (-1, 0), GOLD),
        ('FONTNAME',      (0, 0), (-1, 0), 'Times-Roman'),
        ('FONTSIZE',      (0, 0), (-1, 0), 8),
        ('LINEBELOW',     (0, 0), (-1, 0), 0.8, GOLD),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [WHITE, WARM_WHITE]),
    ]
    t.setStyle(TableStyle(cmds))
    return t


def build_pdf(proposal_text, designer_name, client_name, city, designer_email='',
              style='Modern', mood='Elegant', rooms='', property_type='',
              inspiration_image_url=''):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=MARGIN, leftMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=0.85 * inch,
    )

    suffixes = ['studio', 'interiors', 'design', 'designs', 'creative', 'co', 'group']
    studio_suffix = "" if any(designer_name.lower().rstrip().endswith(s)
                              for s in suffixes) else " Studio"
    doc._studio = f"{designer_name}{studio_suffix}"
    doc._client = client_name

    S = make_styles()
    story = []

    images = generate_all_images(style, mood, city, rooms, property_type)
    mood_img_buffer    = images[0]  # After Design Vision
    rooms_img_buffer   = images[1]  # After Room-By-Room
    closing_img_buffer = images[2]  # Before Signature Moment

    # ── COVER ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.42 * inch))
    story.append(Paragraph("Interior Design", S['CoverSubtitle']))
    story.append(Paragraph("Proposal", S['CoverTitle']))
    story.append(Spacer(1, 2))
    story.append(Paragraph(f"Prepared exclusively for {client_name}", S['CoverSubtitle']))
    story.append(Paragraph(f"{city} Residence", S['CoverSubtitle']))
    story.append(Spacer(1, 6))
    story.append(Paragraph("2026", S['CoverYear']))
    story.append(Spacer(1, 1.55 * inch))

    story.append(Paragraph(
        f"{doc._studio} &nbsp;·&nbsp; Private &amp; Confidential &nbsp;·&nbsp; "
        f"Prepared for {client_name}", S['MetaLine']))
    story.append(thin_rule())
    story.append(Spacer(1, 14))

    # ── BODY PARSING ─────────────────────────────────────────────────────────
    proposal_text = re.sub(r'\n[ \t]*[-]{4,}[ \t]*\n', '\n', proposal_text)
    proposal_text = re.sub(r'\n[ \t]*[=]{4,}[ \t]*\n', '\n', proposal_text)

    lines = proposal_text.splitlines()
    i = 0
    table_rows = []
    timeline_rows = []
    section_counter = 0
    in_investment = False
    in_timeline = False
    in_next_steps = False
    current_phase = None
    phase_activities = []
    mood_image_inserted = False
    rooms_image_inserted = False
    closing_image_inserted = False

    def flush_table():
        nonlocal table_rows
        if table_rows:
            flowables = build_investment_flowables(table_rows, S)
            for f in flowables:
                story.append(f)
            if flowables:
                story.append(Spacer(1, 8))
            table_rows = []

    def flush_timeline():
        nonlocal timeline_rows, current_phase, phase_activities
        if current_phase and phase_activities:
            timeline_rows.append([current_phase, '\n'.join(phase_activities)])
            current_phase = None
            phase_activities = []
        if len(timeline_rows) > 1:
            t = build_timeline_table(timeline_rows)
            if t:
                story.append(t)
                story.append(Spacer(1, 14))
        timeline_rows.clear()

    def insert_image(buf, caption, inserted_flag):
        if buf and not inserted_flag:
            buf.seek(0)
            img = image_flowable(buf, width=W)
            if img:
                story.append(Spacer(1, 8))
                story.append(img)
                story.append(Paragraph(caption, S['ImageCaption']))
                story.append(Spacer(1, 8))
            return True
        return inserted_flag

    KNOWN_ROOMS = {
        'bathroom', 'kitchen', 'living room', 'master bedroom', 'bedroom',
        'dining', 'dining room', 'office', 'balcony', 'kids room',
        'guest room', 'hallway', 'entryway', 'studio', 'lounge',
        'powder room', 'laundry', 'garage', 'terrace', 'garden'
    }

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1

        if not line:
            if not in_investment and not in_timeline:
                flush_table()
            continue

        # Section header
        num, title = parse_section_header(line)
        if num:
            flush_table()
            flush_timeline()

            if section_counter == 1 and not mood_image_inserted:
                mood_image_inserted = insert_image(
                    mood_img_buffer,
                    f"AI-visualised mood for {client_name}'s {city} residence",
                    mood_image_inserted)
            if section_counter == 2 and not rooms_image_inserted:
                rooms_image_inserted = insert_image(
                    rooms_img_buffer,
                    f"AI-visualised room direction for {client_name}'s {city} residence",
                    rooms_image_inserted)

            in_investment = False
            in_timeline = False
            in_next_steps = False
            section_counter += 1
            num_str = f"0 {section_counter}" if section_counter < 10 else str(section_counter)
            in_investment  = ('investment' in title.lower() or 'budget' in title.lower())
            in_timeline    = ('timeline' in title.lower() or 'schedule' in title.lower())
            in_next_steps  = ('next steps' in title.lower() or 'next step' in title.lower())

            story.append(Spacer(1, 4))
            story.append(thin_rule())
            story.append(Paragraph(num_str, S['SectionNum']))
            story.append(Paragraph(title, S['SectionTitle']))

            if in_investment:
                table_rows = [['CATEGORY', 'ESTIMATED RANGE']]
            if in_timeline:
                timeline_rows = [['PHASE', 'KEY ACTIVITIES']]
            continue

        # Bold subheader **text**
        if line.startswith('**') and line.endswith('**'):
            flush_table()
            story.append(Paragraph(line.strip('*').strip().title(), S['SubHead']))
            continue

        # ALL CAPS subheader
        if line.isupper() and 2 < len(line) < 60 and '|' not in line:
            flush_table()
            if in_timeline:
                if current_phase and phase_activities:
                    timeline_rows.append([current_phase, '\n'.join(phase_activities)])
                current_phase = line.title()
                phase_activities = []
            else:
                story.append(Paragraph(line.title(), S['SubHead']))
            continue

        # Title Case room name
        if (not in_investment and not in_timeline
                and 2 < len(line) < 50 and '|' not in line and '$' not in line
                and not line.startswith(('-', '—', '*'))
                and line.lower() in KNOWN_ROOMS):
            flush_table()
            story.append(Paragraph(line.title(), S['SubHead']))
            continue

        # Separator lines
        stripped = line.strip()
        if stripped in ('-', '–', '—', '*', '**'):
            continue
        if stripped and len(stripped) >= 2:
            dash_ratio = sum(1 for c in stripped if c in '-=_*') / len(stripped)
            if dash_ratio >= 0.5:
                continue

        # Pipe table rows — route to timeline or investment based on context
        if '|' in line:
            if not is_table_separator(line):
                row = parse_table_row(line)
                if row and not is_duplicate_header(row):
                    if in_timeline:
                        if len(row) >= 2:
                            timeline_rows.append([row[0], row[1]])
                        elif len(row) == 1:
                            timeline_rows.append([row[0], ''])
                    else:
                        table_rows.append(row)
            continue

        # Italic signature
        if line.startswith('*') and line.endswith('*') and not line.startswith('**'):
            flush_table()
            flush_timeline()
            # Insert closing image before signature moment
            closing_image_inserted = insert_image(
                closing_img_buffer,
                f"Design detail · {client_name}'s {city} residence",
                closing_image_inserted)
            sig_text = line.strip('*').strip()
            story.append(Spacer(1, 10))
            story.append(gold_rule(width='50%'))
            story.append(Paragraph(sig_text, S['SignatureText']))
            story.append(Paragraph(f"— {designer_name}", S['SignatureAttr']))
            story.append(gold_rule(width='50%'))
            continue

        # Bullet items
        if line.startswith(('- ', '• ', '* ', '— ')):
            flush_table()
            content = re.sub(r'^[\-–—\•\*]\s+', '', line)
            if in_timeline and current_phase is not None:
                phase_activities.append(f"— {content}")
            else:
                story.append(Paragraph('— &nbsp;' + content, S['BulletItem']))
            continue

        # Timeline phase headers
        if in_timeline:
            clean_line = line.strip('*').strip()
            phase_m = re.match(
                r'^(Phase\s+(?:\d+|[A-Za-z]+)[:\.]?\s*.+?)(?:\s*[\(\[].*[\)\]])?$',
                clean_line, re.IGNORECASE)
            if phase_m:
                if current_phase and phase_activities:
                    timeline_rows.append([current_phase, '\n'.join(phase_activities)])
                current_phase = clean_line.strip()
                phase_activities = []
                continue
            if re.match(r'^[A-Z][a-z]+ \d+', clean_line) and current_phase and not phase_activities:
                current_phase = f"{current_phase}\n{clean_line}"
                continue
            if current_phase is not None:
                content = re.sub(r'^[\-–—\•]\s*', '', clean_line)
                if content:
                    if len(content) > 80:
                        phase_activities.append(content)
                    else:
                        phase_activities.append(f"— {content}")
                continue
            else:
                story.append(Paragraph(clean_line, S['Body']))
                continue

        # Investment section
        if in_investment:
            if 'recommend positioning' in line.lower():
                story.append(Paragraph(line, S['Body']))
                continue
            line_lower = line.lower().strip()
            if (line_lower in ('category  estimated range', 'category estimated range',
                               'phase  date range', 'phase date range',
                               'category | estimated range')
                    or re.match(r'^category\s+estimated\s+range$', line_lower)
                    or re.match(r'^phase\s+(date\s+range|key\s+activities)$', line_lower)):
                continue
            if re.match(r'^(category|estimated)', line_lower):
                continue
            budget_row = try_parse_budget_line(line)
            if budget_row:
                label = budget_row[0].lower()
                sub_keywords = ['bathroom fixture', 'kitchen cabinet', 'flooring',
                                'wall treatment', 'textile', 'pendant', 'dining table',
                                'office desk', 'wall sconce', 'statement']
                is_subitem = any(k in label for k in sub_keywords) and len(label) < 50
                if not is_subitem:
                    table_rows.append(budget_row)
                continue
            if '$' not in line:
                if len(line) > 60:
                    story.append(Paragraph(line, S['Body']))
                continue

        # Default: body text
        flush_table()
        if in_next_steps and len(line) > 20:
            story.append(Paragraph('— &nbsp;' + line, S['BulletItem']))
        else:
            story.append(Paragraph(line, S['Body']))

    flush_table()
    flush_timeline()

    if not mood_image_inserted:
        mood_image_inserted = insert_image(
            mood_img_buffer,
            f"AI-visualised mood for {client_name}'s {city} residence",
            mood_image_inserted)
    if not rooms_image_inserted:
        rooms_image_inserted = insert_image(
            rooms_img_buffer,
            f"AI-visualised room direction for {client_name}'s {city} residence",
            rooms_image_inserted)

    # ── CLOSING FOOTER ───────────────────────────────────────────────────────
    story.append(Spacer(1, 28))
    story.append(gold_rule())
    story.append(Paragraph(
        f"{doc._studio} &nbsp;·&nbsp; {city}", S['FooterCity']))
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

        proposal_text         = data.get('proposal_text', '')
        designer              = data.get('designer', 'Your Designer')
        client                = data.get('client', 'Valued Client')
        city                  = data.get('city', '')
        recipient_email       = data.get('recipient_email', '')
        style                 = data.get('style', 'Modern')
        mood                  = data.get('mood', 'Elegant')
        rooms                 = data.get('rooms', '')
        property_type         = data.get('property_type', '')
        inspiration_image_url = data.get('inspiration_image_url', '')

        if not recipient_email:
            return jsonify({"error": "recipient_email required"}), 400

        designer_email = data.get('designer_email', recipient_email)
        suffixes = ['studio', 'interiors', 'design', 'designs', 'creative', 'co', 'group']
        studio_sfx = "" if any(designer.lower().rstrip().endswith(s) for s in suffixes) else " Studio"
        designer_studio = f"{designer}{studio_sfx}"

        pdf_bytes = build_pdf(
            proposal_text, designer, client, city, designer_email,
            style=style, mood=mood, rooms=rooms, property_type=property_type,
            inspiration_image_url=inspiration_image_url
        )
        pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')

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
    <p style="color:#C4A97D;font-size:10px;letter-spacing:3px;margin:0 0 8px;text-transform:uppercase;">{designer.upper()}</p>
    <h1 style="color:#ffffff;font-size:22px;margin:0 0 6px;font-weight:normal;font-style:italic;">Your proposal is ready.</h1>
    <p style="color:#AAAAAA;font-size:13px;margin:0;">Prepared for <strong style="color:#fff;">{client}</strong> · {city}</p>
  </div>
  <p style="padding:0 4px;">Please find attached your bespoke interior design proposal. This document outlines the full design vision, room-by-room direction, investment breakdown, and project timeline.</p>
  <p style="color:#555;font-size:13px;padding:0 4px;">If you have any questions, simply reply to this email.</p>
  <hr style="border:none;border-top:1px solid #C4A97D;margin:24px 0;"/>
  <p style="font-style:italic;color:#999;font-size:12px;padding:0 4px;">{designer_studio} · Powered by Vansh Craft</p>
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
