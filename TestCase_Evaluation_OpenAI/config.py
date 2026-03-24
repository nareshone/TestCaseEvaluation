"""
config.py — Load all configuration from .env file
"""
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    FAISS_STORE_PATH: str = os.getenv("FAISS_STORE_PATH", "data/faiss_store")
    CLEAR_DB_ON_STARTUP: bool = os.getenv("CLEAR_DB_ON_STARTUP", "true").lower() == "true"
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "outputs")

    def validate(self) -> list[str]:
        errors = []
        if not self.OPENAI_API_KEY or self.OPENAI_API_KEY.startswith("sk-your"):
            errors.append("OPENAI_API_KEY is not set in .env")
        return errors

    def clear_vector_store(self):
        """Delete FAISS store directory contents (called on startup or new session)."""
        path = Path(self.FAISS_STORE_PATH)
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    def ensure_dirs(self):
        Path(self.FAISS_STORE_PATH).mkdir(parents=True, exist_ok=True)
        Path(self.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


settings = Settings()
