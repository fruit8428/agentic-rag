import React, { useEffect, useState } from 'react'
import {
  Building2, Users, Plus, Trash2, KeyRound, Loader2, AlertCircle, CheckCircle2, RefreshCw, ShieldCheck, X,
} from 'lucide-react'
import { apiFetch } from '../lib/api'

interface AdminClub {
  id: string
  name: string
  division: string | null
  code: string | null
  has_password: boolean
  member_count: number
  document_count: number
}

interface AdminMember {
  user_id: string
  email: string
  role: 'member' | 'admin'
  club_id: string | null
  club_name: string | null
  joined_at: string | null
}

interface AdminViewProps {
  accessToken: string
  myUserId: string
}

type Dialog =
  | { kind: 'create' }
  | { kind: 'reset'; club: AdminClub }
  | { kind: 'delete'; club: AdminClub }
  | { kind: 'assign'; member: AdminMember }
  | null

// 地區管理員：社的新增／刪除／重設密碼，以及社友指派
export function AdminView({ accessToken, myUserId }: AdminViewProps) {
  const [tab, setTab] = useState<'clubs' | 'members'>('clubs')
  const [clubs, setClubs] = useState<AdminClub[]>([])
  const [members, setMembers] = useState<AdminMember[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [busy, setBusy] = useState(false)

  // 表單欄位
  const [fName, setFName] = useState('')
  const [fDivision, setFDivision] = useState('')
  const [fCode, setFCode] = useState('')
  const [fPassword, setFPassword] = useState('')
  const [fClubId, setFClubId] = useState('')

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [c, m] = await Promise.all([
        apiFetch<AdminClub[]>('/api/admin/clubs', accessToken),
        apiFetch<AdminMember[]>('/api/admin/members', accessToken),
      ])
      setClubs(c)
      setMembers(m)
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
    setFClubId(d?.kind === 'assign' ? d.member.club_id || '' : '')
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

  const submitDialog = () => {
    if (!dialog) return
    if (dialog.kind === 'create') {
      return run(async () => {
        await apiFetch('/api/admin/clubs', accessToken, {
          method: 'POST',
          body: JSON.stringify({ name: fName, password: fPassword, division: fDivision || null, code: fCode || null }),
        })
        return `已新增「${fName}」`
      })
    }
    if (dialog.kind === 'reset') {
      return run(async () => {
        await apiFetch(`/api/admin/clubs/${dialog.club.id}/reset-password`, accessToken, {
          method: 'POST',
          body: JSON.stringify({ new_password: fPassword }),
        })
        return `「${dialog.club.name}」的社內密碼已重設`
      })
    }
    if (dialog.kind === 'delete') {
      return run(async () => {
        await apiFetch(`/api/admin/clubs/${dialog.club.id}`, accessToken, { method: 'DELETE' })
        return `已刪除「${dialog.club.name}」`
      })
    }
    if (dialog.kind === 'assign') {
      return run(async () => {
        await apiFetch(`/api/admin/members/${dialog.member.user_id}`, accessToken, {
          method: 'PATCH',
          body: JSON.stringify({ club_id: fClubId || null }),
        })
        return `已更新 ${dialog.member.email} 的社別`
      })
    }
  }

  const inputCls =
    'w-full px-3 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm focus:outline-none focus:border-indigo-500'

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
            <p className="text-sm text-slate-400 mt-1">管理 3523 地區各社清單、社內密碼，以及社友所屬社別。</p>
          </div>
          <button
            onClick={load}
            className="self-start sm:self-auto px-3.5 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 text-xs font-medium flex items-center gap-2 transition cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" /><span>重新整理</span>
          </button>
        </div>

        <nav className="inline-flex items-center gap-1 bg-slate-900 p-1 rounded-xl border border-slate-800">
          {([['clubs', '社管理', Building2], ['members', '社友管理', Users]] as const).map(([key, label, Icon]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition cursor-pointer ${
                tab === key ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Icon className="w-3.5 h-3.5" /><span>{label}</span>
            </button>
          ))}
        </nav>

        {notice && (
          <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm flex items-center justify-between gap-3">
            <span className="flex items-center gap-2"><CheckCircle2 className="w-4 h-4" />{notice}</span>
            <button onClick={() => setNotice(null)} className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer">關閉</button>
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
        ) : tab === 'clubs' ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm text-slate-300">共 {clubs.length} 個社</p>
              <button
                onClick={() => openDialog({ kind: 'create' })}
                className="px-3.5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium flex items-center gap-1.5 transition cursor-pointer"
              >
                <Plus className="w-3.5 h-3.5" /> 新增社
              </button>
            </div>
            <div className="rounded-2xl border border-slate-800 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-900 text-slate-400 text-xs">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium">編號</th>
                    <th className="text-left px-4 py-2.5 font-medium">社名</th>
                    <th className="text-right px-4 py-2.5 font-medium hidden sm:table-cell">社友</th>
                    <th className="text-right px-4 py-2.5 font-medium hidden sm:table-cell">文件</th>
                    <th className="text-left px-4 py-2.5 font-medium">密碼</th>
                    <th className="px-4 py-2.5"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 bg-slate-950">
                  {clubs.map((c) => (
                    <tr key={c.id} className="text-slate-200">
                      <td className="px-4 py-2.5 text-slate-400 whitespace-nowrap">{c.code || '—'}</td>
                      <td className="px-4 py-2.5 font-medium">{c.name}</td>
                      <td className="px-4 py-2.5 text-right hidden sm:table-cell">{c.member_count}</td>
                      <td className="px-4 py-2.5 text-right hidden sm:table-cell">{c.document_count}</td>
                      <td className="px-4 py-2.5">
                        {c.has_password ? (
                          <span className="text-emerald-300 text-xs">已設定</span>
                        ) : (
                          <span className="text-amber-300 text-xs">未設定</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => openDialog({ kind: 'reset', club: c })}
                            title={c.has_password ? '重設社內密碼' : '設定社內密碼'}
                            className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs flex items-center gap-1 cursor-pointer"
                          >
                            <KeyRound className="w-3.5 h-3.5" /><span className="hidden sm:inline">{c.has_password ? '重設密碼' : '設定密碼'}</span>
                          </button>
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
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-slate-300">共 {members.length} 位使用者</p>
            <div className="rounded-2xl border border-slate-800 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-900 text-slate-400 text-xs">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium">Email</th>
                    <th className="text-left px-4 py-2.5 font-medium">所屬社</th>
                    <th className="text-left px-4 py-2.5 font-medium hidden sm:table-cell">角色</th>
                    <th className="px-4 py-2.5"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 bg-slate-950">
                  {members.map((m) => (
                    <tr key={m.user_id} className="text-slate-200">
                      <td className="px-4 py-2.5 break-all">{m.email}</td>
                      <td className="px-4 py-2.5">{m.club_name || <span className="text-amber-300 text-xs">尚未加入</span>}</td>
                      <td className="px-4 py-2.5 hidden sm:table-cell">
                        {m.role === 'admin' ? <span className="text-amber-300 text-xs">管理員</span> : <span className="text-slate-400 text-xs">社友</span>}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <button
                          onClick={() => openDialog({ kind: 'assign', member: m })}
                          className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs cursor-pointer"
                        >
                          指派社別
                        </button>
                      </td>
                    </tr>
                  ))}
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
                {dialog.kind === 'reset' && `${dialog.club.has_password ? '重設' : '設定'}「${dialog.club.name}」的社內密碼`}
                {dialog.kind === 'delete' && `刪除「${dialog.club.name}」？`}
                {dialog.kind === 'assign' && `指派 ${dialog.member.email} 的社別`}
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
                <input className={inputCls} type="password" placeholder="初始社內密碼（至少 6 個字元）" value={fPassword} onChange={(e) => setFPassword(e.target.value)} autoComplete="new-password" />
              </div>
            )}
            {dialog.kind === 'reset' && (
              <input className={inputCls} type="password" placeholder="新的社內密碼（至少 6 個字元）" value={fPassword} onChange={(e) => setFPassword(e.target.value)} autoComplete="new-password" />
            )}
            {dialog.kind === 'delete' && (
              <p className="text-sm text-slate-300 leading-relaxed">
                目前有 <strong>{dialog.club.member_count}</strong> 位社友、<strong>{dialog.club.document_count}</strong> 份文件。
                社內仍有社友或文件時系統會拒絕刪除。此動作無法復原。
              </p>
            )}
            {dialog.kind === 'assign' && (
              <select className={inputCls} value={fClubId} onChange={(e) => setFClubId(e.target.value)}>
                <option value="">（移出所有社）</option>
                {clubs.map((c) => (
                  <option key={c.id} value={c.id}>{c.code ? `${c.code} ` : ''}{c.name}</option>
                ))}
              </select>
            )}
            {dialog.kind === 'assign' && dialog.member.user_id === myUserId && (
              <p className="text-xs text-amber-300">您正在變更自己的社別。</p>
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
