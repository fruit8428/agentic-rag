# Claude Code Agentic RAG 大師課

通過與 Claude Code 協作，從零開始構建一個 Agentic RAG 應用。跟隨我們的視頻系列，使用此倉庫中的文檔進行學習。



## 這是什麼

一門實踐課程，你通過與 Claude Code 協作來構建一個功能完整的 RAG 系統。你不是寫代碼的人——Claude 才是。你的工作是引導它、理解你在構建什麼，並在需要時進行糾正。

**你不需要知道如何編程。** 你需要具備技術思維，並願意學習 API、數據庫和系統架構。

## 你將構建什麼

- **聊天界面**，具有線程對話、流式傳輸、工具調用和子代理推理
- **文件導入**，具有拖放上傳和處理狀態
- **完整 RAG 管道**：分塊、嵌入、混合搜索、重排序
- **代理模式**：文本轉 SQL、網頁搜索、具有隔離上下文的子代理

## 技術棧

| 層次 | 技術 |
|------|------|
| 前端 | React、TypeScript、Tailwind、shadcn/ui、Vite |
| 後端 | Python、FastAPI |
| 數據庫 | Supabase（Postgres + pgvector + 認證 + 存儲） |
| 文件處理 | Docling |
| AI 模型 | 本地（LM Studio）或雲端（OpenAI、OpenRouter） |
| 可觀測性 | LangSmith |

## 8 個模組

1. **應用外殼** — 認證、聊天 UI、使用 OpenAI Responses API 的託管 RAG
2. **自建檢索 + 記憶** — 導入、pgvector、切換到通用 Completions API
3. **記錄管理器** — 內容哈希、去重
4. **元數據提取** — LLM 提取的元數據、過濾檢索
5. **多格式支持** — 通過 Docling 支持 PDF、DOCX、HTML、Markdown
6. **混合搜索和重排序** — 關鍵詞 + 向量搜索、RRF、重排序
7. **附加工具** — 文本轉 SQL、網頁搜索回退
8. **子代理** — 隔離上下文、文件分析委派

## 開始使用

1. 克隆此倉庫
2. 安裝 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
3. 在你的 IDE 中打開（Cursor、VS Code 等）
4. 在終端中運行 `claude`
5. 使用 `/onboard` 命令開始

## 文檔

- [PRD.md](./PRD.md) — 要構建什麼（8 個模組的詳細說明）
- [CLAUDE.md](./CLAUDE.md) — Claude Code 的上下文
- [PROGRESS.md](./PROGRESS.md) — 追蹤你的構建進度

## 加入社區

如果你想與數百位構建生產級 AI 和 RAG 系統的開發者交流，加入我們的 [The AI Automators 社區]https://www.skool.com/aiagent/about。分享你的進度，在遇到困難時獲得幫助，看看其他人在構建什麼。
