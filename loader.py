import os
import asyncio
import requests
import pandas as pd
from io import BytesIO
from openai import AsyncOpenAI
from supabase import create_client, Client

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

TABLE_NAME = "price_items"
BATCH_SIZE = 50

# Ссылка на прайс — берётся из env или используется дефолтная
YANDEX_DISK_URL = os.getenv(
    "YANDEX_DISK_URL",
    "https://disk.yandex.ru/i/ZAGUDhmyt6SvUA"
)

# Локальный файл как запасной вариант
LOCAL_PRICE_FILE = "w_doc/price.xlsx"


def get_yandex_direct_url(public_url: str) -> str:
    """Получить прямую ссылку для скачивания с Яндекс Диска."""
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
    resp = requests.get(api_url, params={"public_key": public_url}, timeout=15)
    resp.raise_for_status()
    return resp.json()["href"]


def download_from_yandex(public_url: str) -> BytesIO:
    """Скачать файл с Яндекс Диска в память."""
    print(f"📥 Получаем прямую ссылку с Яндекс Диска...")
    direct_url = get_yandex_direct_url(public_url)
    print(f"📥 Скачиваем файл...")
    resp = requests.get(direct_url, timeout=60)
    resp.raise_for_status()
    return BytesIO(resp.content)


def read_price(source) -> pd.DataFrame:
    """
    Читает прайс из файла или BytesIO.
    Ожидаемые колонки (по данным реального прайса):
      id, артикул товара, наименование товара, цена, наличие много/есть/мало, Аналоги
    """
    df = pd.read_excel(source, dtype=str)
    df = df.fillna("")

    # Нормализуем названия колонок
    df.columns = [c.strip().lower() for c in df.columns]

    # Маппинг реальных колонок → внутренние имена
    rename_map = {
        "артикул товара":          "article",
        "наименование товара":     "name",
        "цена":                    "price",
        "наличие много/есть/мало": "availability",
        "аналоги":                 "analogs",
    }
    df = df.rename(columns=rename_map)

    # Убираем колонку id если есть
    if "id" in df.columns:
        df = df.drop(columns=["id"])

    return df


def row_to_text(row: dict) -> str:
    """Текст для embedding: наименование + артикул + цена."""
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
    Загружает прайс в Supabase.
    Приоритет источника:
      1. yandex_url из запроса
      2. YANDEX_DISK_URL из env
      3. Локальный файл w_doc/price.xlsx
    """
    source_url = yandex_url or YANDEX_DISK_URL
    source_desc = ""

    # Определяем источник
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
        # Если Яндекс недоступен — пробуем локальный файл
        print(f"⚠️ Ошибка загрузки с Яндекс Диска: {e}")
        if os.path.exists(LOCAL_PRICE_FILE):
            file_data = LOCAL_PRICE_FILE
            source_desc = f"локальный файл (fallback)"
            print(f"📂 Используем локальный файл как запасной вариант")
        else:
            return {"error": f"Ошибка загрузки с Яндекс Диска: {e}"}

    print(f"📊 Источник: {source_desc}")
    df = read_price(file_data)
    records = df.to_dict("records")
    print(f"📊 Строк в прайсе: {len(records)}")

    # Очищаем старые данные
    supabase.table(TABLE_NAME).delete().neq("id", 0).execute()
    print("🗑️  Старые данные удалены")

    inserted = 0
    errors = 0

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        texts = [row_to_text(row) for row in batch]

        try:
            embeddings = await get_embeddings_batch(texts)

            rows_to_insert = []
            for row, embedding in zip(batch, embeddings):
                rows_to_insert.append({
                    "article":      row.get("article", ""),
                    "name":         row.get("name", ""),
                    "price":        row.get("price", ""),
                    "availability": row.get("availability", ""),
                    "analogs":      row.get("analogs", ""),
                    "raw_text":     row_to_text(row),
                    "embedding":    embedding
                })

            supabase.table(TABLE_NAME).insert(rows_to_insert).execute()
            inserted += len(batch)
            print(f"✅ Загружено: {inserted}/{len(records)}")

        except Exception as e:
            errors += len(batch)
            print(f"❌ Ошибка в батче {i}: {e}")

        await asyncio.sleep(0.3)

    return {
        "status": "done",
        "source": source_desc,
        "total": len(records),
        "inserted": inserted,
        "errors": errors
    }
