import { useEffect, useState } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from './lib/supabase'
import { apiFetch, type MyClub } from './lib/api'
import { AuthPage } from './components/AuthPage'
import { ChatView } from './components/ChatView'
import { IngestView } from './components/IngestView'
import { JoinClubPage } from './components/JoinClubPage'
import { ClubSettingsView } from './components/ClubSettingsView'
import { AdminView } from './components/AdminView'
import {
  Sparkles, MessageSquare, FileText, LogOut, Loader2, Building2, Settings, ShieldCheck, AlertTriangle,
} from 'lucide-react'

type Tab = 'chat' | 'ingest' | 'club' | 'admin'

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [initializing, setInitializing] = useState(true)
  const [me, setMe] = useState<MyClub | null>(null)
  const [meError, setMeError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>('chat')

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session)
      setInitializing(false)
    })
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session)
      if (!session) setMe(null)
    })
    return () => subscription.unsubscribe()
  }, [])

  // 登入後讀取「我是誰、屬於哪個社、是否為管理員」
  useEffect(() => {
    if (!session) return
    let cancelled = false
    setMe(null)
    setMeError(null)
    apiFetch<MyClub>('/api/clubs/me', session.access_token)
      .then((data) => {
        if (!cancelled) setMe(data)
      })
      .catch((e) => {
        if (!cancelled) setMeError(e.message)
      })
    return () => {
      cancelled = true
    }
  }, [session?.access_token, session?.user.id])

  if (initializing) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />
        <span>系統啟動中...</span>
      </div>
    )
  }

  if (!session) {
    return <AuthPage />
  }

  if (meError) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
        <div className="max-w-md p-5 rounded-2xl bg-slate-900 border border-amber-500/30 text-amber-200 text-sm space-y-3">
          <div className="flex items-center gap-2 font-semibold"><AlertTriangle className="w-4 h-4" /> 無法讀取社友資料</div>
          <p className="text-slate-300 leading-relaxed">{meError}</p>
          <button onClick={() => supabase.auth.signOut()} className="text-xs text-slate-400 hover:text-slate-200 cursor-pointer">登出</button>
        </div>
      </div>
    )
  }

  if (!me) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />
        <span>讀取社友資料中...</span>
      </div>
    )
  }

  const isAdmin = me.role === 'admin'

  // 尚未加入任何社（管理員例外）：只顯示加入社頁
  if (!me.club_id && !isAdmin) {
    return <JoinClubPage accessToken={session.access_token} email={me.email} onJoined={setMe} />
  }

  const tabs: { key: Tab; label: string; Icon: typeof MessageSquare; show: boolean }[] = [
    { key: 'chat', label: 'AI 聊天', Icon: MessageSquare, show: true },
    { key: 'ingest', label: '文件導入', Icon: FileText, show: true },
    { key: 'club', label: '社設定', Icon: Settings, show: true },
    { key: 'admin', label: '管理', Icon: ShieldCheck, show: isAdmin },
  ]

  return (
    <div className="h-screen flex flex-col bg-slate-950 text-slate-100">
      {/* 頂部導覽列 */}
      <header className="min-h-14 border-b border-slate-800 bg-slate-900/80 px-4 sm:px-6 py-2 flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex flex-wrap items-center gap-3 sm:gap-6">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
              <Sparkles className="w-4 h-4" />
            </div>
            <span className="font-bold text-white tracking-tight">3523 地區知識庫</span>
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 inline-flex items-center gap-1">
              <Building2 className="w-3 h-3" />
              {me.club_name || (isAdmin ? '地區管理員' : '未加入')}
            </span>
          </div>

          <nav className="flex items-center gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800">
            {tabs.filter((t) => t.show).map(({ key, label, Icon }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition cursor-pointer ${
                  activeTab === key ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{label}</span>
              </button>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-400 hidden sm:inline">{me.email}</span>
          <button
            onClick={() => supabase.auth.signOut()}
            className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium flex items-center gap-1.5 transition cursor-pointer"
          >
            <LogOut className="w-3.5 h-3.5" />
            <span>登出</span>
          </button>
        </div>
      </header>

      {/* 主內容視圖 */}
      {activeTab === 'chat' && <ChatView accessToken={session.access_token} />}
      {activeTab === 'ingest' && (
        <IngestView
          accessToken={session.access_token}
          userId={session.user.id}
          clubName={me.club_name}
          isAdmin={isAdmin}
        />
      )}
      {activeTab === 'club' && <ClubSettingsView accessToken={session.access_token} me={me} />}
      {activeTab === 'admin' && isAdmin && <AdminView accessToken={session.access_token} myUserId={me.user_id} />}
    </div>
  )
}
