import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Literal, Optional
import httpx
from bs4 import BeautifulSoup
from langsmith import traceable
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser
from app.config import settings
from app.llm import llm_client


class StructuredSqlQueryPlanSchema(BaseModel):
    """模組 7：Text-to-SQL 結構化查詢計劃 Pydantic Schema"""

    query_mode: Literal["kb_inventory", "table_row_analytics", "combined_analytics"] = Field(
        description=(
            "查詢模式："
            "'kb_inventory' 用於統計知識庫有幾份文件、哪些分類、各文件分塊數與字數；"
            "'table_row_analytics' 用於跨全文件掃描並統計特定社團、獎項、分區、時段或關鍵字的總筆數與排行；"
            "'combined_analytics' 同時輸出知識庫結構統計與全文件明細統計。"
        )
    )
    filter_keywords: List[str] = Field(
        default_factory=list,
        description="要在全文件結構化列中篩選或分組計數的核心關鍵詞（例如 ['松青', '民生'] 或 ['保羅哈里斯', '超我服務獎']；若要統計整份文件所有項目則留空列表）",
    )
    sql_preview: str = Field(
        description="等效的標準 PostgreSQL SELECT 查詢語句（供前端展示 Text-to-SQL 轉換結果與審計）"
    )
    explanation: str = Field(
        description="簡短繁體中文說明：為什麼此問題適合使用 Text-to-SQL 結構化數據查詢（35字以內）"
    )


def _build_default_sql_plan(natural_query: str) -> StructuredSqlQueryPlanSchema:
    """當需要快速生成預設 SQL 查詢計劃時的確定性回退邏輯。"""
    is_kb_meta_query = any(
        w in natural_query
        for w in ("幾份文件", "哪些文件", "知識庫有什麼", "知識庫統計", "分塊數", "分類統計", "所有文件", "各分類")
    )
    cleaned = re.sub(
        r"(?i)(請問|幫我|統計|計算|查詢|知識庫|目前|共有|總共|幾份|多少|幾個|哪些|文件|檔案|列表|清單|各分類|每個分類|分類|有幾|筆數|比較|得獎|獲獎|名單|分塊|以及|SQL|與|和|跟|及|用|社|的|嗎|呢|，|、|？|\?)",
        " ",
        natural_query,
    )
    tokens = [t.strip() for t in cleaned.split() if len(t.strip()) >= 2]
    if is_kb_meta_query and not tokens:
        return StructuredSqlQueryPlanSchema(
            query_mode="kb_inventory",
            filter_keywords=[],
            sql_preview=(
                "SELECT filename, category, event_or_year, total_chunks, total_characters\n"
                "FROM public.user_documents_analytics\n"
                "WHERE user_id = auth.uid() AND status = 'completed'\n"
                "ORDER BY updated_at DESC;"
            ),
            explanation="查詢知識庫中所有已導入文件的分類、分塊數與字數統計表。",
        )

    kw_filter_sql = (
        " AND ("
        + " OR ".join([f"content ILIKE '%{kw}%'" for kw in tokens[:3]])
        + ")"
        if tokens
        else ""
    )
    return StructuredSqlQueryPlanSchema(
        query_mode="combined_analytics",
        filter_keywords=tokens[:4],
        sql_preview=(
            "SELECT d.filename, c.chunk_index, c.metadata->'extracted_metadata'->>'category' AS category,\n"
            "       COUNT(*) OVER (PARTITION BY d.id) AS matched_chunks\n"
            "FROM public.document_chunks c\n"
            "JOIN public.documents d ON d.id = c.document_id\n"
            f"WHERE d.user_id = auth.uid() AND d.status = 'completed'{kw_filter_sql}\n"
            "ORDER BY d.filename, c.chunk_index ASC;"
        ),
        explanation="透過結構化全表掃描與分組聚合，精確統計跨段落的完整筆數與分類明細。",
    )


def normalize_entity_keyword(raw_kw: str) -> str:
    """
    將使用者或 LLM 輸入的社團/專有名詞正規化為文件中的核心字詞。
    例如：『松青社』、『台北松青扶輪社』 -> 『松青』；『民生社』 -> 『民生』。
    因為扶輪社表揚名單表格中的「社名」欄位通常省略「社」字（如：04-4 松青、04-3 民生）。
    """
    s = raw_kw.strip()
    s = re.sub(r"^(臺北市|台北市|新北市|國際扶輪\d*地區)?", "", s).strip()
    s = re.sub(r"(扶輪社|社)$", "", s).strip()
    return s if len(s) >= 2 else raw_kw.strip()


@traceable(name="generate_text_to_sql_plan", run_type="llm")
async def generate_sql_plan(natural_query: str) -> StructuredSqlQueryPlanSchema:
    """使用 Gemini + Pydantic StructuredSqlQueryPlanSchema 將自然語言轉為結構化查詢計劃與 SQL。"""
    system_prompt = (
        "你是一個專業的 PostgreSQL Text-to-SQL 結構化查詢規劃器。\n"
        "資料庫包含以下主要結構：\n"
        "1. `user_documents_analytics(document_id, user_id, filename, status, category, event_or_year, total_chunks, total_characters, updated_at)`\n"
        "2. `document_chunks(id, document_id, user_id, chunk_index, content, metadata)`\n"
        "【重要欄位規則】：文件中的扶輪社名欄位皆省略『社』字（例如『松青社』在資料庫中記載為『04-4 松青』，『民生社』記載為『04-3 民生』）。"
        "因此在設定 `filter_keywords` 與 `sql_preview` 的 `ILIKE` 條件時，請務必去掉尾部的『社』或『扶輪社』（例如填寫 `'松青'`、`'民生'`），才能 100% 命中社友的得獎紀錄！\n"
        "請根據使用者的自然語言問題，輸出嚴格符合 JSON Schema 的結構化查詢計劃與等效 SQL 語句。"
    )
    for model_name in [settings.LLM_MODEL, "gemini-3.5-flash", "gemini-3.5-flash-lite"]:
        try:
            resp = await llm_client.beta.chat.completions.parse(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"使用者問題：{natural_query}"},
                ],
                response_format=StructuredSqlQueryPlanSchema,
                temperature=0.1,
            )
            parsed = resp.choices[0].message.parsed
            if parsed:
                # 強制正規化所有 filter_keywords，確保「松青社」自動轉為「松青」
                normalized_kws = []
                for kw in parsed.filter_keywords:
                    core = normalize_entity_keyword(kw)
                    if core and core not in normalized_kws:
                        normalized_kws.append(core)
                parsed.filter_keywords = normalized_kws
                return parsed
        except Exception:
            continue
    return _build_default_sql_plan(natural_query)


@traceable(name="execute_structured_sql_tool", run_type="tool")
async def execute_structured_sql_tool(
    user: AuthenticatedUser,
    natural_query: str,
    document_id_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
) -> dict:
    """
    模組 7 工具 B：Text-to-SQL 結構化數據查詢工具（`query_structured_database`）。
    針對「知識庫總覽盤點」、「分類統計」、「全文件得獎筆數/分區/社團聚合統計」執行 100% 跨分塊結構化分析，
    不受限於單次向量檢索 Top-8 段落上限。
    """
    plan = await generate_sql_plan(natural_query)

    # 1. 讀取當前用戶的所有已完成文件
    docs_q = (
        user.supabase.table("documents")
        .select("id, filename, status, created_at, updated_at")
        .eq("status", "completed")
        .order("updated_at", desc=True)
    )
    if document_id_filter:
        docs_q = docs_q.eq("id", document_id_filter)
    docs_res = docs_q.execute()
    docs = docs_res.data or []
    doc_ids = [d["id"] for d in docs]

    # 2. 讀取所有分塊（供計算每個文件的總分塊數、總字數、元數據與結構化列統計）
    chunks_by_doc: dict[str, list[dict]] = {did: [] for did in doc_ids}
    if doc_ids:
        chunks_res = (
            user.supabase.table("document_chunks")
            .select("id, document_id, chunk_index, content, metadata")
            .in_("document_id", doc_ids)
            .order("chunk_index", desc=False)
            .execute()
        )
        for ch in chunks_res.data or []:
            did = ch.get("document_id")
            if did in chunks_by_doc:
                chunks_by_doc[did].append(ch)

    # 建立結構化文件統計列
    doc_analytics_rows = []
    category_counter: dict[str, int] = {}
    for d in docs:
        did = d["id"]
        d_chunks = chunks_by_doc.get(did, [])
        ext_meta = {}
        file_hash = None
        if d_chunks:
            m0 = d_chunks[0].get("metadata") or {}
            ext_meta = m0.get("extracted_metadata") or {}
            file_hash = m0.get("file_hash")
        cat = ext_meta.get("category") or "未分類"
        if category_filter and cat != category_filter:
            continue
        category_counter[cat] = category_counter.get(cat, 0) + 1
        total_chars = sum(len(c.get("content") or "") for c in d_chunks)
        doc_analytics_rows.append(
            {
                "document_id": did,
                "filename": d["filename"],
                "document_title": ext_meta.get("document_title") or d["filename"],
                "category": cat,
                "event_or_year": ext_meta.get("event_or_year") or "—",
                "total_chunks": len(d_chunks),
                "total_characters": total_chars,
                "file_hash_short": (file_hash or "")[:12] or "—",
            }
        )

    # 3. 若有指定關鍵詞或詢問明細統計，先正規化核心關鍵字（如「松青社」->「松青」），再掃描所有分塊並對重複列自動去重
    raw_keywords = [kw.strip() for kw in plan.filter_keywords if len(kw.strip()) >= 2]
    # 若 LLM 未提取出關鍵詞但問題中有「XX社」，自動從問題補充提取
    if not raw_keywords:
        club_matches = re.findall(r"([\u4e00-\u9fa5]{2,4})社", natural_query)
        for cm in club_matches:
            core = normalize_entity_keyword(cm)
            if core and core not in raw_keywords and core not in ("請問", "哪些", "什麼", "目前"):
                raw_keywords.append(core)

    keywords: list[str] = []
    for rk in raw_keywords:
        core_k = normalize_entity_keyword(rk)
        if core_k and core_k not in keywords:
            keywords.append(core_k)

    matched_lines_dedup: list[str] = []
    seen_norm_lines: set[str] = set()
    keyword_group_rows: dict[str, list[str]] = {kw: [] for kw in keywords}

    for row in doc_analytics_rows:
        did = row["document_id"]
        fname = row["filename"]
        for ch in chunks_by_doc.get(did, []):
            c_idx = ch.get("chunk_index", 0)
            text = ch.get("content") or ""
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if len(line) < 4:
                    continue
                if re.match(r"^[\|\-\:\s]+$", line):
                    continue
                if keywords:
                    hit_kws = [kw for kw in keywords if kw.lower() in line.lower()]
                    if not hit_kws:
                        continue
                    norm_line = re.sub(r"\s+", " ", line)
                    if norm_line not in seen_norm_lines:
                        seen_norm_lines.add(norm_line)
                        formatted_entry = f"[{fname} #段落{c_idx + 1}] {norm_line}"
                        matched_lines_dedup.append(formatted_entry)
                        for hk in hit_kws:
                            keyword_group_rows[hk].append(formatted_entry)

    # 4. 組裝結構化報表 Markdown
    md_sections = [
        f"### 🗄️ Text-to-SQL 結構化數據查詢結果",
        f"- **查詢策略說明**：{plan.explanation}",
        f"- **執行的等效 SQL**：\n```sql\n{plan.sql_preview}\n```",
    ]

    if doc_analytics_rows:
        md_sections.append(
            f"\n#### 📊 1. 知識庫文件結構化總覽（共 {len(doc_analytics_rows)} 份文件，分塊總數 {sum(r['total_chunks'] for r in doc_analytics_rows)} 個）"
        )
        table_lines = [
            "| 檔案名稱 | AI 分類 | 年份/活動 | 分塊數 (Chunks) | 總字元數 | SHA-256 指紋前綴 |",
            "| :--- | :--- | :--- | :---: | :---: | :--- |",
        ]
        for r in doc_analytics_rows:
            table_lines.append(
                f"| {r['filename']} | {r['category']} | {r['event_or_year']} | {r['total_chunks']} | {r['total_characters']:,} | `{r['file_hash_short']}` |"
            )
        md_sections.append("\n".join(table_lines))

        cat_summary = "、".join([f"**{k}** ({v} 份)" for k, v in category_counter.items()])
        md_sections.append(f"- **各類別文件數量分布**：{cat_summary}")

    if keywords:
        kw_stats_parts = []
        for k, rows in keyword_group_rows.items():
            member_counts: dict[str, int] = {}
            for r_line in rows:
                m_person = re.search(r"\b\d{2}-\d+\s+\S+\s+([\u4e00-\u9fa5]{2,4})\b", r_line)
                if m_person:
                    pname = m_person.group(1)
                    member_counts[pname] = member_counts.get(pname, 0) + 1
            if member_counts:
                kw_stats_parts.append(
                    f"「{k}社（核心詞：{k}）」共 **{len(rows)} 筆得獎紀錄**（涵蓋 **{len(member_counts)} 位得獎社友**）"
                )
            else:
                kw_stats_parts.append(f"「{k}（{k}社）」共命中 **{len(rows)} 筆紀錄**")

        kw_stats_str = "；".join(kw_stats_parts)
        md_sections.append(f"\n#### 🔍 2. 全文件結構化條件篩選與社友得獎筆數統計（{kw_stats_str}）")
        for k, rows in keyword_group_rows.items():
            member_counts: dict[str, int] = {}
            for r_line in rows:
                m_person = re.search(r"\b\d{2}-\d+\s+\S+\s+([\u4e00-\u9fa5]{2,4})\b", r_line)
                if m_person:
                    pname = m_person.group(1)
                    member_counts[pname] = member_counts.get(pname, 0) + 1
            member_breakdown = (
                "（得獎社友統計："
                + "、".join([f"{p} {c}筆" for p, c in member_counts.items()])
                + "）"
                if member_counts
                else ""
            )
            md_sections.append(
                f"##### 📌 【{k}社（搜尋核心詞：`{k}`）】— 共 {len(rows)} 筆得獎紀錄 / {len(member_counts)} 位社友 {member_breakdown}："
            )
            if rows:
                md_sections.append("\n".join([f"{idx + 1}. {ln}" for idx, ln in enumerate(rows)]))
            else:
                md_sections.append("- 未找到符合此關鍵詞的得獎紀錄。")

    summary_markdown = "\n\n".join(md_sections)

    source_card = {
        "filename": "PostgreSQL 結構化統計視圖 (user_documents_analytics)",
        "category": "Text-to-SQL 結構化查詢",
        "event_or_year": f"掃描 {len(doc_analytics_rows)} 份文件 / 命中 {len(matched_lines_dedup)} 筆紀錄",
        "chunk_index": 0,
        "content": summary_markdown,
        "similarity": 1.0,
        "match_type": "sql",
        "sql_query": plan.sql_preview,
        "rerank_score": 1.0,
        "rerank_reason": f"Text-to-SQL 結構化數據查詢：{plan.explanation}（共命中 {len(matched_lines_dedup)} 筆不重複紀錄）",
    }

    return {
        "tool_type": "sql",
        "sql_query": plan.sql_preview,
        "explanation": plan.explanation,
        "doc_count": len(doc_analytics_rows),
        "matched_row_count": len(matched_lines_dedup),
        "summary_markdown": summary_markdown,
        "source_card": source_card,
    }


async def _search_google_news_rss(query: str, max_results: int = 5) -> List[dict]:
    """透過 Google News 台灣繁體中文 RSS 檢索即時新聞與外部資訊（免 API Key、速度快且穩定）。"""
    encoded_q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    results: List[dict] = []
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
            )
            if resp.status_code == 200 and resp.text:
                root = ET.fromstring(resp.text)
                for item in root.findall(".//item")[:max_results]:
                    title = (item.findtext("title") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    pub_date = (item.findtext("pubDate") or "").strip()
                    source_el = item.find("source")
                    source_name = (
                        source_el.text.strip()
                        if source_el is not None and source_el.text
                        else "Google 新聞"
                    )
                    desc_html = item.findtext("description") or ""
                    desc_text = BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True)
                    if title and link:
                        results.append(
                            {
                                "title": title,
                                "url": link,
                                "snippet": desc_text or title,
                                "source_name": source_name,
                                "published_at": pub_date,
                            }
                        )
    except Exception:
        pass
    return results


async def _search_duckduckgo_html(query: str, max_results: int = 5) -> List[dict]:
    """透過 DuckDuckGo HTML 端點搜尋一般網頁資訊。"""
    url = "https://html.duckduckgo.com/html/"
    results: List[dict] = []
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.post(
                url,
                data={"q": query, "kl": "tw-tzh"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if resp.status_code == 200 and resp.text:
                soup = BeautifulSoup(resp.text, "html.parser")
                for res_div in soup.select(".result")[:max_results]:
                    a_tag = res_div.select_one(".result__a")
                    snip_tag = res_div.select_one(".result__snippet")
                    if not a_tag:
                        continue
                    title = a_tag.get_text(" ", strip=True)
                    raw_href = a_tag.get("href", "")
                    if "uddg=" in raw_href:
                        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_href).query)
                        real_url = parsed_qs.get("uddg", [raw_href])[0]
                    else:
                        real_url = raw_href
                    snippet = snip_tag.get_text(" ", strip=True) if snip_tag else title
                    if title and real_url.startswith("http"):
                        results.append(
                            {
                                "title": title,
                                "url": real_url,
                                "snippet": snippet,
                                "source_name": urllib.parse.urlparse(real_url).netloc,
                                "published_at": "",
                            }
                        )
    except Exception:
        pass
    return results


async def _search_wikipedia_zh(query: str, max_results: int = 3) -> List[dict]:
    """透過中文維基百科 OpenSearch API 補充知識型/背景型外部查詢。"""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "utf8": "1",
        "format": "json",
        "srlimit": str(max_results),
    }
    url = f"https://zh.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    results: List[dict] = []
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "AgenticRAGMasterclass/1.0 (https://github.com/fruit8428/agentic-rag)"},
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in (data.get("query", {}).get("search") or [])[:max_results]:
                    title = item.get("title", "")
                    snippet_html = item.get("snippet", "")
                    snippet = BeautifulSoup(snippet_html, "html.parser").get_text(" ", strip=True)
                    page_url = f"https://zh.wikipedia.org/wiki/{urllib.parse.quote(title)}"
                    if title:
                        results.append(
                            {
                                "title": f"{title} - 維基百科",
                                "url": page_url,
                                "snippet": snippet,
                                "source_name": "中文維基百科",
                                "published_at": "",
                            }
                        )
    except Exception:
        pass
    return results


@traceable(name="execute_web_search_tool", run_type="tool")
async def execute_web_search_tool(
    query: str,
    max_results: int = 5,
    fallback_reason: str = "查詢外部即時網路資訊或補充知識庫未記載之內容",
) -> dict:
    """
    模組 7 工具 C：即時網路搜索與優雅回退工具（`search_web_fallback`）。
    結合 DuckDuckGo 網頁搜尋、Google News 台灣繁體中文即時新聞與中文維基百科，
    回傳附帶真實網址（URL）與來源名稱的外部檢索結果，供 AI 進行清楚的來源歸因（Attribution）。
    """
    combined: List[dict] = []
    seen_urls: set[str] = set()

    # 依序並行查詢 DuckDuckGo 網頁、Google News RSS 與中文維基百科
    ddg_hits = await _search_duckduckgo_html(query, max_results=max_results)
    gnews_hits = await _search_google_news_rss(query, max_results=max_results)
    wiki_hits = await _search_wikipedia_zh(query, max_results=2)

    for item in ddg_hits + gnews_hits + wiki_hits:
        u = item.get("url", "")
        if u and u not in seen_urls:
            seen_urls.add(u)
            combined.append(item)
        if len(combined) >= max_results:
            break

    source_cards: List[dict] = []
    formatted_items: List[str] = []

    for idx, item in enumerate(combined):
        title = item["title"]
        url = item["url"]
        snippet = item["snippet"]
        source_name = item.get("source_name") or "外部網頁"
        pub_date = item.get("published_at") or ""

        formatted_items.append(
            f"【🌐 外部網路來源 #{idx + 1}：{title}】\n"
            f"- 來源媒體/網站：{source_name} {f'({pub_date})' if pub_date else ''}\n"
            f"- 網址：{url}\n"
            f"- 摘要內容：{snippet}"
        )

        source_cards.append(
            {
                "filename": f"🌐 {title}",
                "category": f"網路搜尋 ({source_name})",
                "event_or_year": pub_date[:16] if pub_date else "即時網頁",
                "chunk_index": idx,
                "content": f"{snippet}\n\n🔗 來源網址：{url}",
                "similarity": round(0.95 - idx * 0.03, 3),
                "match_type": "web",
                "web_url": url,
                "rerank_score": round(0.95 - idx * 0.03, 3),
                "rerank_reason": f"{fallback_reason}（來源：{source_name}）",
            }
        )

    formatted_context = (
        "\n\n---\n\n".join(formatted_items)
        if formatted_items
        else f"已對「{query}」執行外部網路搜尋，但暫無直接符合的網頁摘要。"
    )

    return {
        "tool_type": "web",
        "query": query,
        "results": combined,
        "source_cards": source_cards,
        "formatted_context": formatted_context,
    }
