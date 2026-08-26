from datetime import datetime

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.price_history import PriceHistory
from app.schemas.price import PriceBar
from app.services.connection_manager import price_connection_manager

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("/{symbol}/history", response_model=list[PriceBar])
def get_price_history(
    symbol: str,
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=1000, le=10_000),
    db: Session = Depends(get_db),
):
    query = db.query(PriceHistory).filter(PriceHistory.symbol == symbol)
    if start is not None:
        query = query.filter(PriceHistory.timestamp >= start)
    if end is not None:
        query = query.filter(PriceHistory.timestamp <= end)
    return query.order_by(PriceHistory.timestamp.asc()).limit(limit).all()


@router.websocket("/ws")
async def prices_ws(websocket: WebSocket):
    """Streams every live quote as {"type": "quote", "symbol", "last_price", "timestamp"}."""
    await price_connection_manager.connect(websocket)
    try:
        while True:
            # Client isn't expected to send anything; this just detects disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await price_connection_manager.disconnect(websocket)
