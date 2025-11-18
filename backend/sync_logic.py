"""
Logic for syncing Fitbit data for the single user.
Handles token refresh and data pulling.
"""
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Any, Callable
from sqlalchemy.orm import Session
from fitbit import Fitbit

from backend.config import CLIENT_ID, CLIENT_SECRET, DATA_DIR
from backend.db import get_single_token, upsert_single_token


def sync_single_user(session: Session) -> Dict[str, Any]:
    """
    Sync Fitbit data for the single connected user.
    
    Pulls yesterday's steps summary and heart rate intraday data (1-minute).
    Automatically refreshes tokens if expired.
    
    Args:
        session: SQLAlchemy session
        
    Returns:
        Dictionary with sync results:
        - status: "ok", "no_token", or "error"
        - date: ISO date string (if successful)
        - files: List of saved file paths (if successful)
        - error: Error message (if status="error")
    """
    # Check if we have a token stored
    token = get_single_token(session)
    if not token:
        return {
            "status": "no_token",
            "message": "No Fitbit account connected. Please connect your Fitbit account first."
        }
    
    try:
        # Create refresh callback to update tokens
        def refresh_cb(new_token: Dict[str, Any]) -> None:
            """Callback to update token in database when refreshed."""
            upsert_single_token(session, new_token)
        
        # Initialize Fitbit client
        fb = Fitbit(
            CLIENT_ID,
            CLIENT_SECRET,
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            expires_at=token.expires_at,
            refresh_cb=refresh_cb,
        )
        
        # Calculate yesterday's date
        yesterday = date.today() - timedelta(days=1)
        date_str = yesterday.isoformat()
        
        # Prepare data directory
        data_path = Path(DATA_DIR) / "default"
        data_path.mkdir(parents=True, exist_ok=True)
        
        saved_files = []
        
        # Fetch steps summary for yesterday
        steps = fb.time_series(
            resource="activities/steps",
            base_date=date_str,
            period="1d",
        )
        steps_file = data_path / f"{date_str}_steps.json"
        with open(steps_file, "w") as f:
            json.dump(steps, f, indent=2)
        saved_files.append(str(steps_file))
        
        # Fetch heart rate intraday data (1-minute resolution)
        # NOTE: Intraday data requires:
        # 1. "heartrate" scope in your OAuth scopes
        # 2. Intraday data access enabled in your Fitbit app settings
        #    (Application Type must be "Personal" or you need special permission for "Server" apps)
        try:
            hr = fb.intraday_time_series(
                resource="activities/heart",
                base_date=date_str,
                detail_level="1min",
            )
            hr_file = data_path / f"{date_str}_heartrate_1min.json"
            with open(hr_file, "w") as f:
                json.dump(hr, f, indent=2)
            saved_files.append(str(hr_file))
        except Exception as hr_error:
            # If intraday fails, log it but don't fail the entire sync
            error_msg = str(hr_error)
            error_file = data_path / f"{date_str}_heartrate_error.txt"
            with open(error_file, "w") as f:
                f.write(f"Heart rate intraday fetch failed:\n{error_msg}\n\n")
                f.write("This usually means:\n")
                f.write("1. Your app doesn't have 'heartrate' scope\n")
                f.write("2. Your app doesn't have intraday access enabled\n")
                f.write("3. The Fitbit API application type is 'Server' without special permission\n")
            saved_files.append(f"Error: {error_msg} (see {error_file})")
        
        return {
            "status": "ok",
            "date": date_str,
            "files": saved_files,
            "fitbit_user_id": token.fitbit_user_id,
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
        }

