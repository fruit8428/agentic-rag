-- ============================================================================
-- 模組 9：地區與社內權限分級（3523 地區扶輪社）
-- 權限規則：使用者能看到文件 ⇔ 文件 scope='district' 或 文件 club_id = 使用者所屬社（管理員看全部）
-- 本檔可重複執行（idempotent）
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. 社（clubs）與社友檔案（profiles）
-- ----------------------------------------------------------------------------
create table if not exists public.clubs (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    division text,                 -- 分區（1~13；地區辦公室為 null）
    code text,                     -- 編號（例如 01-1）
    password_hash text,            -- 社內密碼 bcrypt 雜湊；null = 管理員尚未設定，無法加入
    created_at timestamptz not null default now()
);

create table if not exists public.profiles (
    user_id uuid primary key references auth.users(id) on delete cascade,
    club_id uuid references public.clubs(id) on delete restrict,   -- 社內仍有社友時禁止刪社
    role text not null default 'member' check (role in ('member', 'admin')),
    joined_at timestamptz,
    created_at timestamptz not null default now()
);
create index if not exists idx_profiles_club_id on public.profiles(club_id);

-- 新使用者註冊時自動建立 profiles 列
create or replace function public.handle_new_user()
returns trigger
language plpgsql security definer set search_path = public
as $$
begin
    insert into public.profiles (user_id) values (new.id) on conflict (user_id) do nothing;
    return new;
end;
$$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- 回填既有使用者
insert into public.profiles (user_id)
select id from auth.users
on conflict (user_id) do nothing;

-- 地區管理員
update public.profiles set role = 'admin'
where user_id = (select id from auth.users where email = 'fruit8428@gmail.com' limit 1);

-- ----------------------------------------------------------------------------
-- 2. documents 加上範圍（scope）與所屬社（club_id）
-- ----------------------------------------------------------------------------
alter table public.documents add column if not exists scope text not null default 'club';
alter table public.documents add column if not exists club_id uuid references public.clubs(id) on delete restrict;

-- 既有文件（頒獎名單、保齡球 PDF）全部歸為地區級
update public.documents set scope = 'district', club_id = null where club_id is null;

alter table public.documents drop constraint if exists documents_scope_chk;
alter table public.documents add constraint documents_scope_chk check (scope in ('district', 'club'));
alter table public.documents drop constraint if exists documents_scope_club_chk;
alter table public.documents add constraint documents_scope_club_chk
    check ((scope = 'district' and club_id is null) or (scope = 'club' and club_id is not null));
create index if not exists idx_documents_scope_club on public.documents(scope, club_id);

-- ----------------------------------------------------------------------------
-- 3. 輔助函數（供 RLS 與 SQL 函數使用）
-- ----------------------------------------------------------------------------
create or replace function public.current_club_id()
returns uuid
language sql stable security definer set search_path = public
as $$
    select club_id from public.profiles where user_id = auth.uid()
$$;

create or replace function public.is_admin()
returns boolean
language sql stable security definer set search_path = public
as $$
    select coalesce((select role = 'admin' from public.profiles where user_id = auth.uid()), false)
$$;

create or replace function public.can_view_document(doc_scope text, doc_club_id uuid)
returns boolean
language sql stable security definer set search_path = public
as $$
    select doc_scope = 'district'
        or (doc_club_id is not null and doc_club_id = public.current_club_id())
        or public.is_admin()
$$;

grant execute on function public.current_club_id() to authenticated;
grant execute on function public.is_admin() to authenticated;
grant execute on function public.can_view_document(text, uuid) to authenticated;

-- ----------------------------------------------------------------------------
-- 4. RLS：clubs / profiles
-- ----------------------------------------------------------------------------
alter table public.clubs enable row level security;
drop policy if exists "Admins manage clubs" on public.clubs;
create policy "Admins manage clubs" on public.clubs
    for all using (public.is_admin()) with check (public.is_admin());

-- 一般社友只能透過此視圖看到社名（看不到 password_hash）
create or replace view public.clubs_public as
    select id, name, division, code, (password_hash is not null) as joinable
    from public.clubs;
revoke all on public.clubs_public from anon;
grant select on public.clubs_public to authenticated;

alter table public.profiles enable row level security;
drop policy if exists "Users view own profile" on public.profiles;
create policy "Users view own profile" on public.profiles
    for select using (auth.uid() = user_id);
drop policy if exists "Admins view all profiles" on public.profiles;
create policy "Admins view all profiles" on public.profiles
    for select using (public.is_admin());
drop policy if exists "Admins update profiles" on public.profiles;
create policy "Admins update profiles" on public.profiles
    for update using (public.is_admin()) with check (public.is_admin());

-- ----------------------------------------------------------------------------
-- 5. RLS：documents / document_chunks 改為地區／社內可見性規則
-- ----------------------------------------------------------------------------
drop policy if exists "Users can view own documents" on public.documents;
create policy "Members view visible documents" on public.documents
    for select using (public.can_view_document(scope, club_id));

drop policy if exists "Users can insert own documents" on public.documents;
create policy "Members insert documents in own scope" on public.documents
    for insert with check (
        auth.uid() = user_id
        and (
            (scope = 'club' and club_id = public.current_club_id())
            or (scope = 'district' and public.is_admin())
        )
    );

drop policy if exists "Users can delete own documents" on public.documents;
create policy "Owners or admins delete documents" on public.documents
    for delete using (auth.uid() = user_id or public.is_admin());

drop policy if exists "Users can view own document_chunks" on public.document_chunks;
create policy "Members view visible document_chunks" on public.document_chunks
    for select using (
        exists (
            select 1 from public.documents d
            where d.id = document_chunks.document_id
              and public.can_view_document(d.scope, d.club_id)
        )
    );

drop policy if exists "Users can delete own document_chunks" on public.document_chunks;
create policy "Owners or admins delete document_chunks" on public.document_chunks
    for delete using (auth.uid() = user_id or public.is_admin());

-- ----------------------------------------------------------------------------
-- 6. 更新既有 SQL 函數與視圖：改用可見性規則
-- ----------------------------------------------------------------------------
create or replace function public.match_document_chunks(
    query_embedding vector(768),
    match_threshold float default 0.3,
    match_count int default 5
)
returns table (
    id uuid,
    document_id uuid,
    filename text,
    chunk_index int,
    content text,
    metadata jsonb,
    similarity float
)
language sql stable
as $$
    select
        dc.id,
        dc.document_id,
        d.filename,
        dc.chunk_index,
        dc.content,
        dc.metadata,
        1 - (dc.embedding <=> query_embedding) as similarity
    from public.document_chunks dc
    join public.documents d on d.id = dc.document_id
    where public.can_view_document(d.scope, d.club_id)
      and 1 - (dc.embedding <=> query_embedding) >= match_threshold
    order by dc.embedding <=> query_embedding asc
    limit match_count;
$$;

drop view if exists public.user_documents_analytics;
create view public.user_documents_analytics
with (security_invoker = true) as
select
    d.id as document_id,
    d.user_id,
    d.filename,
    d.status,
    d.scope,
    d.club_id,
    c.name as club_name,
    d.created_at,
    d.updated_at,
    count(ch.id) as total_chunks,
    coalesce(sum(length(ch.content)), 0) as total_characters,
    max(ch.metadata -> 'extracted_metadata' ->> 'document_title') as document_title,
    max(ch.metadata -> 'extracted_metadata' ->> 'category') as category,
    max(ch.metadata -> 'extracted_metadata' ->> 'event_or_year') as event_or_year,
    max(ch.metadata ->> 'file_hash') as file_hash
from public.documents d
left join public.clubs c on c.id = d.club_id
left join public.document_chunks ch on ch.document_id = d.id
where public.can_view_document(d.scope, d.club_id)
group by d.id, d.user_id, d.filename, d.status, d.scope, d.club_id, c.name, d.created_at, d.updated_at;

-- ----------------------------------------------------------------------------
-- 7. 種子資料：3523 地區 80 個扶輪社 + 地區辦公室（密碼待管理員設定）
-- ----------------------------------------------------------------------------
insert into public.clubs (division, code, name) values
    ('1', '01-1', '臺北市南區扶輪社'),
    ('1', '01-2', '台北逸仙扶輪社'),
    ('1', '01-3', '台北逸天扶輪社'),
    ('1', '01-4', '台北市雲聯網扶輪社'),
    ('1', '01-5', '台北逸澤扶輪社'),
    ('1', '01-6', '臺北黃埔扶輪社'),
    ('1', '01-7', '台北逸新扶輪社'),
    ('1', '01-8', '台北蘭亭鐵馬扶輪社'),
    ('1', '01-9', '台北銀河扶輪社'),
    ('2', '02-1', '台北市西南區扶輪社'),
    ('2', '02-2', '台北健康扶輪社'),
    ('2', '02-3', '台北高峰扶輪社'),
    ('2', '02-4', '台北永康扶輪社'),
    ('2', '02-5', '台北市南山扶輪社'),
    ('3', '03-1', '台北市華南扶輪社'),
    ('3', '03-2', '台北市華陽扶輪社'),
    ('3', '03-3', '台北市瑞光扶輪社'),
    ('3', '03-4', '台北市華東扶輪社'),
    ('3', '03-5', '台北市永續扶輪社'),
    ('3', '03-6', '影響力扶輪社'),
    ('4', '04-1', '台北市南欣扶輪社'),
    ('4', '04-2', '台北松山扶輪社'),
    ('4', '04-3', '台北市民生扶輪社'),
    ('4', '04-4', '台北政愛扶輪社'),
    ('4', '04-5', '台北添愛扶輪社'),
    ('4', '04-6', '台北泰愛扶輪社'),
    ('4', '04-7', '文化扶輪社'),
    ('5', '05-1', '台北府門扶輪社'),
    ('5', '05-2', '台北南陽扶輪社'),
    ('5', '05-3', '台北明星扶輪社'),
    ('5', '05-4', '台北風雲扶輪社'),
    ('6', '06-1', '台北市南門扶輪社'),
    ('6', '06-2', '台北大都會扶輪社'),
    ('6', '06-3', '台北市南方扶輪社'),
    ('6', '06-4', '台北市南光扶輪社'),
    ('6', '06-5', '台北南英扶輪社'),
    ('6', '06-6', '台北市南揚扶輪社'),
    ('6', '06-7', '台北市南波扶輪社'),
    ('6', '06-8', '臺北市南星扶輪社'),
    ('6', '06-9', '台北南法扶輪社'),
    ('7', '07-1', '台北市南海扶輪社'),
    ('7', '07-2', '台北市南雅扶輪社'),
    ('7', '07-3', '台北市新世代扶輪社'),
    ('7', '07-4', '台北市南鷹扶輪社'),
    ('7', '07-5', '台北大加蚋扶輪社'),
    ('8', '08-1', '台北市華麗扶輪社'),
    ('8', '08-2', '台北市華欣扶輪社'),
    ('8', '08-3', '台北市華樂扶輪社'),
    ('8', '08-4', '台北網路扶輪社'),
    ('8', '08-5', '臺北新北投扶輪社'),
    ('8', '08-6', '台北市華真扶輪社'),
    ('9', '09-1', '台北市華安扶輪社'),
    ('9', '09-2', '台北市華中扶輪社'),
    ('9', '09-3', '台北市益成扶輪社'),
    ('9', '09-4', '台北市南德扶輪社'),
    ('9', '09-5', '台北市華茂扶輪社'),
    ('9', '09-6', '台北南茂扶輪社'),
    ('9', '09-7', '台北市三友扶輪社'),
    ('10', '10-1', '台北市南港扶輪社'),
    ('10', '10-2', '台北市南北扶輪社'),
    ('10', '10-3', '台北市南西扶輪社'),
    ('10', '10-4', '台北市南東扶輪社'),
    ('11', '11-1', '台北市南華扶輪社'),
    ('11', '11-2', '台北市文華扶輪社'),
    ('11', '11-3', '台北永華扶輪社'),
    ('11', '11-4', '台北市西華扶輪社'),
    ('11', '11-5', '台北市碩華扶輪社'),
    ('11', '11-6', '台北富華扶輪社'),
    ('12', '12-1', '台北龍門扶輪社'),
    ('12', '12-2', '台北龍華扶輪社'),
    ('12', '12-3', '台北龍鳳扶輪社'),
    ('12', '12-4', '台北龍族扶輪社'),
    ('12', '12-5', '台北龍欣扶輪社'),
    ('12', '12-6', '台北龍來扶輪社'),
    ('12', '12-7', '台北龍穎扶輪社'),
    ('12', '12-8', '台北龍舟扶輪社'),
    ('13', '13-1', '台北市南天扶輪社'),
    ('13', '13-2', '台北市天一扶輪社'),
    ('13', '13-3', '台北樂雅扶輪社'),
    ('13', '13-4', '台北風澤扶輪社'),
    (NULL, NULL, '地區辦公室')
on conflict (name) do nothing;
