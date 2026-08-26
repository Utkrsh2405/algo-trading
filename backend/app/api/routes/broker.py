import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from kiteconnect import KiteConnect

from app.core.config import settings
from app.db.session import get_db
from app.services.broker.zerodha import ZerodhaBroker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/broker", tags=["broker"])

# In a full implementation, you would store the access_token in the database
# associated with the user. For Phase 2 scaffolding, we'll store it globally
# in memory or let the ZerodhaBroker instance hold it.
# We will assume a single-user system for the vibe-coding phase.

_global_access_token: str | None = None


@router.get("/login")
def broker_login():
    """Redirects the user to the Zerodha login page."""
    if not settings.KITE_API_KEY:
        raise HTTPException(status_code=500, detail="KITE_API_KEY not configured")

    kite = KiteConnect(api_key=settings.KITE_API_KEY)
    login_url = kite.login_url()
    return RedirectResponse(url=login_url)


@router.get("/callback")
async def broker_callback(
    request: Request,
    request_token: str = Query(...),
    action: str | None = Query(None),
    status: str | None = Query(None)
):
    """Handles the redirect from Zerodha after successful login."""
    global _global_access_token

    if status != "success" and action == "login":
        raise HTTPException(status_code=400, detail="Login failed or was cancelled")

    if not settings.KITE_API_KEY or not settings.KITE_API_SECRET:
        raise HTTPException(status_code=500, detail="KITE API credentials not fully configured")

    try:
        kite = KiteConnect(api_key=settings.KITE_API_KEY)
        data = kite.generate_session(request_token, api_secret=settings.KITE_API_SECRET)
        _global_access_token = data["access_token"]
        
        logger.info("Successfully generated Kite Connect access token.")
        
        # Inject the token into the running broker and start the feed
        feed = request.app.state.price_feed
        if isinstance(feed._broker, ZerodhaBroker):
            feed._broker.kite.set_access_token(_global_access_token)
            
            # DEFAULT_SYMBOLS should ideally be configurable, for now we use a hardcoded list
            # just to start the stream.
            await feed.start(["RELIANCE", "TCS", "INFY"])

        return {"status": "success", "message": "Broker authenticated successfully."}
    except Exception as e:
        logger.error(f"Failed to generate session: {e}")
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

def get_access_token() -> str | None:
    return _global_access_token
