import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
from rag import search_and_answer
from loader import load_price_to_supabase

load_dotenv()

app = FastAPI(title="АвтоСклад — RAG Bot")

app.mount("/static", StaticFiles(directory="static"), name="static")


class CarInfo(BaseModel):
    brand_model: Optional[str] = None
    year:        Optional[str] = None
    engine:      Optional[str] = None
    vin:         Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    car: Optional[CarInfo] = None


class LoadRequest(BaseModel):
    secret:     str
    yandex_url: Optional[str] = None  # можно передать другую ссылку


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


@app.post("/admin/load")
async def load_price(req: LoadRequest):
    """
    Загружает прайс в Supabase.
    Источник: Яндекс Диск (из env YANDEX_DISK_URL или из req.yandex_url).
    Fallback: w_doc/price.xlsx
    """
    admin_secret = os.getenv("ADMIN_SECRET", "change-me-please")
    if req.secret != admin_secret:
        raise HTTPException(status_code=403, detail="Неверный секрет")
    result = await load_price_to_supabase(yandex_url=req.yandex_url)
    return result


@app.get("/health")
async def health():
    return {"status": "ok"}
