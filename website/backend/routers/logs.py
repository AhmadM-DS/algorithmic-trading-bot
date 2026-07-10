from fastapi import APIRouter
from pathlib import Path

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR.parent.parent.parent / "logs" / "trading_bot.log"
MAX_LINES = 50

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
def get_trade_logs():
    if not LOG_FILE.exists():
        return {"logs": []}
    
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    
    recent = lines[-MAX_LINES:]
    recent.reverse()
    return {"logs": [parse_line(l) for l in recent]}