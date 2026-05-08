"""Load prompt templates from disk."""
import os
from functools import lru_cache

from app.config import settings


@lru_cache(maxsize=32)
def load_prompt(filename: str) -> str:
    """Load a prompt template by filename from PROMPTS_DIR."""
    path = os.path.join(settings.PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
