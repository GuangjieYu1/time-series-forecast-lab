from __future__ import annotations

import base64
import html
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from app.core.errors import AppError

try:
    from PIL import Image as PILImage
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        HRFlowable,
        Image,
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        Preformatted,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    REPORTLAB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised through runtime guard
    REPORTLAB_IMPORT_ERROR = exc


_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_ORDERED_RE = re.compile(r"^\d+\.\s+")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
_DATA_URL_RE = re.compile(r"^data:image/[^;]+;base64,(.+)$", re.IGNORECASE | re.DOTALL)
_FONT_REGISTERED = False
_BASE_FONT_NAME = "Helvetica"
_EMBEDDED_FONT_CANDIDATES: list[tuple[str, str]] = [
    ("ReportSans", "C:/Windows/Fonts/simhei.ttf"),
    ("ReportSans", "C:/Windows/Fonts/msyh.ttc"),
    ("ReportSans", "C:/Windows/Fonts/simsun.ttc"),
    ("ReportSans", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ("ReportSans", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ("ReportSans", "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    ("ReportSans", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
]


def build_report_pdf(
    *,
    title: str,
    content_markdown: str,
    visual_artifacts: list[dict[str, Any]] | None = None,
) -> bytes:
    if REPORTLAB_IMPORT_ERROR is not None:
        raise AppError(
            "当前环境缺少文本型 PDF 导出依赖 reportlab，请先安装后再重试。",
            500,
            "REPORT_PDF_DEPENDENCY_MISSING",
            {"dependency": "reportlab", "error": str(REPORTLAB_IMPORT_ERROR)},
        )

    _ensure_fonts()
    styles = _build_styles()
    story: list[Any] = [Paragraph(_inline_markup(title), styles["title"]), Spacer(1, 6 * mm)]
    story.extend(_markdown_to_story(content_markdown, styles))
    artifacts = visual_artifacts or []
    if artifacts:
        story.append(PageBreak())
        story.append(Paragraph("附录：图像与结果解读", styles["heading2"]))
        story.append(Paragraph("图像会作为插图进入 PDF，标题、说明和结论摘要保持为真实文本，支持复制与搜索。", styles["body"]))
        story.append(Spacer(1, 2 * mm))
        for artifact in artifacts:
            story.extend(_artifact_to_story(artifact, styles))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title,
        author="Time Series Forecast Lab",
        pageCompression=1,
    )
    document.build(story, onFirstPage=_decorate_page(title), onLaterPages=_decorate_page(title))
    return buffer.getvalue()


def _decorate_page(title: str):
    def _draw(canvas, document):
        canvas.saveState()
        canvas.setFont(_BASE_FONT_NAME, 9)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(document.leftMargin, 10 * mm, title[:80])
        canvas.drawRightString(document.pagesize[0] - document.rightMargin, 10 * mm, f"{canvas.getPageNumber()}")
        canvas.restoreState()

    return _draw


def _ensure_fonts() -> None:
    global _FONT_REGISTERED, _BASE_FONT_NAME
    if _FONT_REGISTERED:
        return
    for font_name, font_path in _EMBEDDED_FONT_CANDIDATES:
        candidate = Path(font_path)
        if not candidate.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(font_name, str(candidate)))
            pdfmetrics.registerFontFamily(
                font_name,
                normal=font_name,
                bold=font_name,
                italic=font_name,
                boldItalic=font_name,
            )
            _BASE_FONT_NAME = font_name
            _FONT_REGISTERED = True
            return
        except Exception:
            continue

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdfmetrics.registerFontFamily(
        "STSong-Light",
        normal="STSong-Light",
        bold="STSong-Light",
        italic="STSong-Light",
        boldItalic="STSong-Light",
    )
    _BASE_FONT_NAME = "STSong-Light"
    _FONT_REGISTERED = True


def _build_styles() -> dict[str, ParagraphStyle]:
    base_font = _BASE_FONT_NAME
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            fontName=base_font,
            fontSize=22,
            leading=28,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=8,
            alignment=TA_LEFT,
        ),
        "heading1": ParagraphStyle(
            "Heading1",
            fontName=base_font,
            fontSize=18,
            leading=24,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=4,
            spaceAfter=8,
        ),
        "heading2": ParagraphStyle(
            "Heading2",
            fontName=base_font,
            fontSize=15,
            leading=20,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=6,
            spaceAfter=6,
        ),
        "heading3": ParagraphStyle(
            "Heading3",
            fontName=base_font,
            fontSize=12.5,
            leading=18,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=4,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName=base_font,
            fontSize=10.5,
            leading=17,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=5,
        ),
        "caption": ParagraphStyle(
            "Caption",
            fontName=base_font,
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#475569"),
            spaceAfter=4,
        ),
        "quote": ParagraphStyle(
            "Quote",
            fontName=base_font,
            fontSize=10,
            leading=17,
            textColor=colors.HexColor("#164e63"),
            backColor=colors.HexColor("#ecfeff"),
            borderPadding=8,
            borderWidth=0.75,
            borderColor=colors.HexColor("#67e8f9"),
            leftIndent=4,
            spaceAfter=6,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            fontName=base_font,
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#334155"),
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            fontName=base_font,
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#0f172a"),
        ),
    }


def _inline_markup(text: str) -> str:
    placeholders: list[tuple[str, str]] = []

    def _placeholder(value: str) -> str:
        token = f"@@TOKEN_{len(placeholders)}@@"
        placeholders.append((token, value))
        return token

    value = text
    value = _INLINE_CODE_RE.sub(
        lambda match: _placeholder(f'<font name="Courier">{html.escape(match.group(1))}</font>'),
        value,
    )
    value = _LINK_RE.sub(
        lambda match: _placeholder(
            f'<link href="{html.escape(match.group(2), quote=True)}" color="#0f766e">{html.escape(match.group(1))}</link>'
        ),
        value,
    )
    value = _BOLD_RE.sub(lambda match: _placeholder(f"<b>{html.escape(match.group(1))}</b>"), value)
    value = html.escape(value).replace("\n", "<br/>")
    for token, replacement in placeholders:
        value = value.replace(token, replacement)
    return value


def _markdown_to_story(content_markdown: str, styles: dict[str, ParagraphStyle]) -> list[Any]:
    lines = content_markdown.replace("\r\n", "\n").split("\n")
    story: list[Any] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        trimmed = line.strip()
        next_line = lines[index + 1] if index + 1 < len(lines) else None

        if not trimmed:
            index += 1
            continue

        if trimmed.startswith("```"):
            language = trimmed[3:].strip() or "text"
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            story.append(Paragraph(f"代码块 · {html.escape(language)}", styles["caption"]))
            story.append(
                Preformatted(
                    "\n".join(code_lines) or "",
                    ParagraphStyle(
                        "CodeBlock",
                        fontName="Courier",
                        fontSize=8.8,
                        leading=12,
                        textColor=colors.HexColor("#f8fafc"),
                        backColor=colors.HexColor("#0f172a"),
                        borderPadding=10,
                        spaceAfter=8,
                    ),
                )
            )
            continue

        if re.match(r"^#{1,3}\s", trimmed):
            level = len(trimmed.split(" ", 1)[0])
            text = trimmed[level + 1 :]
            style = styles["heading1"] if level == 1 else styles["heading2"] if level == 2 else styles["heading3"]
            story.append(Paragraph(_inline_markup(text), style))
            index += 1
            continue

        if re.match(r"^(-{3,}|\*{3,})$", trimmed):
            story.append(HRFlowable(color=colors.HexColor("#cbd5e1"), thickness=0.8, spaceBefore=6, spaceAfter=6))
            index += 1
            continue

        if trimmed.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip()[1:].lstrip())
                index += 1
            story.append(Paragraph(_inline_markup("\n".join(quote_lines)), styles["quote"]))
            continue

        if re.match(r"^[-*]\s+", trimmed):
            items: list[Any] = []
            while index < len(lines) and re.match(r"^[-*]\s+", lines[index].strip()):
                content = re.sub(r"^[-*]\s+", "", lines[index].strip())
                items.append(ListItem(Paragraph(_inline_markup(content), styles["body"])))
                index += 1
            story.append(ListFlowable(items, bulletType="bullet", leftIndent=16))
            story.append(Spacer(1, 2 * mm))
            continue

        if _ORDERED_RE.match(trimmed):
            items = []
            while index < len(lines) and _ORDERED_RE.match(lines[index].strip()):
                content = _ORDERED_RE.sub("", lines[index].strip())
                items.append(ListItem(Paragraph(_inline_markup(content), styles["body"])))
                index += 1
            story.append(ListFlowable(items, bulletType="1", leftIndent=16))
            story.append(Spacer(1, 2 * mm))
            continue

        if "|" in trimmed and next_line and _TABLE_SEPARATOR_RE.match(next_line.strip()):
            table_lines = [line, next_line]
            index += 2
            while index < len(lines) and "|" in lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            story.append(_build_table(table_lines, styles))
            story.append(Spacer(1, 2 * mm))
            continue

        paragraph_lines = [line]
        index += 1
        while index < len(lines) and not _is_special_block_start(lines[index], lines[index + 1] if index + 1 < len(lines) else None):
            paragraph_lines.append(lines[index])
            index += 1
        story.append(Paragraph(_inline_markup("\n".join(value.strip() for value in paragraph_lines)), styles["body"]))

    return story


def _is_special_block_start(line: str, next_line: str | None) -> bool:
    trimmed = line.strip()
    return (
        not trimmed
        or trimmed.startswith("```")
        or bool(re.match(r"^#{1,3}\s", trimmed))
        or bool(re.match(r"^(-{3,}|\*{3,})$", trimmed))
        or trimmed.startswith(">")
        or bool(re.match(r"^[-*]\s+", trimmed))
        or bool(_ORDERED_RE.match(trimmed))
        or ("|" in trimmed and bool(next_line) and bool(_TABLE_SEPARATOR_RE.match(next_line.strip())))
    )


def _build_table(lines: list[str], styles: dict[str, ParagraphStyle]):
    rows = []
    for line in lines:
        trimmed = line.strip().strip("|")
        rows.append([cell.strip() for cell in trimmed.split("|")])

    header = rows[0]
    body = rows[2:]
    data = [
        [Paragraph(_inline_markup(cell), styles["table_header"]) for cell in header],
        *[[Paragraph(_inline_markup(cell), styles["table_cell"]) for cell in row] for row in body],
    ]
    table = Table(data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#334155")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _artifact_to_story(artifact: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    title = str(artifact.get("title") or "图像")
    caption = str(artifact.get("caption") or "")
    summary = [str(item) for item in artifact.get("summary") or [] if str(item).strip()]
    story: list[Any] = [
        Paragraph(_inline_markup(title), styles["heading3"]),
    ]
    if caption:
        story.append(Paragraph(_inline_markup(caption), styles["caption"]))
    image = _build_image(artifact.get("dataUrl"))
    if image is not None:
        story.append(image)
        story.append(Spacer(1, 2 * mm))
    if summary:
        items = [ListItem(Paragraph(_inline_markup(item), styles["body"])) for item in summary]
        story.append(ListFlowable(items, bulletType="bullet", leftIndent=16))
        story.append(Spacer(1, 3 * mm))
    return story


def _build_image(data_url: Any):
    if not isinstance(data_url, str):
        return None
    match = _DATA_URL_RE.match(data_url.strip())
    if not match:
        return None
    try:
        raw = base64.b64decode(match.group(1))
        source = BytesIO(raw)
        with PILImage.open(BytesIO(raw)) as pil_image:
            width, height = pil_image.size
        flowable = Image(source)
        max_width = A4[0] - 32 * mm
        max_height = 120 * mm
        scale = min(max_width / max(width, 1), max_height / max(height, 1), 1.0)
        flowable.drawWidth = width * scale
        flowable.drawHeight = height * scale
        flowable.hAlign = "CENTER"
        return flowable
    except Exception:
        return None
