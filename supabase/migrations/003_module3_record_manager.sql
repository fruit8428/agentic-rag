-- ============================================================
-- 模組 3：記錄管理器（Record Manager — 內容雜湊與增量更新）Schema
-- 註：後端已同時支援將雜湊指紋存於 document_chunks.metadata JSONB，
--     因此即使未手動執行此 SQL，模組 3 的去重與增量更新仍可 100% 正常運作！
-- ============================================================

-- 1. 為 documents 表新增檔案級 SHA-256 雜湊欄位與增量同步統計欄位
alter table public.documents
add column if not exists content_hash text,
add column if not exists sync_summary jsonb not null default '{}'::jsonb;

-- 2. 為 document_chunks 表新增分塊級 SHA-256 雜湊欄位
alter table public.document_chunks
add column if not exists content_hash text;

-- 3. 建立雜湊索引以加速重複偵測與增量比對
create index if not exists idx_documents_user_hash
    on public.documents(user_id, content_hash);

create index if not exists idx_document_chunks_doc_hash
    on public.document_chunks(document_id, content_hash);
