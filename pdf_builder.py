import re
from datetime import datetime, timezone
from io import BytesIO
from fpdf import FPDF
from fpdf.enums import XPos, YPos


BRAND_DARK   = (15,  23,  42)
BRAND_ACCENT = (56, 189, 248)
BRAND_RED    = (239,  68,  68)
BRAND_GREEN  = (34,  197,  94)
BRAND_MUTED  = (100, 116, 139)
WHITE        = (255, 255, 255)
LIGHT_BG     = (241, 245, 249)
BORDER_COLOR = (203, 213, 225)

PAGE_WIDTH:       float = 210.0
LEFT_MARGIN:      float = 15.0
RIGHT_MARGIN:     float = 15.0
CONTENT_WIDTH:    float = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
BOTTOM_MARGIN:    float = 20.0
PAGE_HEIGHT:      float = 297.0
USABLE_HEIGHT:    float = PAGE_HEIGHT - BOTTOM_MARGIN

RAW_DATA_COL_WIDTHS:     list[float] = [22.0, 72.0, 22.0, 64.0]
ANALYSIS_COL_WIDTHS:     list[float] = [180.0]
ASSESSMENT_COL_WIDTHS:   list[float] = [80.0, 100.0]
DEFAULT_COL_WIDTHS:      list[float] = []

SECTION_ESTIMATED_HEIGHTS: dict[str, float] = {
    "CONFIDENCE ASSESSMENT": 45.0,
    "METHODOLOGY":           40.0,
    "FLAGGED MARKETS":       35.0,
}


class IntelligenceReportPDF(FPDF):

    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id
        self.set_margins(left=LEFT_MARGIN, top=15, right=RIGHT_MARGIN)
        self.set_auto_page_break(auto=True, margin=BOTTOM_MARGIN)

    def _load_fonts(self):
        import os
        font_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
        self.add_font("DejaVu", style="",  fname=os.path.join(font_dir, "DejaVuSansCondensed.ttf"))
        self.add_font("DejaVu", style="B", fname=os.path.join(font_dir, "DejaVuSansCondensed-Bold.ttf"))

    def header(self):
        self.set_fill_color(*BRAND_DARK)
        self.rect(0, 0, 210, 22, style="F")
        self.set_y(5)
        self.set_font("DejaVu", "B", 11)
        self.set_text_color(*BRAND_ACCENT)
        self.cell(0, 8, "ALPHA SIGNALS INTELLIGENCE SYSTEM", align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("DejaVu", "", 7)
        self.set_text_color(*BRAND_MUTED)
        self.set_x(LEFT_MARGIN)
        self.cell(0, 4, f"Run ID: {self.run_id}  |  Confidential — Authorised Recipients Only", align="L")
        self.ln(6)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*BRAND_ACCENT)
        self.set_line_width(0.4)
        self.line(LEFT_MARGIN, self.get_y(), PAGE_WIDTH - RIGHT_MARGIN, self.get_y())
        self.ln(2)
        self.set_font("DejaVu", "", 7)
        self.set_text_color(*BRAND_MUTED)
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.cell(0, 4, f"Generated: {generated}  |  Page {self.page_no()}", align="C")

    def cover_band(self, title: str, subtitle: str):
        self.set_fill_color(*LIGHT_BG)
        self.set_draw_color(*BORDER_COLOR)
        self.set_line_width(0.3)
        self.rect(LEFT_MARGIN, self.get_y(), CONTENT_WIDTH, 22, style="FD")
        y = self.get_y() + 4
        self.set_xy(20, y)
        self.set_font("DejaVu", "B", 14)
        self.set_text_color(*BRAND_DARK)
        self.cell(0, 7, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_x(20)
        self.set_font("DejaVu", "", 8)
        self.set_text_color(*BRAND_MUTED)
        self.cell(0, 5, subtitle)
        self.ln(14)

    def _space_remaining(self) -> float:
        return USABLE_HEIGHT - self.get_y()

    def _ensure_space(self, needed: float):
        if self._space_remaining() < needed:
            self.add_page()

    def section_header(self, text: str):
        section_label = text.replace("## ", "").replace("# ", "").upper()
        estimated = SECTION_ESTIMATED_HEIGHTS.get(section_label, 20.0)
        self._ensure_space(estimated)
        self.ln(4)
        self.set_fill_color(*BRAND_ACCENT)
        self.rect(LEFT_MARGIN, self.get_y(), 3, 7, style="F")
        self.set_xy(20, self.get_y())
        self.set_font("DejaVu", "B", 10)
        self.set_text_color(*BRAND_DARK)
        self.cell(0, 7, section_label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*BORDER_COLOR)
        self.set_line_width(0.2)
        self.line(LEFT_MARGIN, self.get_y(), PAGE_WIDTH - RIGHT_MARGIN, self.get_y())
        self.ln(3)

    def body_line(self, text: str):
        self.set_font("DejaVu", "", 8.5)
        self.set_text_color(*BRAND_DARK)

        text = text.strip()
        if not text:
            self.ln(2)
            return

        is_anomaly = "ANOMALY" in text and not text.startswith("|")
        is_clean   = text.startswith("CLEAN")
        is_flag    = "🚨" in text
        is_bullet  = text.startswith("- ") and not is_flag
        is_bold_kv = text.startswith("**") and ":**" in text
        is_action  = "ACTION REQUIRED" in text or "ALL CLEAR" in text
        is_warning = text.startswith(">") or "Correction Run" in text

        if is_anomaly:
            self.set_text_color(*BRAND_RED)
        elif is_clean:
            self.set_text_color(*BRAND_GREEN)
        elif is_flag:
            self.set_text_color(*BRAND_RED)
        elif is_action and "ACTION" in text:
            self.set_text_color(*BRAND_RED)
        elif is_action and "ALL CLEAR" in text:
            self.set_text_color(*BRAND_GREEN)
        elif is_warning:
            self.set_text_color(*BRAND_MUTED)
        else:
            self.set_text_color(*BRAND_DARK)

        self._ensure_space(8)

        if is_bold_kv:
            parts = text.split(":**", 1)
            key = parts[0].replace("**", "").strip()
            val = parts[1].replace("**", "").strip() if len(parts) > 1 else ""
            val = re.sub(r"`(.*?)`", r"\1", val)
            self.set_font("DejaVu", "B", 8.5)
            self.set_x(LEFT_MARGIN)
            self.cell(55, 5, key + ":", new_x=XPos.RIGHT, new_y=YPos.TOP)
            self.set_font("DejaVu", "", 8.5)
            self.multi_cell(CONTENT_WIDTH - 55, 5, val)

        elif is_bullet or is_flag:
            cleaned = text.lstrip("- ").replace("🚨", "").strip()
            cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
            cleaned = re.sub(r"`(.*?)`", r"\1", cleaned)
            self.set_x(18)
            self.cell(5, 5, "•", new_x=XPos.RIGHT, new_y=YPos.TOP)
            self.multi_cell(CONTENT_WIDTH - 5, 5, cleaned)

        elif is_warning:
            cleaned = text.lstrip("> ").strip()
            cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
            self.set_font("DejaVu", "", 8.0)
            self.set_x(LEFT_MARGIN)
            self.set_fill_color(255, 251, 235)
            self.multi_cell(CONTENT_WIDTH, 5, f"  {cleaned}", fill=True)

        else:
            cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
            cleaned = re.sub(r"`(.*?)`",        r"\1", cleaned)
            self.set_x(LEFT_MARGIN)
            self.multi_cell(CONTENT_WIDTH, 5, cleaned)

    def render_table(self, table_lines: list[str], section_context: str = ""):
        data_rows = [
            [cell.strip() for cell in row.strip().strip("|").split("|")]
            for row in table_lines
            if not re.match(r"^\|[-| :]+\|$", row.strip())
        ]
        if not data_rows:
            return

        headers = data_rows[0]
        rows    = data_rows[1:]
        n_cols  = len(headers)

        if section_context == "RAW DATA SNAPSHOT" and n_cols == 4:
            col_widths = RAW_DATA_COL_WIDTHS
        elif section_context == "CONFIDENCE ASSESSMENT" and n_cols == 2:
            col_widths = ASSESSMENT_COL_WIDTHS
        elif n_cols == 2:
            col_widths = [CONTENT_WIDTH * 0.45, CONTENT_WIDTH * 0.55]
        else:
            col_widths = [CONTENT_WIDTH / n_cols] * n_cols

        estimated_table_height = (len(rows) + 1) * 6 + 5
        self._ensure_space(min(estimated_table_height, 40.0))

        self.set_fill_color(*BRAND_DARK)
        self.set_text_color(*WHITE)
        self.set_font("DejaVu", "B", 7)
        self.set_x(LEFT_MARGIN)
        for i, h in enumerate(headers):
            w = col_widths[i] if i < len(col_widths) else CONTENT_WIDTH / n_cols
            self.cell(w, 6, h[:40], border=0, fill=True, align="C",
                      new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.ln()

        self.set_font("DejaVu", "", 7)
        for row_idx, row in enumerate(rows):
            self._ensure_space(6)
            fill_color = LIGHT_BG if row_idx % 2 == 0 else WHITE
            self.set_fill_color(*fill_color)
            self.set_text_color(*BRAND_DARK)

            row_y = self.get_y()
            self.set_x(LEFT_MARGIN)

            for col_idx in range(n_cols):
                w    = col_widths[col_idx] if col_idx < len(col_widths) else CONTENT_WIDTH / n_cols
                val  = row[col_idx].strip() if col_idx < len(row) else ""

                if col_idx == n_cols - 1 and section_context == "RAW DATA SNAPSHOT":
                    val = val[:19].replace("T", " ")

                x_before = self.get_x()
                self.set_xy(LEFT_MARGIN + sum(
                    col_widths[k] if k < len(col_widths) else CONTENT_WIDTH / n_cols
                    for k in range(col_idx)
                ), row_y)
                self.cell(w, 5, val[:45], border=0, fill=True, align="C",
                          new_x=XPos.RIGHT, new_y=YPos.TOP)

            self.ln()

        self.set_draw_color(*BORDER_COLOR)
        self.set_line_width(0.2)
        self.line(LEFT_MARGIN, self.get_y(), PAGE_WIDTH - RIGHT_MARGIN, self.get_y())
        self.ln(3)


def build_pdf(report_markdown: str, run_id: str) -> BytesIO:
    pdf = IntelligenceReportPDF(run_id=run_id)
    pdf._load_fonts()
    pdf.add_page()
    pdf.cover_band(
        title="Market Intelligence Report",
        subtitle=f"Automated signal digest  |  {run_id}"
    )

    lines = report_markdown.splitlines()
    current_section: str = ""
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("# "):
            i += 1
            continue

        if line.startswith("## "):
            current_section = line.replace("## ", "").strip().upper()
            pdf.section_header(line)
            i += 1
            continue

        if line.startswith("|"):
            table_block: list[str] = []
            while i < len(lines) and lines[i].startswith("|"):
                table_block.append(lines[i])
                i += 1
            pdf.render_table(table_block, section_context=current_section)
            continue

        pdf.body_line(line)
        i += 1

    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer