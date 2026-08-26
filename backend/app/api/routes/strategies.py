from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Any

from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


class StrategyStateResponse(BaseModel):
    id: str
    name: str
    is_running: bool
    status_message: str
    config: dict[str, Any]


@router.get("", response_model=list[StrategyStateResponse])
async def list_strategies(request: Request, current_user: User = Depends(get_current_user)):
    """List all available strategies and their current state."""
    engine = request.app.state.strategy_engine
    return [strat.get_state() for strat in engine.strategies.values()]


@router.post("/{strategy_id}/start")
async def start_strategy(strategy_id: str, request: Request, current_user: User = Depends(get_current_user)):
    """Start a specific strategy."""
    engine = request.app.state.strategy_engine
    strat = engine.get_strategy(strategy_id)
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
        
    strat.start()
    return {"status": "started", "strategy": strat.get_state()}


@router.post("/{strategy_id}/stop")
async def stop_strategy(strategy_id: str, request: Request, current_user: User = Depends(get_current_user)):
    """Stop a specific strategy."""
    engine = request.app.state.strategy_engine
    strat = engine.get_strategy(strategy_id)
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
        
    strat.stop(reason="Stopped via API")
    return {"status": "stopped", "strategy": strat.get_state()}
