import { createClient } from '@supabase/supabase-js'

// 只從環境變數讀取，不在程式碼內寫死任何金鑰。
// 本機：專案根目錄 .env 的 VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY
// Vercel：Project Settings → Environment Variables（建置時由 Vite 注入）
const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL || '').trim()
const supabaseAnonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY || '').trim()

const looksLikeJwt = supabaseAnonKey.split('.').length === 3 && supabaseAnonKey.length > 100

if (!supabaseUrl.startsWith('https://') || !looksLikeJwt) {
  // 在畫面上顯示清楚的錯誤，而不是讓使用者看到一片空白或「Invalid API key」
  document.body.innerHTML =
    '<div style="font-family:sans-serif;padding:2rem;max-width:40rem;margin:auto;line-height:1.6">' +
    '<h2>系統設定不完整</h2>' +
    '<p>前端缺少 Supabase 連線設定（VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY），或金鑰格式不正確。</p>' +
    '<p>請管理員檢查 Vercel 專案的環境變數後重新部署。</p></div>'
  throw new Error('缺少或無效的 VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY')
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
