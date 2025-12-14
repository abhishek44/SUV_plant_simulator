# app/config.py
import os


class Settings:
    """
    Very simple settings holder.
    Reads DATABASE_URL from environment if present,
    otherwise defaults to local sqlite file.
    """

    def __init__(self) -> None:
        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:///./simulation.db")


settings = Settings()
