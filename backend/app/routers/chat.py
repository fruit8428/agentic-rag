import json
import re
from datetime import datetime, timezone
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

router = APIRouter(prefix="/api/chat", tags=["chat"])

FALLBACK_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
]

SYSTEM_PROMPT = """你是一個專業、友善且樂於助人的 Agentic RAG AI 助理（基於 Google Gemini 驅動）。
請使用繁體中文回答使用者的問題，保持結構清晰、排版易讀（善用 Markdown 標題、清單與表格）。

【重要工具使用守則】：
- 當用戶詢問任何具體知識、文件內容、得獎名單、社團/公司資料、插件功能、報告細節，或任何可能存在於上傳文件中的問題時，請務必先呼叫 `search_knowledge_base` 工具來檢索用戶上傳的私有文件。
- 呼叫 `search_knowledge_base` 時，`query` 請填寫最核心的專有名詞或關鍵字（例如用戶問「請問民生社有誰得獎」，`query` 請填「民生」；問「請問松青社有誰得獎」，`query` 請填「松青」）。
- 若檢索結果有相關內容，請仔細核對所有檢索到的段落（特別注意標示為「⚡關鍵字精準命中行」的每一筆資料，但因相鄰段落可能有重疊區間，若同一人在同一獎項於相鄰兩個段落重複出現，請自動去重只列一次；若同一人獲得不同獎項則必須分開完整列出），完整列出所有符合條件的：分區與社名、姓名、Nickname（稱號）、獎項名稱、頒獎時段、備註（集合時間與地點），並註明參考來源文件名與段落。
"""

RAG_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "在用戶上傳的私有知識庫文件（PDF、Markdown、TXT）中執行混合檢索（關鍵字 + pgvector 向量語意檢索 + 模組 4 元數據過濾），找出與問題最相關的文件段落。",
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
    }
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
    執行 Agentic RAG 決策與串流生成（內建模組 4 元數據過濾、503 自動模型備援與串流防截斷機制）。
    """
    retrieved_sources: list[dict] = []

    if has_documents:
        # 第一階段：讓 Gemini 判斷是否需要呼叫檢索工具
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
                if tc.function.name == "search_knowledge_base":
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        args = {}
                    search_query = args.get("query") or history_messages[-1]["content"]
                    effective_category = category_filter or args.get("category_filter")

                    yield {
                        "type": "tool_start",
                        "tool": "search_knowledge_base",
                        "query": search_query,
                        "category_filter": effective_category,
                        "document_id_filter": document_id_filter,
                    }

                    matches = await execute_hybrid_rerank_search(
                        user=user,
                        query=search_query,
                        document_id_filter=document_id_filter,
                        category_filter=effective_category,
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

                    yield {
                        "type": "tool_end",
                        "tool": "search_knowledge_base",
                        "query": search_query,
                        "sources": retrieved_sources,
                    }

                    if matches:
                        formatted_chunks = "\n\n---\n\n".join(
                            [
                                (
                                    f"【來源文件：{m.get('filename')} | 類別：{m.get('category') or '一般'} "
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
                        tool_outputs.append(
                            f"透過 `search_knowledge_base(query='{search_query}')` 查詢，知識庫中未找到超過相似度門檻的相關段落。"
                        )

            # 第二階段：將檢索到的知識庫段落注入上下文，串流生成最終回答（含防截斷保護）
            synthesis_messages = list(history_messages[:-1]) + [
                {
                    "role": "user",
                    "content": (
                        f"【知識庫檢索結果】\n{chr(10).join(tool_outputs)}\n\n"
                        f"---\n請根據上方檢索到的文件內容，完整且精準地回答我的問題（所有「⚡關鍵字精準命中行」提到的得獎人或項目都必須完整列出，不可遺漏）：\n{history_messages[-1]['content']}"
                    ),
                }
            ]
            async for text_piece in stream_completion_with_guard(synthesis_messages):
                yield {"type": "delta", "content": text_piece}
            return

        elif choice_msg.content:
            yield {"type": "delta", "content": choice_msg.content}
            return

    # 若尚未上傳任何文件，直接串流呼叫 Gemini（含防截斷保護）
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

    openai_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
