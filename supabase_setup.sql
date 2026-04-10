-- =============================================
-- Запусти этот SQL в Supabase → SQL Editor
-- =============================================

-- 1. Включаем расширение для векторного поиска
create extension if not exists vector;

-- 2. Создаём таблицу прайса (колонки под реальный прайс АвтоСклад)
create table if not exists price_items (
  id           bigserial primary key,
  article      text,        -- артикул товара
  name         text,        -- наименование товара
  price        text,        -- цена
  availability text,        -- наличие: много / есть / мало
  analogs      text,        -- аналоги (артикулы через запятую)
  raw_text     text,        -- текст для embedding
  embedding    vector(1536),
  created_at   timestamptz default now()
);

-- 3. Индекс для быстрого векторного поиска
create index if not exists price_items_embedding_idx
  on price_items
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

-- 4. Функция поиска
create or replace function match_price_items(
  query_embedding vector(1536),
  match_count     int default 10
)
returns table (
  id           bigint,
  article      text,
  name         text,
  price        text,
  availability text,
  analogs      text,
  similarity   float
)
language sql stable
as $$
  select
    id,
    article,
    name,
    price,
    availability,
    analogs,
    1 - (embedding <=> query_embedding) as similarity
  from price_items
  order by embedding <=> query_embedding
  limit match_count;
$$;
