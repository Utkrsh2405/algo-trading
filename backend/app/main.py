from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, health, prices, broker, orders
from app.core.config import settings
from app.services.broker.mock import MockBroker
from app.services.broker.zerodha import ZerodhaBroker
from app.services.broker.exceptions import BrokerAuthError
from app.services.price_feed import PriceFeedService
import logging

from app.services.strategy_engine import StrategyEngine

# Default watchlist for the mock feed until a real broker + strategy config
# picks the symbol universe. Swap MockBroker for a real BrokerInterface
# implementation once Phase 2 (broker connector) lands.
DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "INFY"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.KITE_API_KEY and settings.KITE_API_SECRET:
        logging.getLogger(__name__).info("Using ZerodhaBroker for live connection.")
        broker_instance = ZerodhaBroker(settings.KITE_API_KEY, settings.KITE_API_SECRET)
    else:
        broker_instance = MockBroker()

    feed = PriceFeedService(broker_instance)
    engine = StrategyEngine(feed)
    
    app.state.price_feed = feed
    app.state.strategy_engine = engine
    
    try:
        await feed.start(DEFAULT_SYMBOLS)
    except BrokerAuthError:
        logging.getLogger(__name__).warning("Broker not authenticated. Start price feed manually after login.")
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to start price feed: {e}")
        
    yield
    await feed.stop()


app = FastAPI(title="Algo Trading Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(prices.router)
app.include_router(broker.router)
app.include_router(orders.router)
