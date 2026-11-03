import React, { useEffect, useState } from 'react'
import { Building2, KeyRound, Loader2, AlertCircle, ArrowRight, LogOut } from 'lucide-react'
import { apiFetch, type ClubPublic, type MyClub } from '../lib/api'
import { supabase } from '../lib/supabase'

interface JoinClubPageProps {
  accessToken: string
  email: string
  onJoined: (me: MyClub) => void
}

// 登入後尚未加入任何社：必須輸入社內密碼才能進入系統
export function JoinClubPage({ accessToken, email, onJoined }: JoinClubPageProps) {
  const [clubs, setClubs] = useState<ClubPublic[]>([])
  const [clubId, setClubId] = useState('')
  const [password, setPassword] = useState('')
  const [loadingClubs, setLoadingClubs] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiFetch<ClubPublic[]>('/api/clubs', accessToken)
      .then(setClubs)
      .catch((e) => setError(e.message))
      .finally(() => setLoadingClubs(false))
  }, [accessToken])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!clubId) {
      setError('請先選擇您所屬的社')
      return
    }
    setSubmitting(true)
    try {
      const me = await apiFetch<MyClub>('/api/clubs/join', accessToken, {
        method: 'POST',
        body: JSON.stringify({ club_id: clubId, password }),
      })
      onJoined(me)
    } catch (err: any) {
      setError(err.message || '加入失敗，請稍後再試')
    } finally {
      setSubmitting(false)
    }
  }

  // 依分區分組顯示
  const grouped = clubs.reduce<Record<string, ClubPublic[]>>((acc, c) => {
    const key = c.division ? `第 ${c.division} 分區` : '其他'
    ;(acc[key] ||= []).push(c)
    return acc
  }, {})

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400 mb-4">
            <Building2 className="w-7 h-7" />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">加入所屬扶輪社</h1>
          <p className="text-sm text-slate-400 mt-2 leading-relaxed">
            請選擇您所屬的社並輸入<strong className="text-slate-200">社內密碼</strong>。
            加入後即可查閱 3523 地區公開資料與貴社社內資料。
          </p>
          <p className="text-xs text-slate-500 mt-1">目前登入：{email}</p>
        </div>

        <form onSubmit={handleSubmit} className="p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-4">
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-slate-300">所屬社</span>
            <div className="relative">
              <Building2 className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <select
                value={clubId}
                onChange={(e) => setClubId(e.target.value)}
                disabled={loadingClubs}
                className="w-full pl-9 pr-3 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm focus:outline-none focus:border-indigo-500 appearance-none"
              >
                <option value="">{loadingClubs ? '載入社名清單中…' : '請選擇您的社'}</option>
                {Object.entries(grouped).map(([division, list]) => (
                  <optgroup key={division} label={division}>
                    {list.map((c) => (
                      <option key={c.id} value={c.id} disabled={!c.joinable}>
                        {c.code ? `${c.code} ` : ''}{c.name}{c.joinable ? '' : '（尚未設定密碼）'}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-slate-300">社內密碼</span>
            <div className="relative">
              <KeyRound className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="請向貴社執秘索取"
                autoComplete="off"
                className="w-full pl-9 pr-3 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-sm placeholder:text-slate-600 focus:outline-none focus:border-indigo-500"
              />
            </div>
          </label>

          {error && (
            <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || loadingClubs}
            className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white text-sm font-medium flex items-center justify-center gap-2 transition cursor-pointer"
          >
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
            <span>{submitting ? '驗證中…' : '加入並進入系統'}</span>
          </button>
        </form>

        <button
          onClick={() => supabase.auth.signOut()}
          className="mt-4 w-full py-2 text-xs text-slate-500 hover:text-slate-300 flex items-center justify-center gap-1.5 cursor-pointer"
        >
          <LogOut className="w-3.5 h-3.5" />
          <span>登出，改用其他帳號</span>
        </button>
      </div>
    </div>
  )
}
