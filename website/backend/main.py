from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from routers import expenses, logs
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
app = FastAPI()
#CHANGE * IN ALLOW ORIGINS TO ACTUAL FRONTEND DOMAIN WHEN DEPLOY
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(expenses.router)
app.include_router(logs.router)


app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
