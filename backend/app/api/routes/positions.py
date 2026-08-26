from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/positions", tags=["positions"])


class PositionResponse(BaseModel):
    symbol: str
    quantity: int
    average_price: float
    pnl: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None


@router.get("", response_model=list[PositionResponse])
async def get_positions(request: Request, current_user: User = Depends(get_current_user)):
    """Get live positions directly from the broker."""
    broker = request.app.state.broker
    try:
        raw_positions = await broker.get_positions()
        # Transform broker-specific positions into our response model
        # Zerodha returns a complex object, we'll map common fields here.
        
        # If it's a dict (like MockBroker might return), handle accordingly
        # MockBroker isn't implementing get_positions fully yet, so this might return empty list.
        if not isinstance(raw_positions, list):
            # Try to parse 'net' positions from Kite
            if isinstance(raw_positions, dict) and "net" in raw_positions:
                raw_positions = raw_positions["net"]
            else:
                raw_positions = []
                
        positions = []
        for pos in raw_positions:
            # Handle Kite format vs simple dict format
            symbol = pos.get("tradingsymbol", pos.get("symbol", "UNKNOWN"))
            quantity = pos.get("quantity", pos.get("net_quantity", 0))
            if quantity == 0:
                continue # Skip closed positions
                
            avg_price = pos.get("average_price", 0.0)
            pnl = pos.get("pnl", 0.0)
            realized = pos.get("realized", 0.0)
            unrealized = pos.get("unrealized", 0.0)
            
            positions.append(PositionResponse(
                symbol=symbol,
                quantity=quantity,
                average_price=avg_price,
                pnl=pnl,
                realized_pnl=realized,
                unrealized_pnl=unrealized
            ))
            
        return positions
    except Exception as e:
        # Don't crash the UI if broker is unreachable
        return []
