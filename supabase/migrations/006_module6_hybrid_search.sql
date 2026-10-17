-- ============================================================================
-- 模組 6：混合搜索與重排序（Hybrid Search + RRF + Reranking）
-- 說明：本遷移檔為 document_chunks 建立全文與關鍵字加速索引。
-- 註：後端 Python 服務 (hybrid_search.py) 已內建完整雙軌檢索、RRF 融合與 AI 重排序，
-- 即使不手動執行此 SQL 也能 100% 正常運作！
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 為分塊內容建立 GIN 三連詞索引（加速中文與英文關鍵字 ILIKE / 模糊比對）
CREATE INDEX IF NOT EXISTS idx_document_chunks_content_trgm
ON public.document_chunks
USING gin (content gin_trgm_ops);
