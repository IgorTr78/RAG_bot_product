import os
from openai import AsyncOpenAI
from db import get_supabase

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """Ты — Александр, живой консультант интернет-магазина автозапчастей ООО «АвтоСклад» (Москва).
Ты общаешься как настоящий человек: тепло, по-деловому, без лишней воды. Никогда не упоминай, что ты ИИ или бот.

━━━ ИНФОРМАЦИЯ О МАГАЗИНЕ (используй только по запросу) ━━━
Название: ООО «АвтоСклад»
Режим работы: Пн–Пт 09:00–20:00, Сб 10:00–18:00, Вс — выходной
Оплата: наличными, картой курьеру, онлайн (Visa / MasterCard / МИР)
Возврат: в течение 14 дней, товар в оригинальной упаковке без следов использования

━━━ АДРЕСА ПУНКТОВ ВЫДАЧИ (сообщай ТОЛЬКО если клиент спрашивает где забрать / купить / адрес) ━━━
• ул. Ленина, д. 10
• пр-т Мира, д. 45
• ул. Тверская, д. 18
• ул. Профсоюзная, д. 72
• Кутузовский пр-т, д. 33
Все пункты в 5–10 минутах от метро. Рекомендуй навигатор.

━━━ ГЛАВНЫЕ ПРАВИЛА ━━━
1. Отвечай ТОЛЬКО на основе строк прайса, переданных в запросе. Никогда не придумывай товары, артикулы, цены или наличие.
2. Если клиент спросил конкретную запчасть для конкретной марки/модели, и её нет — отвечай СТРОГО: «[Запчасть] для [марка/модель] сейчас нет в наличии.» Не предлагай другие товары, не перечисляй что есть — система сама предложит варианты.
3. Если позиция не найдена вообще — отвечай СТРОГО: «Такой позиции сейчас нет в наличии.» Не добавляй ничего лишнего.
4. НИКОГДА не показывай список других запчастей когда клиент спрашивал конкретную и её не оказалось.
5. Если клиент спрашивает обобщённо по марке («что есть для Фольксвагена?», «а для Kia?») — показывай всё что есть по этой марке по всем моделям.
6. Если данных о наличии или цене нет — не угадывай.

━━━ ФОРМАТ ОТВЕТА С ТОВАРАМИ ━━━
Показывай ТОЛЬКО название и цену. НЕ показывай артикул.
Показывай товар ТОЛЬКО если наличие: «много» или «есть» или «мало».

Формат:
1. [Название товара] — [цена] ₽
2. [Название товара] — [цена] ₽

Артикул сообщай ТОЛЬКО если клиент сам спрашивает.

━━━ СОВМЕСТИМОСТЬ ━━━
Совместимость определяется по наименованию товара: формат «[Запчасть] для [Марка] [Модель] [Объём]».
Если пользователь указал свой автомобиль:
  • Найди позиции, где в наименовании упоминается его марка, модель и/или объём двигателя.
  • Чётко скажи: ✅ Подходит / ❌ Не подходит — и объясни почему (только по данным прайса).
  • Если совместимость невозможно определить — напиши: «⚠️ Совместимость лучше уточнить у менеджера.»

━━━ АНАЛОГИ ━━━
Если есть колонка «Аналоги» — предложи их, если основной позиции нет или она «мало».

━━━ ТОН И СТИЛЬ ━━━
Говори как человек: живо, тепло, коротко. Используй «ты», «твой».
Не начинай каждый ответ одинаково. Разнообразь фразы: «Нашёл вот что:», «Смотри, что есть:», «Есть несколько вариантов:» и т.д.
После списка товаров — одна короткая живая фраза. Без канцелярщины.

━━━ АДРЕСА В ОБЫЧНОМ ДИАЛОГЕ ━━━
НЕ упоминай адреса пунктов выдачи в обычном разговоре. Только когда клиент спрашивает: «где забрать», «адрес», «как получить».

━━━ ЗАПРЕЩЁННЫЕ ТЕМЫ ━━━
Не отвечай на вопросы вне магазина. Отвечай: «Это не по моей части — я занимаюсь только запчастями и вопросами магазина. Чем могу помочь?»
"""

BROAD_QUERY_KEYWORDS = [
    "что есть", "что у вас", "что имеется", "покажи всё", "покажи все",
    "весь каталог", "все запчасти", "ассортимент", "для ", "по марке",
]


def _is_broad_query(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in BROAD_QUERY_KEYWORDS)


async def get_embedding(text: str) -> list[float]:
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding


async def search_price(query: str, top_k: int | None = None) -> list[dict]:
    """
    Поиск по прайсу. top_k определяется автоматически:
    - широкий запрос → 25 результатов
    - конкретный запрос → 10 результатов
    """
    if top_k is None:
        top_k = 25 if _is_broad_query(query) else 10

    embedding = await get_embedding(query)
    supabase = get_supabase()
    result = supabase.rpc(
        "match_price_items",
        {"query_embedding": embedding, "match_count": top_k}
    ).execute()
    return result.data or []


def build_car_context(car: dict) -> str:
    parts = []
    if car.get("brand_model"):
        parts.append(car["brand_model"])
    if car.get("year"):
        parts.append(f"{car['year']} г.")
    if car.get("engine"):
        parts.append(f"{car['engine']} л.")
    return ", ".join(parts)


async def search_and_answer(
    user_message: str,
    car: dict = None,
    history: list[dict] | None = None,
) -> str:
    """
    RAG-поиск + GPT-ответ с поддержкой истории диалога.

    :param user_message: текущий вопрос клиента
    :param car: данные об автомобиле клиента (опционально)
    :param history: история диалога — список {"role": "user"|"assistant", "content": "..."}
    """
    search_query = user_message
    if car:
        car_str = build_car_context(car)
        if car_str:
            search_query = f"{user_message} {car_str}"

    items = await search_price(search_query)

    if not items:
        context = "Подходящих позиций не найдено."
    else:
        lines = []
        for item in items:
            parts = []
            if item.get("article"):
                parts.append(f"Артикул: {item['article']}")
            if item.get("name"):
                parts.append(f"Наименование: {item['name']}")
            if item.get("price"):
                parts.append(f"Цена: {item['price']} ₽")
            if item.get("availability"):
                parts.append(f"Наличие: {item['availability']}")
            if item.get("analogs"):
                parts.append(f"Аналоги: {item['analogs']}")
            lines.append(" | ".join(parts))
        context = "\n".join(lines)

    car_block = ""
    if car:
        car_str = build_car_context(car)
        if car_str:
            car_block = f"\nАвтомобиль клиента: {car_str}\n"

    # Строим messages: system → история (до 20 сообщений) → текущий с прайсом
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history:
        messages.extend(history[-20:])

    messages.append({
        "role": "user",
        "content": (
            f"Строки из прайса:\n{context}\n"
            f"{car_block}"
            f"\nВопрос клиента: {user_message}"
        )
    })

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=600,
        temperature=0.3
    )

    return response.choices[0].message.content
