from fastapi import APIRouter, Query
from pathlib import Path
from datetime import date as date_cls

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR.parent.parent.parent / "logs" / "trading_bot.log"

def parse_line(line: str) -> dict:
    parts = line.split(" - ")
    if len(parts) >= 3:
        return {
            "time": parts[0].strip(),
            "level": parts[1].strip(),
            "message": " - ".join(parts[2:]).strip(),
        }
    return {"time": "", "level": "", "message": line.strip()}

@router.get("/api/tradelogs")
def get_trade_logs(date: str = Query(default=None)):
    target_date = date or date_cls.today().isoformat()

    if not LOG_FILE.exists():
        return {"logs": [], "date": target_date}

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    matching = [l for l in lines if l.startswith(target_date)]
    matching.reverse()
    return {"logs": [parse_line(l) for l in matching], "date": target_date}