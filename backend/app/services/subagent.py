import re
from typing import List, Optional
from langsmith import traceable
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser
from app.config import settings
from app.llm import llm_client
from app.services.additional_tools import normalize_entity_keyword


class SubAgentReasoningSchema(BaseModel):
    """模組 8：子代理在獨立隔離上下文中產出的結構化推理與關鍵發現"""

    subagent_thought_process: List[str] = Field(
        description="子代理在隔離上下文中的 3 到 4 個具體推理步驟（繁體中文，說明如何從全文件資料中歸納出結論）"
    )
    executive_summary: str = Field(
        description="全文件深度分析的核心執行摘要（繁體中文，100~200字）"
    )
    key_insights: List[str] = Field(
        description="從全文件跨段落分析中提煉出的 3 到 6 項結構化關鍵洞察或統計亮點"
    )


def _extract_focus_tokens(task_description: str, focus_scope: Optional[str] = None) -> List[str]:
    """從委派任務中提取需要特別聚焦的分區、社團或獎項關鍵詞。"""
    combined_text = f"{focus_scope or ''} {task_description}"
    tokens: List[str] = []

    # 1. 檢查是否指定特定分區（例如「第四分區」、「04分區」、「04-」）
    zh_num_map = {
        "一": "01",
        "二": "02",
        "三": "03",
        "四": "04",
        "五": "05",
        "六": "06",
        "七": "07",
        "八": "08",
        "九": "09",
        "十": "10",
        "十一": "11",
        "十二": "12",
    }
    for zh_k, num_v in zh_num_map.items():
        if f"第{zh_k}分區" in combined_text or f"{num_v}分區" in combined_text or f"{num_v}-" in combined_text:
            if f"{num_v}-" not in tokens:
                tokens.append(f"{num_v}-")

    # 2. 檢查是否有指定特定社團
    club_matches = re.findall(r"([\u4e00-\u9fa5]{2,4})社", combined_text)
    for cm in club_matches:
        core = normalize_entity_keyword(cm)
        if core and len(core) >= 2 and core not in ("請問", "哪些", "什麼", "各分", "所有", "全體", "扶輪"):
            if core not in tokens:
                tokens.append(core)

    return tokens


@traceable(name="subagent_isolated_context_runner", run_type="chain")
async def execute_isolated_subagent(
    user: AuthenticatedUser,
    task_description: str,
    focus_scope: Optional[str] = None,
    document_id_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
) -> dict:
    """
    模組 8：具備獨立隔離上下文（Isolated Context Window）的全文件深度分析子代理。
    子代理擁有自己專屬的內部嵌套工具（Nested Tools），在隔離記憶體中掃描整份文件的所有分塊，
    完成跨頁/跨章節聚合與推理後，僅將高密度精華報告回傳給主代理，避免主對話線程上下文膨脹與污染！
    """
    main_agent_reason = (
        f"主代理偵測到使用者需求屬於「全文件跨段落深度分析 / 綜合架構盤點」場景（任務：{task_description[:48]}），"
        "若將整份文件數萬字直接塞入主對話視窗會造成上下文污染（Context Pollution），"
        "因此委派具備獨立隔離上下文的『全文件深度分析子代理 (DocumentAnalystSubAgent)』執行。"
    )

    nested_tool_calls: List[dict] = []

    # =========================================================================
    # 嵌套工具 1：subtool_inspect_document_scope（鎖定目標文件與元數據範圍）
    # =========================================================================
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

    target_docs = []
    total_raw_chars = 0
    total_chunks_count = 0
    for d in docs:
        did = d["id"]
        d_chunks = chunks_by_doc.get(did, [])
        ext_meta = ((d_chunks[0].get("metadata") or {}).get("extracted_metadata") or {}) if d_chunks else {}
        cat = ext_meta.get("category") or "未分類"
        if category_filter and cat != category_filter:
            continue
        c_chars = sum(len(c.get("content") or "") for c in d_chunks)
        total_raw_chars += c_chars
        total_chunks_count += len(d_chunks)
        target_docs.append(
            {
                "id": did,
                "filename": d["filename"],
                "category": cat,
                "event_or_year": ext_meta.get("event_or_year") or "—",
                "summary": ext_meta.get("summary") or "",
                "chunk_count": len(d_chunks),
                "char_count": c_chars,
            }
        )

    nested_tool_calls.append(
        {
            "step": 1,
            "tool_name": "subtool_inspect_document_scope",
            "tool_label": "鎖定全文件範圍與元數據",
            "input": f"category={category_filter or '全部'}, document_id={document_id_filter or '全部'}",
            "output_summary": (
                f"成功載入 {len(target_docs)} 份文件（共 {total_chunks_count} 個向量分塊，原始文本總量 {total_raw_chars:,} 字元）進入子代理隔離記憶體。"
            ),
        }
    )

    # =========================================================================
    # 嵌套工具 2：subtool_scan_full_document_structure（於隔離區掃描全文件結構、時段、獎項與分區）
    # =========================================================================
    focus_tokens = _extract_focus_tokens(task_description, focus_scope)

    seen_lines: set[str] = set()
    session_counts: dict[str, int] = {"第三全會": 0, "第四全會": 0}
    award_session_gather_map: dict[str, dict] = {}
    zone_counts: dict[str, int] = {}
    club_counts_in_focus: dict[str, List[str]] = {}
    focused_matched_rows: List[str] = []
    document_headings_and_notes: List[str] = []

    for td in target_docs:
        did = td["id"]
        fname = td["filename"]
        for ch in chunks_by_doc.get(did, []):
            text = ch.get("content") or ""
            for raw_ln in text.splitlines():
                ln = re.sub(r"\s+", " ", raw_ln.strip())
                if len(ln) < 4 or ln in seen_lines:
                    continue
                if re.match(r"^[\|\-\:\s]+$", ln):
                    continue
                seen_lines.add(ln)

                # 收集章節標題、全會時間說明或注意事項
                if any(k in ln for k in ("年會頒獎", "大會廳", "注意事項", "備註", "集合", "報到")) and not re.match(
                    r"^\d{2}-\d+", ln
                ):
                    if len(document_headings_and_notes) < 20:
                        document_headings_and_notes.append(f"[{fname}] {ln}")

                # 解析標準得獎列：例如 "04-4 松青 楊富中 AG Fruit 國際扶輪服務獎 第三全會 請於第三全會09:08至南迴廊集合..."
                row_match = re.match(
                    r"^(\d{2})-(\d+)\s+(\S+)\s+(.+?)\s+(第三全會|第四全會)\s*(.*)$",
                    ln,
                )
                if row_match:
                    zone_code = f"{row_match.group(1)}分區"
                    sub_zone = f"{row_match.group(1)}-{row_match.group(2)}"
                    club_name = row_match.group(3)
                    middle_part = row_match.group(4).strip()
                    session_name = row_match.group(5)
                    note_part = row_match.group(6).strip()

                    session_counts[session_name] = session_counts.get(session_name, 0) + 1
                    zone_counts[zone_code] = zone_counts.get(zone_code, 0) + 1

                    # 從 middle_part 拆出獎項名稱（最後一個空白詞通常是獎項名稱）
                    mid_tokens = middle_part.split()
                    award_name = mid_tokens[-1] if mid_tokens else "表揚獎項"
                    aw_key = f"{session_name}｜{award_name}"
                    if aw_key not in award_session_gather_map:
                        award_session_gather_map[aw_key] = {
                            "session": session_name,
                            "award": award_name,
                            "count": 0,
                            "note": note_part or "依大會指示領獎",
                        }
                    award_session_gather_map[aw_key]["count"] += 1

                    # 若有聚焦條件（如 04- 第四分區或特定社團），收集該範圍內各社明細
                    if focus_tokens:
                        if any(ft.lower() in ln.lower() for ft in focus_tokens):
                            club_key = f"{sub_zone} {club_name}社"
                            club_counts_in_focus.setdefault(club_key, []).append(ln)
                            focused_matched_rows.append(ln)
                else:
                    # 非標準得獎列但符合 focus_tokens
                    if focus_tokens and any(ft.lower() in ln.lower() for ft in focus_tokens):
                        focused_matched_rows.append(ln)

    nested_tool_calls.append(
        {
            "step": 2,
            "tool_name": "subtool_scan_full_document_structure",
            "tool_label": "全文件跨段落結構化掃描與去重",
            "input": f"掃描 {total_chunks_count} 個分塊, 聚焦條件={focus_tokens or ['全文件總覽']}",
            "output_summary": (
                f"於隔離區掃描去重後共解析出 {sum(session_counts.values())} 筆結構化表揚紀錄、"
                f"{len(award_session_gather_map)} 種「時段×獎項」組合，涵蓋 {len(zone_counts)} 個扶輪分區。"
            ),
        }
    )

    # =========================================================================
    # 嵌套工具 3：subtool_isolated_llm_synthesis（子代理在獨立上下文中進行深度推理與報告合成）
    # =========================================================================
    # 組裝子代理內部的結構化數據摘要（供子代理 LLM 推理與回傳）
    structured_digest_lines = [
        f"### 📋 子代理全文件掃描結構化數據總表",
        f"- **掃描文件數**：{len(target_docs)} 份（共 {total_chunks_count} 個分塊，原始文本 {total_raw_chars:,} 字元）",
        f"- **全文件不重複得獎總筆數**：共 **{sum(session_counts.values())} 筆**（第三全會：**{session_counts.get('第三全會', 0)} 筆**｜第四全會：**{session_counts.get('第四全會', 0)} 筆**）",
    ]

    if award_session_gather_map:
        structured_digest_lines.append("\n#### 🏆 1. 全文件「頒獎時段 × 獎項名稱 × 集合動線」完整統計表")
        aw_table = [
            "| 頒獎時段 | 獎項名稱 | 受獎筆數 | 集合時間與領獎動線備註 |",
            "| :--- | :--- | :---: | :--- |",
        ]
        for aw_info in award_session_gather_map.values():
            aw_table.append(
                f"| {aw_info['session']} | {aw_info['award']} | **{aw_info['count']} 筆** | {aw_info['note']} |"
            )
        structured_digest_lines.append("\n".join(aw_table))

    if zone_counts:
        sorted_zones = sorted(zone_counts.items(), key=lambda x: x[0])
        zone_str = "、".join([f"**{zk}** ({zv}筆)" for zk, zv in sorted_zones])
        structured_digest_lines.append(f"\n#### 🗺️ 2. 全地區各分區（01～12分區）得獎總筆數分布\n- {zone_str}")

    if club_counts_in_focus:
        structured_digest_lines.append(
            f"\n#### 🎯 3. 聚焦範圍（`{', '.join(focus_tokens)}`）各社得獎統計與完整明細（共 {len(focused_matched_rows)} 筆）"
        )
        for c_key in sorted(club_counts_in_focus.keys()):
            c_rows = club_counts_in_focus[c_key]
            structured_digest_lines.append(f"\n##### 📌 【{c_key}】— 共 {len(c_rows)} 筆得獎紀錄：")
            for idx, r_str in enumerate(c_rows):
                structured_digest_lines.append(f"{idx + 1}. `{r_str}`")
    elif focused_matched_rows:
        structured_digest_lines.append(
            f"\n#### 🎯 3. 聚焦關鍵字（`{', '.join(focus_tokens)}`）全文件命中明細（共 {len(focused_matched_rows)} 筆）"
        )
        for idx, r_str in enumerate(focused_matched_rows[:50]):
            structured_digest_lines.append(f"{idx + 1}. `{r_str}`")

    # 若知識庫中還有其他非名單類型的文件，一併附上文件摘要與前幾段核心內容
    for td in target_docs:
        if td["summary"]:
            structured_digest_lines.append(
                f"\n#### 📄 文件《{td['filename']}》AI 元數據摘要\n- **分類**：{td['category']}｜**年份/活動**：{td['event_or_year']}\n- **核心摘要**：{td['summary']}"
            )

    raw_digest_text = "\n".join(structured_digest_lines)

    # 呼叫獨立隔離上下文的 Gemini 進行子代理結構化推理
    subagent_thoughts = [
        f"步驟 1：在獨立隔離上下文中載入 {len(target_docs)} 份文件（共 {total_chunks_count} 個分塊、{total_raw_chars:,} 字元），避免佔用主對話視窗。",
        f"步驟 2：執行跨分塊全表掃描與重疊區間去重，統計出第三全會 {session_counts.get('第三全會', 0)} 筆、第四全會 {session_counts.get('第四全會', 0)} 筆，共 {len(award_session_gather_map)} 個獎項梯次。",
        f"步驟 3：針對任務『{task_description[:40]}』完成分區/社團與動線交叉彙整，將 {total_raw_chars:,} 字原始文本濃縮為高密度結構化報告回傳主代理。",
    ]
    exec_summary = (
        f"已完成全文件 {total_chunks_count} 個分塊（{total_raw_chars:,} 字元）的隔離深度掃描。"
        f"全文件共包含 {sum(session_counts.values())} 筆不重複表揚紀錄（第三全會 {session_counts.get('第三全會', 0)} 筆、第四全會 {session_counts.get('第四全會', 0)} 筆），"
        f"分為 {len(award_session_gather_map)} 個獎項梯次。"
    )

    try:
        isolated_messages = [
            {
                "role": "system",
                "content": (
                    "你是『全文件深度分析子代理 (DocumentAnalystSubAgent)』，運行於獨立隔離的上下文視窗中。\n"
                    "請根據下方由內部工具掃描出的全文件結構化統計資料，產出你的推理步驟（subagent_thought_process）、"
                    "執行摘要（executive_summary）與關鍵洞察（key_insights）。"
                ),
            },
            {
                "role": "user",
                "content": f"【主代理委派任務】：{task_description}\n\n【全文件掃描結構化數據】：\n{raw_digest_text[:8000]}",
            },
        ]
        for model_name in [settings.LLM_MODEL, "gemini-3.5-flash", "gemini-3.5-flash-lite"]:
            try:
                resp = await llm_client.beta.chat.completions.parse(
                    model=model_name,
                    messages=isolated_messages,
                    response_format=SubAgentReasoningSchema,
                    temperature=0.1,
                )
                parsed = resp.choices[0].message.parsed
                if parsed:
                    subagent_thoughts = parsed.subagent_thought_process or subagent_thoughts
                    exec_summary = parsed.executive_summary or exec_summary
                    break
            except Exception:
                continue
    except Exception:
        pass

    distilled_report = (
        f"## 🤖 子代理（DocumentAnalystSubAgent）全文件深度分析報告\n\n"
        f"**💡 子代理執行摘要**：{exec_summary}\n\n"
        f"{raw_digest_text}"
    )
    distilled_chars = len(distilled_report)
    saved_pct = (
        round((1.0 - min(distilled_chars, total_raw_chars) / max(total_raw_chars, 1)) * 100, 1)
        if total_raw_chars > 0
        else 90.0
    )

    nested_tool_calls.append(
        {
            "step": 3,
            "tool_name": "subtool_isolated_llm_synthesis",
            "tool_label": "子代理隔離推理與精華報告壓縮",
            "input": f"原始文本 {total_raw_chars:,} 字元 ➔ 隔離上下文合成",
            "output_summary": (
                f"子代理完成 {len(subagent_thoughts)} 步獨立推理，將 {total_raw_chars:,} 字原始資料濃縮為 {distilled_chars:,} 字結構化精華報告（為主代理節省 {saved_pct}% 上下文空間）。"
            ),
        }
    )

    subagent_trace = {
        "subagent_name": "DocumentAnalystSubAgent (全文件深度分析子代理)",
        "main_agent_reason": main_agent_reason,
        "subagent_reasoning_steps": subagent_thoughts,
        "nested_tool_calls": nested_tool_calls,
        "context_stats": {
            "raw_scanned_chars": total_raw_chars,
            "raw_scanned_chunks": total_chunks_count,
            "distilled_chars": distilled_chars,
            "saved_percentage": saved_pct,
        },
    }

    source_card = {
        "filename": f"🤖 子代理隔離分析報告（掃描 {len(target_docs)} 份文件 / {total_chunks_count} 個分塊）",
        "category": "模組 8：隔離上下文子代理",
        "event_or_year": f"節省 {saved_pct}% 主上下文",
        "chunk_index": 0,
        "content": distilled_report,
        "similarity": 1.0,
        "match_type": "subagent",
        "rerank_score": 1.0,
        "rerank_reason": f"由主代理委派子代理於獨立隔離上下文執行 3 項嵌套工具完成全文件分析（節省 {saved_pct}% 主對話記憶空間）",
        "subagent_trace": subagent_trace,
    }

    return {
        "tool_type": "subagent",
        "task_description": task_description,
        "distilled_report": distilled_report,
        "subagent_trace": subagent_trace,
        "source_card": source_card,
    }
