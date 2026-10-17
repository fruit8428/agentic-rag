-- ============================================================
-- 模組 4：元數據提取（Metadata Extraction 與過濾檢索）Schema
-- 註：後端已直接利用現有的 document_chunks.metadata (JSONB) 儲存與過濾結構化元數據，
--     因此即使未手動執行此 SQL，模組 4 的所有功能仍可 100% 正常運作！
-- ============================================================

-- 1. 為 documents 表新增選配的 extracted_metadata 欄位
alter table public.documents
add column if not exists extracted_metadata jsonb not null default '{}'::jsonb;

-- 2. 為 document_chunks 表的 metadata 欄位建立 GIN 索引，加速按元數據標籤與類別過濾
create index if not exists idx_document_chunks_metadata_gin
    on public.document_chunks using gin (metadata);
