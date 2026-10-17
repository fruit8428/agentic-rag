import io
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pypdf import PdfReader
from langsmith import traceable
from app.auth import get_admin_supabase, get_user_supabase
from app.config import settings
from app.llm import llm_client


def normalize_pdf_page_text(raw: str) -> str:
    """修復部分中文 PDF 康熙部首異體字（NFKC 正規化）與每個中文字被單獨換行的排版問題。"""
    if not raw:
        return ""
    raw = unicodedata.normalize("NFKC", raw)
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return ""
    short_lines = sum(1 for line in lines if len(line.strip()) <= 2)
    # 若超過一半的行數都是單字斷行，進行智慧段落重組
    if len(lines) > 10 and (short_lines / len(lines)) > 0.5:
        txt = re.sub(r"([。！？：])\s*\n\s*\n\s*", r"\1\n\n", raw)
        txt = re.sub(r"\n \n", " ", txt)
        txt = re.sub(r"(?<!\n)\n(?!\n)", "", txt)
        return txt.strip()
    return raw.strip()


def extract_text_from_bytes(filename: str, content_bytes: bytes) -> str:
    """從上傳的 PDF、Markdown 或純文字檔中提取文字內容。"""
    lower_name = filename.lower()
    if lower_name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content_bytes))
        pages_text = []
        for idx, page in enumerate(reader.pages):
            page_txt = normalize_pdf_page_text(page.extract_text() or "")
            if page_txt:
                pages_text.append(f"[第 {idx + 1} 頁]\n{page_txt}")
        return "\n\n".join(pages_text)
    else:
        # 支援 UTF-8 / Big5 純文字與 Markdown
        for encoding in ("utf-8", "utf-8-sig", "big5", "latin-1"):
            try:
                return content_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content_bytes.decode("utf-8", errors="ignore")


def chunk_text(
    text: str, chunk_size: int = 800, chunk_overlap: int = 150
) -> list[str]:
    """
    將長文本切分為具重疊區間（Overlap）的語意區塊（Chunks），
    優先在段落、換行或句號處切分，避免截斷完整句子。
    """
    cleaned = text.replace("\r\n", "\n").strip()
    if not cleaned:
        return []

    if len(cleaned) <= chunk_size:
        return [cleaned]

    separators = ["\n\n", "\n", "。", "！", "？", ". ", " ", ""]
    chunks: list[str] = []
    start = 0
    text_len = len(cleaned)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        if end < text_len:
            # 在結尾往前尋找最適合的自然斷句點
            window = cleaned[start:end]
            best_split = -1
            for sep in separators:
                if not sep:
                    continue
                pos = window.rfind(sep)
                if pos > chunk_size // 2:
                    best_split = start + pos + len(sep)
                    break
            if best_split != -1:
                end = best_split

        chunk_str = cleaned[start:end].strip()
        if chunk_str:
            chunks.append(chunk_str)

        if end >= text_len:
            break

        start = max(start + 1, end - chunk_overlap)

    return chunks


@traceable(name="gemini_embed_batch", run_type="embedding")
async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    呼叫 Google AI Studio (Gemini) Embedding 模型將文字陣列轉為 768 維向量。
    內建 429 (Rate Limit) 與 503 自動等待重試機制，確保大檔案導入永遠不會因免費版每分鐘配額中斷！
    """
    import asyncio

    all_embeddings: list[list[float]] = []
    batch_size = 25
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        for attempt in range(5):
            try:
                resp = await llm_client.embeddings.create(
                    model=settings.EMBEDDING_MODEL,
                    input=batch,
                    dimensions=768,
                )
                for item in resp.data:
                    all_embeddings.append(item.embedding)
                break
            except Exception as e:
                err_str = str(e)
                if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str) and attempt < 4:
                    wait_sec = 6 * (attempt + 1)
                    await asyncio.sleep(wait_sec)
                    continue
                raise
        # 批次間微幅緩衝，避免瞬間衝破免費版 RPM 限制
        if i + batch_size < len(texts):
            await asyncio.sleep(0.4)
    return all_embeddings


@traceable(name="gemini_embed_query", run_type="embedding")
async def embed_query(query: str) -> list[float]:
    """將使用者的搜尋問題轉為 768 維向量（含 429/503 自動重試）。"""
    import asyncio

    for attempt in range(3):
        try:
            resp = await llm_client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=query,
                dimensions=768,
            )
            return resp.data[0].embedding
        except Exception as e:
            err_str = str(e)
            if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str) and attempt < 2:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            raise


@traceable(name="ingest_document_pipeline", run_type="chain")
async def process_document_background(
    doc_id: str,
    user_id: str,
    filename: str,
    content_bytes: bytes,
    access_token: str,
    is_new_document: bool = True,
):
    """
    背景執行模組 5 多格式文件解析 (PDF/DOCX/HTML/CSV/MD/TXT) -> 分塊 (Chunking) ->
    模組 3 記錄管理器 (Record Manager SHA-256 增量比對) ->
    僅針對新增/修改分塊呼叫 Gemini 向量化 (Embedding) ->
    模組 4 AI 結構化元數據提取 -> 存入 pgvector 並更新 documents 狀態。
    """
    from app.services.document_parser import parse_document_multiformat
    from app.services.record_manager import compute_sha256_bytes, reconcile_and_sync_chunks

    admin_supabase = get_admin_supabase()
    try:
        file_hash = compute_sha256_bytes(content_bytes)

        # 1. 模組 5：多格式文件解析（自動將 PDF / DOCX / HTML / CSV / MD / TXT 轉為結構化 Markdown）
        parsed_result = parse_document_multiformat(filename, content_bytes)
        full_text = parsed_result.markdown_text
        if not full_text or not full_text.strip():
            raise ValueError("無法從此檔案中提取出任何文字內容（請確認檔案不是純掃描圖片或空檔）")

        # 2. 分塊 (Chunking：使用 1400 字元區塊，完整保留大型表格上下文並減少一半 API 配額消耗)
        chunks = chunk_text(full_text, chunk_size=1400, chunk_overlap=200)
        if not chunks:
            raise ValueError("文件切塊結果為空")

        # 3. 交由模組 3 記錄管理器 (Record Manager) 進行 SHA-256 雜湊比對與增量同步
        await reconcile_and_sync_chunks(
            supabase_client=admin_supabase,
            doc_id=doc_id,
            user_id=user_id,
            filename=filename,
            file_hash=file_hash,
            new_chunks=chunks,
            embed_fn=embed_texts,
            is_new_document=is_new_document,
        )

        # 4. 儲存模組 5 多格式解析統計（parse_info）至第 0 號分塊 metadata
        try:
            c0_res = (
                admin_supabase.table("document_chunks")
                .select("id, metadata")
                .eq("document_id", doc_id)
                .eq("chunk_index", 0)
                .execute()
            )
            if c0_res.data:
                meta0 = dict(c0_res.data[0].get("metadata") or {})
                meta0["parse_info"] = parsed_result.model_dump(exclude={"markdown_text"})
                admin_supabase.table("document_chunks").update({"metadata": meta0}).eq(
                    "id", c0_res.data[0]["id"]
                ).execute()
        except Exception:
            pass

        # 5. 模組 4：透過 Gemini + Pydantic 自動提取結構化文件元數據（類別、年份、摘要、關鍵字標籤）
        try:
            from app.services.metadata_extractor import extract_and_save_document_metadata

            await extract_and_save_document_metadata(
                admin_supabase=admin_supabase,
                doc_id=doc_id,
                filename=filename,
                full_text=full_text,
            )
        except Exception:
            pass

        # 6. 更新文件狀態為 completed（觸發 Supabase Realtime）
        admin_supabase.table("documents").update(
            {
                "status": "completed",
                "chunk_count": len(chunks),
                "error_message": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", doc_id).eq("user_id", user_id).execute()

    except Exception as e:
        admin_supabase.table("documents").update(
            {
                "status": "failed",
                "error_message": str(e),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", doc_id).eq("user_id", user_id).execute()
