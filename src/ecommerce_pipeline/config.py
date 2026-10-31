"""Application settings loaded from environment variables (.env file)."""

import os
from dataclasses import dataclass
from urllib.parse import quote_plus

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    redis_host: str
    redis_port: int
    mongo_host: str
    mongo_port: int
    mongo_db: str
    mongo_user: str
    mongo_password: str

    @property
    def postgres_dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
            f"user={self.postgres_user} password={self.postgres_password}"
        )

    @property
    def mongo_uri(self) -> str:
        # Credentials are URL-encoded so characters like '@' or ':' can't break the URI.
        user = quote_plus(self.mongo_user)
        password = quote_plus(self.mongo_password)
        return f"mongodb://{user}:{password}@{self.mongo_host}:{self.mongo_port}/?authSource=admin"


def load_settings() -> Settings:
    """Read settings from the environment, loading .env first if present.

    Real environment variables take precedence over .env values, which lets
    tests and CI override individual settings (e.g. POSTGRES_DB).
    """
    load_dotenv()
    return Settings(
        postgres_host=os.getenv("POSTGRES_HOST", "localhost"),
        postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
        postgres_db=os.getenv("POSTGRES_DB", "ecommerce"),
        postgres_user=os.getenv("POSTGRES_USER", "ecommerce_user"),
        postgres_password=os.getenv("POSTGRES_PASSWORD", ""),
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        mongo_host=os.getenv("MONGO_HOST", "localhost"),
        mongo_port=int(os.getenv("MONGO_PORT", "27017")),
        mongo_db=os.getenv("MONGO_DB", "ecommerce_sessions"),
        mongo_user=os.getenv("MONGO_USER", "mongo_user"),
        mongo_password=os.getenv("MONGO_PASSWORD", ""),
    )
