"""
Logic for syncing Fitbit data for the single user.
Handles token refresh, data pulling, and exporting.
"""
import json
import logging
import os
import pandas as pd
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from fitbit import Fitbit

from backend.config import CLIENT_ID, CLIENT_SECRET, DATA_DIR
from backend.db import get_single_token, upsert_single_token

# Get logger
logger = logging.getLogger("fitbit_app.sync")


def get_fitbit_client(session: Session, token) -> Fitbit:
    """Helper to create an authenticated Fitbit client."""
    def refresh_cb(new_token: Dict[str, Any]) -> None:
        """Callback to update token in database when refreshed."""
        logger.info("Access token refreshed automatically")
        upsert_single_token(session, new_token)
    
    return Fitbit(
        CLIENT_ID,
        CLIENT_SECRET,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_at=token.expires_at,
        refresh_cb=refresh_cb,
    )


def sync_date_range(session: Session, start_date: date, end_date: date) -> Dict[str, Any]:
    """
    Sync Fitbit data for a range of dates.
    """
    logger.info(f"Starting date range sync: {start_date} to {end_date}")
    
    token = get_single_token(session)
    if not token:
        return {"status": "no_token", "message": "No Fitbit account connected."}
    
    try:
        fb = get_fitbit_client(session, token)
        data_path = Path(DATA_DIR) / "default"
        data_path.mkdir(parents=True, exist_ok=True)
        
        synced_days = []
        errors = []
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.isoformat()
            logger.info(f"Syncing data for {date_str}")
            
            try:
                # 1. Fetch Steps
                steps = fb.time_series("activities/steps", base_date=date_str, period="1d")
                with open(data_path / f"{date_str}_steps.json", "w") as f:
                    json.dump(steps, f, indent=2)
                
                # 2. Fetch Intraday Heart Rate
                try:
                    hr = fb.intraday_time_series("activities/heart", base_date=date_str, detail_level="1min")
                    with open(data_path / f"{date_str}_heartrate_1min.json", "w") as f:
                        json.dump(hr, f, indent=2)
                except Exception as e:
                    logger.warning(f"Failed to fetch heart rate for {date_str}: {e}")
                    errors.append(f"{date_str} HR: {str(e)}")

                synced_days.append(date_str)
                
            except Exception as e:
                logger.error(f"Failed to sync {date_str}: {e}")
                errors.append(f"{date_str}: {str(e)}")
            
            current_date += timedelta(days=1)
            
        return {
            "status": "ok",
            "synced_days": synced_days,
            "errors": errors,
            "count": len(synced_days)
        }

    except Exception as e:
        logger.error(f"Range sync failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def sync_single_user(session: Session) -> Dict[str, Any]:
    """Sync yesterday's data (backward compatibility)."""
    yesterday = date.today() - timedelta(days=1)
    result = sync_date_range(session, yesterday, yesterday)
    
    # Adapt result format to match what app.py expects for single-day sync
    if result["status"] == "ok":
        result["date"] = yesterday.isoformat()
        # Construct file list just for display compatibility
        result["files"] = [f"{yesterday.isoformat()}_steps.json"] 
    return result


def export_data(start_date: date, end_date: date, format: str = "csv") -> str:
    """
    Read JSON files for the date range, aggregate data, and save as CSV/Excel.
    Returns the path to the generated file.
    """
    logger.info(f"Exporting data from {start_date} to {end_date} as {format}")
    
    data_path = Path(DATA_DIR) / "default"
    export_dir = Path(DATA_DIR) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    
    all_records = []
    
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.isoformat()
        
        # Load Steps
        steps_val = 0
        steps_file = data_path / f"{date_str}_steps.json"
        if steps_file.exists():
            try:
                with open(steps_file) as f:
                    d = json.load(f)
                    # specific to fitbit response structure: {"activities-steps": [{"value": "123", ...}]}
                    if "activities-steps" in d and d["activities-steps"]:
                        steps_val = int(d["activities-steps"][0].get("value", 0))
            except Exception:
                pass

        # Load Resting Heart Rate (from intraday file structure if available)
        resting_hr = None
        hr_file = data_path / f"{date_str}_heartrate_1min.json"
        if hr_file.exists():
            try:
                with open(hr_file) as f:
                    d = json.load(f)
                    # {"activities-heart": [{"value": {"restingHeartRate": 60, ...}}]}
                    if "activities-heart" in d and d["activities-heart"]:
                         resting_hr = d["activities-heart"][0].get("value", {}).get("restingHeartRate")
            except Exception:
                pass
        
        all_records.append({
            "Date": date_str,
            "Steps": steps_val,
            "RestingHR": resting_hr
        })
        
        current_date += timedelta(days=1)
    
    # Create DataFrame
    df = pd.DataFrame(all_records)
    
    # Save file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"fitbit_export_{start_date}_{end_date}_{timestamp}.{format}"
    output_path = export_dir / filename
    
    if format == "csv":
        df.to_csv(output_path, index=False)
    elif format == "xlsx":
        df.to_excel(output_path, index=False)
    else:
        raise ValueError("Unsupported format")
        
    logger.info(f"Export saved to {output_path}")
    return str(output_path)
