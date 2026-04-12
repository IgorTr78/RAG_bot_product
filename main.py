import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from rag import search_and_answer
from loader import load_price_to_supabase

load_dotenv()
import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from rag import search_and_answer
from loader import load_price_to_supabase

load_dotenv()

app = FastAPI(title="АвтоСклад — RAG Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)


class CarInfo(BaseModel):
    brand_model: Optional[str] = None
    year:        Optional[str] = None
    engine:      Optional[str] = None
    vin:         Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    car: Optional[CarInfo] = None


class ContactRequest(BaseModel):
    name:  str
    phone: Optional[str] = None
    email: Optional[str] = None
    topic: Optional[str] = None


class LoadRequest(BaseModel):
    secret:     str
    yandex_url: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/chat")
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    car_dict = req.car.model_dump() if req.car else None
    answer = await search_and_answer(req.message, car=car_dict)
    return {"answer": answer}


@app.post("/contacts")
async def save_contact(req: ContactRequest):
    """Сохраняет контакт из чат-бота в Supabase."""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Имя обязательно")
    if not req.phone and not req.email:
        raise HTTPException(status_code=400, detail="Нужен телефон или email")
    try:
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
    Возвращает структуру {brand: [model, ...]} только для тех марок и моделей,
    которые реально есть в прайсе (таблица price_items).
    Парсит поле name по шаблону: «[Запчасть] для [Марка] [Модель] [Объём]»
    """
    import re
    try:
        result = supabase.table("price_items").select("name, availability").execute()
        items = result.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Только позиции в наличии
    available = [i for i in items if i.get("availability") in ("много", "есть", "мало")]

    # Словарь марок для нормализации
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

    # Парсим «... для Марка Модель Объём»
    pattern = re.compile(r'для\s+(.+)', re.IGNORECASE)
    brands: dict = {}

    for item in available:
        name = item.get("name", "")
        m = pattern.search(name)
        if not m:
            continue
        rest = m.group(1).strip()  # «Lada Vesta 1.6» или «Kia Rio III 1.6»
        parts = rest.split()
        if len(parts) < 2:
            continue

        brand_raw = parts[0].lower()
        brand = BRAND_MAP.get(brand_raw)
        if not brand:
            brand = parts[0].capitalize()

        # Модель — всё после марки (может быть «Vesta 1.6» или «Rio III 1.6»)
        model = " ".join(parts[1:])

        if brand not in brands:
            brands[brand] = set()
        brands[brand].add(model)

    # Сортируем
    result_sorted = {b: sorted(list(models)) for b, models in sorted(brands.items())}
    return result_sorted


@app.get("/health")
async def health():
    return {"status": "ok"}
app = FastAPI(title="АвтоСклад — RAG Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)


class CarInfo(BaseModel):
    brand_model: Optional[str] = None
    year:        Optional[str] = None
    engine:      Optional[str] = None
    vin:         Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    car: Optional[CarInfo] = None


class ContactRequest(BaseModel):
    name:  str
    phone: Optional[str] = None
    email: Optional[str] = None
    topic: Optional[str] = None


class LoadRequest(BaseModel):
    secret:     str
    yandex_url: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/chat")
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    car_dict = req.car.model_dump() if req.car else None
    answer = await search_and_answer(req.message, car=car_dict)
    return {"answer": answer}


@app.post("/contacts")
async def save_contact(req: ContactRequest):
    """Сохраняет контакт из чат-бота в Supabase."""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Имя обязательно")
    if not req.phone and not req.email:
        raise HTTPException(status_code=400, detail="Нужен телефон или email")
    try:
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


@app.get("/health")
async def health():
    return {"status": "ok"}
