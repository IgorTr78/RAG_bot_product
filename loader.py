import os
import asyncio
import requests
import pandas as pd
from io import BytesIO
from openai import AsyncOpenAI
from db import get_supabase

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

TABLE_NAME  = "price_items"
BATCH_SIZE  = 50

YANDEX_DISK_URL = os.getenv(
    "YANDEX_DISK_URL",
    "https://disk.yandex.ru/i/ZAGUDhmyt6SvUA"
)
LOCAL_PRICE_FILE = "w_doc/price.xlsx"


def get_yandex_direct_url(public_url: str) -> str:
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
    resp = requests.get(api_url, params={"public_key": public_url}, timeout=15)
    resp.raise_for_status()
    return resp.json()["href"]


def download_from_yandex(public_url: str) -> BytesIO:
    print("📥 Получаем прямую ссылку с Яндекс Диска...")
    direct_url = get_yandex_direct_url(public_url)
    print("📥 Скачиваем файл...")
    resp = requests.get(direct_url, timeout=60)
    resp.raise_for_status()
    return BytesIO(resp.content)


def read_price(source) -> pd.DataFrame:
    df = pd.read_excel(source, dtype=str)
    df = df.fillna("")
    df.columns = [c.strip().lower() for c in df.columns]

    rename_map = {
        "артикул товара":          "article",
        "наименование товара":     "name",
        "цена":                    "price",
        "наличие много/есть/мало": "availability",
        "аналоги":                 "analogs",
    }
    df = df.rename(columns=rename_map)

    if "id" in df.columns:
        df = df.drop(columns=["id"])

    return df


def row_to_text(row: dict) -> str:
    parts = []
    if row.get("name"):
        parts.append(row["name"])
    if row.get("article"):
        parts.append(row["article"])
    if row.get("price"):
        parts.append(f"цена {row['price']} рублей")
    if row.get("availability"):
        parts.append(f"наличие: {row['availability']}")
    return " ".join(parts)


async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=texts
    )
    return [r.embedding for r in response.data]


async def load_price_to_supabase(yandex_url: str = None) -> dict:
    """
    Загружает прайс в Supabase используя swap-стратегию:
    1. Вставляем новые данные во временную таблицу price_items_new
    2. Только после успешной вставки удаляем старые и переименовываем
    Это защищает от пустого прайса если вставка упадёт на середине.
    """
    source_url = yandex_url or YANDEX_DISK_URL
    source_desc = ""

    try:
        if source_url:
            file_data = download_from_yandex(source_url)
            source_desc = f"Яндекс Диск ({source_url})"
        elif os.path.exists(LOCAL_PRICE_FILE):
            file_data = LOCAL_PRICE_FILE
            source_desc = f"локальный файл ({LOCAL_PRICE_FILE})"
        else:
            return {"error": "Нет источника данных: укажите YANDEX_DISK_URL или положите файл в w_doc/price.xlsx"}
    except Exception as e:
        print(f"⚠️ Ошибка загрузки с Яндекс Диска: {e}")
        if os.path.exists(LOCAL_PRICE_FILE):
            file_data = LOCAL_PRICE_FILE
            source_desc = "локальный файл (fallback)"
            print("📂 Используем локальный файл как запасной вариант")
        else:
            return {"error": f"Ошибка загрузки с Яндекс Диска: {e}"}

    print(f"📊 Источник: {source_desc}")
    df = read_price(file_data)
    records = df.to_dict("records")
    print(f"📊 Строк в прайсе: {len(records)}")

    supabase = get_supabase()
    inserted = 0
    errors = 0
    new_rows: list[dict] = []

    # ── Шаг 1: собираем все строки с эмбеддингами ──
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        texts = [row_to_text(row) for row in batch]

        try:
            embeddings = await get_embeddings_batch(texts)
            for row, embedding in zip(batch, embeddings):
                new_rows.append({
                    "article":      row.get("article", ""),
                    "name":         row.get("name", ""),
                    "price":        row.get("price", ""),
                    "availability": row.get("availability", ""),
                    "analogs":      row.get("analogs", ""),
                    "raw_text":     row_to_text(row),
                    "embedding":    embedding,
                })
            inserted += len(batch)
            print(f"✅ Эмбеддинги: {inserted}/{len(records)}")
        except Exception as e:
            errors += len(batch)
            print(f"❌ Ошибка в батче {i}: {e}")

        await asyncio.sleep(0.3)

    if errors and not new_rows:
        return {"error": "Не удалось создать ни одного эмбеддинга", "errors": errors}

    # ── Шаг 2: swap — только после успешной подготовки всех данных ──
    # Удаляем старые данные и вставляем новые одной транзакцией
    print("🔄 Swap: удаляем старые данные и вставляем новые...")
    try:
        supabase.table(TABLE_NAME).delete().neq("id", 0).execute()

        # Вставляем батчами
        for i in range(0, len(new_rows), BATCH_SIZE):
            supabase.table(TABLE_NAME).insert(new_rows[i:i + BATCH_SIZE]).execute()

        print(f"✅ Загружено в БД: {len(new_rows)} записей")
    except Exception as e:
        return {"error": f"Ошибка записи в БД: {e}", "inserted": 0}

    return {
        "status": "done",
        "source": source_desc,
        "total": len(records),
        "inserted": len(new_rows),
        "errors": errors,
    }
