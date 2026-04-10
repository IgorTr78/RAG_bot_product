# RAG Price Bot 🤖

Чат-бот для поиска по прайс-листу на базе RAG + GPT-4o mini + Supabase.  
Портфолио-проект: демонстрирует работу с бизнес-данными в реальном времени.

## Стек
- **FastAPI** — Python-сервер
- **OpenAI** — embeddings (text-embedding-3-small) + ответы (GPT-4o mini)
- **Supabase** — хранение векторов (pgvector)
- **Railway** — деплой с публичным URL

---

## Структура
```
rag-portfolio-bot/
├── w_doc/
│   └── price.xlsx          ← сюда кладёшь прайс
├── static/
│   └── index.html          ← веб-интерфейс чата
├── main.py                 ← FastAPI сервер
├── rag.py                  ← RAG поиск + GPT ответ
├── loader.py               ← загрузка Excel → Supabase
├── supabase_setup.sql      ← SQL для настройки БД
├── requirements.txt
├── Procfile                ← для Railway
└── .env.example
```

---

## Формат прайса (Excel)

Файл `w_doc/price.xlsx` должен содержать колонки:

| name | category | price | unit | description |
|------|----------|-------|------|-------------|
| Кирпич М150 | Стройматериалы | 12.50 | шт | Полнотелый красный |
| Монтаж окна | Работы | 3500 | услуга | Установка ПВХ окна |

Колонки `category`, `unit`, `description` — опциональны.

---

## Настройка: 5 шагов

### 1. Supabase
1. Зайди на [supabase.com](https://supabase.com) → создай проект
2. Открой **SQL Editor** → вставь содержимое `supabase_setup.sql` → Run
3. Скопируй `Project URL` и `anon public key` из **Settings → API**

### 2. OpenAI
Получи API ключ на [platform.openai.com](https://platform.openai.com)

### 3. Локальный запуск
```bash
# Клонируй репо
git clone https://github.com/твой-юзер/rag-portfolio-bot
cd rag-portfolio-bot

# Установи зависимости
pip install -r requirements.txt

# Создай .env из примера
cp .env.example .env
# Заполни .env своими ключами

# Положи прайс
cp /путь/к/price.xlsx w_doc/price.xlsx

# Запусти сервер
uvicorn main:app --reload
# → http://localhost:8000
```

### 4. Загрузка прайса в Supabase
```bash
curl -X POST http://localhost:8000/admin/load \
  -H "Content-Type: application/json" \
  -d '{"secret": "твой-ADMIN_SECRET"}'
```
Ответ: `{"status":"done","total":500,"inserted":500,"errors":0}`

### 5. Деплой на Railway
1. Залей код на GitHub
2. Зайди на [railway.com](https://railway.com) → New Project → Deploy from GitHub
3. В **Variables** добавь:
   - `OPENAI_API_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `ADMIN_SECRET`
4. Railway автоматически найдёт `Procfile` и запустит сервер
5. В **Settings → Networking** включи Public Domain
6. После деплоя вызови эндпоинт загрузки прайса (п.4, но с Railway URL)

---

## API эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/` | Веб-интерфейс чата |
| POST | `/chat` | Запрос к боту `{"message": "..."}` |
| POST | `/admin/load` | Загрузка прайса `{"secret": "..."}` |
| GET | `/health` | Проверка работы сервера |

---

## Обновление прайса
1. Замени `w_doc/price.xlsx` новым файлом
2. Закоммить и запушь в GitHub
3. Railway автоматически передеплоит
4. Вызови `/admin/load` ещё раз — старые данные заменятся новыми

---

## Будущее: виджет на сайт
```html
<!-- Одна строка на любой сайт -->
<script src="https://твой-railway-url/static/widget.js"></script>
```
_(widget.js — следующий этап разработки)_
