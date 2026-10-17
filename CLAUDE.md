# CLAUDE.md

RAG 應用，具有聊天（預設）和文件導入界面。通過環境變數配置，沒有管理界面。

## 技術棧
- 前端：React + Vite + Tailwind + shadcn/ui
- 後端：Python + FastAPI
- 數據庫：Supabase（Postgres、pgvector、認證、存儲、實時）
- LLM：Google AI Studio / Gemini API（透過 OpenAI 兼容端點 `https://generativelanguage.googleapis.com/v1beta/openai/`，支援對話、工具調用與 Embedding）
- 可觀測性：LangSmith

## 規則
- Python 後端必須使用 `venv` 虛擬環境
- 不使用 LangChain，不使用 LangGraph - 僅使用原始 `openai` SDK（指向 Google AI Studio 的 OpenAI 兼容端點）調用
- 使用 Pydantic 進行結構化 LLM 輸出
- 所有表都需要行級安全性（RLS） - 用戶只能看到自己的數據
- 通過 SSE 進行流式聊天回應
- 使用 Supabase Realtime 進行導入狀態更新
- 從模組 1 起統一使用無狀態 Chat Completions API - 在 Supabase 自行存儲和發送聊天歷史（Threads 與 Messages）
- 導入僅限手動文件上傳 - 沒有連接器或自動化管道

## 規劃
- 將所有計劃保存到 `.agent/plans/` 文件夾
- 命名慣例：`{序號}.{計劃名稱}.md`（例如 `1.認證設置.md`、`2.文件導入.md`）
- 計劃應足夠詳細，可以無歧義地執行
- 計劃中的每個任務必須包含至少一個驗證測試來確認其正常工作
- 評估複雜度和一次性可行性 - 代理能否真實地一次完成？
- 在每個計劃頂部包含複雜度指標：
  - ✅ **簡單** - 可一次執行，低風險
  - ⚠️ **中等** - 可能需要迭代，有一定複雜性
  - 🔴 **複雜** - 執行前拆分為子計劃

## 開發流程
1. **規劃** - 創建詳細計劃並保存到 `.agent/plans/`
2. **構建** - 執行計劃來實現功能
3. **驗證** - 測試並驗證實現是否正確工作。適用時通過適當的 MCP 進行瀏覽器測試
4. **迭代** - 修復驗證中發現的任何問題

## 進度
查看 PROGRESS.md 了解當前模組狀態。完成任務後更新它。
