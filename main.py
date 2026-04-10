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


@app.get("/health")
async def health():
    return {"status": "ok"}
