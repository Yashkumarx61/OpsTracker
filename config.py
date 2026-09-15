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

    # SQLite database (file lives next to app.py by default)
    DB_PATH = os.getenv(
        "DB_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "opstracker.db"),
    )
