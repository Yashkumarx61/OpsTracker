"""
OpsTracker — Application Configuration
Loads environment variables from .env and exposes them as a Config class.
"""

import os
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv()


class Config:
    """Central configuration loaded from environment variables."""

    # Flask core
    SECRET_KEY = os.getenv("SECRET_KEY", "fallback-insecure-key-change-me")
    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

    # Session cookie hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("FLASK_ENV") == "production"

    # SQLite database (file lives in data/ directory for volume persistence)
    DB_PATH = os.getenv(
        "DB_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "opstracker.db"),
    )
