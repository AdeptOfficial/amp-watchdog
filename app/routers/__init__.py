from app.routers.api import partials as partials_router
from app.routers.api import router as api_router
from app.routers.pages import router as pages_router
from app.routers.sse import router as sse_router

__all__ = ["api_router", "partials_router", "pages_router", "sse_router"]
