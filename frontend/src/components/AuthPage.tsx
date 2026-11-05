import React, { useEffect, useMemo, useState } from 'react'
import { supabase } from '../lib/supabase'
import { publicFetch, type ClubPublic, type SessionResponse } from '../lib/api'
import {
  Sparkles, Lock, ArrowRight, Loader2, CheckCircle2, AlertCircle, Building2, KeyRound, ShieldCheck, Mail, X,
} from 'lucide-react'

const ADMIN_VALUE = '__admin__'
const REMEMBER_KEY = 'rag.rememberedClub'

type Mode = 'login' | 'register'

function readRemembered(): string {
  try {
    return localStorage.getItem(REMEMBER_KEY) || ''
  } catch {
    return ''
  }
}

function writeRemembered(value: string | null) {
  try {
    if (value) localStorage.setItem(REMEMBER_KEY, value)
    else localStorage.removeItem(REMEMBER_KEY)
  } catch {
    /* 私密視窗等情況無法寫入，忽略 */
  }
}

// 登入頁：社名登入（整個社共用一組密碼）／首次進入(註冊)（用管理員發的啟用碼設定社密碼）
export function AuthPage() {
  const [mode, setMode] = useState<Mode>('login')
  const [clubs, setClubs] = useState<ClubPublic[]>([])
  const [clubsLoading, setClubsLoading] = useState(true)
  const [clubsError, setClubsError] = useState<string | null>(null)
  const [adminContact, setAdminContact] = useState<string | null>(null)

  const remembered = useMemo(readRemembered, [])
  const [selected, setSelected] = useState<string>(remembered)
  const [remember, setRemember] = useState<boolean>(!!remembered)
  const [password, setPassword] = useState('')
  const [activationCode, setActivationCode] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showContact, setShowContact] = useState(false)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  // 從報名系統「AI 小幫手」按鈕帶入的社名（網址 ?club=社名），載入清單後自動選好
  const [prefilledClub, setPrefilledClub] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    publicFetch<ClubPublic[]>('/api/auth/clubs')
      .then((list) => {
        if (cancelled) return
        setClubs(list)
        try {
          const wanted = (new URLSearchParams(window.location.search).get('club') || '').trim()
          if (wanted) {
            const hit = list.find((c) => c.name.trim() === wanted)
            if (hit) {
              setSelected(hit.id)
              setRemember(true)
              setPrefilledClub(hit.name)
            }
          }
        } catch {
          /* 網址參數解析失敗就當沒帶 */
        }
      })
      .catch((e) => {
        if (!cancelled) setClubsError(e.message || '無法載入社名清單')
      })
      .finally(() => {
        if (!cancelled) setClubsLoading(false)
      })
    publicFetch<{ admin_contact: string | null }>('/api/auth/config')
      .then((c) => {
        if (!cancelled) setAdminContact(c.admin_contact)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  // 依分區分組（地區辦公室等沒有分區的放最後）
  const groups = useMemo(() => {
    const map = new Map<string, ClubPublic[]>()
    for (const c of clubs) {
      const key = c.division ? `第 ${c.division} 分區` : '其他'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(c)
    }
    return Array.from(map.entries())
  }, [clubs])

  const switchMode = (m: Mode) => {
    setMode(m)
    setError(null)
    setSuccessMsg(null)
    setPassword('')
    setConfirm('')
    setActivationCode('')
    if (m === 'register' && selected === ADMIN_VALUE) setSelected('')
  }

  const applySession = async (s: SessionResponse) => {
    const { error: sessionError } = await supabase.auth.setSession({
      access_token: s.access_token,
      refresh_token: s.refresh_token,
    })
    if (sessionError) throw new Error(sessionError.message)
  }

  const handleLogin = async () => {
    if (!selected) throw new Error('請先選擇所屬社名')
    const body =
      selected === ADMIN_VALUE ? { as_admin: true, password } : { club_id: selected, password }
    const s = await publicFetch<SessionResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    writeRemembered(remember ? selected : null)
    await applySession(s)
  }

  const handleRegister = async () => {
    if (!selected || selected === ADMIN_VALUE) throw new Error('請先選擇所屬社名')
    if (!activationCode.trim()) throw new Error('請輸入地區管理員提供的啟用碼')
    if (password.length < 6) throw new Error('社密碼至少需要 6 個字元')
    if (password !== confirm) throw new Error('兩次輸入的社密碼不一致')
    const s = await publicFetch<SessionResponse>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ club_id: selected, activation_code: activationCode.trim(), password }),
    })
    setSuccessMsg(`「${s.club_name}」首次設定完成，正在為您登入…`)
    writeRemembered(remember ? selected : null)
    await applySession(s)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMsg(null)
    setLoading(true)
    try {
      if (mode === 'login') await handleLogin()
      else await handleRegister()
    } catch (err: any) {
      setError(err.message || '發生未知錯誤')
    } finally {
      setLoading(false)
    }
  }

  const isAdminSelected = selected === ADMIN_VALUE
  // 還有社需要用啟用碼做首次設定時才顯示註冊分頁
  const showRegister = clubsLoading || clubs.some((c) => !c.activated)
  const selectCls =
    'w-full px-4 py-3 bg-slate-100 border border-slate-300 rounded-xl text-base text-slate-900 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 transition appearance-none'
  const inputCls =
    'w-full pl-11 pr-4 py-3 bg-slate-100 border border-slate-300 rounded-xl text-base text-slate-900 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 transition'
  const labelCls = 'block text-base font-medium text-slate-300 mb-2'

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4 py-8">
      <div className="w-full max-w-md bg-slate-900/90 border border-slate-800 rounded-3xl shadow-2xl p-6 sm:p-8 backdrop-blur">
        {/* 標題區 */}
        <div className="flex flex-col items-center text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400 mb-4">
            <Sparkles className="w-7 h-7" />
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">Agentic RAG AI 系統</h1>
        </div>

        {/* 切換「社名登入 / 首次進入(註冊)」：所有社都已啟用時只剩登入 */}
        <div className={`grid ${showRegister ? 'grid-cols-2' : 'grid-cols-1'} gap-1 p-1 bg-slate-950 rounded-2xl border border-slate-800 mb-6`}>
          {(
            [
              ['login', '社名登入'],
              ['register', '首次進入(註冊)'],
            ] as const
          ).filter(([key]) => key === 'login' || showRegister).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => switchMode(key)}
              className={`py-3 text-base font-semibold rounded-xl transition cursor-pointer ${
                mode === key ? 'bg-indigo-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {error && (
          <div className="mb-5 p-3.5 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-sm flex items-start gap-2.5">
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
        {successMsg && (
          <div className="mb-5 p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm flex items-start gap-2.5">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
            <span>{successMsg}</span>
          </div>
        )}
        {clubsError && (
          <div className="mb-5 p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-sm flex items-start gap-2.5">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>無法載入社名清單：{clubsError}。請重新整理頁面，若持續發生請聯絡地區管理員。</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* 所屬社名 */}
          <div>
            <label className={labelCls}>
              所屬社名
              {prefilledClub && mode === 'login' && (
                <span className="ml-2 text-[11px] font-normal text-emerald-400">已從報名系統帶入「{prefilledClub}」，輸入社密碼即可</span>
              )}
            </label>
            <div className="relative">
              <select
                required
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
                disabled={clubsLoading}
                className={selectCls}
              >
                <option value="">{clubsLoading ? '載入社名中…' : '請選擇所屬社名'}</option>
                {mode === 'login' && <option value={ADMIN_VALUE}>🛡 地區管理員</option>}
                {groups.map(([group, list]) => (
                  <optgroup key={group} label={group}>
                    {list.map((c) => {
                      const needsSetup = !c.activated
                      const disabled = mode === 'register' ? c.activated : false
                      const suffix =
                        mode === 'register' && c.activated ? '（已完成設定）' : mode === 'login' && needsSetup ? '（尚未設定）' : ''
                      return (
                        <option key={c.id} value={c.id} disabled={disabled}>
                          {c.code ? `${c.code} ` : ''}{c.name}{suffix}
                        </option>
                      )
                    })}
                  </optgroup>
                ))}
              </select>
              <Building2 className="w-4 h-4 text-slate-500 absolute right-4 top-4 pointer-events-none" />
            </div>
          </div>

          {/* 首次進入：啟用碼 */}
          {mode === 'register' && (
            <div>
              <label className={labelCls}>啟用碼</label>
              <div className="relative">
                <KeyRound className="w-4 h-4 text-slate-500 absolute left-4 top-4" />
                <input
                  type="text"
                  required
                  value={activationCode}
                  onChange={(e) => setActivationCode(e.target.value.toUpperCase())}
                  placeholder="例如 AB3K-9XQ2（由地區管理員提供）"
                  autoComplete="one-time-code"
                  className={`${inputCls} tracking-widest uppercase`}
                />
              </div>
              <p className="text-xs text-slate-500 mt-1.5">每個社只能用啟用碼設定一次，之後請用「社名登入」。</p>
            </div>
          )}

          {/* 密碼 */}
          <div>
            <label className={labelCls}>{mode === 'login' ? '登入密碼' : '設定社密碼（至少 6 個字元）'}</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-500 absolute left-4 top-4" />
              <input
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={
                  mode === 'login'
                    ? isAdminSelected
                      ? '請輸入管理員密碼'
                      : '請輸入社密碼(管理員請輸入管理員密碼)'
                    : '全社共用這組密碼，請妥善保管'
                }
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                className={inputCls}
              />
            </div>
          </div>

          {mode === 'register' && (
            <div>
              <label className={labelCls}>再輸入一次社密碼</label>
              <div className="relative">
                <Lock className="w-4 h-4 text-slate-500 absolute left-4 top-4" />
                <input
                  type="password"
                  required
                  minLength={6}
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder="請再輸入一次"
                  autoComplete="new-password"
                  className={inputCls}
                />
              </div>
            </div>
          )}

          {/* 記住社名 / 忘記密碼 */}
          <div className="flex items-center justify-between gap-3 text-sm">
            <label className="inline-flex items-center gap-2 text-slate-300 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="w-4 h-4 rounded accent-indigo-600"
              />
              <span>記住社名</span>
            </label>
            {mode === 'login' && (
              <div className="inline-flex items-center gap-2 text-slate-400">
                <span>忘記密碼？</span>
                <button
                  type="button"
                  onClick={() => setShowContact((v) => !v)}
                  className="px-2.5 py-1 rounded-md bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-xs font-medium hover:bg-indigo-500/25 transition cursor-pointer"
                >
                  聯絡管理員
                </button>
              </div>
            )}
          </div>

          {showContact && mode === 'login' && (
            <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 text-sm text-slate-300 flex items-start gap-3">
              <ShieldCheck className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
              <div className="flex-1 space-y-1">
                <p>社密碼由地區管理員重設。請聯絡地區管理員，告知貴社社名即可。</p>
                {adminContact && (
                  <a
                    href={`mailto:${adminContact}?subject=${encodeURIComponent('3523 地區知識庫：申請重設社密碼')}`}
                    className="inline-flex items-center gap-1.5 text-indigo-300 hover:text-indigo-200 underline underline-offset-2"
                  >
                    <Mail className="w-3.5 h-3.5" /> {adminContact}
                  </a>
                )}
              </div>
              <button type="button" onClick={() => setShowContact(false)} className="text-slate-500 hover:text-slate-300 cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          <button
            type="submit"
            disabled={loading || clubsLoading}
            className="w-full py-3.5 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-lg font-semibold rounded-2xl shadow-lg shadow-indigo-600/25 flex items-center justify-center gap-2 transition cursor-pointer"
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>處理中...</span>
              </>
            ) : (
              <>
                <span>{mode === 'login' ? '立即登入' : '完成設定並進入'}</span>
                <ArrowRight className="w-5 h-5" />
              </>
            )}
          </button>
        </form>

        {mode === 'register' ? (
          <p className="mt-5 text-xs text-slate-500 leading-relaxed text-center">
            還沒拿到啟用碼？請向地區管理員索取。已設定過的社請切換到「社名登入」。
          </p>
        ) : (
          <p className="mt-5 text-xs text-slate-500 leading-relaxed text-center">
            首次登入請使用地區統一提供的預設密碼，登入後到「社設定」更改成貴社自己的密碼。
          </p>
        )}
      </div>
    </div>
  )
}
