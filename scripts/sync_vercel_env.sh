#!/bin/bash
# 把專案根目錄 .env 的環境變數「完整」寫入 Vercel 的 Production 與 Preview 環境。
# 用途：避免在 Vercel 網頁上手動複製貼上造成金鑰被截斷。
# 用法：在專案根目錄執行  bash scripts/sync_vercel_env.sh
set -e
cd "$(dirname "$0")/.."

VARS="SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY GEMINI_API_KEY LLM_BASE_URL LLM_MODEL EMBEDDING_MODEL LANGSMITH_TRACING LANGSMITH_ENDPOINT LANGSMITH_API_KEY LANGSMITH_PROJECT VITE_SUPABASE_URL VITE_SUPABASE_ANON_KEY CLUB_PASSWORD_SECRET SIGNUP_SUPABASE_URL SIGNUP_SUPABASE_ANON_KEY SIGNUP_STORAGE_KEY SIGNUP_PAYMENT_KEY SIGNUP_SITE_URL"

for name in $VARS; do
  val=$(grep "^$name=" .env | head -1 | cut -d= -f2- | tr -d '\r')
  if [ -z "$val" ]; then echo "⚠️  $name 在 .env 是空的，跳過"; continue; fi
  for envn in production preview; do
    vercel env rm "$name" "$envn" -y >/dev/null 2>&1 || true
    if printf '%s' "$val" | vercel env add "$name" "$envn" >/dev/null 2>&1; then
      echo "✓ $name ($envn) 已寫入，長度=${#val}"
    else
      echo "✗ $name ($envn) 寫入失敗"
    fi
  done
done

echo "----- Vercel 目前的環境變數 -----"
vercel env ls 2>&1 | grep -E "^ [A-Z]" | awk '{print "  " $1, "→", $4, $5}'
