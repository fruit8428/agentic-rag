import React, { useEffect, useRef, useState } from 'react'
import { supabase } from '../lib/supabase'
import {
  UploadCloud,
  FileText,
  Trash2,
  CheckCircle2,
  Loader2,
  AlertCircle,
  RefreshCw,
  Layers,
  AlertTriangle,
  Fingerprint,
  Zap,
  GitCompare,
  Sparkles,
  Tag,
  Calendar,
  FileCode,
  Table2,
  ShieldCheck,
} from 'lucide-react'

interface SyncSummary {
  mode: 'created' | 'unchanged' | 'incremental'
  file_hash?: string
  short_hash?: string
  total_chunks: number
  unchanged_chunks: number
  added_chunks: number
  removed_chunks: number
  saved_embeddings: number
  synced_at?: string
}

interface ExtractedMetadata {
  document_title: string
  category: string
  event_or_year: string
  summary: string
  keywords: string[]
  extracted_at?: string
}

interface ParseInfo {
  format_type: 'PDF' | 'DOCX' | 'HTML' | 'CSV' | 'MARKDOWN' | 'TXT' | string
  parser_engine: string
  section_count?: number
  table_count?: number
  char_count?: number
}

interface DocumentItem {
  id: string
  user_id: string
  filename: string
  file_size: number
  mime_type: string
  status: 'uploading' | 'processing' | 'completed' | 'failed'
  chunk_count: number
  error_message?: string | null
  content_hash?: string | null
  sync_summary?: SyncSummary | null
  extracted_metadata?: ExtractedMetadata | null
  parse_info?: ParseInfo | null
  created_at: string
  updated_at: string
}

interface IngestViewProps {
  accessToken: string
  userId: string
}

export function IngestView({ accessToken, userId }: IngestViewProps) {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [extractingDocId, setExtractingDocId] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [errorBanner, setErrorBanner] = useState<string | null>(null)
  const [syncNotice, setSyncNotice] = useState<{
    filename: string
    summary: SyncSummary
  } | null>(null)
  const [deleteNotice, setDeleteNotice] = useState<{
    filename: string
    deleted_chunks_count: number
    storage_removed: boolean
    verified_zero_orphans: boolean
  } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchDocuments = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await fetch('/api/documents', {
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      const data: DocumentItem[] = await res.json()
      if (!res.ok) {
        throw new Error((data as any).detail || '無法讀取文件列表')
      }
      setDocuments(data)
      setErrorBanner(null)
    } catch (err: any) {
      setErrorBanner(err.message)
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    fetchDocuments()

    const channel = supabase
      .channel('documents-status-channel')
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'documents',
          filter: `user_id=eq.${userId}`,
        },
        () => {
          fetchDocuments(true)
        }
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [accessToken, userId])

  useEffect(() => {
    const hasProcessing = documents.some(
      (d) => d.status === 'processing' || d.status === 'uploading'
    )
    if (!hasProcessing) return
    const timer = setInterval(() => {
      fetchDocuments(true)
    }, 1500)
    return () => clearInterval(timer)
  }, [documents, accessToken])

  const uploadSingleFileObject = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)

    const res = await fetch('/api/documents/upload', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
      body: formData,
    })
    const data: DocumentItem = await res.json()
    if (!res.ok) {
      throw new Error((data as any).detail || `上傳 ${file.name} 失敗`)
    }
    setDocuments((prev) => [data, ...prev.filter((d) => d.id !== data.id)])

    if (data.sync_summary) {
      setSyncNotice({
        filename: data.filename,
        summary: data.sync_summary,
      })
    } else {
      // 背景處理完成後自動抓取最新 sync_summary
      setTimeout(async () => {
        const listRes = await fetch('/api/documents', {
          headers: { Authorization: `Bearer ${accessToken}` },
        })
        if (listRes.ok) {
          const listData: DocumentItem[] = await listRes.json()
          setDocuments(listData)
          const updated = listData.find((d) => d.id === data.id)
          if (updated && updated.sync_summary) {
            setSyncNotice({
              filename: updated.filename,
              summary: updated.sync_summary,
            })
          }
        }
      }, 2800)
    }
  }

  const handleFilesUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setErrorBanner(null)
    setUploading(true)

    try {
      for (const file of Array.from(files)) {
        await uploadSingleFileObject(file)
      }
    } catch (err: any) {
      setErrorBanner(err.message || '檔案上傳失敗')
    } finally {
      setUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  // 模組 3 互動實驗室：產生測試用 Markdown 檔案以驗證「秒速去重」與「增量更新」
  const handleRunRecordManagerDemo = async (mode: 'v1' | 'v1_dup' | 'v2_inc') => {
    setErrorBanner(null)
    setUploading(true)
    try {
      const para1 =
        '【第一段：活動基本資訊】\n2026 國際扶輪 3481 地區年會將於 3 月 29 日（週日）在 12 樓大會廳盛大舉行。上午 08:30–11:20 為第三全會，下午 14:40–16:50 為第四全會。\n' +
        '請各分區助理總監（AG）、社長（P）與受獎社友提前 20 分鐘至報到處領取受獎名牌並依指定座位入席。'.repeat(12)

      const para2_v1 =
        '【第二段：松青社（04-4）報到與集合提醒 - 初版 v1.0】\n松青社本次共有楊富中（AG Fruit）、林啟平（P Tony）、李瑞琦（IPP Rachel）、黃郁晴（PP Kitty）、黃世欽（PP Albert）等社友獲獎。集合地點暫定於 12 樓一號報到櫃檯前。'.repeat(
          12
        )

      const para2_v2 =
        '【第二段：松青社（04-4）報到與集合提醒 - 修訂版 v2.0】\n松青社本次共有楊富中（AG Fruit）、林啟平（P Tony，榮獲永久基金*1與模範貢獻獎）、李瑞琦（IPP Rachel）、黃郁晴（PP Kitty）、黃世欽（PP Albert）獲獎。最新通知：集合地點改至 12 樓貴賓室門口，並請穿著正式西裝配戴年度領帶！'.repeat(
          12
        )

      const content =
        mode === 'v2_inc'
          ? `${para1}\n\n${para2_v2}`
          : `${para1}\n\n${para2_v1}`

      const blob = new Blob([content], { type: 'text/markdown' })
      const demoFile = new File([blob], '模組3測試_松青社年會備忘錄.md', {
        type: 'text/markdown',
      })
      await uploadSingleFileObject(demoFile)
    } catch (err: any) {
      setErrorBanner(err.message || '測試執行失敗')
    } finally {
      setUploading(false)
    }
  }

  // 模組 5 互動實驗室：一鍵測試多格式解析（Word .docx 表格、HTML 網頁表格、CSV 結構化名冊）
  const handleRunMultiformatDemo = async (format: 'docx' | 'html' | 'csv') => {
    setErrorBanner(null)
    setUploading(true)
    try {
      if (format === 'docx') {
        const res = await fetch('/api/documents/demo/docx', {
          method: 'POST',
          headers: { Authorization: `Bearer ${accessToken}` },
        })
        const data: DocumentItem = await res.json()
        if (!res.ok) {
          throw new Error((data as any).detail || '建立測試 Word 檔失敗')
        }
        setDocuments((prev) => [data, ...prev.filter((d) => d.id !== data.id)])
        setTimeout(() => fetchDocuments(true), 2800)
        return
      }

      if (format === 'html') {
        const htmlContent = `<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8" />
  <title>2026 國際扶輪 3481 地區年會場地與流程網頁公告</title>
  <script>console.log("這段網頁腳本雜訊會被模組 5 解析器自動濾除！");</script>
  <style>body { color: #333; }</style>
</head>
<body>
  <nav>首頁 &gt; 最新消息 &gt; 網頁導覽列雜訊（將自動清除）</nav>
  <h1>2026 國際扶輪 3481 地區年會場地與全會時間表（HTML 格式測試）</h1>
  <p>本網頁公告由模組 5 HTML DOM-to-Markdown 解析器自動清除 script/style/nav 雜訊，並將下方 HTML table 轉為結構化 Markdown 表格。</p>
  <h2>年會全會時程與領獎須知表</h2>
  <table>
    <thead>
      <tr>
        <th>場次名稱</th>
        <th>活動時間</th>
        <th>主要頒發獎項</th>
        <th>受獎人報到與集合地點</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>第三全會</td>
        <td>08:30–11:20</td>
        <td>超我服務獎、國際扶輪服務獎、地區服務卓越貢獻獎</td>
        <td>08:10 12樓一號報到櫃檯</td>
      </tr>
      <tr>
        <td>第四全會</td>
        <td>14:40–16:50</td>
        <td>阿奇·柯藍夫會員、保羅哈里斯之友、永久基金</td>
        <td>14:20 12樓貴賓室門口</td>
      </tr>
    </tbody>
  </table>
</body>
</html>`
        const blob = new Blob([htmlContent], { type: 'text/html' })
        const demoFile = new File([blob], '模組5測試_年會場地與流程網頁公告.html', {
          type: 'text/html',
        })
        await uploadSingleFileObject(demoFile)
        return
      }

      if (format === 'csv') {
        const csvContent = `分區,社名,職稱與姓名,Nickname,代表出席項目,聯絡備註
第四分區,04-4 松青社,AG 楊富中,Fruit,第四分區助理總監暨年會總召集,全程出席第三全會與第四全會
第四分區,04-4 松青社,P 林啟平,Tony,永久基金與社長模範貢獻獎受獎,上午08:10報到
第四分區,04-4 松青社,IPP 李瑞琦,Rachel,社員發展與服務計畫受獎代表,上午08:20入席
第四分區,04-1 民生社,P 楊宗儒,Richard,保羅哈里斯之友受獎代表,下午14:20集合`
        const blob = new Blob([csvContent], { type: 'text/csv' })
        const demoFile = new File([blob], '模組5測試_第四分區出席名冊.csv', {
          type: 'text/csv',
        })
        await uploadSingleFileObject(demoFile)
      }
    } catch (err: any) {
      setErrorBanner(err.message || '多格式測試失敗')
    } finally {
      setUploading(false)
    }
  }

  const handleExtractMetadata = async (docId: string) => {
    setExtractingDocId(docId)
    setErrorBanner(null)
    try {
      const res = await fetch(`/api/documents/${docId}/extract-metadata`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      const updatedDoc: DocumentItem = await res.json()
      if (!res.ok) {
        throw new Error((updatedDoc as any).detail || '提取元數據失敗')
      }
      setDocuments((prev) =>
        prev.map((d) => (d.id === docId ? updatedDoc : d))
      )
    } catch (err: any) {
      setErrorBanner(err.message || '提取元數據失敗')
    } finally {
      setExtractingDocId(null)
    }
  }

  const handleDelete = async (docId: string) => {
    try {
      const res = await fetch(`/api/documents/${docId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      const data = await res.json()
      if (res.ok) {
        setDocuments((prev) => prev.filter((d) => d.id !== docId))
        setDeleteNotice({
          filename: data.filename || '文件',
          deleted_chunks_count: data.deleted_chunks_count ?? 0,
          storage_removed: Boolean(data.storage_removed),
          verified_zero_orphans: data.verified_zero_orphans !== false,
        })
      }
    } catch (err: any) {
      setErrorBanner(err.message)
    }
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
  }

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 p-6 sm:p-10">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* 標題與說明 */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-2xl font-bold text-white tracking-tight">
                多格式知識庫導入 · 記錄管理器 & AI 元數據
              </h1>
              <span className="px-2.5 py-0.5 rounded-full bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-xs font-medium">
                Module 3 · 4 · 5
              </span>
            </div>
            <p className="text-sm text-slate-400 mt-1">
              支援 <strong>PDF、Word (.docx)、HTML、CSV、Markdown、TXT</strong> 統一轉 Markdown 結構化解析，內建 <strong>SHA-256 去重增量同步</strong>、<strong>AI 元數據提取</strong>與<strong>零殘留級聯刪除</strong>！
            </p>
          </div>
          <button
            onClick={() => fetchDocuments()}
            className="self-start sm:self-auto px-3.5 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 text-xs font-medium flex items-center gap-2 transition cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>重新整理狀態</span>
          </button>
        </div>

        {errorBanner && (
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-sm flex items-center justify-between gap-4">
            <div className="flex items-center gap-2.5">
              <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />
              <span>{errorBanner}</span>
            </div>
            <button
              onClick={() => fetchDocuments()}
              className="px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 text-xs font-medium shrink-0 cursor-pointer"
            >
              重試
            </button>
          </div>
        )}

        {/* 模組 5：級聯刪除（Cascade Delete）驗證報告橫幅 */}
        {deleteNotice && (
          <div className="p-4 rounded-2xl bg-emerald-950/40 border border-emerald-500/40 text-slate-200 space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold text-emerald-300">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>
                  模組 5 級聯刪除（Cascade Delete）完整性報告：{deleteNotice.filename}
                </span>
              </div>
              <button
                onClick={() => setDeleteNotice(null)}
                className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer"
              >
                關閉
              </button>
            </div>
            <p className="text-xs text-emerald-200/90 leading-relaxed">
              ✅ 已從 <code>documents</code> 主表移除文件紀錄 · ✅ 已同步清理雲端 Storage 原始檔案 · ✅ 已透過{' '}
              <code>ON DELETE CASCADE</code> 連動清除{' '}
              <strong>{deleteNotice.deleted_chunks_count}</strong> 個{' '}
              <code>pgvector</code> 向量分塊（資料庫孤兒殘留驗證：
              <strong>{deleteNotice.verified_zero_orphans ? '0 筆殘留' : '已清除'}</strong>）！
            </p>
          </div>
        )}

        {/* 模組 3：最新同步報告橫幅 */}
        {syncNotice && (
          <div className="p-4 rounded-2xl bg-indigo-950/40 border border-indigo-500/40 text-slate-200 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold text-indigo-300">
                <Fingerprint className="w-4 h-4 text-indigo-400" />
                <span>
                  記錄管理器（Record Manager）同步報告：{syncNotice.filename}
                </span>
              </div>
              <button
                onClick={() => setSyncNotice(null)}
                className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer"
              >
                關閉
              </button>
            </div>

            {syncNotice.summary.mode === 'unchanged' ? (
              <p className="text-xs text-amber-300 leading-relaxed">
                ⚡ <strong>偵測到 100% 相同的 SHA-256 檔案指紋（{syncNotice.summary.short_hash}...）！</strong>
                系統已於瞬間攔截重複導入，直接保留現有的{' '}
                <strong>{syncNotice.summary.unchanged_chunks}</strong> 個向量分塊，
                <strong>成功節省 {syncNotice.summary.saved_embeddings} 次 Gemini Embedding API 呼叫！</strong>
              </p>
            ) : syncNotice.summary.mode === 'incremental' ? (
              <p className="text-xs text-cyan-300 leading-relaxed">
                🔄 <strong>偵測到同名文件改版（增量更新完成）！</strong>
                比對新舊段落 SHA-256 指紋後：直接保留未變動段落{' '}
                <strong>{syncNotice.summary.unchanged_chunks}</strong> 塊（0 API 呼叫）、僅重新嵌入新增/修改段落{' '}
                <strong>{syncNotice.summary.added_chunks}</strong> 塊，並自動清除舊版作廢段落{' '}
                <strong>{syncNotice.summary.removed_chunks}</strong> 塊！
              </p>
            ) : (
              <p className="text-xs text-emerald-300 leading-relaxed">
                ✨ <strong>全新文件導入完成！</strong>已計算檔案 SHA-256 指紋（{syncNotice.summary.short_hash}...），共切分為{' '}
                <strong>{syncNotice.summary.total_chunks}</strong> 個分塊並寫入向量資料庫。
              </p>
            )}
          </div>
        )}

        {/* 模組 5 互動實驗室：一鍵實測多格式文件（Word / HTML / CSV）結構化表格解析 */}
        <div className="p-5 rounded-2xl bg-slate-900/70 border border-slate-800 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-emerald-300">
              <FileCode className="w-4 h-4 text-emerald-400" />
              <span>🧪 模組 5 多格式解析實驗室：一鍵實測 Word (.docx)、HTML 網頁與 CSV 表格轉 Markdown</span>
            </div>
            <span className="text-[11px] text-slate-400 hidden sm:inline">
              自動清除雜訊標籤並保留完整表格結構
            </span>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            沒有現成的 Word 或 HTML 檔也沒關係！點擊下方按鈕即可自動生成一份包含真實表格的檔案並導入知識庫（測試後可點擊右側「刪除」體驗<strong>級聯刪除驗證報告</strong>）：
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 pt-1">
            <button
              disabled={uploading}
              onClick={() => handleRunMultiformatDemo('docx')}
              className="px-3.5 py-2.5 rounded-xl bg-slate-950 hover:bg-slate-800 border border-slate-800 text-xs text-slate-200 font-medium flex items-center justify-center gap-2 transition cursor-pointer disabled:opacity-50"
            >
              <FileText className="w-3.5 h-3.5 text-blue-400" />
              <span>📘 導入測試 Word (.docx 含表格)</span>
            </button>
            <button
              disabled={uploading}
              onClick={() => handleRunMultiformatDemo('html')}
              className="px-3.5 py-2.5 rounded-xl bg-slate-950 hover:bg-slate-800 border border-slate-800 text-xs text-slate-200 font-medium flex items-center justify-center gap-2 transition cursor-pointer disabled:opacity-50"
            >
              <FileCode className="w-3.5 h-3.5 text-orange-400" />
              <span>🌐 導入測試網頁 (.html 含表格)</span>
            </button>
            <button
              disabled={uploading}
              onClick={() => handleRunMultiformatDemo('csv')}
              className="px-3.5 py-2.5 rounded-xl bg-slate-950 hover:bg-slate-800 border border-slate-800 text-xs text-slate-200 font-medium flex items-center justify-center gap-2 transition cursor-pointer disabled:opacity-50"
            >
              <Table2 className="w-3.5 h-3.5 text-emerald-400" />
              <span>📊 導入測試名冊 (.csv 結構化表)</span>
            </button>
          </div>
        </div>

        {/* 拖放上傳區 */}
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setIsDragging(true)
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setIsDragging(false)
            handleFilesUpload(e.dataTransfer.files)
          }}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-2xl p-8 text-center transition cursor-pointer ${
            isDragging
              ? 'border-indigo-500 bg-indigo-500/10'
              : 'border-slate-800 bg-slate-900/50 hover:border-indigo-500/60 hover:bg-slate-900'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.html,.htm,.csv,.md,.markdown,.txt"
            multiple
            className="hidden"
            onChange={(e) => handleFilesUpload(e.target.files)}
          />
          <div className="w-14 h-14 rounded-2xl bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400 mx-auto mb-3.5">
            {uploading ? (
              <Loader2 className="w-7 h-7 animate-spin" />
            ) : (
              <UploadCloud className="w-7 h-7" />
            )}
          </div>
          <h3 className="text-base font-semibold text-white mb-1">
            {uploading
              ? '正在執行多格式結構化解析、SHA-256 同步與 AI 元數據提取...'
              : '點擊此處選擇檔案，或直接將 PDF / DOCX / HTML / CSV / MD / TXT 拖放到這裡'}
          </h3>
          <p className="text-xs text-slate-400">
            支援 6 大格式：PDF (.pdf)、Word (.docx)、網頁 (.html)、表格 (.csv)、Markdown (.md)、純文字 (.txt)
          </p>
        </div>

        {/* 已上傳文件列表 */}
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            <Layers className="w-4 h-4 text-indigo-400" />
            <span>已導入知識庫的文件 ({documents.length})</span>
          </h2>

          {loading ? (
            <div className="py-12 flex items-center justify-center text-slate-400 text-sm gap-2 bg-slate-900/40 rounded-2xl border border-slate-800">
              <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
              <span>讀取文件列表中...</span>
            </div>
          ) : documents.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-sm bg-slate-900/30 rounded-2xl border border-slate-800/80">
              目前尚未上傳任何文件。請點擊上方虛線框上傳你的第一份文件！
            </div>
          ) : (
            <div className="space-y-3">
              {documents.map((doc) => {
                const sync = doc.sync_summary
                const meta = doc.extracted_metadata
                const pInfo = doc.parse_info
                const isExtracting = extractingDocId === doc.id
                const shortHash =
                  sync?.short_hash ||
                  (doc.content_hash ? doc.content_hash.slice(0, 12) : null)

                return (
                  <div
                    key={doc.id}
                    className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 space-y-3.5"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                      <div className="flex items-start gap-3.5 min-w-0">
                        <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 shrink-0 mt-0.5">
                          <FileText className="w-5 h-5" />
                        </div>
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="text-sm font-medium text-white truncate">
                              {doc.filename}
                            </p>
                            {pInfo?.format_type && (
                              <span className="px-2 py-0.5 rounded-md bg-blue-500/15 border border-blue-500/30 text-blue-300 text-[11px] font-semibold">
                                {pInfo.format_type}
                              </span>
                            )}
                            {meta?.category && (
                              <span className="px-2 py-0.5 rounded-full bg-violet-500/15 border border-violet-500/30 text-violet-300 text-[11px] font-medium inline-flex items-center gap-1">
                                <Tag className="w-3 h-3" />
                                {meta.category}
                              </span>
                            )}
                            {meta?.event_or_year && (
                              <span className="px-2 py-0.5 rounded-full bg-sky-500/15 border border-sky-500/30 text-sky-300 text-[11px] font-medium inline-flex items-center gap-1">
                                <Calendar className="w-3 h-3" />
                                {meta.event_or_year}
                              </span>
                            )}
                          </div>
                          <div className="flex flex-wrap items-center gap-2.5 text-xs text-slate-400">
                            <span>大小：{formatSize(doc.file_size)}</span>
                            <span>•</span>
                            <span>
                              更新：{new Date(doc.updated_at).toLocaleTimeString()}
                            </span>
                            {pInfo?.parser_engine && (
                              <>
                                <span>•</span>
                                <span className="text-slate-300">
                                  解析引擎：{pInfo.parser_engine}
                                  {pInfo.table_count && pInfo.table_count > 0
                                    ? ` (含 ${pInfo.table_count} 處表格結構)`
                                    : ''}
                                </span>
                              </>
                            )}
                            {shortHash && (
                              <>
                                <span>•</span>
                                <span
                                  title={`SHA-256: ${doc.content_hash}`}
                                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-slate-950 border border-slate-800 text-[11px] font-mono text-indigo-300"
                                >
                                  <Fingerprint className="w-3 h-3 text-indigo-400" />
                                  SHA256: {shortHash}...
                                </span>
                              </>
                            )}
                          </div>

                          {/* 記錄管理器詳細統計 */}
                          {doc.status === 'completed' && sync && (
                            <div className="pt-1 flex flex-wrap items-center gap-2 text-[11px]">
                              {sync.mode === 'unchanged' && (
                                <span className="px-2 py-0.5 rounded-md bg-amber-500/15 border border-amber-500/30 text-amber-300 flex items-center gap-1">
                                  <Zap className="w-3 h-3" />
                                  內容完全相同：已略過重複嵌入（節省 {sync.saved_embeddings} 次 API）
                                </span>
                              )}
                              {sync.mode === 'incremental' && (
                                <span className="px-2 py-0.5 rounded-md bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 flex items-center gap-1">
                                  <GitCompare className="w-3 h-3" />
                                  增量同步：保留 {sync.unchanged_chunks} 塊 · 新增/更新 {sync.added_chunks} 塊 · 移除 {sync.removed_chunks} 塊
                                </span>
                              )}
                              {sync.mode === 'created' && (
                                <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-emerald-300">
                                  初始導入：{sync.total_chunks} 個分塊皆已建立雜湊索引
                                </span>
                              )}
                            </div>
                          )}

                          {doc.error_message && (
                            <p className="text-xs text-red-400 mt-1">
                              錯誤原因：{doc.error_message}
                            </p>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-2.5 self-end sm:self-center shrink-0">
                        {doc.status === 'processing' || doc.status === 'uploading' ? (
                          <span className="px-3 py-1 rounded-full bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-xs font-medium flex items-center gap-1.5">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            <span>正在解析與同步向量...</span>
                          </span>
                        ) : doc.status === 'completed' ? (
                          <>
                            <button
                              onClick={() => handleExtractMetadata(doc.id)}
                              disabled={isExtracting}
                              title="使用 Gemini + Pydantic 重新提取結構化元數據"
                              className="px-2.5 py-1 rounded-xl bg-violet-500/10 hover:bg-violet-500/20 border border-violet-500/25 text-violet-300 text-xs font-medium flex items-center gap-1.5 transition cursor-pointer disabled:opacity-50"
                            >
                              {isExtracting ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <Sparkles className="w-3.5 h-3.5" />
                              )}
                              <span>{meta ? '重新提取元數據' : '提取 AI 元數據'}</span>
                            </button>
                            <span className="px-3 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs font-medium flex items-center gap-1.5">
                              <CheckCircle2 className="w-3.5 h-3.5" />
                              <span>已就緒 ({doc.chunk_count} 個分塊)</span>
                            </span>
                          </>
                        ) : (
                          <span className="px-3 py-1 rounded-full bg-red-500/15 border border-red-500/30 text-red-300 text-xs font-medium flex items-center gap-1.5">
                            <AlertCircle className="w-3.5 h-3.5" />
                            <span>處理失敗</span>
                          </span>
                        )}

                        <button
                          onClick={() => handleDelete(doc.id)}
                          title="執行級聯刪除（同步清除 Storage 原檔與所有 pgvector 向量分塊）"
                          className="px-3 py-1.5 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 hover:border-red-500/40 text-red-300 text-xs font-medium flex items-center gap-1.5 transition cursor-pointer"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          <span>刪除</span>
                        </button>
                      </div>
                    </div>

                    {/* 模組 4：AI 提取結構化元數據（Pydantic Schema）展示區 */}
                    {doc.status === 'completed' && meta && (
                      <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800/90 space-y-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2 text-xs font-semibold text-violet-300">
                            <Sparkles className="w-3.5 h-3.5 text-violet-400" />
                            <span>AI 結構化元數據：{meta.document_title}</span>
                          </div>
                          <span className="text-[11px] text-slate-500">
                            Pydantic Schema 驗證通過
                          </span>
                        </div>
                        <p className="text-xs text-slate-300 leading-relaxed">
                          {meta.summary}
                        </p>
                        {meta.keywords && meta.keywords.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                            <span className="text-[11px] text-slate-400 mr-1">
                              關鍵標籤：
                            </span>
                            {meta.keywords.map((kw, i) => (
                              <span
                                key={i}
                                className="px-2 py-0.5 rounded-md bg-slate-900 border border-slate-800 text-[11px] text-indigo-300"
                              >
                                #{kw}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
