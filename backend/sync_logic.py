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
from backend.db import get_single_token, upsert_single_token

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


def get_fitbit_client(session: Session, token) -> Fitbit:
    def refresh_cb(new_token: Dict[str, Any]) -> None:
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


# ----------------------------------------------------------------------------
# Sync operations
# ----------------------------------------------------------------------------

def sync_date_range(
    session: Session,
    start_date: date,
    end_date: date,
    resources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    resources = normalize_resources(resources)
    logger.info(f"Starting date range sync: {start_date} to {end_date}, resources={resources}")

    token = get_single_token(session)
    if not token:
        return {"status": "no_token", "message": "No Fitbit account connected."}

    data_root = resolve_path(DATA_DIR)
    data_path = (data_root / "default").resolve()
    data_path.mkdir(parents=True, exist_ok=True)

    try:
        fb = get_fitbit_client(session, token)
        synced_days: List[str] = []
        errors: List[str] = []

        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.isoformat()
            logger.info(f"Syncing data for {date_str}")

            try:
                if "steps" in resources:
                    steps = fb.time_series("activities/steps", base_date=date_str, period="1d")
                    with open(data_path / f"{date_str}_steps.json", "w") as f:
                        json.dump(steps, f, indent=2)

                if "heartrate" in resources:
                    try:
                        hr = fb.intraday_time_series(
                            "activities/heart", base_date=date_str, detail_level="1min"
                        )
                        with open(data_path / f"{date_str}_heartrate_1min.json", "w") as f:
                            json.dump(hr, f, indent=2)
                    except Exception as hr_error:
                        logger.warning(f"Failed to fetch heart rate for {date_str}: {hr_error}")
                        errors.append(f"{date_str} HR: {hr_error}")

                if "sleep" in resources:
                    try:
                        sleep = fb.get_sleep(date=current_date)
                        with open(data_path / f"{date_str}_sleep.json", "w") as f:
                            json.dump(sleep, f, indent=2)
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
                logger.error(f"Failed to sync {date_str}: {e}")
                errors.append(f"{date_str}: {e}")

            current_date += timedelta(days=1)

        if "profile" in resources:
            try:
                profile = fb.user_profile_get()
                with open(data_path / "user_profile.json", "w") as f:
                    json.dump(profile, f, indent=2)
            except Exception as profile_error:
                logger.warning(f"Failed to fetch profile: {profile_error}")
                errors.append(f"Profile: {profile_error}")

        return {
            "status": "ok",
            "synced_days": synced_days,
            "errors": errors,
            "count": len(synced_days),
        }

    except Exception as e:
        logger.error(f"Range sync failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def sync_single_user(session: Session, resources: Optional[List[str]] = None) -> Dict[str, Any]:
    yesterday = date.today() - timedelta(days=1)
    result = sync_date_range(session, yesterday, yesterday, resources=resources)

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
    resources: Optional[List[str]] = None,
) -> str:
    resources = normalize_resources(resources or ALL_RESOURCES)
    logger.info(f"Exporting data {start_date} -> {end_date} as {format} | resources={resources}")

    data_root = resolve_path(DATA_DIR)
    data_path = (data_root / "default").resolve()
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
            hr_file = data_path / f"{date_str}_heartrate_1min.json"
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
    filename = f"fitbit_export_{start_date}_{end_date}_{timestamp}.{format}"
    output_path = (export_dir / filename).resolve()

    if format == "csv":
        df.to_csv(output_path, index=False)
    elif format == "xlsx":
        df.to_excel(output_path, index=False)
    else:
        raise ValueError("Unsupported format")

    logger.info(f"Export saved to {output_path}")
    return str(output_path)
