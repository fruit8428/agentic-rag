-- ============================================================================
-- 模組 10 補充：記錄各社目前的社密碼（加密後存放），讓地區管理員在後台看得到
-- 加密金鑰只放在伺服器環境變數 CLUB_PASSWORD_SECRET，資料庫本身讀不出原文
-- 本檔可重複執行（idempotent）
-- ============================================================================
alter table public.clubs add column if not exists password_enc text;
alter table public.clubs add column if not exists password_updated_at timestamptz;
