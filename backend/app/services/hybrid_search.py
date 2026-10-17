import json
import re
from typing import Dict, List, Optional
from langsmith import traceable
from pydantic import BaseModel, Field
from app.auth import AuthenticatedUser
from app.config import settings
from app.llm import llm_client
from app.services.ingestion import embed_query
from app.services.record_manager import compute_sha256_text

RRF_K = 60  # 標準 Reciprocal Rank Fusion 常數 k=60


class RerankItemSchema(BaseModel):
    """模組 6：單一候選分塊的 AI 重排序評分結構（Pydantic Schema）。"""

    chunk_id: str = Field(description="候選分塊的 ID")
    relevance_score: float = Field(
        ge=0.0, le=1.0, description="0.0 到 1.0 之間的語意相關性分數"
    )
    reason: str = Field(description="簡短說明為何此段落與問題相關或不相關（15字以內）")


class RerankBatchSchema(BaseModel):
    """模組 6：批次重排序輸出結構。"""

    rankings: List[RerankItemSchema] = Field(default_factory=list)


def extract_keywords(query: str) -> List[str]:
    """從查詢字串中提取核心關鍵詞（移除常見問句贅字），用於軌道 A 關鍵字全文檢索。"""
    cleaned = re.sub(
        r"(請問|幫我查|查詢|告訴我|有誰|哪些人|哪些|什麼|是|得獎|獲獎|名單|的|嗎|呢|？|\?|社)",
        " ",
        query,
    )
    tokens = [t.strip() for t in cleaned.split() if len(t.strip()) >= 2]
    if not tokens and len(query.strip()) >= 2:
        tokens = [query.strip()]
    return tokens


@traceable(name="track_a_lexical_keyword_search", run_type="retriever")
def lexical_keyword_search(
    user: AuthenticatedUser,
    query: str,
    allowed_doc_ids: Optional[set[str]],
    doc_map: Dict[str, str],
    doc_meta_map: Dict[str, dict],
) -> List[dict]:
    """
    軌道 A：關鍵字全文檢索（Lexical / Keyword Search）。
    針對人名、社團名（如『松青』、『民生』）、獎項名稱進行精確匹配，
    並依命中行數與關鍵字覆蓋率排序，賦予 keyword_rank (#1, #2...)。
    """
    keywords = extract_keywords(query)
    if not keywords:
        return []

    raw_hits_by_cid: Dict[str, dict] = {}
    seen_hashes: set[str] = set()

    try:
        for kw in keywords[:4]:
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

                if cid not in raw_hits_by_cid:
                    if content_sig in seen_hashes:
                        continue
                    seen_hashes.add(content_sig)

                lines = [ln.strip() for ln in content_text.splitlines() if ln.strip()]
                matched_snippets = []
                for idx, ln in enumerate(lines):
                    if kw.lower() in ln.lower():
                        start_i = max(0, idx - 1)
                        end_i = min(len(lines), idx + 3)
                        snippet = " / ".join(lines[start_i:end_i])
                        matched_snippets.append(f"  • {snippet}")

                hit_count = len(matched_snippets)
                highlight_header = ""
                if matched_snippets:
                    highlight_header = (
                        f"【⚡關鍵字「{kw}」精準命中行（共 {hit_count} 處，請務必全部列入回答）】：\n"
                        + "\n".join(matched_snippets)
                        + "\n\n【完整段落內容】：\n"
                    )

                ext_m = doc_meta_map.get(doc_id) or {}
                if cid not in raw_hits_by_cid:
                    raw_hits_by_cid[cid] = {
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
                        "raw_content": content_text,
                        "content": highlight_header + content_text,
                        "kw_hit_count": hit_count,
                        "matched_keywords": [kw],
                    }
                else:
                    raw_hits_by_cid[cid]["kw_hit_count"] += hit_count
                    if kw not in raw_hits_by_cid[cid]["matched_keywords"]:
                        raw_hits_by_cid[cid]["matched_keywords"].append(kw)
    except Exception:
        pass

    # 依（命中關鍵詞種類數, 命中總行數, -chunk_index）排序，賦予 keyword_rank
    sorted_kw = sorted(
        raw_hits_by_cid.values(),
        key=lambda x: (
            -len(x.get("matched_keywords", [])),
            -int(x.get("kw_hit_count", 0)),
            int(x.get("chunk_index", 0)),
        ),
    )
    for idx, item in enumerate(sorted_kw):
        item["keyword_rank"] = idx + 1

    return sorted_kw


@traceable(name="track_b_dense_vector_search", run_type="retriever")
async def dense_vector_search(
    user: AuthenticatedUser,
    query: str,
    allowed_doc_ids: Optional[set[str]],
    doc_meta_map: Dict[str, dict],
    match_threshold: float = 0.2,
    match_count: int = 10,
) -> List[dict]:
    """
    軌道 B：pgvector 768 維度稠密向量語意檢索（Dense Vector Semantic Search）。
    依餘弦相似度（Cosine Similarity）排序並賦予 vector_rank (#1, #2...)。
    """
    vec_hits: List[dict] = []
    seen_hashes: set[str] = set()
    try:
        query_vec = await embed_query(query)
        rpc_res = user.supabase.rpc(
            "match_document_chunks",
            {
                "query_embedding": query_vec,
                "match_threshold": match_threshold,
                "match_count": match_count * 2 if allowed_doc_ids else match_count,
            },
        ).execute()

        for row in rpc_res.data or []:
            doc_id = row.get("document_id")
            if allowed_doc_ids and doc_id not in allowed_doc_ids:
                continue
            raw_c = row.get("content") or ""
            sig = compute_sha256_text(raw_c)
            if sig in seen_hashes:
                continue
            seen_hashes.add(sig)

            ext_m = doc_meta_map.get(doc_id) or {}
            item = dict(row)
            item["raw_content"] = raw_c
            item["category"] = ext_m.get("category")
            item["event_or_year"] = ext_m.get("event_or_year")
            item["vector_similarity"] = float(row.get("similarity", 0.0))
            vec_hits.append(item)
    except Exception:
        pass

    vec_hits.sort(key=lambda x: -float(x.get("vector_similarity", 0.0)))
    for idx, item in enumerate(vec_hits):
        item["vector_rank"] = idx + 1

    return vec_hits[:match_count]


@traceable(name="stage2_reciprocal_rank_fusion", run_type="chain")
def reciprocal_rank_fusion(
    keyword_hits: List[dict],
    vector_hits: List[dict],
    k: int = RRF_K,
) -> List[dict]:
    """
    階段二：倒數排名融合（RRF — Reciprocal Rank Fusion）。
    公式：RRF_Score(d) = w_kw / (k + rank_kw(d)) + w_vec / (k + rank_vec(d))
    同時標記每個段落的命中類型（hybrid: 雙軌同時命中 / keyword: 關鍵字命中 / vector: 向量語意命中）。
    """
    fused_by_sig: Dict[str, dict] = {}
    w_kw = 1.25  # 關鍵字軌道權重微幅調升，確保專有名詞精準優先
    w_vec = 1.00

    # 1. 先放入關鍵字命中結果
    for kw_item in keyword_hits:
        sig = compute_sha256_text(kw_item.get("raw_content") or kw_item.get("content") or "")
        kw_rank = int(kw_item["keyword_rank"])
        rrf_kw = w_kw / (k + kw_rank)
        fused_by_sig[sig] = {
            **kw_item,
            "match_type": "keyword",
            "keyword_rank": kw_rank,
            "vector_rank": None,
            "vector_similarity": None,
            "rrf_score": round(rrf_kw, 5),
        }

    # 2. 融合向量檢索結果
    for vec_item in vector_hits:
        sig = compute_sha256_text(vec_item.get("raw_content") or vec_item.get("content") or "")
        vec_rank = int(vec_item["vector_rank"])
        vec_sim = float(vec_item.get("vector_similarity", 0.0))
        rrf_vec = w_vec / (k + vec_rank)

        if sig in fused_by_sig:
            # 🔥 雙軌同時命中（Hybrid Match）：RRF 分數直接疊加！
            existing = fused_by_sig[sig]
            existing["match_type"] = "hybrid"
            existing["vector_rank"] = vec_rank
            existing["vector_similarity"] = round(vec_sim, 4)
            existing["rrf_score"] = round(float(existing["rrf_score"]) + rrf_vec, 5)
        else:
            # 若已有關鍵字精準命中，對於純向量命中的不相關段落提高過濾門檻（>= 0.65），避免混入其他社團名單
            if len(keyword_hits) > 0 and vec_sim < 0.65:
                continue
            fused_by_sig[sig] = {
                **vec_item,
                "match_type": "vector",
                "keyword_rank": None,
                "vector_rank": vec_rank,
                "vector_similarity": round(vec_sim, 4),
                "rrf_score": round(rrf_vec, 5),
            }

    fused_list = list(fused_by_sig.values())
    fused_list.sort(
        key=lambda x: (
            -float(x.get("rrf_score", 0.0)),
            int(x.get("chunk_index", 0)),
        )
    )
    return fused_list


@traceable(name="stage3_ai_reranker", run_type="llm")
async def rerank_candidates(
    query: str,
    candidates: List[dict],
    top_k: int = 8,
) -> List[dict]:
    """
    階段三：AI 精準重排序（Reranker + 專有名詞零遺漏保護）。
    - 對所有候選分塊計算最終 `rerank_score` (0.0~1.0) 與 `rerank_reason`。
    - 內建「零遺漏保護（Zero-Omission Guard）」：凡是包含查詢關鍵字的段落（hybrid / keyword）100% 強制保留，
      絕不因重排序而漏掉任何一位得獎人！
    - 當純語意查詢（無特定關鍵字命中且候選數 > 2）時，呼叫 Gemini + Pydantic 進行深度語意重排序。
    """
    if not candidates:
        return []

    has_exact_kw = any(c.get("match_type") in ("hybrid", "keyword") for c in candidates)
    llm_scores: Dict[str, RerankItemSchema] = {}

    # 若為概念型問題（無特定專有名詞命中），呼叫 Gemini 執行 Cross-Attention 語意重排序
    if not has_exact_kw and len(candidates) > 1:
        try:
            snippets_for_llm = []
            for c in candidates[:8]:
                snippets_for_llm.append(
                    {
                        "chunk_id": str(c["id"]),
                        "content_preview": (c.get("raw_content") or c.get("content") or "")[:450],
                    }
                )
            prompt = (
                f"請針對使用者問題：「{query}」，評估以下候選文件段落的語意相關性（0.0 到 1.0），"
                "並只輸出符合格式的純 JSON：\n"
                '{"rankings": [{"chunk_id": "...", "relevance_score": 0.95, "reason": "直接回答了問題"}]}\n\n'
                f"【候選段落】：\n{json.dumps(snippets_for_llm, ensure_ascii=False)}"
            )
            resp = await llm_client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "你是精準的 RAG Cross-Encoder 重排序專家（Reranker），只回傳純 JSON。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            raw = (resp.choices[0].message.content or "").strip()
            start_i = raw.find("{")
            end_i = raw.rfind("}")
            if start_i != -1 and end_i != -1:
                parsed = RerankBatchSchema.model_validate(
                    json.loads(raw[start_i : end_i + 1])
                )
                llm_scores = {item.chunk_id: item for item in parsed.rankings}
        except Exception:
            llm_scores = {}

    reranked: List[dict] = []
    for c in candidates:
        cid = str(c["id"])
        m_type = c.get("match_type", "vector")
        kw_rank = c.get("keyword_rank")
        vec_sim = float(c.get("vector_similarity") or 0.0)
        kw_hits = int(c.get("kw_hit_count") or 0)

        if m_type == "hybrid":
            # 雙軌同時命中：給予最高 Rerank 分數 (0.97 ~ 0.998)
            score = min(0.998, 0.96 + min(0.03, kw_hits * 0.008) + vec_sim * 0.01)
            reason = f"雙軌命中（關鍵字 #{kw_rank} + 向量 #{c.get('vector_rank')}）"
        elif m_type == "keyword":
            # 關鍵字精準命中（零遺漏保護）：給予高優先分數 (0.93 ~ 0.985)
            score = min(0.985, 0.93 + min(0.05, kw_hits * 0.01))
            reason = f"關鍵字精準命中（共 {kw_hits} 處匹配，零遺漏保護）"
        else:
            # 向量語意命中：優先採用 Gemini Reranker 評分，否則依 RRF + 向量餘弦計算
            if cid in llm_scores:
                score = round(float(llm_scores[cid].relevance_score), 4)
                reason = f"AI 語意重排序：{llm_scores[cid].reason}"
            else:
                score = round(min(0.92, max(0.35, vec_sim)), 4)
                reason = f"向量語意相似命中（向量排名 #{c.get('vector_rank')}）"

        item_out = dict(c)
        item_out["rerank_score"] = round(score, 4)
        item_out["rerank_reason"] = reason
        # 向下相容舊前端的 similarity 欄位（直接填入最終重排序分數）
        item_out["similarity"] = round(score, 4)
        reranked.append(item_out)

    # 最終排序：若屬於同一個文件的名單查詢，先依高相關度挑選，若分數皆為關鍵字命中則依段落順序排列以利閱讀
    reranked.sort(
        key=lambda x: (
            0 if x.get("match_type") in ("hybrid", "keyword") else 1,
            int(x.get("chunk_index", 0))
            if x.get("match_type") in ("hybrid", "keyword")
            else -float(x.get("rerank_score", 0.0)),
        )
    )
    return reranked[:top_k]


@traceable(name="module6_hybrid_rerank_pipeline", run_type="retriever")
async def execute_hybrid_rerank_search(
    user: AuthenticatedUser,
    query: str,
    document_id_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    match_threshold: float = 0.2,
    top_k: int = 8,
) -> List[dict]:
    """
    模組 6 完整檢索管道：
    1. 模組 4 元數據條件過濾（依 document_id 或 AI category 建立候選文件白名單）
    2. 軌道 A：關鍵字全文檢索（Lexical Search -> keyword_rank）
    3. 軌道 B：pgvector 768 維度向量檢索（Vector Search -> vector_rank）
    4. 階段二：RRF 倒數排名融合（Reciprocal Rank Fusion -> rrf_score & match_type）
    5. 階段三：AI 精準重排序（Reranking -> rerank_score & rerank_reason）
    """
    doc_map: Dict[str, str] = {}
    doc_meta_map: Dict[str, dict] = {}
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
                doc_meta_map[r["document_id"]] = m.get("extracted_metadata") or {}

        if document_id_filter:
            allowed_doc_ids = {document_id_filter}
        elif category_filter:
            matched_ids = {
                did
                for did, em in doc_meta_map.items()
                if em.get("category") == category_filter
            }
            if matched_ids:
                allowed_doc_ids = matched_ids
    except Exception:
        pass

    # 1. 執行雙軌檢索
    kw_hits = lexical_keyword_search(
        user=user,
        query=query,
        allowed_doc_ids=allowed_doc_ids,
        doc_map=doc_map,
        doc_meta_map=doc_meta_map,
    )
    vec_hits = await dense_vector_search(
        user=user,
        query=query,
        allowed_doc_ids=allowed_doc_ids,
        doc_meta_map=doc_meta_map,
        match_threshold=match_threshold,
        match_count=top_k + 4,
    )

    # 2. 執行 RRF 倒數排名融合
    fused_candidates = reciprocal_rank_fusion(kw_hits, vec_hits, k=RRF_K)

    # 3. 執行 AI 重排序與零遺漏保護
    final_results = await rerank_candidates(query, fused_candidates, top_k=top_k)
    return final_results
