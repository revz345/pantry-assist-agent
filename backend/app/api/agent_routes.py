from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.services.agent import run_agent_cycle

settings = get_settings()
router = APIRouter(tags=["agent"])


@router.post("/run")
async def trigger_agent_run(session: Session = Depends(get_session)):
    """Manually trigger an agent cycle (dev only)."""
    if not settings.debug:
        raise HTTPException(status_code=403, detail="Only available in debug mode")
    result = await run_agent_cycle(session)
    return {"status": "completed", "result": result, "timestamp": datetime.utcnow()}


@router.get("/status")
async def agent_status():
    """Get agent status - last run, next scheduled, recent actions."""
    from app.main import get_agent_scheduler_state

    state = get_agent_scheduler_state()
    return {
        "enabled": settings.agent_enabled,
        "interval_minutes": settings.agent_interval_minutes,
        "scheduler_running": state.get("running", False),
        "last_run": state.get("last_run"),
        "next_run": state.get("next_run"),
        "recent_actions": [],
    }
