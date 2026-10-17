-- ============================================================
-- 模組 1：應用外殼與對話記憶 Schema (Threads & Messages + RLS)
-- 請複製此檔案全部內容，貼到 Supabase 左側選單「SQL Editor」並點擊 Run
-- ============================================================

-- 1. 啟用 UUID 擴充功能
create extension if not exists "pgcrypto";

-- 2. 建立 threads（對話線程）資料表
create table if not exists public.threads (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    title text not null default '新對話',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 3. 建立 messages（對話訊息）資料表
create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    thread_id uuid not null references public.threads(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null check (role in ('user', 'assistant', 'system')),
    content text not null,
    created_at timestamptz not null default now()
);

-- 4. 建立索引以加速查詢
create index if not exists idx_threads_user_id on public.threads(user_id, updated_at desc);
create index if not exists idx_messages_thread_id on public.messages(thread_id, created_at asc);

-- 5. 啟用行級安全性 (Row-Level Security, RLS) —— 確保每個用戶只能看到自己的資料
alter table public.threads enable row level security;
alter table public.messages enable row level security;

-- 6. 設定 threads 表的 RLS 策略
drop policy if exists "Users can view own threads" on public.threads;
create policy "Users can view own threads"
    on public.threads for select
    using (auth.uid() = user_id);

drop policy if exists "Users can create own threads" on public.threads;
create policy "Users can create own threads"
    on public.threads for insert
    with check (auth.uid() = user_id);

drop policy if exists "Users can update own threads" on public.threads;
create policy "Users can update own threads"
    on public.threads for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can delete own threads" on public.threads;
create policy "Users can delete own threads"
    on public.threads for delete
    using (auth.uid() = user_id);

-- 7. 設定 messages 表的 RLS 策略
drop policy if exists "Users can view own messages" on public.messages;
create policy "Users can view own messages"
    on public.messages for select
    using (auth.uid() = user_id);

drop policy if exists "Users can create own messages" on public.messages;
create policy "Users can create own messages"
    on public.messages for insert
    with check (auth.uid() = user_id);

drop policy if exists "Users can update own messages" on public.messages;
create policy "Users can update own messages"
    on public.messages for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can delete own messages" on public.messages;
create policy "Users can delete own messages"
    on public.messages for delete
    using (auth.uid() = user_id);
