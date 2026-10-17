# 進度

追蹤你在大師課中的進度。完成模組後更新此文件 - Claude Code 會讀取此文件以了解你在項目中的位置。

## 慣例
- `[ ]` = 未開始
- `[-]` = 進行中
- `[x]` = 已完成

## 模組

### 模組 1：應用外殼 + 可觀測性
- [x] 1. 規劃並建立模組 1 實施計劃（`.agent/plans/1.應用外殼與可觀測性.md`）
- [x] 2. 建立 Supabase 資料表（`threads`、`messages`）與行級安全性（RLS）
- [x] 3. 建立 Python FastAPI 後端（`venv`、Supabase 認證驗證、Gemini SSE 串流對話、LangSmith 追蹤）
- [x] 4. 建立 React + Vite + Tailwind + shadcn/ui 前端（登入/註冊介面、對話線程列表、即時串流聊天室）
- [x] 5. 端到端驗證測試（認證、對話儲存、Gemini 回應、LangSmith 追蹤紀錄）

### 模組 2：自建檢索 + 文件導入
- [x] 1. 規劃並建立模組 2 實施計劃（`.agent/plans/2.自建檢索與文件導入.md`）
- [x] 2. 建立 Supabase `pgvector` 資料表（`documents`、`document_chunks`）、RLS 與 `match_document_chunks` 檢索函數
- [x] 3. 建立後端文件導入管道（PDF/文字解析、分塊、Gemini 768 維 Embedding）與 Agent 檢索工具調用
- [x] 4. 建立前端「文件導入」拖放上傳介面（含 Supabase Realtime 狀態更新）與聊天室檢索來源展示
- [x] 5. 端到端驗證測試（上傳 PDF 文件、向量檢索問答、LangSmith 追蹤檢視）

### 模組 3：記錄管理器（去重與增量更新）
- [x] 1. 規劃並建立模組 3 實施計劃（`.agent/plans/3.記錄管理器與增量更新.md`）
- [x] 2. 建立 SHA-256 內容雜湊指紋計算與現有文件指紋回填（`supabase/migrations/003_module3_record_manager.sql` + JSONB 向下兼容）
- [x] 3. 建立後端記錄管理器服務（`backend/app/services/record_manager.py`：完全重複檔案攔截、同名改版文件分塊 Diff 與增量更新）
- [x] 4. 升級前端「文件導入」介面（顯示 SHA-256 指紋、增量同步統計徽章，以及「一鍵體驗去重與增量更新」互動實驗室）
- [x] 5. 端到端驗證測試（測試重複上傳攔截與改版文件增量更新）

### 模組 4：元數據提取（Metadata Extraction 與過濾檢索）
- [x] 1. 規劃並建立模組 4 實施計劃（`.agent/plans/4.元數據提取與過濾檢索.md`）
- [x] 2. 建立元數據儲存結構（`supabase/migrations/004_module4_metadata_schema.sql` + `document_chunks.metadata` JSONB 零斷點相容）
- [x] 3. 建立 Pydantic 結構化元數據提取服務（`backend/app/services/metadata_extractor.py`：使用 `DocumentMetadataSchema` 自動提取標題、分類、年份/活動日期、核心摘要與關鍵標籤）
- [x] 4. 升級後端檢索工具（`backend/app/routers/chat.py`：支援依文件 `document_id` 與 AI 分類 `category` 過濾檢索，並自動去重跨版本相同內容分塊）
- [x] 5. 升級前端「文件導入」與「AI 聊天」介面（顯示 AI 結構化元數據卡片、重新提取按鈕，以及對話輸入框上方的元數據檢索過濾器）

### 模組 5：多格式文件支持與級聯刪除
- [x] 1. 規劃並建立模組 5 實施計劃（`.agent/plans/5.多格式文件支持與級聯刪除.md`）
- [x] 2. 安裝並建立多格式統一轉 Markdown 解析器（`backend/app/services/document_parser.py`：支援 PDF、DOCX Word 表格轉 Markdown、HTML 網頁雜訊濾除與表格轉換、CSV 結構化表格、Markdown、TXT）
- [x] 3. 升級文件導入管道與 API（`backend/app/services/ingestion.py` 與 `backend/app/routers/documents.py`：記錄 `parse_info` 解析器統計，並新增 `/api/documents/demo/docx` 真實 Word 測試端點）
- [x] 4. 實作完整級聯刪除與零孤兒驗證（`DELETE /api/documents/{document_id}`：同步清除 Storage 原檔、`documents` 主表與 `document_chunks` 向量分塊，並驗證 0 殘留）
- [x] 5. 升級前端「文件導入」介面（`frontend/src/components/IngestView.tsx`：新增「模組 5 多格式解析實驗室」、格式與解析引擎徽章，以及「級聯刪除完整性報告橫幅」）

### 模組 6：混合搜索與重排序（Hybrid Search + RRF + Reranking）
- [x] 1. 規劃並建立模組 6 實施計劃（`.agent/plans/6.混合搜索與重排序.md`）與 SQL 遷移檔（`supabase/migrations/006_module6_hybrid_search.sql`）
- [x] 2. 建立三階段混合檢索與重排序引擎（`backend/app/services/hybrid_search.py`：雙軌並行檢索 `lexical_keyword_search` + `dense_vector_search`、倒數排名融合 `reciprocal_rank_fusion` RRF $k=60$、以及 AI 語意重排序 `rerank_candidates` 含專有名詞零遺漏保護）
- [x] 3. 升級後端聊天檢索管道（`backend/app/routers/chat.py`：在 `run_agentic_rag_turn` 全面接入 `execute_hybrid_rerank_search` 並輸出完整混合檢索與重排序指標）
- [x] 4. 升級前端聊天室檢索來源卡片（`frontend/src/components/ChatView.tsx` 與 `frontend/src/App.tsx`：顯示 `🔥 雙軌命中` / `🎯 關鍵字命中` / `🧠 向量語意命中` 徽章、RRF 分數與雙軌排名、以及 `✨ Rerank 精準度` 與重排序依據）
- [x] 5. 端到端驗證測試（驗證 RRF 雙軌融合排名、AI Reranking 與前端 TypeScript 編譯）

### 模組 7：附加工具（Text-to-SQL 結構化數據查詢 ＋ 網路搜索回退 Web Search Fallback）
- [x] 1. 規劃並建立模組 7 實施計劃（`.agent/plans/7.附加工具與網路搜索.md`）與 SQL 結構化統計視圖（`supabase/migrations/007_module7_additional_tools.sql`）
- [x] 2. 建立多工具服務（`backend/app/services/additional_tools.py`：Pydantic `StructuredSqlQueryPlanSchema` + `execute_structured_sql_tool` 全表結構化統計查詢，以及 `execute_web_search_tool` 結合 DuckDuckGo / Google News RSS / 中文維基百科之即時網路搜索）
- [x] 3. 升級多工具代理路由（`backend/app/routers/chat.py`：支援 `search_knowledge_base`、`query_structured_database`、`search_web_fallback` 智慧分流，並在知識庫無結果時自動啟動優雅網路回退）
- [x] 4. 升級前端聊天介面（`frontend/src/components/ChatView.tsx` 與 `frontend/src/App.tsx`：顯示 `🗄️ Text-to-SQL 結構化統計` SQL 語法區塊、`🌐 外部網路搜尋來源` 可點擊外部連結與多工具範例提問按鈕）
- [x] 5. 端到端驗證測試與 GitHub 同步更新


