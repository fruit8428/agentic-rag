-- ============================================================================
-- 模組 7：附加工具（Text-to-SQL 結構化數據查詢視圖與輔助函數）
-- 遵循行級安全性（RLS）：僅允許查詢當前登入用戶（auth.uid()）自己的文件與統計數據
-- ============================================================================

-- 1. 建立用戶知識庫結構化統計視圖（供 Text-to-SQL 工具查詢文件清單、分類、分塊數與字數統計）
CREATE OR REPLACE VIEW public.user_documents_analytics
WITH (security_invoker = true) AS
SELECT
    d.id AS document_id,
    d.user_id,
    d.filename,
    d.status,
    d.created_at,
    d.updated_at,
    COUNT(c.id) AS total_chunks,
    COALESCE(SUM(LENGTH(c.content)), 0) AS total_characters,
    MAX(c.metadata -> 'extracted_metadata' ->> 'document_title') AS document_title,
    MAX(c.metadata -> 'extracted_metadata' ->> 'category') AS category,
    MAX(c.metadata -> 'extracted_metadata' ->> 'event_or_year') AS event_or_year,
    MAX(c.metadata ->> 'file_hash') AS file_hash
FROM public.documents d
LEFT JOIN public.document_chunks c ON c.document_id = d.id
WHERE d.user_id = auth.uid()
GROUP BY d.id, d.user_id, d.filename, d.status, d.created_at, d.updated_at;
