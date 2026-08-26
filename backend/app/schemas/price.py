from datetime import datetime

from pydantic import BaseModel


class PriceBar(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    model_config = {"from_attributes": True}
