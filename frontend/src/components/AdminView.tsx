import { useEffect, useState } from 'react'
import {
  Plus, Trash2, KeyRound, Loader2, AlertCircle, CheckCircle2, RefreshCw, ShieldCheck, X, Copy, Check, Ticket, Eye, EyeOff,
} from 'lucide-react'
import { apiFetch } from '../lib/api'

interface AdminClub {
  id: string
  name: string
  division: string | null
  code: string | null
  activated: boolean
  activation_code: string | null
  activated_at: string | null
  password: string | null
  password_updated_at: string | null
  document_count: number
}

interface AdminViewProps {
  accessToken: string
}

type Dialog =
  | { kind: 'create' }
  | { kind: 'reset'; club: AdminClub }
  | { kind: 'regen'; club: AdminClub }
  | { kind: 'delete'; club: AdminClub }
  | null

// 地區管理員：社的新增／刪除、啟用碼配發、重設社密碼
export function AdminView({ accessToken }: AdminViewProps) {
  const [clubs, setClubs] = useState<AdminClub[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('')
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [shownPw, setShownPw] = useState<Set<string>>(new Set())

  // 表單欄位
  const [fName, setFName] = useState('')
  const [fDivision, setFDivision] = useState('')
  const [fCode, setFCode] = useState('')
  const [fPassword, setFPassword] = useState('')

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setClubs(await apiFetch<AdminClub[]>('/api/admin/clubs', accessToken))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [accessToken])

  const openDialog = (d: Dialog) => {
    setFName(''); setFDivision(''); setFCode(''); setFPassword('')
    setError(null)
    setDialog(d)
  }

  const run = async (fn: () => Promise<string>) => {
    setBusy(true)
    setError(null)
    try {
      const msg = await fn()
      setNotice(msg)
      setDialog(null)
      await load()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const copyText = async (id: string, label: string, value: string | null) => {
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      setCopiedId(id)
      setTimeout(() => setCopiedId((v) => (v === id ? null : v)), 1500)
    } catch {
      setNotice(`${label}：${value}（無法自動複製，請手動抄寫）`)
    }
  }
  const copyCode = (club: AdminClub) => copyText(club.id, '啟用碼', club.activation_code)
  const togglePw = (id: string) =>
    setShownPw((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const submitDialog = () => {
    if (!dialog) return
    if (dialog.kind === 'create') {
      return run(async () => {
        const c = await apiFetch<AdminClub>('/api/admin/clubs', accessToken, {
          method: 'POST',
          body: JSON.stringify({ name: fName, division: fDivision || null, code: fCode || null }),
        })
        return `已新增「${c.name}」，啟用碼：${c.activation_code}`
      })
    }
    if (dialog.kind === 'reset') {
      return run(async () => {
        await apiFetch(`/api/admin/clubs/${dialog.club.id}/reset-password`, accessToken, {
          method: 'POST',
          body: JSON.stringify({ new_password: fPassword }),
        })
        return `「${dialog.club.name}」的社密碼已重設，請把新密碼交給該社執秘`
      })
    }
    if (dialog.kind === 'regen') {
      return run(async () => {
        const c = await apiFetch<AdminClub>(`/api/admin/clubs/${dialog.club.id}/activation-code`, accessToken, { method: 'POST' })
        return `「${c.name}」的新啟用碼：${c.activation_code}（舊的已作廢）`
      })
    }
    if (dialog.kind === 'delete') {
      return run(async () => {
        await apiFetch(`/api/admin/clubs/${dialog.club.id}`, accessToken, { method: 'DELETE' })
        return `已刪除「${dialog.club.name}」`
      })
    }
  }

  const inputCls =
    'w-full px-3 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm focus:outline-none focus:border-indigo-500'

  const q = filter.trim().toLowerCase()
  const visible = q ? clubs.filter((c) => c.name.toLowerCase().includes(q) || (c.code || '').toLowerCase().includes(q)) : clubs
  const activatedCount = clubs.filter((c) => c.activated).length

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 p-6 sm:p-10">
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-2xl font-bold text-white tracking-tight">地區管理</h1>
              <span className="px-2.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs font-medium inline-flex items-center gap-1">
                <ShieldCheck className="w-3.5 h-3.5" /> 僅管理員可見
              </span>
            </div>
            <p className="text-sm text-slate-400 mt-1">
              把「啟用碼」交給各社執秘，執秘在登入頁「首次進入(註冊)」輸入啟用碼並自訂社密碼後，全社即可用社名登入。
            </p>
          </div>
          <button
            onClick={load}
            className="self-start sm:self-auto px-3.5 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 text-xs font-medium flex items-center gap-2 transition cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" /><span>重新整理</span>
          </button>
        </div>

        {notice && (
          <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 break-all"><CheckCircle2 className="w-4 h-4 shrink-0" />{notice}</span>
            <button onClick={() => setNotice(null)} className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer shrink-0">關閉</button>
          </div>
        )}
        {error && !dialog && (
          <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-sm flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" /><span>{error}</span>
          </div>
        )}

        {loading ? (
          <div className="flex items-center gap-2 text-slate-400 text-sm py-10 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" /> 載入中…
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <p className="text-sm text-slate-300">
                共 {clubs.length} 個社，已啟用 <span className="text-emerald-300">{activatedCount}</span>，未啟用{' '}
                <span className="text-amber-300">{clubs.length - activatedCount}</span>
              </p>
              <div className="flex items-center gap-2">
                <input
                  className="px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-100 text-xs focus:outline-none focus:border-indigo-500 w-44"
                  placeholder="搜尋社名或編號"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
                <button
                  onClick={() => openDialog({ kind: 'create' })}
                  className="px-3.5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium flex items-center gap-1.5 transition cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" /> 新增社
                </button>
              </div>
            </div>
            <div className="rounded-2xl border border-slate-800 overflow-x-auto">
              <table className="w-full text-sm min-w-[560px]">
                <thead className="bg-slate-900 text-slate-400 text-xs">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium">編號</th>
                    <th className="text-left px-4 py-2.5 font-medium">社名</th>
                    <th className="text-left px-4 py-2.5 font-medium">啟用碼 / 社密碼</th>
                    <th className="text-right px-4 py-2.5 font-medium">文件</th>
                    <th className="px-4 py-2.5"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 bg-slate-950">
                  {visible.map((c) => (
                    <tr key={c.id} className="text-slate-200">
                      <td className="px-4 py-2.5 text-slate-400 whitespace-nowrap">{c.code || '—'}</td>
                      <td className="px-4 py-2.5 font-medium">{c.name}</td>
                      <td className="px-4 py-2.5">
                        {c.activated ? (
                          <div className="flex items-center gap-2">
                            <span className="text-emerald-300 text-xs inline-flex items-center gap-1 shrink-0"><Check className="w-3.5 h-3.5" /> 已啟用</span>
                            {c.password ? (
                              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 text-xs font-mono">
                                <KeyRound className="w-3.5 h-3.5 text-slate-400" />
                                <span className="tracking-wider">{shownPw.has(c.id) ? c.password : '••••••••'}</span>
                                <button onClick={() => togglePw(c.id)} title={shownPw.has(c.id) ? '隱藏密碼' : '顯示密碼'} className="text-slate-400 hover:text-slate-100 cursor-pointer ml-1">
                                  {shownPw.has(c.id) ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                                </button>
                                <button onClick={() => copyText(c.id, '社密碼', c.password)} title="複製密碼" className="text-slate-400 hover:text-slate-100 cursor-pointer">
                                  {copiedId === c.id ? <Check className="w-3.5 h-3.5 text-emerald-300" /> : <Copy className="w-3.5 h-3.5" />}
                                </button>
                              </span>
                            ) : (
                              <span className="text-xs text-slate-500" title="此社在密碼紀錄功能啟用前就設定了密碼；按「重設密碼」設定一次後即可顯示">密碼未記錄</span>
                            )}
                          </div>
                        ) : (
                          <button
                            onClick={() => copyCode(c)}
                            title="點一下複製啟用碼"
                            className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs font-mono tracking-wider cursor-pointer hover:bg-amber-500/20"
                          >
                            <Ticket className="w-3.5 h-3.5" />
                            {c.activation_code || '—'}
                            {copiedId === c.id ? <Check className="w-3.5 h-3.5 text-emerald-300" /> : <Copy className="w-3.5 h-3.5 text-amber-300/70" />}
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right">{c.document_count}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center justify-end gap-1.5">
                          {c.activated ? (
                            <button
                              onClick={() => openDialog({ kind: 'reset', club: c })}
                              title="重設社密碼"
                              className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs flex items-center gap-1 cursor-pointer"
                            >
                              <KeyRound className="w-3.5 h-3.5" /><span className="hidden sm:inline">重設密碼</span>
                            </button>
                          ) : (
                            <button
                              onClick={() => openDialog({ kind: 'regen', club: c })}
                              title="重新產生啟用碼"
                              className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs flex items-center gap-1 cursor-pointer"
                            >
                              <RefreshCw className="w-3.5 h-3.5" /><span className="hidden sm:inline">新啟用碼</span>
                            </button>
                          )}
                          <button
                            onClick={() => openDialog({ kind: 'delete', club: c })}
                            title="刪除社"
                            className="px-2.5 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-300 text-xs flex items-center gap-1 cursor-pointer"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {visible.length === 0 && (
                    <tr><td colSpan={5} className="px-4 py-6 text-center text-slate-500 text-xs">沒有符合的社</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* 自訂對話框（不使用 window.confirm） */}
      {dialog && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center px-4" onClick={() => !busy && setDialog(null)}>
          <div className="w-full max-w-md p-5 rounded-2xl bg-slate-900 border border-slate-700 space-y-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">
                {dialog.kind === 'create' && '新增社'}
                {dialog.kind === 'reset' && `重設「${dialog.club.name}」的社密碼`}
                {dialog.kind === 'regen' && `重新產生「${dialog.club.name}」的啟用碼？`}
                {dialog.kind === 'delete' && `刪除「${dialog.club.name}」？`}
              </h2>
              <button onClick={() => setDialog(null)} className="text-slate-400 hover:text-slate-200 cursor-pointer"><X className="w-4 h-4" /></button>
            </div>

            {dialog.kind === 'create' && (
              <div className="space-y-3">
                <input className={inputCls} placeholder="社名（必填）" value={fName} onChange={(e) => setFName(e.target.value)} />
                <div className="grid grid-cols-2 gap-3">
                  <input className={inputCls} placeholder="分區（例如 4）" value={fDivision} onChange={(e) => setFDivision(e.target.value)} />
                  <input className={inputCls} placeholder="編號（例如 04-8）" value={fCode} onChange={(e) => setFCode(e.target.value)} />
                </div>
                <p className="text-xs text-slate-400">建立後系統會自動產生啟用碼，請交給該社執秘做首次設定。</p>
              </div>
            )}
            {dialog.kind === 'reset' && (
              <div className="space-y-2">
                <input className={inputCls} type="password" placeholder="新的社密碼（至少 6 個字元）" value={fPassword} onChange={(e) => setFPassword(e.target.value)} autoComplete="new-password" />
                <p className="text-xs text-slate-400">重設後舊密碼立即失效，請把新密碼交給該社執秘。</p>
              </div>
            )}
            {dialog.kind === 'regen' && (
              <p className="text-sm text-slate-300 leading-relaxed">舊的啟用碼會立即作廢，請改交新的啟用碼給該社。</p>
            )}
            {dialog.kind === 'delete' && (
              <p className="text-sm text-slate-300 leading-relaxed">
                目前有 <strong>{dialog.club.document_count}</strong> 份社內文件。社內仍有文件時系統會拒絕刪除；
                刪社會一併刪除該社的共用登入帳號。此動作無法復原。
              </p>
            )}

            {error && (
              <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-start gap-2">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" /><span>{error}</span>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button onClick={() => setDialog(null)} disabled={busy} className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs cursor-pointer">取消</button>
              <button
                onClick={submitDialog}
                disabled={busy}
                className={`px-3.5 py-2 rounded-xl text-white text-xs font-medium flex items-center gap-1.5 cursor-pointer disabled:opacity-60 ${
                  dialog.kind === 'delete' ? 'bg-red-600 hover:bg-red-500' : 'bg-indigo-600 hover:bg-indigo-500'
                }`}
              >
                {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                <span>{dialog.kind === 'delete' ? '確認刪除' : '確認'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
