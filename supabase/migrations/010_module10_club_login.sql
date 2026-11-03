-- ============================================================================
-- 模組 10：社共用登入（社名 + 社密碼）與啟用碼註冊
-- 每個社對應一個 Supabase Auth 帳號（合成 Email），社密碼由 Supabase Auth 保管。
-- 本檔可重複執行（idempotent）
-- ============================================================================

-- 1. clubs 新增欄位：對應的 Auth 帳號、啟用碼、啟用時間
alter table public.clubs add column if not exists auth_user_id uuid references auth.users(id) on delete set null;
alter table public.clubs add column if not exists activation_code text;
alter table public.clubs add column if not exists activated_at timestamptz;
create unique index if not exists idx_clubs_auth_user_id
    on public.clubs(auth_user_id) where auth_user_id is not null;

-- 2. 啟用碼產生函數（8 碼 + 中間連字號，排除 0/O/1/I 等易混淆字元）
create or replace function public.generate_activation_code()
returns text
language plpgsql volatile
as $$
declare
    chars text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    result text := '';
    i int;
begin
    for i in 1..8 loop
        result := result || substr(chars, 1 + floor(random() * length(chars))::int, 1);
        if i = 4 then
            result := result || '-';
        end if;
    end loop;
    return result;
end;
$$;

-- 3. 為所有尚未啟用且還沒有啟用碼的社產生啟用碼
update public.clubs
set activation_code = public.generate_activation_code()
where auth_user_id is null and activation_code is null;

-- 4. 重建 clubs_public 視圖（joinable → activated；視圖依賴 password_hash，必須先 drop 再刪欄位）
drop view if exists public.clubs_public;

-- 5. 舊的社內密碼欄位不再使用（密碼改由 Supabase Auth 管理）
alter table public.clubs drop column if exists password_hash;

create view public.clubs_public as
    select id, name, division, code, (auth_user_id is not null) as activated
    from public.clubs;
revoke all on public.clubs_public from anon;
grant select on public.clubs_public to authenticated;
