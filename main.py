import os
import re
import time
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

from db import get_supabase
from rag import search_and_answer
from loader import load_price_to_supabase

load_dotenv()

app = FastAPI(title="АвтоСклад — RAG Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Rate limiting (простой in-memory счётчик) ──
# Максимум 20 запросов в минуту с одного IP
RATE_LIMIT     = 20
RATE_WINDOW    = 60  # секунд
_rate_counters: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(ip: str) -> bool:
    """Возвращает True если запрос разрешён, False если лимит превышен."""
    now = time.time()
    window_start = now - RATE_WINDOW
    # Удаляем старые запросы
    _rate_counters[ip] = [t for t in _rate_counters[ip] if t > window_start]
    if len(_rate_counters[ip]) >= RATE_LIMIT:
        return False
    _rate_counters[ip].append(now)
    return True


# ── Pydantic модели ──

class CarInfo(BaseModel):
    brand_model: Optional[str] = None
    year:        Optional[str] = None
    engine:      Optional[str] = None
    vin:         Optional[str] = None


class HistoryMessage(BaseModel):
    role:    str   # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    car:     Optional[CarInfo]            = None
    history: Optional[list[HistoryMessage]] = None  # история диалога


class ContactRequest(BaseModel):
    name:  str
    phone: Optional[str] = None
    email: Optional[str] = None
    topic: Optional[str] = None


class LoadRequest(BaseModel):
    secret:     str
    yandex_url: Optional[str] = None


# ── Эндпоинты ──

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    # Rate limiting
    ip = request.client.host
    if not check_rate_limit(ip):
        raise HTTPException(
            status_code=429,
            detail="Слишком много запросов. Подожди минуту и попробуй ещё раз."
        )

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    car_dict = req.car.model_dump() if req.car else None

    # Преобразуем историю в формат для GPT
    history = None
    if req.history:
        history = [{"role": m.role, "content": m.content} for m in req.history]

    answer = await search_and_answer(req.message, car=car_dict, history=history)
    return {"answer": answer}


@app.post("/contacts")
async def save_contact(req: ContactRequest):
    """Сохраняет контакт из чат-бота в Supabase."""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Имя обязательно")
    if not req.phone and not req.email:
        raise HTTPException(status_code=400, detail="Нужен телефон или email")
    try:
        supabase = get_supabase()
        supabase.table("chat_contacts").insert({
            "name":  req.name.strip(),
            "phone": req.phone.strip() if req.phone else None,
            "email": req.email.strip() if req.email else None,
            "topic": req.topic.strip() if req.topic else None,
        }).execute()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/load")
async def load_price(req: LoadRequest):
    admin_secret = os.getenv("ADMIN_SECRET", "change-me-please")
    if req.secret != admin_secret:
        raise HTTPException(status_code=403, detail="Неверный секрет")
    result = await load_price_to_supabase(yandex_url=req.yandex_url)
    return result


@app.get("/available-models")
async def available_models():
    """
    Возвращает структуру {brand: [model, ...]} только для позиций в наличии.
    """
    try:
        supabase = get_supabase()
        result = supabase.table("price_items").select("name, availability").execute()
        items = result.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    available = [i for i in items if i.get("availability") in ("много", "есть", "мало")]

    BRAND_MAP = {
        "lada": "Lada", "лада": "Lada", "ваз": "Lada",
        "kia": "Kia", "киа": "Kia",
        "hyundai": "Hyundai", "хендай": "Hyundai",
        "toyota": "Toyota", "тойота": "Toyota",
        "volkswagen": "Volkswagen", "фольксваген": "Volkswagen",
        "renault": "Renault", "рено": "Renault",
        "nissan": "Nissan", "ниссан": "Nissan",
        "skoda": "Skoda", "шкода": "Skoda",
        "mazda": "Mazda", "мазда": "Mazda",
        "ford": "Ford", "форд": "Ford",
        "opel": "Opel", "опель": "Opel",
        "chevrolet": "Chevrolet", "шевроле": "Chevrolet",
        "mitsubishi": "Mitsubishi", "мицубиши": "Mitsubishi",
        "honda": "Honda", "хонда": "Honda",
        "bmw": "BMW", "бмв": "BMW",
        "mercedes": "Mercedes", "мерседес": "Mercedes",
        "audi": "Audi", "ауди": "Audi",
    }

    pattern = re.compile(r'для\s+(.+)', re.IGNORECASE)
    brands: dict = {}

    for item in available:
        name = item.get("name", "")
        m = pattern.search(name)
        if not m:
            continue
        rest = m.group(1).strip()
        parts = rest.split()
        if len(parts) < 2:
            continue

        brand_raw = parts[0].lower()
        brand = BRAND_MAP.get(brand_raw, parts[0].capitalize())
        model = " ".join(parts[1:])

        brands.setdefault(brand, set()).add(model)

    return {b: sorted(list(models)) for b, models in sorted(brands.items())}


@app.get("/health")
async def health():
    return {"status": "ok"}
