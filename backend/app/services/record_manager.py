import hashlib
import uuid
from datetime import datetime, timezone
from typing import Callable, Awaitable
from langsmith import traceable


def compute_sha256_bytes(data: bytes) -> str:
    """計算原始檔案位元組的 SHA-256 雜湊指紋。"""
    return hashlib.sha256(data).hexdigest()


def compute_sha256_text(text: str) -> str:
    """計算文字分塊（Chunk）正規化後的 SHA-256 雜湊指紋。"""
    normalized = text.replace("\r\n", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@traceable(name="record_manager_reconcile_chunks", run_type="chain")
async def reconcile_and_sync_chunks(
    supabase_client,
    doc_id: str,
    user_id: str,
    filename: str,
    file_hash: str,
    new_chunks: list[str],
    embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
    is_new_document: bool = False,
) -> dict:
    """
    模組 3 核心：記錄管理器（Record Manager）
    比對新舊文件分塊的 SHA-256 雜湊指紋：
    - 未變更的分塊（Unchanged）：直接保留原向量，零 API 呼叫！
    - 新增或修改的分塊（Added/Modified）：僅針對變更部分呼叫 Gemini Embedding API。
    - 已移除的舊分塊（Removed）：自動從資料庫刪除，避免殘留過期資訊。
    """
    existing_res = (
        supabase_client.table("document_chunks")
        .select("id, chunk_index, content, metadata")
        .eq("document_id", doc_id)
        .order("chunk_index", desc=False)
        .execute()
    )
    existing_rows = existing_res.data or []

    # 建立現有分塊的雜湊索引池：hash -> list of row dicts
    pool_by_hash: dict[str, list[dict]] = {}
    for row in existing_rows:
        meta = row.get("metadata") or {}
        c_hash = meta.get("content_hash") or compute_sha256_text(row.get("content", ""))
        pool_by_hash.setdefault(c_hash, []).append(row)
        # 若該分塊曾有人工校正（manual_override），同時註冊原始雜湊以免重傳時覆蓋校正內容
        orig_hash = meta.get("original_hash")
        if orig_hash and orig_hash != c_hash:
            pool_by_hash.setdefault(orig_hash, []).append(row)

    reused_row_ids: set[str] = set()
    plan_items: list[dict] = []
    texts_to_embed: list[str] = []

    for idx, chunk_str in enumerate(new_chunks):
        c_hash = compute_sha256_text(chunk_str)
        candidates = pool_by_hash.get(c_hash, [])
        matched_row = None
        for cand in candidates:
            if cand["id"] not in reused_row_ids:
                matched_row = cand
                break

        if matched_row is not None:
            reused_row_ids.add(matched_row["id"])
            plan_items.append(
                {
                    "type": "reused",
                    "chunk_index": idx,
                    "content_hash": (matched_row.get("metadata") or {}).get("content_hash", c_hash),
                    "row": matched_row,
                }
            )
        else:
            embed_pos = len(texts_to_embed)
            texts_to_embed.append(chunk_str)
            plan_items.append(
                {
                    "type": "new",
                    "chunk_index": idx,
                    "content": chunk_str,
                    "content_hash": c_hash,
                    "embed_pos": embed_pos,
                }
            )

    # 找出舊版中已不存在的分塊 ID 並刪除
    removed_ids = [r["id"] for r in existing_rows if r["id"] not in reused_row_ids]
    if removed_ids:
        for i in range(0, len(removed_ids), 50):
            batch_ids = removed_ids[i : i + 50]
            supabase_client.table("document_chunks").delete().in_("id", batch_ids).execute()

    # 僅針對新增/修改的分塊呼叫 Gemini Embedding API
    new_vectors: list[list[float]] = []
    if texts_to_embed:
        new_vectors = await embed_fn(texts_to_embed)

    unchanged_count = sum(1 for item in plan_items if item["type"] == "reused")
    added_count = len(texts_to_embed)
    removed_count = len(removed_ids)

    if is_new_document or not existing_rows:
        sync_mode = "created"
    elif added_count == 0 and removed_count == 0:
        sync_mode = "unchanged"
    else:
        sync_mode = "incremental"

    sync_summary = {
        "mode": sync_mode,
        "file_hash": file_hash,
        "short_hash": file_hash[:12],
        "total_chunks": len(new_chunks),
        "unchanged_chunks": unchanged_count,
        "added_chunks": added_count,
        "removed_chunks": removed_count,
        "saved_embeddings": unchanged_count if not is_new_document else 0,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }

    # 更新保留分塊的 chunk_index 與 metadata，並組裝新分塊進行批次寫入
    rows_to_insert = []
    for item in plan_items:
        idx = item["chunk_index"]
        if item["type"] == "reused":
            old_row = item["row"]
            old_meta = dict(old_row.get("metadata") or {})
            old_meta["filename"] = filename
            old_meta["chunk_index"] = idx
            old_meta["total_chunks"] = len(new_chunks)
            old_meta["content_hash"] = item["content_hash"]
            old_meta["file_hash"] = file_hash
            if idx == 0:
                old_meta["doc_sync"] = sync_summary

            if old_row.get("chunk_index") != idx or idx == 0 or "content_hash" not in (old_row.get("metadata") or {}):
                supabase_client.table("document_chunks").update(
                    {
                        "chunk_index": idx,
                        "metadata": old_meta,
                    }
                ).eq("id", old_row["id"]).execute()
        else:
            vec = new_vectors[item["embed_pos"]]
            meta = {
                "filename": filename,
                "chunk_index": idx,
                "total_chunks": len(new_chunks),
                "content_hash": item["content_hash"],
                "file_hash": file_hash,
            }
            if idx == 0:
                meta["doc_sync"] = sync_summary

            rows_to_insert.append(
                {
                    "id": str(uuid.uuid4()),
                    "document_id": doc_id,
                    "user_id": user_id,
                    "chunk_index": idx,
                    "content": item["content"],
                    "metadata": meta,
                    "embedding": vec,
                }
            )

    if rows_to_insert:
        for i in range(0, len(rows_to_insert), 50):
            supabase_client.table("document_chunks").insert(rows_to_insert[i : i + 50]).execute()

    return sync_summary
