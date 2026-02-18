from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

from app.config import settings
from app import database as db
from app.utils.security import hash_password

from app.routers import whatsapp, customer, pharmacy, admin, medicines, auth

ALLOWED_ORIGINS = settings.CORS_ORIGINS + ["https://dashboardrerun.vercel.app"]
ALLOWED_ORIGINS = list(set(ALLOWED_ORIGINS))


class CORSPreflight(BaseHTTPMiddleware):
    """Catch OPTIONS preflight early — guarantees CORS headers on Vercel."""

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")
        if request.method == "OPTIONS":
            resp = Response(status_code=200)
            resp.headers["Access-Control-Allow-Origin"] = origin or "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Max-Age"] = "600"
            return resp
        response = await call_next(request)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown events."""
    # --- Startup: seed admin account if it doesn't exist ---
    try:
        existing = await db.get_admin_by_email(settings.ADMIN_EMAIL)
        if not existing:
            hashed = hash_password(settings.ADMIN_PASSWORD)
            await db.create_admin({
                "email": settings.ADMIN_EMAIL,
                "password_hash": hashed,
                "name": settings.ADMIN_NAME,
                "role": "admin",
            })
            logger.info(f"Admin account seeded: {settings.ADMIN_EMAIL}")
        else:
            logger.info("Admin account already exists, skipping seed.")
    except Exception as e:
        logger.error(f"Failed to seed admin account: {e}")

    yield
    # --- Shutdown ---
    logger.info("Application shutting down.")


app = FastAPI(
    title="RERUN Health AI",
    description="Two-sided marketplace connecting customers (WhatsApp) with pharmacies (dashboard) in Zimbabwe.",
    version="1.0.0",
    lifespan=lifespan,
)

# Custom preflight handler — must be added FIRST (outermost middleware)
app.add_middleware(CORSPreflight)

# Standard CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(whatsapp.router)
app.include_router(customer.router)
app.include_router(pharmacy.router)
app.include_router(admin.router)
app.include_router(medicines.router)
app.include_router(auth.router)


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy", "service": "RERUN Health AI", "version": "1.0.0"}


@app.get("/", tags=["Health"])
async def root():
    return {
        "message": "Welcome to RERUN Health AI API",
        "docs": "/docs",
        "health": "/health",
    }
