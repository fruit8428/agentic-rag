-- ============================================================
-- 模組 2：自建檢索 (pgvector) + 文件導入 Schema
-- 請在 Supabase 左側選單「SQL Editor」貼上並點擊 Run
-- ============================================================

-- 1. 啟用 pgvector 向量擴充功能
create extension if not exists vector;

-- 2. 為 messages 表新增 sources 欄位（用來永久保存每次回答參考的文件片段）
alter table public.messages
add column if not exists sources jsonb not null default '[]'::jsonb;

-- 3. 建立 documents（上傳文件主表）
create table if not exists public.documents (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    filename text not null,
    file_size bigint not null default 0,
    mime_type text not null default 'application/octet-stream',
    storage_path text not null,
    status text not null default 'processing' check (status in ('uploading', 'processing', 'completed', 'failed')),
    chunk_count int not null default 0,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 4. 建立 document_chunks（文件分塊與 768 維度 Gemini 向量表）
create table if not exists public.document_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.documents(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    chunk_index int not null,
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(768) not null,
    created_at timestamptz not null default now()
);

-- 5. 建立查詢與 HNSW 向量索引
create index if not exists idx_documents_user_id on public.documents(user_id, created_at desc);
create index if not exists idx_document_chunks_doc_id on public.document_chunks(document_id, chunk_index asc);
create index if not exists idx_document_chunks_user_id on public.document_chunks(user_id);
create index if not exists idx_document_chunks_embedding on public.document_chunks using hnsw (embedding vector_cosine_ops);

-- 6. 啟用行級安全性 (RLS)
alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;

-- 7. 設定 documents 表的 RLS 策略
drop policy if exists "Users can view own documents" on public.documents;
create policy "Users can view own documents"
    on public.documents for select
    using (auth.uid() = user_id);

drop policy if exists "Users can insert own documents" on public.documents;
create policy "Users can insert own documents"
    on public.documents for insert
    with check (auth.uid() = user_id);

drop policy if exists "Users can update own documents" on public.documents;
create policy "Users can update own documents"
    on public.documents for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can delete own documents" on public.documents;
create policy "Users can delete own documents"
    on public.documents for delete
    using (auth.uid() = user_id);

-- 8. 設定 document_chunks 表的 RLS 策略
drop policy if exists "Users can view own document_chunks" on public.document_chunks;
create policy "Users can view own document_chunks"
    on public.document_chunks for select
    using (auth.uid() = user_id);

drop policy if exists "Users can insert own document_chunks" on public.document_chunks;
create policy "Users can insert own document_chunks"
    on public.document_chunks for insert
    with check (auth.uid() = user_id);

drop policy if exists "Users can delete own document_chunks" on public.document_chunks;
create policy "Users can delete own document_chunks"
    on public.document_chunks for delete
    using (auth.uid() = user_id);

-- 9. 將 documents 表加入 Supabase Realtime 即時廣播
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'documents'
  ) then
    alter publication supabase_realtime add table public.documents;
  end if;
end $$;

-- 10. 建立向量相似度檢索函數 match_document_chunks
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
    where dc.user_id = auth.uid()
      and 1 - (dc.embedding <=> query_embedding) >= match_threshold
    order by dc.embedding <=> query_embedding asc
    limit match_count;
$$;
