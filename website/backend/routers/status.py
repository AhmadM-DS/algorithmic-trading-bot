from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from fastapi import APIRouter
from database import get_connection, run_query

router = APIRouter()

HEARTBEAT_STALE_AFTER = timedelta(minutes=5)
EASTERN = ZoneInfo("America/New_York")

PRE_MARKET_START = dtime(4, 0)
REGULAR_START = dtime(9, 30)
REGULAR_END = dtime(16, 0)
POST_MARKET_END = dtime(20, 0)


def is_regular_market_hours(now_et: datetime) -> bool:
    t = now_et.time()
    return REGULAR_START <= t < REGULAR_END


@router.get("/api/status")
def get_status():
    # If this handler runs at all, the API responded.
    server_status = "green"

    db_status = "red"
    bot_status = "red"
    try:
        with get_connection() as conn:
            db_status = "green"
            rows = run_query(conn, "SELECT Last_Heartbeat FROM BotStatus WHERE Bot_Status_ID = 1;")
            if rows:
                last_heartbeat = rows[0]["Last_Heartbeat"]
                is_fresh = (datetime.utcnow() - last_heartbeat) < HEARTBEAT_STALE_AFTER
                if is_fresh:
                    now_et = datetime.now(EASTERN)
                    bot_status = "green" if is_regular_market_hours(now_et) else "yellow"
                else:
                    bot_status = "red"
    except Exception:
        db_status = "red"
        bot_status = "red"

    return {
        "bot": bot_status,
        "server": server_status,
        "webHost": db_status,
    }
