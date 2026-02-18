import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Database
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
    SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")

    # Twilio
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_NUMBER: str = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

    # OCR
    OCRSPACE_API_KEY: str = os.getenv("OCRSPACE_API_KEY", "helloworld")

    # OpenRouter (Step 3.5 Flash)
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    STEPFUN_MODEL: str = os.getenv("STEPFUN_MODEL", "stepfun/step-3.5-flash:free")

    # JWT
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))

    # Admin
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@rerun.health")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin-change-me")
    ADMIN_NAME: str = os.getenv("ADMIN_NAME", "RERUN Admin")

    # Gmail SMTP (App Password method)
    GMAIL_ADDRESS: str = os.getenv("GMAIL_ADDRESS", "")
    GMAIL_APP_PASSWORD: str = os.getenv("GMAIL_APP_PASSWORD", "")
    EMAIL_FROM_NAME: str = os.getenv("EMAIL_FROM_NAME", "RERUN Health")

    # Dashboard
    DASHBOARD_URL: str = os.getenv("DASHBOARD_URL", "https://dashboard.rerun.health")

    # App
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    API_VERSION: str = os.getenv("API_VERSION", "v1")
    CORS_ORIGINS: list = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")


settings = Settings()
