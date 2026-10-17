import React, { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  MessageSquarePlus,
  Trash2,
  Send,
  Bot,
  User as UserIcon,
  Loader2,
  MessageSquare,
  AlertTriangle,
  RefreshCw,
  Search,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Filter,
  Tag,
} from 'lucide-react'

interface ThreadItem {
  id: string
  title: string
  created_at: string
  updated_at: string
}

interface SourceChunk {
  filename: string
  category?: string
  event_or_year?: string
  chunk_index: number
  content: string
  similarity: number
  match_type?: 'hybrid' | 'keyword' | 'vector'
  keyword_rank?: number | null
  vector_rank?: number | null
  vector_similarity?: number | null
  rrf_score?: number | null
  rerank_score?: number | null
  rerank_reason?: string | null
}

interface DocOption {
  id: string
  filename: string
  status: string
  extracted_metadata?: {
    document_title?: string
    category?: string
    event_or_year?: string
    keywords?: string[]
  } | null
}

interface MessageItem {
  id: string
  thread_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  sources?: SourceChunk[]
  toolQuery?: string
  isSearchingTool?: boolean
  created_at: string
}

interface ChatViewProps {
  accessToken: string
}

export function ChatView({ accessToken }: ChatViewProps) {
  const [threads, setThreads] = useState<ThreadItem[]>([])
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageItem[]>([])
  const [input, setInput] = useState('')
  const [loadingThreads, setLoadingThreads] = useState(true)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [errorBanner, setErrorBanner] = useState<string | null>(null)
  const [expandedSourceMsgIds, setExpandedSourceMsgIds] = useState<Record<string, boolean>>({})
  const [availableDocs, setAvailableDocs] = useState<DocOption[]>([])
  const [selectedCategory, setSelectedCategory] = useState<string>('')
  const [selectedDocId, setSelectedDocId] = useState<string>('')

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const isComposingRef = useRef(false)
  const compositionEndTimeRef = useRef(0)
  const skipFetchThreadIdRef = useRef<string | null>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const toggleSources = (msgId: string) => {
    setExpandedSourceMsgIds((prev) => ({ ...prev, [msgId]: !prev[msgId] }))
  }

  const fetchThreads = async () => {
    setLoadingThreads(true)
    setErrorBanner(null)
    try {
      const res = await fetch('/api/threads', {
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.detail || '無法取得對話列表')
      }
      setThreads(data)
      if (data.length > 0 && !activeThreadId) {
        setActiveThreadId(data[0].id)
      }
    } catch (err: any) {
      setErrorBanner(err.message)
    } finally {
      setLoadingThreads(false)
    }
  }

  const fetchAvailableDocs = async () => {
    try {
      const res = await fetch('/api/documents', {
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      if (res.ok) {
        const docs: DocOption[] = await res.json()
        setAvailableDocs(docs.filter((d) => d.status === 'completed'))
      }
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    fetchThreads()
    fetchAvailableDocs()
  }, [accessToken])

  useEffect(() => {
    if (!activeThreadId) {
      setMessages([])
      return
    }
    if (skipFetchThreadIdRef.current === activeThreadId) {
      skipFetchThreadIdRef.current = null
      return
    }
    const fetchMessages = async () => {
      setLoadingMessages(true)
      try {
        const res = await fetch(`/api/threads/${activeThreadId}/messages`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        })
        const data = await res.json()
        if (!res.ok) {
          throw new Error(data.detail || '無法讀取對話內容')
        }
        setMessages(data)
      } catch (err: any) {
        setErrorBanner(err.message)
      } finally {
        setLoadingMessages(false)
      }
    }
    fetchMessages()
  }, [activeThreadId, accessToken])

  const handleCreateThread = async (fromSend = false): Promise<string | null> => {
    setErrorBanner(null)
    try {
      const res = await fetch('/api/threads', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ title: '新對話' }),
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.detail || '建立對話失敗')
      }
      if (fromSend) {
        skipFetchThreadIdRef.current = data.id
      } else {
        setMessages([])
      }
      setThreads((prev) => [data, ...prev])
      setActiveThreadId(data.id)
      return data.id
    } catch (err: any) {
      setErrorBanner(err.message)
      return null
    }
  }

  const handleDeleteThread = async (threadId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      const res = await fetch(`/api/threads/${threadId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      if (res.ok) {
        const remaining = threads.filter((t) => t.id !== threadId)
        setThreads(remaining)
        if (activeThreadId === threadId) {
          setActiveThreadId(remaining.length > 0 ? remaining[0].id : null)
        }
      }
    } catch (err: any) {
      setErrorBanner(err.message)
    }
  }

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    const latestValue = textareaRef.current ? textareaRef.current.value : input
    const trimmed = latestValue.trim()
    if (!trimmed || isStreaming) return

    setInput('')
    if (textareaRef.current) {
      textareaRef.current.value = ''
    }

    setErrorBanner(null)
    let targetThreadId = activeThreadId
    if (!targetThreadId) {
      targetThreadId = await handleCreateThread(true)
      if (!targetThreadId) return
    }

    const tempUserMsg: MessageItem = {
      id: `temp-user-${Date.now()}`,
      thread_id: targetThreadId,
      role: 'user',
      content: trimmed,
      created_at: new Date().toISOString(),
    }

    const tempAssistantId = `temp-assistant-${Date.now()}`
    const tempAssistantMsg: MessageItem = {
      id: tempAssistantId,
      thread_id: targetThreadId,
      role: 'assistant',
      content: '',
      sources: [],
      created_at: new Date().toISOString(),
    }

    setMessages((prev) => [...prev, tempUserMsg, tempAssistantMsg])
    setIsStreaming(true)

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({
          thread_id: targetThreadId,
          message: trimmed,
          document_id: selectedDocId || undefined,
          category: selectedCategory || undefined,
        }),
      })

      if (!response.ok || !response.body) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.detail || '串流請求失敗')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''

        for (const chunk of lines) {
          const line = chunk.trim()
          if (!line.startsWith('data:')) continue
          const jsonStr = line.replace(/^data:\s*/, '')
          try {
            const event = JSON.parse(jsonStr)
            if (event.type === 'title_updated' && event.title) {
              setThreads((prev) =>
                prev.map((t) =>
                  t.id === targetThreadId ? { ...t, title: event.title } : t
                )
              )
            } else if (event.type === 'tool_start') {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === tempAssistantId
                    ? {
                        ...m,
                        isSearchingTool: true,
                        toolQuery: event.query,
                      }
                    : m
                )
              )
            } else if (event.type === 'tool_end') {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === tempAssistantId
                    ? {
                        ...m,
                        isSearchingTool: false,
                        toolQuery: event.query,
                        sources: event.sources || [],
                      }
                    : m
                )
              )
            } else if (event.type === 'delta' && event.content) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === tempAssistantId
                    ? { ...m, content: m.content + event.content }
                    : m
                )
              )
            } else if (event.type === 'error') {
              throw new Error(event.error || 'Gemini 回應發生錯誤')
            }
          } catch (parseErr: any) {
            if (parseErr.message && parseErr.message !== 'Unexpected end of JSON input') {
              setErrorBanner(parseErr.message)
            }
          }
        }
      }
    } catch (err: any) {
      setErrorBanner(err.message || '發送訊息失敗')
    } finally {
      setIsStreaming(false)
    }
  }

  const uniqueCategories = Array.from(
    new Set(
      availableDocs
        .map((d) => d.extracted_metadata?.category)
        .filter((c): c is string => Boolean(c))
    )
  )

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* 左側對話線程欄 */}
      <aside className="w-72 bg-slate-900/70 border-r border-slate-800 flex flex-col">
        <div className="p-4 border-b border-slate-800">
          <button
            onClick={() => handleCreateThread(false)}
            className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-xl flex items-center justify-center gap-2 shadow-lg shadow-indigo-600/20 transition cursor-pointer"
          >
            <MessageSquarePlus className="w-4 h-4" />
            <span>開啟新對話</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          {loadingThreads ? (
            <div className="flex items-center justify-center py-8 text-slate-400 text-sm gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>載入對話中...</span>
            </div>
          ) : threads.length === 0 ? (
            <div className="text-center py-10 px-4 text-xs text-slate-500">
              目前還沒有對話紀錄，點擊上方「開啟新對話」或直接在右側輸入問題！
            </div>
          ) : (
            threads.map((thread) => {
              const active = thread.id === activeThreadId
              return (
                <div
                  key={thread.id}
                  onClick={() => setActiveThreadId(thread.id)}
                  className={`group flex items-center justify-between px-3 py-2.5 rounded-xl text-sm cursor-pointer transition ${
                    active
                      ? 'bg-indigo-600/20 text-indigo-200 border border-indigo-500/30'
                      : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200 border border-transparent'
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <MessageSquare className="w-4 h-4 shrink-0 text-indigo-400" />
                    <span className="truncate">{thread.title}</span>
                  </div>
                  <button
                    onClick={(e) => handleDeleteThread(thread.id, e)}
                    title="刪除此對話"
                    className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 p-1 rounded transition"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              )
            })
          )}
        </div>
      </aside>

      {/* 右側主聊天視區 */}
      <main className="flex-1 flex flex-col bg-slate-950 overflow-hidden">
        {errorBanner && (
          <div className="m-4 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-sm flex items-center justify-between gap-4">
            <div className="flex items-center gap-2.5">
              <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />
              <span>{errorBanner}</span>
            </div>
            <button
              onClick={fetchThreads}
              className="px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 text-xs font-medium flex items-center gap-1.5 shrink-0 cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>重試</span>
            </button>
          </div>
        )}

        {/* 訊息列表 */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
          {loadingMessages ? (
            <div className="flex items-center justify-center h-full text-slate-400 text-sm gap-2">
              <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />
              <span>讀取對話歷史中...</span>
            </div>
          ) : messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center max-w-xl mx-auto px-4">
              <div className="w-14 h-14 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 mb-4">
                <Bot className="w-7 h-7" />
              </div>
              <h2 className="text-xl font-semibold text-white mb-2">
                歡迎使用你的 Agentic RAG 助理
              </h2>
              <p className="text-sm text-slate-400 leading-relaxed mb-6">
                目前已啟用 <strong>模組 6：混合搜索與重排序（Hybrid Search + RRF + AI Reranking）</strong>。系統會同時執行「關鍵字精準檢索」與「pgvector 語意向量搜尋」，透過 RRF 倒數排名融合與 AI 重排序，確保名單與語意問題皆 100% 精準命中！
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full text-left">
                {[
                  '請問松青社有誰得獎？',
                  '請問民生社有誰得獎？',
                  '請問第三全會有誰獲得超我服務獎？',
                  '這份年會頒獎名單的集合時間與領獎注意事項是什麼？',
                ].map((sample) => (
                  <button
                    key={sample}
                    onClick={() => setInput(sample)}
                    className="p-3 rounded-xl bg-slate-900/90 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 transition text-left cursor-pointer"
                  >
                    “{sample}”
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg) => {
              const isUser = msg.role === 'user'
              const hasSources = msg.sources && msg.sources.length > 0
              const isExpanded = !!expandedSourceMsgIds[msg.id]

              return (
                <div
                  key={msg.id}
                  className={`flex items-start gap-3.5 max-w-5xl mx-auto ${
                    isUser ? 'justify-end' : 'justify-start'
                  }`}
                >
                  {!isUser && (
                    <div className="w-8 h-8 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400 shrink-0 mt-0.5">
                      <Bot className="w-4 h-4" />
                    </div>
                  )}

                  <div className={`space-y-2 max-w-[92%] ${isUser ? 'items-end' : 'items-start'}`}>
                    {/* Agent 工具調用與檢索來源卡片 */}
                    {!isUser && (msg.isSearchingTool || hasSources) && (
                      <div className="rounded-xl bg-slate-900/90 border border-indigo-500/30 overflow-hidden text-xs">
                        {msg.isSearchingTool ? (
                          <div className="px-3.5 py-2.5 flex items-center gap-2 text-indigo-300">
                            <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-400" />
                            <span>
                              Agent 正在執行混合檢索 (關鍵字 + 向量 + RRF + AI 重排序)：<strong>「{msg.toolQuery}」</strong>...
                            </span>
                          </div>
                        ) : (
                          <div>
                            <button
                              type="button"
                              onClick={() => toggleSources(msg.id)}
                              className="w-full px-3.5 py-2 flex items-center justify-between gap-3 text-indigo-300 hover:bg-indigo-500/10 transition cursor-pointer"
                            >
                              <div className="flex items-center gap-2">
                                <BookOpen className="w-3.5 h-3.5 text-indigo-400" />
                                <span>
                                  混合檢索 + RRF + AI 重排序：已精選 <strong>{msg.sources?.length}</strong> 個最佳段落（點擊{isExpanded ? '收合' : '查看檢索指標與原文'}）
                                </span>
                              </div>
                              {isExpanded ? (
                                <ChevronDown className="w-3.5 h-3.5" />
                              ) : (
                                <ChevronRight className="w-3.5 h-3.5" />
                              )}
                            </button>

                            {isExpanded && (
                              <div className="p-3 border-t border-slate-800 space-y-2.5 bg-slate-950/80 max-h-80 overflow-y-auto">
                                {msg.sources?.map((src, idx) => {
                                  const matchType = src.match_type || 'vector'
                                  return (
                                    <div
                                      key={idx}
                                      className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 space-y-1.5"
                                    >
                                      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-indigo-300 font-medium">
                                        <div className="flex flex-wrap items-center gap-1.5 min-w-0">
                                          <span className="truncate">
                                            📄 {src.filename} (段落 #{src.chunk_index + 1})
                                          </span>
                                          {src.category && (
                                            <span className="px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-300 text-[10px]">
                                              {src.category}
                                            </span>
                                          )}
                                          {src.event_or_year && (
                                            <span className="px-1.5 py-0.5 rounded bg-sky-500/20 text-sky-300 text-[10px]">
                                              {src.event_or_year}
                                            </span>
                                          )}
                                        </div>

                                        {/* 模組 6：雙軌檢索來源徽章 + RRF + Rerank 分數 */}
                                        <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                                          {matchType === 'hybrid' ? (
                                            <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[10px]">
                                              🔥 雙軌命中 (關鍵字 #{src.keyword_rank} + 向量 #{src.vector_rank})
                                            </span>
                                          ) : matchType === 'keyword' ? (
                                            <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[10px]">
                                              🎯 關鍵字命中 #{src.keyword_rank ?? 1}
                                            </span>
                                          ) : (
                                            <span className="px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 text-[10px]">
                                              🧠 向量語意命中 #{src.vector_rank ?? idx + 1}
                                            </span>
                                          )}

                                          {typeof src.rrf_score === 'number' && (
                                            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                                              RRF {src.rrf_score.toFixed(4)}
                                            </span>
                                          )}

                                          <span className="px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-200 text-[10px]">
                                            ✨ Rerank 精準度 {((src.rerank_score ?? src.similarity) * 100).toFixed(1)}%
                                          </span>
                                        </div>
                                      </div>

                                      {src.rerank_reason && (
                                        <div className="text-[10px] text-emerald-300/90 bg-emerald-950/40 border border-emerald-500/20 rounded px-2 py-1">
                                          💡 重排序依據：{src.rerank_reason}
                                        </div>
                                      )}

                                      <p className="text-slate-400 text-[11px] leading-relaxed whitespace-pre-wrap">
                                        {src.content}
                                      </p>
                                    </div>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {/* 訊息本體 */}
                    <div
                      className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                        isUser
                          ? 'bg-indigo-600 text-white'
                          : 'bg-slate-900 border border-slate-800 text-slate-100'
                      }`}
                    >
                      {isUser ? (
                        <div className="whitespace-pre-wrap">{msg.content}</div>
                      ) : msg.content ? (
                        <div className="prose prose-invert prose-sm max-w-none space-y-2 overflow-x-auto">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 text-slate-400 py-1">
                          <Search className="w-4 h-4 animate-pulse text-indigo-400" />
                          <span>
                            {msg.isSearchingTool
                              ? '正在比對 pgvector 向量資料庫...'
                              : 'Gemini 正在思考並生成回應...'}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>

                  {isUser && (
                    <div className="w-8 h-8 rounded-lg bg-slate-800 border border-slate-700 flex items-center justify-center text-slate-300 shrink-0 mt-0.5">
                      <UserIcon className="w-4 h-4" />
                    </div>
                  )}
                </div>
              )
            })
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* 底部輸入列（含模組 4 元數據檢索過濾器） */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/50 space-y-2.5">
          {availableDocs.length > 0 && (
            <div className="max-w-4xl mx-auto flex flex-wrap items-center gap-2 text-xs">
              <span className="flex items-center gap-1 text-slate-400 font-medium">
                <Filter className="w-3.5 h-3.5 text-indigo-400" />
                <span>元數據檢索過濾：</span>
              </span>

              {/* 依 AI 分類過濾 */}
              <div className="flex items-center gap-1.5">
                <Tag className="w-3 h-3 text-violet-400" />
                <select
                  value={selectedCategory}
                  onChange={(e) => {
                    setSelectedCategory(e.target.value)
                    if (e.target.value) setSelectedDocId('')
                  }}
                  className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 cursor-pointer"
                >
                  <option value="">全部 AI 文件類別</option>
                  {uniqueCategories.map((cat) => (
                    <option key={cat} value={cat}>
                      類別：{cat}
                    </option>
                  ))}
                </select>
              </div>

              {/* 依特定文件過濾 */}
              <select
                value={selectedDocId}
                onChange={(e) => {
                  setSelectedDocId(e.target.value)
                  if (e.target.value) setSelectedCategory('')
                }}
                className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 max-w-xs truncate cursor-pointer"
              >
                <option value="">
                  全部知識庫文件 ({availableDocs.length} 份)
                </option>
                {availableDocs.map((doc) => (
                  <option key={doc.id} value={doc.id}>
                    📄 {doc.filename}
                    {doc.extracted_metadata?.event_or_year
                      ? ` (${doc.extracted_metadata.event_or_year})`
                      : ''}
                  </option>
                ))}
              </select>

              {(selectedCategory || selectedDocId) && (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedCategory('')
                    setSelectedDocId('')
                  }}
                  className="text-[11px] text-indigo-400 hover:text-indigo-300 underline cursor-pointer"
                >
                  清除過濾
                </button>
              )}
            </div>
          )}

          <form
            onSubmit={handleSend}
            className="max-w-4xl mx-auto flex items-end gap-3"
          >
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onCompositionStart={() => {
                isComposingRef.current = true
              }}
              onCompositionEnd={(e) => {
                isComposingRef.current = false
                compositionEndTimeRef.current = Date.now()
                setInput(e.currentTarget.value)
              }}
              onKeyDown={(e) => {
                const justFinishedComposing =
                  Date.now() - compositionEndTimeRef.current < 350
                if (
                  e.key === 'Enter' &&
                  !e.shiftKey &&
                  !isComposingRef.current &&
                  !e.nativeEvent.isComposing &&
                  e.keyCode !== 229 &&
                  !justFinishedComposing
                ) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder="詢問關於你上傳文件的任何問題（中文選字後再按 Enter 發送，或點選右側發送鈕）..."
              className="flex-1 bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none"
            />
            <button
              type="submit"
              disabled={!input.trim() || isStreaming}
              className="p-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-xl shadow-lg shadow-indigo-600/20 transition cursor-pointer"
            >
              {isStreaming ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </form>
        </div>
      </main>
    </div>
  )
}
