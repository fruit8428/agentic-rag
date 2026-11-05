#!/bin/bash
# 把專案根目錄 .env 的環境變數「完整」寫入 Vercel 的 Production 與 Preview 環境。
# 用途：避免在 Vercel 網頁上手動複製貼上造成金鑰被截斷。
# 用法：在專案根目錄執行  bash scripts/sync_vercel_env.sh（或在 Finder 點兩下「同步環境變數到Vercel.command」）
# 寫完環境變數後，正在跑的部署不會自動更新，要重新部署一次（push 新 commit 或在 Vercel 按 Redeploy）才生效。
set -e
cd "$(dirname "$0")/.."

VARS="DISTRICT_CODE DISTRICT_NAME ADMIN_EMAIL ADMIN_CONTACT CLUB_DEFAULT_PASSWORD CHAT_RATE_LIMIT_PER_MINUTE SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY GEMINI_API_KEY LLM_BASE_URL LLM_MODEL EMBEDDING_MODEL LANGSMITH_TRACING LANGSMITH_ENDPOINT LANGSMITH_API_KEY LANGSMITH_PROJECT VITE_SUPABASE_URL VITE_SUPABASE_ANON_KEY CLUB_PASSWORD_SECRET SIGNUP_SUPABASE_URL SIGNUP_SUPABASE_ANON_KEY SIGNUP_STORAGE_KEY SIGNUP_PAYMENT_KEY SIGNUP_SITE_URL"

for name in $VARS; do
  val=$(grep "^$name=" .env | head -1 | cut -d= -f2- | tr -d '\r')
  if [ -z "$val" ]; then echo "⚠️  $name 在 .env 是空的，跳過"; continue; fi
  # Vercel CLI 65+ 的寫法：一次寫入 Production 與 Preview，--force 覆蓋舊值，--yes 不互動
  if printf '%s' "$val" | vercel env add "$name" --environment production,preview --force --yes >/dev/null 2>&1; then
    echo "✓ $name (production+preview) 已寫入，長度=${#val}"
  else
    echo "✗ $name 寫入失敗，請把這行貼給 Claude Code"
  fi
done

echo "----- Vercel 目前的環境變數 -----"
vercel env ls 2>&1 | grep -E "^ [A-Z]" | awk '{print "  " $1, "→", $4, $5}'
