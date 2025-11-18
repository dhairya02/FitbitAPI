"""
Configuration module for Fitbit Single-User application.
Loads environment variables and validates required settings.
"""
import os
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# Required environment variables
CLIENT_ID = os.getenv("FITBIT_CLIENT_ID")
CLIENT_SECRET = os.getenv("FITBIT_CLIENT_SECRET")

# Validate required settings
if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError(
        "Missing required Fitbit credentials. Please set the following environment variables:\n"
        "  - FITBIT_CLIENT_ID: Your Fitbit app's Client ID\n"
        "  - FITBIT_CLIENT_SECRET: Your Fitbit app's Client Secret\n\n"
        "You can get these from the Fitbit Developer Portal (https://dev.fitbit.com/apps).\n"
        "See the Help page in the app or README.md for detailed instructions."
    )

# Optional configuration with defaults
REDIRECT_URI = os.getenv("FITBIT_REDIRECT_URI", "http://localhost:5000/fitbit/callback")
SCOPES_STR = os.getenv("FITBIT_SCOPES", "activity heartrate sleep weight profile")
SCOPES: List[str] = SCOPES_STR.split()

SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///fitbit_singleuser.db")
DATA_DIR = os.getenv("FITBIT_DATA_DIR", "fitbit_data")

# Flask configuration
FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "True").lower() in ("true", "1", "yes")

