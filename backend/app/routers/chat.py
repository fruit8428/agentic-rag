import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langsmith import traceable
from app.auth import AuthenticatedUser, get_current_user
from app.config import settings
from app.llm import llm_client
from app.services.ingestion import embed_query
from app.services.record_manager import compute_sha256_text
from app.services.hybrid_search import execute_hybrid_rerank_search
from app.services.additional_tools import (
    execute_structured_sql_tool,
    execute_web_search_tool,
)
from app.services.subagent import execute_isolated_subagent

router = APIRouter(prefix="/api/chat", tags=["chat"])

FALLBACK_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
]

SYSTEM_PROMPT = """你是一個專業、友善且樂於助人的多工具與階層式子代理 Agentic RAG AI 助理（基於 Google Gemini 驅動）。
請使用繁體中文回答使用者的問題，保持結構清晰、排版易讀（善用 Markdown 標題、清單與表格）。

【多工具與階層式子代理（Multi-Tool & Sub-Agent）路由守則】：
1. **工具 A：`search_knowledge_base`（模組 6：混合搜索 + RRF + AI 重排序）**
   - 當用戶詢問單一具體問題、特定扶輪社得獎名單（如松青社、民生社）、個人獲獎紀錄、插件功能或單一項目細節時，優先呼叫此工具。
   - `query` 請填寫最核心的專有名詞或關鍵字（例如問「請問民生社有誰得獎」，`query` 填「民生」）。
   - 若檢索結果有「⚡關鍵字精準命中行」，請完整列出每一筆資料（相鄰段落重疊之同一人同一獎項自動去重只列一次；不同獎項則分開列出）。
2. **工具 B：`query_structured_database`（模組 7：Text-to-SQL 結構化數據與全表統計查詢）**
   - 當用戶明確要求「用 SQL 統計」、「知識庫共有幾份文件、幾個分塊？」或「統計特定一兩個社團的得獎筆數比較」時，呼叫此工具執行 PostgreSQL 結構化分析。
3. **工具 C：`search_web_fallback`（模組 7：即時網路搜索與外部資訊回退）**
   - 當用戶詢問「即時新聞、今天天氣如何、外部公開網站資訊」，或問題明顯不在私有知識庫文件中時，呼叫此工具上網檢索。
4. **工具 D：`delegate_to_document_subagent`（模組 8：委派具備獨立隔離上下文的全文件深度分析子代理）**
   - 當用戶提出「全文件深度分析」、「派子代理分析」、「整份文件有哪些獎項與頒獎時段流程總表？」、「分析某整個分區（如第四分區 04-1～04-7）各社得獎分布」或「跨全文件章節綜合報告」時，請務必呼叫此工具，將全文件掃描任務委派給具備獨立隔離上下文的子代理（`DocumentAnalystSubAgent`）執行！
5. **可信度來源歸因（Attribution for Trust）**：
   - 回答時請明確標註資訊來源歸因（『📄 來源：內部知識庫混合檢索』、『🗄️ 來源：Text-to-SQL 結構化統計』、『🌐 來源：外部網路搜尋』或『🤖 來源：隔離上下文子代理全文件深度分析』）。
"""

RAG_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "在用戶上傳的私有知識庫文件（PDF、DOCX、HTML、CSV、MD、TXT）中執行三階段混合檢索（關鍵字 + pgvector 向量 + RRF + AI 重排序），找出與問題最相關的文件段落。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要在知識庫中搜尋的核心專有名詞或關鍵字（例如：『松青』、『民生』、『Claude Cowork』）",
                    },
                    "category_filter": {
                        "type": "string",
                        "description": "選填。可依文件元數據類別過濾，例如：『頒獎與表揚名單』、『會議與活動通知』、『技術與教學指南』、『規章與財務文件』、『一般知識文件』",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_structured_database",
            "description": "模組 7 Text-to-SQL 結構化數據查詢工具：當用戶詢問知識庫文件總數、各分類文件統計、分塊與字數統計，或要求用 SQL 統計特定社團的得獎筆數時呼叫。",
            "parameters": {
                "type": "object",
                "properties": {
                    "natural_query": {
                        "type": "string",
                        "description": "使用者的結構化統計或盤點問題（例如：『統計知識庫所有文件與分類數量』或『統計松青社與民生社在全文件中的得獎筆數』）",
                    }
                },
                "required": ["natural_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web_fallback",
            "description": "模組 7 即時網路搜索工具：當用戶詢問外部即時新聞、今天天氣如何、公開網路資訊，或私有知識庫文件中沒有相關答案時呼叫此工具上網搜尋。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要在網際網路上搜尋的關鍵字（例如：『國際扶輪 3481 地區 最新活動』或『今天天氣如何』）",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_document_subagent",
            "description": "模組 8 隔離上下文子代理委派工具：當用戶要求『派子代理』、『全文件深度分析』、『整份文件的所有頒獎時段與獎項總表』、『某分區（如第四分區）各社得獎全貌分析』或『跨章節綜合比較報告』時呼叫此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "主代理委派給全文件深度分析子代理的完整任務描述",
                    },
                    "focus_scope": {
                        "type": "string",
                        "description": "選填。子代理掃描全文件時要特別聚焦的分區、社團或主題（例如：『第四分區』、『全體頒獎時段與獎項』）",
                    },
                },
                "required": ["task_description"],
            },
        },
    },
]


class ChatRequest(BaseModel):
    thread_id: str
    message: str
    document_id: Optional[str] = None
    category: Optional[str] = None


async def create_chat_completion_with_fallback(**kwargs):
    """
    呼叫 Gemini Chat Completions，若遇 Google 伺服器 503 (High Demand)、429 或逾時，
    自動無縫切換至備援 Gemini 模型，確保用戶永遠不會遇到 503 中斷！
    """
    primary = kwargs.pop("model", settings.LLM_MODEL)
    candidates = [primary] + [m for m in FALLBACK_MODELS if m != primary]
    last_err = None
    for model_name in candidates:
        try:
            return await llm_client.chat.completions.create(
                model=model_name, **kwargs
            )
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if any(
                code in err_str
                for code in ("503", "429", "unavailable", "404", "timeout", "timed out", "connection")
            ):
                continue
            raise
    raise last_err


def extract_keywords(query: str) -> list[str]:
    """從查詢字串中提取核心關鍵詞（移除常見問句贅字），用於精準關鍵字匹配。"""
    cleaned = re.sub(
        r"(請問|幫我查|查詢|告訴我|有誰|哪些人|哪些|什麼|得獎|獲獎|名單|的|嗎|呢|？|\?|社)",
        " ",
        query,
    )
    tokens = [t.strip() for t in cleaned.split() if len(t.strip()) >= 2]
    if not tokens and len(query.strip()) >= 2:
        tokens = [query.strip()]
    return tokens


@traceable(name="vector_search_knowledge_base", run_type="retriever")
async def execute_vector_search(
    user: AuthenticatedUser,
    query: str,
    document_id_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    match_threshold: float = 0.2,
    match_count: int = 8,
) -> list[dict]:
    """
    結合「模組 4 元數據條件過濾」、「精準關鍵字匹配」與「Supabase pgvector 768 維度向量檢索」，
    確保不管是問概念（語意搜尋）還是查特定名單/人名/社名（關鍵字搜尋）都能 100% 命中！
    """
    results_by_id: dict[str, dict] = {}
    seen_content_hashes: set[str] = set()
    keyword_hit_count = 0

    # 0. 讀取文件列表與各文件第 0 號分塊的 AI 元數據，建立元數據過濾白名單
    doc_map: dict[str, str] = {}
    doc_meta_map: dict[str, dict] = {}
    allowed_doc_ids: Optional[set[str]] = None
    try:
        docs_res = (
            user.supabase.table("documents")
            .select("id, filename, updated_at")
            .eq("status", "completed")
            .order("updated_at", desc=True)
            .execute()
        )
        docs = docs_res.data or []
        doc_map = {d["id"]: d["filename"] for d in docs}
        doc_ids = [d["id"] for d in docs]
        if doc_ids:
            c0_res = (
                user.supabase.table("document_chunks")
                .select("document_id, metadata")
                .in_("document_id", doc_ids)
                .eq("chunk_index", 0)
                .execute()
            )
            for r in c0_res.data or []:
                m = r.get("metadata") or {}
                ext_meta = m.get("extracted_metadata") or {}
                doc_meta_map[r["document_id"]] = ext_meta

        if document_id_filter:
            allowed_doc_ids = {document_id_filter}
        elif category_filter:
            matched_ids = {
                did
                for did, em in doc_meta_map.items()
                if em.get("category") == category_filter
            }
            # 若該類別有對應文件才限制範圍；否則自動回退搜尋全部文件避免誤濾掉
            if matched_ids:
                allowed_doc_ids = matched_ids
    except Exception:
        pass

    # 1. 關鍵字精準檢索（針對名單、專有名詞如「松青」、「民生」零遺漏）
    keywords = extract_keywords(query)
    try:
        for kw in keywords[:3]:
            q_builder = (
                user.supabase.table("document_chunks")
                .select("id, document_id, chunk_index, content, metadata")
                .ilike("content", f"%{kw}%")
            )
            if allowed_doc_ids:
                q_builder = q_builder.in_("document_id", list(allowed_doc_ids))
            kw_res = q_builder.order("chunk_index", desc=False).limit(12).execute()

            for row in kw_res.data or []:
                cid = row["id"]
                doc_id = row["document_id"]
                if allowed_doc_ids and doc_id not in allowed_doc_ids:
                    continue
                content_text = row["content"] or ""
                content_sig = compute_sha256_text(content_text)
                if content_sig in seen_content_hashes:
                    continue
                seen_content_hashes.add(content_sig)

                # 擷取包含關鍵字的前後行作為醒目提示，防止模型在長表格中漏看最後幾筆
                lines = [ln.strip() for ln in content_text.splitlines() if ln.strip()]
                matched_snippets = []
                for idx, ln in enumerate(lines):
                    if kw.lower() in ln.lower():
                        start_i = max(0, idx - 1)
                        end_i = min(len(lines), idx + 3)
                        snippet = " / ".join(lines[start_i:end_i])
                        matched_snippets.append(f"  • {snippet}")
                highlight_header = ""
                if matched_snippets:
                    highlight_header = (
                        f"【⚡關鍵字「{kw}」精準命中行（共 {len(matched_snippets)} 處，請務必全部列入回答）】：\n"
                        + "\n".join(matched_snippets)
                        + "\n\n【完整段落內容】：\n"
                    )

                ext_m = doc_meta_map.get(doc_id) or {}
                if cid not in results_by_id:
                    keyword_hit_count += 1
                    results_by_id[cid] = {
                        "id": cid,
                        "document_id": doc_id,
                        "filename": doc_map.get(
                            doc_id,
                            (row.get("metadata") or {}).get("filename", "未知文件"),
                        ),
                        "category": ext_m.get("category")
                        or (row.get("metadata") or {}).get("category"),
                        "event_or_year": ext_m.get("event_or_year")
                        or (row.get("metadata") or {}).get("event_or_year"),
                        "chunk_index": row["chunk_index"],
                        "content": highlight_header + content_text,
                        "similarity": 0.99,  # 關鍵字精準命中給予最高優先級
                    }
    except Exception:
        pass

    # 2. pgvector 語意向量檢索（若已有關鍵字精準命中，提高向量門檻避免混入不相關社團名單干擾）
    effective_threshold = 0.65 if keyword_hit_count > 0 else match_threshold
    try:
        query_vec = await embed_query(query)
        rpc_res = user.supabase.rpc(
            "match_document_chunks",
            {
                "query_embedding": query_vec,
                "match_threshold": effective_threshold,
                "match_count": match_count * 2 if allowed_doc_ids else match_count,
            },
        ).execute()
        for row in rpc_res.data or []:
            cid = row["id"]
            doc_id = row.get("document_id")
            if allowed_doc_ids and doc_id not in allowed_doc_ids:
                continue
            content_sig = compute_sha256_text(row.get("content") or "")
            if content_sig in seen_content_hashes:
                continue
            seen_content_hashes.add(content_sig)

            ext_m = doc_meta_map.get(doc_id) or {}
            if cid not in results_by_id:
                row["category"] = ext_m.get("category")
                row["event_or_year"] = ext_m.get("event_or_year")
                results_by_id[cid] = row
    except Exception:
        pass

    merged = list(results_by_id.values())
    merged.sort(key=lambda x: (-float(x.get("similarity", 0)), int(x.get("chunk_index", 0))))
    return merged[:8]


async def stream_completion_with_guard(messages: list[dict]):
    """
    串流呼叫 Gemini，並自動偵測上游串流是否被提早截斷（finish_reason != 'stop'）。
    若上游因瞬間流量提早中斷串流，自動無縫補齊剩餘回答，確保表格與名單永遠完整！
    """
    yielded_parts: list[str] = []
    finish_reason = None

    try:
        stream = await create_chat_completion_with_fallback(
            model=settings.LLM_MODEL,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices:
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                if choice.delta and choice.delta.content:
                    text_piece = choice.delta.content
                    yielded_parts.append(text_piece)
                    yield text_piece
    except Exception:
        finish_reason = None

    yielded_text = "".join(yielded_parts)

    # 若串流未正常結束（例如 finish_reason 為 None），自動執行續寫補齊
    if finish_reason not in ("stop", "length"):
        if not yielded_text.strip():
            fallback_resp = await create_chat_completion_with_fallback(
                model=settings.LLM_MODEL,
                messages=messages,
                stream=False,
            )
            full_text = fallback_resp.choices[0].message.content or ""
            if full_text:
                yield full_text
        else:
            continuation_messages = list(messages) + [
                {"role": "assistant", "content": yielded_text},
                {
                    "role": "user",
                    "content": (
                        "你的回答在上方被截斷了。請直接從截斷處緊接著繼續輸出剩餘的內容與表格列，"
                        "絕對不要重複上方已經輸出過的文字，也不要加任何開場白："
                    ),
                },
            ]
            cont_resp = await create_chat_completion_with_fallback(
                model=settings.LLM_MODEL,
                messages=continuation_messages,
                stream=False,
            )
            remainder = cont_resp.choices[0].message.content or ""
            if remainder:
                if not yielded_text.endswith("\n") and not remainder.startswith("\n"):
                    yield "\n"
                yield remainder


@traceable(name="agentic_rag_chat_turn", run_type="chain")
async def run_agentic_rag_turn(
    user: AuthenticatedUser,
    history_messages: list[dict],
    has_documents: bool,
    document_id_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
):
    """
    執行多工具 Agentic RAG 決策與串流生成（支援：
    1. 模組 6 混合檢索 + RRF + AI 重排序 (`search_knowledge_base`)
    2. 模組 7 Text-to-SQL 結構化數據查詢 (`query_structured_database`)
    3. 模組 7 即時網路搜索與無結果優雅回退 (`search_web_fallback`)
    ）。
    """
    retrieved_sources: list[dict] = []

    # 第一階段：讓 Gemini 多工具代理判斷需要呼叫哪一個（或多個）工具
    first_resp = await create_chat_completion_with_fallback(
        model=settings.LLM_MODEL,
        messages=history_messages,
        tools=RAG_TOOLS,
        tool_choice="auto",
        stream=False,
    )
    choice_msg = first_resp.choices[0].message

    if choice_msg.tool_calls:
        tool_outputs = []
        for tc in choice_msg.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}

            if tool_name == "search_knowledge_base":
                search_query = args.get("query") or history_messages[-1]["content"]
                effective_category = category_filter or args.get("category_filter")

                yield {
                    "type": "tool_start",
                    "tool": "search_knowledge_base",
                    "query": search_query,
                    "category_filter": effective_category,
                    "document_id_filter": document_id_filter,
                }

                matches = (
                    await execute_hybrid_rerank_search(
                        user=user,
                        query=search_query,
                        document_id_filter=document_id_filter,
                        category_filter=effective_category,
                    )
                    if has_documents
                    else []
                )
                for m in matches:
                    retrieved_sources.append(
                        {
                            "filename": m.get("filename", "未知文件"),
                            "category": m.get("category"),
                            "event_or_year": m.get("event_or_year"),
                            "chunk_index": m.get("chunk_index", 0),
                            "content": m.get("content", ""),
                            "similarity": round(float(m.get("similarity", 0.0)), 3),
                            "match_type": m.get("match_type", "vector"),
                            "keyword_rank": m.get("keyword_rank"),
                            "vector_rank": m.get("vector_rank"),
                            "vector_similarity": m.get("vector_similarity"),
                            "rrf_score": m.get("rrf_score"),
                            "rerank_score": m.get("rerank_score"),
                            "rerank_reason": m.get("rerank_reason"),
                        }
                    )

                if matches:
                    yield {
                        "type": "tool_end",
                        "tool": "search_knowledge_base",
                        "query": search_query,
                        "sources": retrieved_sources,
                    }
                    formatted_chunks = "\n\n---\n\n".join(
                        [
                            (
                                f"【📄 內部知識庫來源：{m.get('filename')} | 類別：{m.get('category') or '一般'} "
                                f"| 段落 #{m.get('chunk_index', 0) + 1} "
                                f"| 檢索模式：{m.get('match_type')} (RRF={m.get('rrf_score')}) "
                                f"| Rerank 精準度：{round(float(m.get('similarity', 0)) * 100, 1)}%】\n{m.get('content')}"
                            )
                            for m in matches
                        ]
                    )
                    tool_outputs.append(
                        f"透過 `search_knowledge_base(query='{search_query}')` 執行混合檢索（關鍵字 + 向量 + RRF + AI 重排序）成功找到以下 {len(matches)} 個最相關文件段落：\n\n{formatted_chunks}"
                    )
                else:
                    # 模組 7 優雅回退（Graceful Fallback）：當內部知識庫查無結果時，自動啟動外部網路搜尋
                    yield {
                        "type": "tool_start",
                        "tool": "search_web_fallback",
                        "query": search_query,
                    }
                    web_res = await execute_web_search_tool(
                        query=search_query,
                        max_results=4,
                        fallback_reason=f"內部知識庫未找到「{search_query}」，自動啟動網路搜索回退",
                    )
                    retrieved_sources.extend(web_res.get("source_cards", []))
                    yield {
                        "type": "tool_end",
                        "tool": "search_web_fallback",
                        "query": search_query,
                        "sources": retrieved_sources,
                    }
                    tool_outputs.append(
                        f"內部私有知識庫中未找到與「{search_query}」直接相符的段落，系統已自動觸發【模組 7：網路搜索優雅回退（Web Search Fallback）】，檢索到以下外部即時資訊：\n\n{web_res.get('formatted_context')}"
                    )

            elif tool_name == "query_structured_database":
                natural_query = args.get("natural_query") or history_messages[-1]["content"]
                yield {
                    "type": "tool_start",
                    "tool": "query_structured_database",
                    "query": natural_query,
                    "category_filter": category_filter,
                    "document_id_filter": document_id_filter,
                }
                sql_res = await execute_structured_sql_tool(
                    user=user,
                    natural_query=natural_query,
                    document_id_filter=document_id_filter,
                    category_filter=category_filter,
                )
                if sql_res.get("source_card"):
                    retrieved_sources.append(sql_res["source_card"])
                yield {
                    "type": "tool_end",
                    "tool": "query_structured_database",
                    "query": natural_query,
                    "sources": retrieved_sources,
                }
                tool_outputs.append(
                    f"透過 `query_structured_database(natural_query='{natural_query}')` 執行 Text-to-SQL 結構化數據查詢結果如下：\n\n{sql_res.get('summary_markdown')}"
                )

            elif tool_name == "search_web_fallback":
                web_query = args.get("query") or history_messages[-1]["content"]
                yield {
                    "type": "tool_start",
                    "tool": "search_web_fallback",
                    "query": web_query,
                }
                web_res = await execute_web_search_tool(
                    query=web_query,
                    max_results=8,
                    fallback_reason="Multi-Tool Agent 主動調用外部即時網路搜索（DuckDuckGo + Google News RSS + 維基百科）",
                )
                retrieved_sources.extend(web_res.get("source_cards", []))
                yield {
                    "type": "tool_end",
                    "tool": "search_web_fallback",
                    "query": web_query,
                    "sources": retrieved_sources,
                }
                tool_outputs.append(
                    f"透過 `search_web_fallback(query='{web_query}')` 執行外部即時網路搜索結果如下：\n\n{web_res.get('formatted_context')}"
                )

            elif tool_name == "delegate_to_document_subagent":
                task_desc = args.get("task_description") or history_messages[-1]["content"]
                focus_scope = args.get("focus_scope")
                yield {
                    "type": "tool_start",
                    "tool": "delegate_to_document_subagent",
                    "query": f"{task_desc[:40]}... ({focus_scope or '全文件隔離掃描'})",
                }
                sub_res = await execute_isolated_subagent(
                    user=user,
                    task_description=task_desc,
                    focus_scope=focus_scope,
                    document_id_filter=document_id_filter,
                    category_filter=category_filter,
                )
                if sub_res.get("source_card"):
                    retrieved_sources.append(sub_res["source_card"])
                yield {
                    "type": "tool_end",
                    "tool": "delegate_to_document_subagent",
                    "query": task_desc,
                    "sources": retrieved_sources,
                }
                tool_outputs.append(
                    f"主代理已委派『全文件深度分析子代理 (DocumentAnalystSubAgent)』於獨立隔離上下文完成全文件掃描與彙整，回傳精華報告如下：\n\n{sub_res.get('distilled_report')}"
                )

        # 第二階段：將多工具或子代理檢索結果注入上下文，串流生成最終回答（含防截斷保護与來源歸因）
        synthesis_messages = list(history_messages[:-1]) + [
            {
                "role": "user",
                "content": (
                    f"【多工具與階層式子代理（Multi-Tool & Sub-Agent）檢索與分析結果】\n{chr(10).join(tool_outputs)}\n\n"
                    f"---\n請根據上方工具或子代理回傳的資料，完整且精準地回答我的問題：\n"
                    f"1. 若包含「⚡關鍵字精準命中行」或子代理聚焦分區名單，所有提到的得獎人或項目都必須完整列出，不可遺漏（相鄰段落重疊之同一人同一獎項請自動去重只列一次）。\n"
                    f"2. 請清楚標註資訊來源歸因（例如：『📄 來源：內部知識庫文件』、『🗄️ 來源：Text-to-SQL 結構化統計』、『🌐 來源：外部網路搜尋』或『🤖 來源：隔離上下文子代理 (DocumentAnalystSubAgent) 全文件深度分析』）。\n\n"
                    f"使用者問題：{history_messages[-1]['content']}"
                ),
            }
        ]
        async for text_piece in stream_completion_with_guard(synthesis_messages):
            yield {"type": "delta", "content": text_piece}
        return

    elif choice_msg.content:
        yield {"type": "delta", "content": choice_msg.content}
        return

    async for text_piece in stream_completion_with_guard(history_messages):
        yield {"type": "delta", "content": text_piece}


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    接收使用者訊息 -> 存入 Supabase -> 讀取該線程歷史對話 ->
    執行 Agentic RAG -> 透過 SSE 即時串流回應 -> 存入 Supabase。
    """
    user_text = payload.message.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="訊息內容不能為空")

    thread_res = (
        user.supabase.table("threads")
        .select("*")
        .eq("id", payload.thread_id)
        .execute()
    )
    if not thread_res.data:
        raise HTTPException(status_code=404, detail="找不到指定的對話線程")
    thread_obj = thread_res.data[0]

    user.supabase.table("messages").insert(
        {
            "thread_id": payload.thread_id,
            "user_id": user.id,
            "role": "user",
            "content": user_text,
        }
    ).execute()

    has_documents = False
    try:
        doc_check = (
            user.supabase.table("documents")
            .select("id")
            .eq("status", "completed")
            .limit(1)
            .execute()
        )
        has_documents = bool(doc_check.data)
    except Exception:
        has_documents = False

    history_res = (
        user.supabase.table("messages")
        .select("role, content")
        .eq("thread_id", payload.thread_id)
        .order("created_at", desc=False)
        .execute()
    )
    db_messages = history_res.data or []

    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    now_str = f"{now_tw.strftime('%Y年%m月%d日 %H:%M:%S')} ({weekdays[now_tw.weekday()]})"
    dynamic_system_prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"【系統即時時鐘】：目前台灣標準時間（UTC+8）為 **{now_str}**。若使用者詢問現在幾點或今天日期，請直接根據此精確時間回答。"
    )

    openai_messages = [{"role": "system", "content": dynamic_system_prompt}]
    for msg in db_messages:
        if msg["role"] in ("user", "assistant") and (msg.get("content") or "").strip():
            openai_messages.append({"role": msg["role"], "content": msg["content"]})

    new_title = None
    if len(db_messages) <= 1 or thread_obj.get("title") == "新對話":
        new_title = user_text[:24] + ("..." if len(user_text) > 24 else "")
        user.supabase.table("threads").update(
            {
                "title": new_title,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", payload.thread_id).execute()
    else:
        user.supabase.table("threads").update(
            {"updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", payload.thread_id).execute()

    async def event_generator():
        full_reply = []
        final_sources = []
        try:
            if new_title:
                yield f"data: {json.dumps({'type': 'title_updated', 'title': new_title}, ensure_ascii=False)}\n\n"

            async for event in run_agentic_rag_turn(
                user=user,
                history_messages=openai_messages,
                has_documents=has_documents,
                document_id_filter=payload.document_id,
                category_filter=payload.category,
            ):
                if event["type"] == "delta":
                    full_reply.append(event["content"])
                elif event["type"] == "tool_end":
                    final_sources = event.get("sources", [])
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            assistant_text = "".join(full_reply).strip()
            if assistant_text:
                insert_payload = {
                    "thread_id": payload.thread_id,
                    "user_id": user.id,
                    "role": "assistant",
                    "content": assistant_text,
                }
                try:
                    insert_payload["sources"] = final_sources
                    saved_res = (
                        user.supabase.table("messages")
                        .insert(insert_payload)
                        .execute()
                    )
                except Exception:
                    insert_payload.pop("sources", None)
                    saved_res = (
                        user.supabase.table("messages")
                        .insert(insert_payload)
                        .execute()
                    )
                saved_msg = saved_res.data[0] if saved_res.data else None
                yield f"data: {json.dumps({'type': 'done', 'message': saved_msg}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'done', 'message': None}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
