import React, { useState } from 'react'
import { Building2, KeyRound, Loader2, CheckCircle2, AlertCircle, ShieldCheck } from 'lucide-react'
import { apiFetch, publicFetch, type MyClub, type SessionResponse } from '../lib/api'
import { supabase } from '../lib/supabase'

interface ClubSettingsViewProps {
  accessToken: string
  me: MyClub
  onChanged?: () => void
}

// 社設定：顯示所屬社，並以目前密碼更換新的社密碼（管理員則是更換管理員密碼）
export function ClubSettingsView({ accessToken, me, onChanged }: ClubSettingsViewProps) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const isAdminOnly = me.role === 'admin' && !me.club_id

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    if (next.length < 6) return setError('新密碼至少需要 6 個字元')
    if (next !== confirm) return setError('兩次輸入的新密碼不一致')
    setLoading(true)
    try {
      const res = await apiFetch<{ message: string }>('/api/clubs/me/password', accessToken, {
        method: 'POST',
        body: JSON.stringify({ current_password: current, new_password: next }),
      })
      // Supabase 在改密碼後會讓原本的登入狀態失效，這裡用新密碼自動重新登入，使用者不會被登出
      const body = me.club_id && me.role !== 'admin' ? { club_id: me.club_id, password: next } : { as_admin: true, password: next }
      const s = await publicFetch<SessionResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify(body) })
      await supabase.auth.setSession({ access_token: s.access_token, refresh_token: s.refresh_token })
      setSuccess(res.message || '密碼已更新')
      onChanged?.()
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 p-6 sm:p-10">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">社設定</h1>
          <p className="text-sm text-slate-400 mt-1">{isAdminOnly ? '更換地區管理員的登入密碼。' : '管理貴社的登入密碼。全社共用這組密碼，知道密碼的人即可登入並查閱貴社社內資料，請妥善保管。'}</p>
        </div>

        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
            <Building2 className="w-5 h-5" />
          </div>
          <div>
            <p className="text-xs text-slate-400">您所屬的社</p>
            <p className="text-base font-semibold text-white">{me.club_name || (isAdminOnly ? '地區辦公室（管理員帳號）' : '（尚未綁定）')}</p>
          </div>
          {me.role === 'admin' && (
            <span className="ml-auto px-2.5 py-1 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs font-medium inline-flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5" /> 地區管理員
            </span>
          )}
        </div>

        {(me.club_id || isAdminOnly) ? (
          <form onSubmit={handleSubmit} className="p-5 rounded-2xl bg-slate-900 border border-slate-800 space-y-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <KeyRound className="w-4 h-4 text-indigo-400" />
              <span>{isAdminOnly ? '變更管理員密碼' : '變更社密碼'}</span>
            </div>
            {[
              ['目前的密碼', current, setCurrent],
              ['新的密碼（至少 6 個字元）', next, setNext],
              ['再輸入一次新密碼', confirm, setConfirm],
            ].map(([label, value, setter], i) => (
              <label key={i} className="block space-y-1.5">
                <span className="text-xs font-medium text-slate-300">{label as string}</span>
                <input
                  type="password"
                  value={value as string}
                  onChange={(e) => (setter as (v: string) => void)(e.target.value)}
                  autoComplete="new-password"
                  className="w-full px-3 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm focus:outline-none focus:border-indigo-500"
                />
              </label>
            ))}
            {error && (
              <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-start gap-2">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" /><span>{error}</span>
              </div>
            )}
            {success && (
              <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" /><span>{success}</span>
              </div>
            )}
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white text-sm font-medium flex items-center gap-2 transition cursor-pointer"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              <span>更新密碼</span>
            </button>
          </form>
        ) : (
          <p className="text-sm text-slate-400">此帳號尚未綁定任何社，請聯絡地區管理員。</p>
        )}
      </div>
    </div>
  )
}
