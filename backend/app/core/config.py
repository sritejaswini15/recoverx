"""RecoverX Settings via plain environment variables (pydantic-settings not required)."""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME: str = "RecoverX"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    SEED_DEMO_DATA: bool = os.getenv("SEED_DEMO_DATA", "true").lower() == "true"

    # Database & Cache
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Auth & Security
    AUTH_SECRET: str = os.getenv("AUTH_SECRET", "recoverx-local-development-secret")
    AUTH_REQUIRED: bool = os.getenv("AUTH_REQUIRED", "true").lower() == "true"
    ACCESS_TOKEN_TTL_SECONDS: int = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "28800"))
    PAYMENT_LINK_TTL_HOURS: int = int(os.getenv("PAYMENT_LINK_TTL_HOURS", "72"))
    BOOTSTRAP_ADMIN_EMAIL: str | None = os.getenv("BOOTSTRAP_ADMIN_EMAIL")
    BOOTSTRAP_ADMIN_PASSWORD: str | None = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
    BOOTSTRAP_ORGANIZATION_NAME: str = os.getenv("BOOTSTRAP_ORGANIZATION_NAME", "RecoverX Merchant")
    BOOTSTRAP_RAZORPAY_ACCOUNT_ID: str | None = os.getenv("BOOTSTRAP_RAZORPAY_ACCOUNT_ID")

    # Razorpay Provider & Webhook
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "rzp_test_simulated_key")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "rzp_test_simulated_secret")
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "recoverx_webhook_secret_key_2026")
    PAYMENT_PROVIDER: str = os.getenv("PAYMENT_PROVIDER", "simulated").lower()

    # AI & LLM
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "deterministic")
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")

    # Communications
    WHATSAPP_PROVIDER_TOKEN: str | None = os.getenv("WHATSAPP_PROVIDER_TOKEN")
    EMAIL_PROVIDER_API_KEY: str | None = os.getenv("EMAIL_PROVIDER_API_KEY")

    # Temporal
    TEMPORAL_HOST: str = os.getenv("TEMPORAL_HOST", "localhost:7233")
    TEMPORAL_NAMESPACE: str = os.getenv("TEMPORAL_NAMESPACE", "default")
    TEMPORAL_API_KEY: str | None = os.getenv("TEMPORAL_API_KEY")
    TEMPORAL_ENABLED: bool = os.getenv("TEMPORAL_ENABLED", "false").lower() == "true"
    TEMPORAL_TASK_QUEUE: str = os.getenv("TEMPORAL_TASK_QUEUE", "recoverx-recovery")

    # Policy Defaults
    DEFAULT_MAX_AUTO_ACTION_AMOUNT: int = 25000
    DEFAULT_HUMAN_APPROVAL_THRESHOLD: int = 25000
    DEFAULT_MAX_CONTACT_ATTEMPTS: int = 3
    DEFAULT_ESCALATE_AFTER_DAYS: int = 7
    DEFAULT_MIN_AI_CONFIDENCE: float = 0.70
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]

    def validate_production(self) -> None:
        """Fail closed: production never runs with example credentials."""
        if self.ENVIRONMENT.lower() != "production":
            return
        invalid = []
        if not self.AUTH_SECRET or self.AUTH_SECRET == "recoverx-local-development-secret":
            invalid.append("AUTH_SECRET")
        if not self.RAZORPAY_WEBHOOK_SECRET or self.RAZORPAY_WEBHOOK_SECRET == "recoverx_webhook_secret_key_2026":
            invalid.append("RAZORPAY_WEBHOOK_SECRET")
        if not self.BOOTSTRAP_ADMIN_EMAIL or not self.BOOTSTRAP_ADMIN_PASSWORD:
            invalid.append("BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD")
        if self.BOOTSTRAP_ADMIN_PASSWORD and len(self.BOOTSTRAP_ADMIN_PASSWORD) < 16:
            invalid.append("BOOTSTRAP_ADMIN_PASSWORD (minimum 16 characters)")
        if invalid:
            raise RuntimeError("Production configuration is incomplete: " + ", ".join(invalid))


settings = Settings()
