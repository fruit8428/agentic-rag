import csv
import io
import re
import unicodedata
from typing import List
from bs4 import BeautifulSoup, Tag
from docx import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from langsmith import traceable
from pydantic import BaseModel
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = (
    ".pdf",
    ".docx",
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".csv",
    ".txt",
)


class ParsedDocumentResult(BaseModel):
    """模組 5：多格式文件結構化解析結果（統一轉換為 Markdown + 解析統計）。"""

    markdown_text: str
    format_type: str  # PDF | DOCX | HTML | CSV | MARKDOWN | TXT
    parser_engine: str
    section_count: int = 1
    table_count: int = 0
    char_count: int = 0


def decode_text_bytes(content_bytes: bytes) -> str:
    """智慧解碼文字位元組（支援 UTF-8、UTF-8-SIG、Big5/CP950 繁體中文編碼）並執行 NFKC 正規化。"""
    for enc in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            decoded = content_bytes.decode(enc)
            return unicodedata.normalize("NFKC", decoded)
        except Exception:
            continue
    fallback = content_bytes.decode("utf-8", errors="ignore")
    return unicodedata.normalize("NFKC", fallback)


def normalize_clean_text(raw: str) -> str:
    """將文字執行 NFKC 正規化（修正康熙部首與全形符號）並清理多餘空白行。"""
    raw = unicodedata.normalize("NFKC", raw or "")
    lines = []
    for line in raw.splitlines():
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def rows_to_markdown_table(rows: List[List[str]]) -> str:
    """將二維字串陣列轉換為標準 GitHub Flavored Markdown (GFM) 表格。"""
    if not rows:
        return ""
    max_cols = max(len(r) for r in rows)
    if max_cols == 0:
        return ""

    normalized_rows = []
    for r in rows:
        padded = [
            unicodedata.normalize("NFKC", (cell or "")).replace("\n", " ").replace("|", "｜").strip()
            for cell in r
        ] + [""] * (max_cols - len(r))
        if any(padded):
            normalized_rows.append(padded)

    if not normalized_rows:
        return ""

    header = normalized_rows[0]
    separator = ["---"] * max_cols
    body = normalized_rows[1:]

    md_lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for r in body:
        md_lines.append("| " + " | ".join(r) + " |")
    return "\n".join(md_lines)


def parse_pdf_bytes(content_bytes: bytes) -> ParsedDocumentResult:
    """解析 PDF 文件：逐頁提取文字、NFKC 康熙部首正規化，並統計頁數與表格特徵。"""
    reader = PdfReader(io.BytesIO(content_bytes))
    pages_text = []
    table_like_pages = 0

    for idx, page in enumerate(reader.pages):
        txt = normalize_clean_text(page.extract_text() or "")
        if txt:
            if any(k in txt for k in ("姓名", "獎項", "時段", "備註", "分區", "編號", "金額")):
                table_like_pages += 1
            pages_text.append(f"## [第 {idx + 1} 頁]\n{txt}")

    full_md = "\n\n".join(pages_text)
    return ParsedDocumentResult(
        markdown_text=full_md,
        format_type="PDF",
        parser_engine="pypdf + NFKC 結構化解析",
        section_count=len(reader.pages) or 1,
        table_count=table_like_pages,
        char_count=len(full_md),
    )


def parse_docx_bytes(content_bytes: bytes) -> ParsedDocumentResult:
    """
    解析 Word (.docx) 文件：
    依文件原始閱讀順序遍歷段落（Paragraph）與表格（Table），
    將標題轉為 Markdown `#` 語法，並將 Word 表格自動轉為 GFM Markdown 表格！
    """
    doc = DocxDocument(io.BytesIO(content_bytes))
    md_blocks: List[str] = []
    section_count = 0
    table_count = 0

    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            para = DocxParagraph(child, doc)
            text = normalize_clean_text(para.text)
            if not text:
                continue
            style_name = (para.style.name if para.style else "").lower()
            if "heading 1" in style_name or "title" in style_name:
                section_count += 1
                md_blocks.append(f"# {text}")
            elif "heading 2" in style_name:
                section_count += 1
                md_blocks.append(f"## {text}")
            elif "heading 3" in style_name or "heading 4" in style_name:
                section_count += 1
                md_blocks.append(f"### {text}")
            elif "list" in style_name:
                md_blocks.append(f"- {text}")
            else:
                md_blocks.append(text)
        elif isinstance(child, CT_Tbl):
            tbl = DocxTable(child, doc)
            rows_data: List[List[str]] = []
            for row in tbl.rows:
                row_cells = [normalize_clean_text(cell.text) for cell in row.cells]
                if any(row_cells):
                    rows_data.append(row_cells)
            md_table = rows_to_markdown_table(rows_data)
            if md_table:
                table_count += 1
                md_blocks.append(f"\n{md_table}\n")

    full_md = "\n\n".join(md_blocks).strip()
    return ParsedDocumentResult(
        markdown_text=full_md,
        format_type="DOCX",
        parser_engine="Docling-Style DOCX 解析器 (python-docx + GFM 表格轉換)",
        section_count=max(1, section_count),
        table_count=table_count,
        char_count=len(full_md),
    )


def parse_html_bytes(content_bytes: bytes) -> ParsedDocumentResult:
    """
    解析 HTML (.html / .htm) 網頁文件：
    移除 script/style/nav 等雜訊標籤，保留 h1~h6 標題、清單與 HTML <table> 轉 Markdown 表格。
    """
    raw_html = decode_text_bytes(content_bytes)
    soup = BeautifulSoup(raw_html, "lxml")

    for noisy in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer"]):
        noisy.decompose()

    md_blocks: List[str] = []
    section_count = 0
    table_count = 0

    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        md_blocks.append(f"# {normalize_clean_text(title_tag.get_text())}")
        section_count += 1

    body = soup.body or soup
    for elem in body.find_all(["h1", "h2", "h3", "h4", "p", "ul", "ol", "table", "blockquote"]):
        if not isinstance(elem, Tag):
            continue
        # 避免表格內的 <p> 重複輸出
        if elem.name != "table" and elem.find_parent("table") is not None:
            continue

        tag_name = elem.name.lower()
        if tag_name in ("h1", "h2", "h3", "h4"):
            level = int(tag_name[1])
            txt = normalize_clean_text(elem.get_text(" ", strip=True))
            if txt:
                section_count += 1
                md_blocks.append(f"{'#' * level} {txt}")
        elif tag_name == "p" or tag_name == "blockquote":
            txt = normalize_clean_text(elem.get_text(" ", strip=True))
            if txt:
                md_blocks.append(txt)
        elif tag_name in ("ul", "ol"):
            items = []
            for li in elem.find_all("li", recursive=False):
                li_txt = normalize_clean_text(li.get_text(" ", strip=True))
                if li_txt:
                    items.append(f"- {li_txt}")
            if items:
                md_blocks.append("\n".join(items))
        elif tag_name == "table":
            rows_data: List[List[str]] = []
            for tr in elem.find_all("tr"):
                cells = [
                    normalize_clean_text(c.get_text(" ", strip=True))
                    for c in tr.find_all(["th", "td"])
                ]
                if any(cells):
                    rows_data.append(cells)
            md_table = rows_to_markdown_table(rows_data)
            if md_table:
                table_count += 1
                md_blocks.append(f"\n{md_table}\n")

    if not md_blocks:
        fallback_txt = normalize_clean_text(soup.get_text("\n", strip=True))
        if fallback_txt:
            md_blocks.append(fallback_txt)

    full_md = "\n\n".join(md_blocks).strip()
    return ParsedDocumentResult(
        markdown_text=full_md,
        format_type="HTML",
        parser_engine="BeautifulSoup4 DOM-to-Markdown 解析器",
        section_count=max(1, section_count),
        table_count=table_count,
        char_count=len(full_md),
    )


def parse_csv_bytes(content_bytes: bytes) -> ParsedDocumentResult:
    """
    解析 CSV (.csv) 結構化表格檔案：
    每 25 列自動重複一次表頭並轉為 GFM Markdown 表格，確保切塊後每個段落都保有完整欄位名稱！
    """
    raw_text = decode_text_bytes(content_bytes)
    reader = csv.reader(io.StringIO(raw_text))
    all_rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not all_rows:
        return ParsedDocumentResult(
            markdown_text="",
            format_type="CSV",
            parser_engine="CSV 結構化表格轉 Markdown 解析器",
            section_count=1,
            table_count=0,
            char_count=0,
        )

    header = all_rows[0]
    data_rows = all_rows[1:] or []
    blocks: List[str] = []
    batch_size = 25

    if not data_rows:
        blocks.append(rows_to_markdown_table([header]))
    else:
        for i in range(0, len(data_rows), batch_size):
            batch = data_rows[i : i + batch_size]
            md_tbl = rows_to_markdown_table([header] + batch)
            blocks.append(f"### 表格資料區段（第 {i + 1} ～ {i + len(batch)} 筆）\n{md_tbl}")

    full_md = "\n\n".join(blocks).strip()
    return ParsedDocumentResult(
        markdown_text=full_md,
        format_type="CSV",
        parser_engine="CSV 結構化表格轉 Markdown 解析器",
        section_count=max(1, len(blocks)),
        table_count=1,
        char_count=len(full_md),
    )


def parse_markdown_or_txt_bytes(filename: str, content_bytes: bytes) -> ParsedDocumentResult:
    """解析 Markdown (.md) 或純文字 (.txt) 檔案，並統計標題章節與 Markdown 表格數。"""
    text = decode_text_bytes(content_bytes).strip()
    is_md = filename.lower().endswith((".md", ".markdown"))
    headings = len(re.findall(r"^#{1,6}\s+", text, flags=re.MULTILINE))
    md_tables = len(re.findall(r"^\|.+\|\s*\n\|[\s:\-\|]+\|", text, flags=re.MULTILINE))

    return ParsedDocumentResult(
        markdown_text=text,
        format_type="MARKDOWN" if is_md else "TXT",
        parser_engine="原生 Markdown 結構解析器" if is_md else "UTF-8/Big5 智慧純文字解析器",
        section_count=max(1, headings),
        table_count=md_tables,
        char_count=len(text),
    )


@traceable(name="parse_multiformat_document", run_type="parser")
def parse_document_multiformat(filename: str, content_bytes: bytes) -> ParsedDocumentResult:
    """
    模組 5：多格式文件統一解析入口（支援 PDF、DOCX、HTML、CSV、Markdown、TXT）。
    將所有格式統一轉為結構化 Markdown 並回傳解析統計資訊。
    """
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        return parse_pdf_bytes(content_bytes)
    if lower.endswith(".docx"):
        return parse_docx_bytes(content_bytes)
    if lower.endswith((".html", ".htm")):
        return parse_html_bytes(content_bytes)
    if lower.endswith(".csv"):
        return parse_csv_bytes(content_bytes)
    return parse_markdown_or_txt_bytes(filename, content_bytes)
