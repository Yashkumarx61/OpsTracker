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

    # MySQL database
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", 3306))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "opstracker")
