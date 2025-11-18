"""
Logic for syncing Fitbit data for the single user.
Handles token refresh, data pulling, and exporting.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd
from fitbit import Fitbit
from sqlalchemy.orm import Session

from backend.config import CLIENT_ID, CLIENT_SECRET, DATA_DIR
from backend.db import get_token_for_participant, upsert_token_for_participant, get_participant

# ----------------------------------------------------------------------------
# Path + resource helpers
# ----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


RESOURCE_LABELS = {
    "steps": "Steps",
    "heartrate": "Heart Rate",
    "sleep": "Sleep",
    "weight": "Weight",
    "profile": "Profile",
}
ALL_RESOURCES = list(RESOURCE_LABELS.keys())
DEFAULT_RESOURCES = ["steps", "heartrate"]


def normalize_resources(resources: Optional[List[str]]) -> List[str]:
    if not resources:
        return DEFAULT_RESOURCES.copy()
    normalized = [r.lower() for r in resources if r]
    if "all" in normalized:
        return ALL_RESOURCES.copy()
    filtered = [r for r in ALL_RESOURCES if r in normalized]
    return filtered or DEFAULT_RESOURCES.copy()


# ----------------------------------------------------------------------------
# Fitbit client + logging helpers
# ----------------------------------------------------------------------------
logger = logging.getLogger("fitbit_app.sync")


def get_fitbit_client(session: Session, token, participant) -> Fitbit:
    """Create Fitbit client using shared app credentials."""
    def refresh_cb(new_token: Dict[str, Any]) -> None:
        logger.info("Access token refreshed automatically")
        upsert_token_for_participant(session, token.participant_id, new_token)

    logger.debug(f"Creating Fitbit client for participant {participant.participant_id}")

    return Fitbit(
        CLIENT_ID,
        CLIENT_SECRET,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_at=token.expires_at,
        refresh_cb=refresh_cb,
    )


# ----------------------------------------------------------------------------
# Sync operations
# ----------------------------------------------------------------------------

def sync_date_range(
    session: Session,
    start_date: date,
    end_date: date,
    participant_id: str = "default",
    resources: Optional[List[str]] = None,
    granularity: str = "1min",
) -> Dict[str, Any]:
    resources = normalize_resources(resources)
    logger.info(f"Starting date range sync for {participant_id}: {start_date} to {end_date}, resources={resources}, granularity={granularity}")

    token = get_token_for_participant(session, participant_id)
    if not token:
        return {"status": "no_token", "message": f"No Fitbit account connected for participant '{participant_id}'."}

    participant = get_participant(session, participant_id)
    if not participant:
        return {"status": "error", "message": f"Participant '{participant_id}' not found in database."}

    data_root = resolve_path(DATA_DIR)
    data_path = (data_root / participant_id).resolve()
    data_path.mkdir(parents=True, exist_ok=True)

    try:
        fb = get_fitbit_client(session, token, participant)
        synced_days: List[str] = []
        errors: List[str] = []
        
        # Track rate limit info (will be populated from API responses)
        rate_limit_info = {
            "limit": None,
            "remaining": None,
            "reset_time": None,
        }

        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.isoformat()
            logger.info(f"Syncing data for {date_str}")
            
            # Add delay between requests to avoid rate limiting
            import time
            if current_date != start_date:  # Don't delay on first request
                time.sleep(1)  # 1 second between days

            try:
                if "steps" in resources:
                    # Daily summary
                    steps = fb.time_series("activities/steps", base_date=date_str, period="1d")
                    with open(data_path / f"{date_str}_steps_summary.json", "w") as f:
                        json.dump(steps, f, indent=2)
                    
                    # Try to extract rate limit info from the client's last response
                    try:
                        if hasattr(fb, 'client') and hasattr(fb.client, 'session'):
                            last_response = fb.client.session.last_response if hasattr(fb.client.session, 'last_response') else None
                            if last_response and hasattr(last_response, 'headers'):
                                rate_limit_info['limit'] = last_response.headers.get('Fitbit-Rate-Limit-Limit')
                                rate_limit_info['remaining'] = last_response.headers.get('Fitbit-Rate-Limit-Remaining')
                                rate_limit_info['reset_time'] = last_response.headers.get('Fitbit-Rate-Limit-Reset')
                    except Exception:
                        pass
                    
                    # Intraday data - use correct API method with time range
                    try:
                        steps_intraday = fb.intraday_time_series(
                            resource="activities/steps",
                            base_date=date_str,
                            detail_level=granularity,
                            start_time="00:00",
                            end_time="23:59"
                        )
                        with open(data_path / f"{date_str}_steps_intraday_{granularity}.json", "w") as f:
                            json.dump(steps_intraday, f, indent=2)
                        logger.debug(f"Steps intraday ({granularity}) saved for {date_str}")
                    except Exception as steps_intra_error:
                        logger.warning(f"Failed to fetch steps intraday for {date_str}: {steps_intra_error}")
                        # Continue even if intraday fails

                if "heartrate" in resources:
                    # Daily summary
                    try:
                        hr_summary = fb.time_series("activities/heart", base_date=date_str, period="1d")
                        with open(data_path / f"{date_str}_heartrate_summary.json", "w") as f:
                            json.dump(hr_summary, f, indent=2)
                    except Exception:
                        pass
                    
                    # Intraday data - use correct API method with time range
                    try:
                        hr_intraday = fb.intraday_time_series(
                            resource="activities/heart",
                            base_date=date_str,
                            detail_level=granularity,
                            start_time="00:00",
                            end_time="23:59"
                        )
                        with open(data_path / f"{date_str}_heartrate_intraday_{granularity}.json", "w") as f:
                            json.dump(hr_intraday, f, indent=2)
                        logger.debug(f"Heart rate intraday ({granularity}) saved for {date_str}")
                    except Exception as hr_error:
                        logger.warning(f"Failed to fetch heart rate intraday for {date_str}: {hr_error}")
                        errors.append(f"{date_str} HR Intraday: {hr_error}")

                if "sleep" in resources:
                    try:
                        sleep = fb.get_sleep(date=current_date)
                        with open(data_path / f"{date_str}_sleep.json", "w") as f:
                            json.dump(sleep, f, indent=2)
                        logger.debug(f"Sleep data saved for {date_str} (includes sleep stages)")
                    except Exception as sleep_error:
                        logger.warning(f"Failed to fetch sleep for {date_str}: {sleep_error}")
                        errors.append(f"{date_str} Sleep: {sleep_error}")

                if "weight" in resources:
                    try:
                        weight = fb.get_bodyweight(base_date=date_str, period="1d")
                        with open(data_path / f"{date_str}_weight.json", "w") as f:
                            json.dump(weight, f, indent=2)
                    except Exception as weight_error:
                        logger.warning(f"Failed to fetch weight for {date_str}: {weight_error}")
                        errors.append(f"{date_str} Weight: {weight_error}")

                synced_days.append(date_str)

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Failed to sync {date_str}: {error_msg}")
                
                # Check if it's a rate limit error
                if "retry-after" in error_msg.lower() or "rate" in error_msg.lower():
                    logger.warning(f"Rate limit hit at {date_str}. Consider reducing date range or adding delays.")
                    errors.append(f"{date_str}: Rate limited by Fitbit API")
                else:
                    errors.append(f"{date_str}: {error_msg}")

            current_date += timedelta(days=1)

        if "profile" in resources:
            try:
                profile = fb.user_profile_get()
                with open(data_path / "user_profile.json", "w") as f:
                    json.dump(profile, f, indent=2)
            except Exception as profile_error:
                logger.warning(f"Failed to fetch profile: {profile_error}")
                errors.append(f"Profile: {profile_error}")

        result = {
            "status": "ok",
            "synced_days": synced_days,
            "errors": errors,
            "count": len(synced_days),
            "rate_limit": rate_limit_info,
        }
        
        # Log rate limit status
        if rate_limit_info.get("remaining"):
            logger.info(f"Rate limit status: {rate_limit_info['remaining']}/{rate_limit_info['limit']} requests remaining")
        
        return result

    except Exception as e:
        logger.error(f"Range sync failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def sync_single_user(session: Session, participant_id: str = "default", 
                     resources: Optional[List[str]] = None, granularity: str = "1min") -> Dict[str, Any]:
    yesterday = date.today() - timedelta(days=1)
    result = sync_date_range(session, yesterday, yesterday, participant_id=participant_id, 
                            resources=resources, granularity=granularity)

    if result["status"] == "ok":
        result["date"] = yesterday.isoformat()
        result["files"] = [f"{yesterday.isoformat()}_steps.json"]
    return result


# ----------------------------------------------------------------------------
# Export helpers
# ----------------------------------------------------------------------------

def export_data(
    start_date: date,
    end_date: date,
    format: str = "csv",
    participant_id: str = "default",
    resources: Optional[List[str]] = None,
) -> str:
    resources = normalize_resources(resources or ALL_RESOURCES)
    logger.info(f"Exporting data for {participant_id}: {start_date} -> {end_date} as {format} | resources={resources}")

    data_root = resolve_path(DATA_DIR)
    data_path = (data_root / participant_id).resolve()
    export_dir = (data_root / "exports").resolve()
    export_dir.mkdir(parents=True, exist_ok=True)

    profile_cache: Dict[str, Any] = {}
    if "profile" in resources:
        profile_file = data_path / "user_profile.json"
        if profile_file.exists():
            try:
                user = json.load(profile_file.open()).get("user", {})
                profile_cache = {
                    "ProfileDisplayName": user.get("displayName"),
                    "ProfileAge": user.get("age"),
                    "ProfileGender": user.get("gender"),
                    "ProfileMemberSince": user.get("memberSince"),
                }
            except Exception:
                profile_cache = {}

    all_records: List[Dict[str, Any]] = []

    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.isoformat()
        record: Dict[str, Any] = {"Date": date_str}

        if "steps" in resources:
            steps_val = 0
            # Try summary file first (new naming), then old naming for backward compat
            steps_file = data_path / f"{date_str}_steps_summary.json"
            if not steps_file.exists():
                steps_file = data_path / f"{date_str}_steps.json"
            
            if steps_file.exists():
                try:
                    with open(steps_file) as f:
                        d = json.load(f)
                        if "activities-steps" in d and d["activities-steps"]:
                            steps_val = int(d["activities-steps"][0].get("value", 0))
                except Exception:
                    pass
            record["Steps"] = steps_val

        if "heartrate" in resources:
            resting_hr = None
            # Try summary file first (new naming), then old naming
            hr_file = data_path / f"{date_str}_heartrate_summary.json"
            if not hr_file.exists():
                hr_file = data_path / f"{date_str}_heartrate_1min.json"
            if not hr_file.exists():
                hr_file = data_path / f"{date_str}_heartrate.json"
            
            if hr_file.exists():
                try:
                    with open(hr_file) as f:
                        d = json.load(f)
                        if "activities-heart" in d and d["activities-heart"]:
                            resting_hr = d["activities-heart"][0].get("value", {}).get("restingHeartRate")
                except Exception:
                    pass
            record["RestingHR"] = resting_hr

        if "sleep" in resources:
            sleep_minutes = None
            sleep_efficiency = None
            sleep_file = data_path / f"{date_str}_sleep.json"
            if sleep_file.exists():
                try:
                    with open(sleep_file) as f:
                        d = json.load(f)
                        if "sleep" in d and d["sleep"]:
                            sleep_minutes = sum(item.get("minutesAsleep", 0) for item in d["sleep"])
                            main_sleep = max(d["sleep"], key=lambda x: x.get("minutesAsleep", 0))
                            sleep_efficiency = main_sleep.get("efficiency")
                except Exception:
                    pass
            record["SleepMinutes"] = sleep_minutes
            record["SleepEfficiency"] = sleep_efficiency

        if "weight" in resources:
            weight_val = None
            weight_file = data_path / f"{date_str}_weight.json"
            if weight_file.exists():
                try:
                    with open(weight_file) as f:
                        d = json.load(f)
                        entries = d.get("body-weight") or d.get("weight")
                        if entries:
                            entry = entries[0]
                            weight_val = (
                                entry.get("weight")
                                or entry.get("value")
                                or entry.get("bmi")
                                or entry.get("fat")
                            )
                except Exception:
                    pass
            record["Weight"] = weight_val

        if "profile" in resources and profile_cache:
            record.update(profile_cache)

        all_records.append(record)
        current_date += timedelta(days=1)

    df = pd.DataFrame(all_records)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"fitbit_export_{participant_id}_{start_date}_{end_date}_{timestamp}.{format}"
    output_path = (export_dir / filename).resolve()

    if format == "csv":
        df.to_csv(output_path, index=False)
    elif format == "xlsx":
        df.to_excel(output_path, index=False)
    else:
        raise ValueError("Unsupported format")

    logger.info(f"Export saved to {output_path}")
    return str(output_path)
