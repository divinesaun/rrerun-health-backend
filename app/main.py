from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app import database as db
from app.utils.security import hash_password

from app.routers import whatsapp, customer, pharmacy, admin, medicines, auth


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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
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
