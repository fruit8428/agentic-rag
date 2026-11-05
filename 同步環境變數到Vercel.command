#!/bin/bash
# 在 Finder 點兩下即可：把母版 .env 的所有變數（含新的 SIGNUP_*）寫入 Vercel 專案 agentic-rag 的 Production 與 Preview。
cd "$(dirname "$0")"
echo "開始同步環境變數到 Vercel（專案 agentic-rag）..."
bash scripts/sync_vercel_env.sh
echo
echo "完成。這個視窗可以關掉了。"
read -n 1 -s -r -p "按任意鍵關閉..."
