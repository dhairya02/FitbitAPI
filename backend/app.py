"""
Flask application for Fitbit Single-User data ingestion.
Handles OAuth flow, dashboard, exports, and data sync.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import webbrowser
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from fitbit.api import FitbitOauth2Client
from sqlalchemy.orm import Session as DBSession

from backend.config import (
    CLIENT_ID,
    CLIENT_SECRET,
    REDIRECT_URI,
    SCOPES,
    SECRET_KEY,
    FLASK_HOST,
    FLASK_PORT,
    FLASK_DEBUG,
    LOG_DIR,
    LOG_FILE,
    LOG_LEVEL,
)
from backend.db import (
    init_db,
    SessionLocal,
    get_single_token,
    upsert_single_token,
    create_participant,
    get_participant,
    get_all_participants,
    get_token_for_participant,
    upsert_token_for_participant,
    disconnect_participant,
    delete_participant,
)
from backend.sync_logic import (
    DEFAULT_RESOURCES,
    RESOURCE_LABELS,
    normalize_resources,
    export_data,
    sync_date_range,
    sync_single_user,
)

# -----------------------------------------------------------------------------
# Path + logging helpers
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


log_dir = resolve_path(LOG_DIR)
log_dir.mkdir(parents=True, exist_ok=True)
log_path = (log_dir / LOG_FILE).resolve()

logger = logging.getLogger("fitbit_app")
logger.setLevel(getattr(logging, LOG_LEVEL))

file_handler = logging.FileHandler(log_path)
file_handler.setLevel(getattr(logging, LOG_LEVEL))
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")
)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

logger.info("=" * 60)
logger.info("Fitbit Single-User Data Ingestion App Starting")
logger.info("=" * 60)
logger.info(f"Log file: {log_path}")
logger.info(f"Log level: {LOG_LEVEL}")

# -----------------------------------------------------------------------------
# Flask app setup
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

try:
    init_db()
    logger.info("Database initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize database: {e}", exc_info=True)
    raise

RESOURCE_OPTIONS = [
    {"key": key, "label": label}
    for key, label in RESOURCE_LABELS.items()
]


# -----------------------------------------------------------------------------
# Helper utilities
# -----------------------------------------------------------------------------
def get_db() -> DBSession:
    return SessionLocal()


def get_selected_resources(raw_values: List[str]) -> List[str]:
    if not raw_values:
        raw_values = session.get("selected_resources") or DEFAULT_RESOURCES.copy()
    session["selected_resources"] = raw_values
    return raw_values


def get_current_participant() -> Optional[str]:
    """Get the currently selected participant ID from session."""
    return session.get("current_participant_id")


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/")
def dashboard():
    logger.debug("Dashboard accessed")
    db = get_db()
    try:
        # Get all participants and current selection
        participants = get_all_participants(db)
        
        # If no participants exist, show welcome screen
        if not participants:
            logger.info("No participants found")
            return render_template(
                "dashboard.html",
                token=None,
                participants=[],
                current_participant_id=None,
                sync_status=None,
                sync_message=None,
                sync_date=None,
                default_date=(date.today() - timedelta(days=1)).isoformat(),
                resource_options=RESOURCE_OPTIONS,
                selected_resources=DEFAULT_RESOURCES.copy(),
            )
        
        current_pid = get_current_participant()
        
        # If no current participant selected, or current one doesn't exist, select first
        if not current_pid or not any(p.participant_id == current_pid for p in participants):
            logger.info(f"Selecting first participant: {participants[0].participant_id}")
            current_pid = participants[0].participant_id
            session["current_participant_id"] = current_pid
        
        # Get token for current participant
        token = get_token_for_participant(db, current_pid)
        
        sync_status = request.args.get("sync_status")
        sync_message = request.args.get("sync_message")
        sync_date = request.args.get("sync_date")

        yesterday = date.today() - timedelta(days=1)
        selected_resources = session.get("selected_resources") or DEFAULT_RESOURCES.copy()
        
        # Get rate limit info and last sync results from session
        rate_limit_info = session.get("rate_limit_info", {})
        last_sync_results = session.get("last_sync_results", {})

        return render_template(
            "dashboard.html",
            token=token,
            participants=participants,
            current_participant_id=current_pid,
            sync_status=sync_status,
            sync_message=sync_message,
            sync_date=sync_date,
            default_date=yesterday.isoformat(),
            resource_options=RESOURCE_OPTIONS,
            selected_resources=selected_resources,
            rate_limit_info=rate_limit_info,
            last_sync_results=last_sync_results,
        )
    finally:
        db.close()


@app.route("/help")
def help_page():
    return render_template("help.html", redirect_uri=REDIRECT_URI, scopes=" ".join(SCOPES))


@app.route("/fitbit/authorize")
def fitbit_authorize():
    """Initiate OAuth for currently selected participant."""
    current_pid = get_current_participant()
    if not current_pid:
        return redirect(url_for("dashboard", sync_status="error", 
                              sync_message="No participant selected. Please add a participant first."))
    
    logger.info(f"Initiating Fitbit OAuth authorization for participant: {current_pid}")
    logger.info(f"Using shared app credentials (Client ID: {CLIENT_ID[:10]}...)")
    
    # Clear only OAuth state, keep participant selection
    session.pop("oauth_state", None)

    try:
        oauth = FitbitOauth2Client(CLIENT_ID, CLIENT_SECRET, redirect_uri=REDIRECT_URI)
        url, state = oauth.authorize_token_url(scope=SCOPES)
        
        # Force Fitbit to show login screen (don't auto-login with existing session)
        # Add prompt=login to force re-authentication
        if "?" in url:
            url += "&prompt=login"
        else:
            url += "?prompt=login"
        
        session["oauth_state"] = state
        session["oauth_participant_id"] = current_pid  # Remember which participant is authorizing
        logger.info(f"Redirecting to Fitbit authorization for {current_pid} (state: {state[:10]}...) - forcing login prompt")
        return redirect(url)
    except Exception as e:
        logger.error(f"Failed to initiate OAuth: {e}", exc_info=True)
        raise


@app.route("/fitbit/callback")
def fitbit_callback():
    logger.info("OAuth callback received")
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        error_desc = request.args.get("error_description", "No additional details provided.")
        logger.error(f"Fitbit OAuth error: {error} - {error_desc}")
        return render_template(
            "error.html",
            title="Fitbit Authorization Failed",
            message=f"Fitbit returned an error: {error}",
            details=error_desc,
        ), 400

    stored_state = session.get("oauth_state")
    if not state or not stored_state or state != stored_state:
        logger.error(
            "OAuth state mismatch. received=%s expected=%s",
            state[:10] if state else "None",
            stored_state[:10] if stored_state else "None",
        )
        session.clear()
        return render_template(
            "error.html",
            title="OAuth State Mismatch",
            message="Security validation failed. The session state didn't match.",
            details="We've cleared your session. Please try connecting again.",
        ), 400

    if not code:
        logger.error("No authorization code received from Fitbit")
        return render_template(
            "error.html",
            title="Missing Authorization Code",
            message="No authorization code received from Fitbit.",
            details="Please try the authorization process again.",
        ), 400

    try:
        # Get participant ID from OAuth session
        participant_id = session.get("oauth_participant_id")
        if not participant_id:
            return render_template(
                "error.html",
                title="OAuth Error",
                message="No participant was selected for OAuth.",
                details="Please return to the dashboard and try again.",
            ), 400
        
        db = get_db()
        try:
            # Ensure participant exists
            participant = get_participant(db, participant_id)
            if not participant:
                create_participant(db, participant_id, name=f"Participant {participant_id}")
            
            # Use shared app credentials
            oauth = FitbitOauth2Client(CLIENT_ID, CLIENT_SECRET, redirect_uri=REDIRECT_URI)
            token = oauth.fetch_access_token(code)
            user_id = token.get("user_id", "unknown")
            
            logger.info(f"Successfully obtained access token for participant {participant_id}, Fitbit user: {user_id}")
            
            upsert_token_for_participant(db, participant_id, token)
            logger.info(f"Token stored for participant: {participant_id}")
        finally:
            db.close()

        session.pop("oauth_state", None)
        session.pop("oauth_participant_id", None)
        
        return render_template(
            "success.html",
            title="Fitbit Connected Successfully",
            message=f"Fitbit account connected for participant '{participant_id}'!",
            details=f"Fitbit User ID: {user_id}",
        )
    except Exception as e:
        logger.error(f"Token exchange failed: {e}", exc_info=True)
        return render_template(
            "error.html",
            title="Token Exchange Failed",
            message="Failed to exchange authorization code for access token.",
            details=str(e),
        ), 500


@app.route("/sync/status/<task_id>", methods=["GET"])
def sync_status(task_id: str):
    """Get sync status for progress updates."""
    # For now, return a simple response
    # In future, could use Redis or database to track real progress
    return jsonify({"status": "in_progress"})


@app.route("/sync", methods=["POST"])
def sync_now():
    current_pid = get_current_participant()
    if not current_pid:
        return redirect(url_for("dashboard", sync_status="error", sync_message="No participant selected."))
    
    logger.info(f"Data sync triggered for participant: {current_pid}")
    db = get_db()

    start_str = request.form.get("start_date")
    end_str = request.form.get("end_date")
    raw_resources = get_selected_resources(request.form.getlist("resources"))
    effective_resources = normalize_resources(raw_resources)

    try:
        if start_str and end_str:
            start_date = date.fromisoformat(start_str)
            end_date = date.fromisoformat(end_str)
            result = sync_date_range(db, start_date, end_date, participant_id=current_pid, 
                                    resources=effective_resources)
            success_msg = f"Synced {result.get('count', 0)} days for {current_pid}"
        else:
            result = sync_single_user(db, participant_id=current_pid, resources=effective_resources)
            success_msg = f"Successfully synced data for {current_pid} on {result.get('date')}"

        # Store rate limit info and sync results in session for display
        if result.get("rate_limit"):
            session["rate_limit_info"] = result["rate_limit"]
        
        # Store sync results (both successes and failures)
        if result["status"] == "ok":
            session["last_sync_results"] = {
                "synced_days": result.get("synced_days", []),
                "errors": result.get("errors", []),
                "participant_id": current_pid,
                "date_range": f"{start_str} to {end_str}" if start_str else result.get("date"),
            }
        
        if result["status"] == "ok":
            logger.info(success_msg)
        elif result["status"] == "no_token":
            logger.warning("Sync attempted but no token found")
        else:
            logger.error(f"Sync failed: {result.get('error', 'Unknown error')}")

        if request.headers.get("Accept") == "application/json":
            return jsonify(result)

        if result["status"] == "ok":
            return redirect(
                url_for(
                    "dashboard",
                    sync_status="success",
                    sync_message=success_msg,
                    sync_date=f"{start_str} to {end_str}" if start_str else result.get("date"),
                )
            )
        elif result["status"] == "no_token":
            return redirect(
                url_for(
                    "dashboard",
                    sync_status="warning",
                    sync_message="No Fitbit account connected. Please connect first.",
                )
            )
        else:
            return redirect(
                url_for(
                    "dashboard",
                    sync_status="error",
                    sync_message=f"Sync failed: {result.get('error', 'Unknown error')}",
                )
            )
    finally:
        db.close()


@app.route("/export", methods=["POST"])
def export_data_route():
    current_pid = get_current_participant()
    if not current_pid:
        return redirect(url_for("dashboard", sync_status="error", sync_message="No participant selected."))
    
    logger.info(f"Export requested for participant: {current_pid}")
    
    start_str = request.form.get("start_date")
    end_str = request.form.get("end_date")
    format_type = request.form.get("format", "csv")
    raw_resources = get_selected_resources(request.form.getlist("resources"))
    effective_resources = normalize_resources(raw_resources)

    if not start_str or not end_str:
        return redirect(
            url_for(
                "dashboard",
                sync_status="error",
                sync_message="Please select a date range for export.",
            )
        )

    try:
        start_date = date.fromisoformat(start_str)
        end_date = date.fromisoformat(end_str)
        file_path = Path(
            export_data(start_date, end_date, format_type, participant_id=current_pid, resources=effective_resources)
        ).resolve()

        if not file_path.exists():
            raise FileNotFoundError(f"Export file missing at {file_path}")

        return send_file(file_path, as_attachment=True, download_name=file_path.name)
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        return redirect(url_for("dashboard", sync_status="error", sync_message=f"Export failed: {e}"))


@app.route("/disconnect", methods=["POST"])
def disconnect():
    current_pid = get_current_participant()
    if not current_pid:
        return redirect(url_for("dashboard", sync_status="error", sync_message="No participant selected."))
    
    logger.info(f"Disconnect requested for participant: {current_pid}")
    db = get_db()
    try:
        if disconnect_participant(db, current_pid):
            status, message = "info", f"Fitbit disconnected for participant '{current_pid}'."
        else:
            status, message = "warning", f"No Fitbit account was connected for '{current_pid}'."
        return redirect(url_for("dashboard", sync_status=status, sync_message=message))
    finally:
        db.close()


@app.route("/reset_session", methods=["GET", "POST"])
def reset_session():
    logger.info("Manual session reset requested")
    session.clear()
    return redirect(url_for("dashboard"))


# -----------------------------------------------------------------------------
# Participant Management Routes
# -----------------------------------------------------------------------------

@app.route("/participants/add", methods=["POST"])
def add_participant():
    """Add a new participant."""
    participant_id = request.form.get("participant_id", "").strip()
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    notes = request.form.get("notes", "").strip()
    
    if not participant_id:
        return redirect(url_for("dashboard", sync_status="error", sync_message="Participant ID is required."))
    
    db = get_db()
    try:
        create_participant(db, participant_id, name=name or None, email=email or None, notes=notes or None)
        # Automatically switch to new participant
        session["current_participant_id"] = participant_id
        
        return redirect(url_for("dashboard", sync_status="success", 
                              sync_message=f"Participant '{participant_id}' created successfully."))
    except ValueError as e:
        return redirect(url_for("dashboard", sync_status="error", sync_message=str(e)))
    finally:
        db.close()


@app.route("/participants/select/<participant_id>", methods=["GET", "POST"])
def select_participant(participant_id: str):
    """Switch to a different participant."""
    db = get_db()
    try:
        participant = get_participant(db, participant_id)
        if not participant:
            return redirect(url_for("dashboard", sync_status="error", sync_message=f"Participant '{participant_id}' not found."))
        
        # Switch to this participant
        session["current_participant_id"] = participant_id
        
        # Check if they have a connected Fitbit account
        token = get_token_for_participant(db, participant_id)
        if token:
            logger.info(f"Switched to participant: {participant_id} (Connected to Fitbit user {token.fitbit_user_id})")
        else:
            logger.info(f"Switched to participant: {participant_id} (Not connected)")
        
        return redirect(url_for("dashboard"))
    finally:
        db.close()


@app.route("/participants/delete/<participant_id>", methods=["POST"])
def delete_participant_route(participant_id: str):
    """Delete a participant and all their data."""
    db = get_db()
    try:
        delete_participant(db, participant_id)
        
        # If we deleted the current participant, clear selection
        if get_current_participant() == participant_id:
            session.pop("current_participant_id", None)
        
        return redirect(url_for("dashboard", sync_status="info", sync_message=f"Participant '{participant_id}' deleted."))
    finally:
        db.close()


# -----------------------------------------------------------------------------
# Error handlers
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    logger.warning(f"404 Not Found: {request.url}")
    return render_template(
        "error.html",
        title="Page Not Found",
        message="The page you're looking for doesn't exist.",
        details="Please check the URL or return to the dashboard.",
    ), 404


@app.errorhandler(500)
def server_error(e):
    logger.error(f"500 Server Error: {e}", exc_info=True)
    return render_template(
        "error.html",
        title="Server Error",
        message="An unexpected error occurred.",
        details=str(e),
    ), 500


# -----------------------------------------------------------------------------
# Startup helpers
# -----------------------------------------------------------------------------
def open_browser():
    time.sleep(1.5)
    url = f"http://{FLASK_HOST}:{FLASK_PORT}/"
    logger.info(f"Opening browser to {url}")
    try:
        webbrowser.open(url)
    except Exception as e:
        logger.warning(f"Could not open browser automatically: {e}")


if __name__ == "__main__":
    print(f"\n{'=' * 60}")
    print("Fitbit Single-User Data Ingestion App")
    print(f"{'=' * 60}")
    print(f"Starting server on http://{FLASK_HOST}:{FLASK_PORT}")
    print(f"Dashboard: http://{FLASK_HOST}:{FLASK_PORT}/")
    print(f"Help: http://{FLASK_HOST}:{FLASK_PORT}/help")
    print(f"Logs: {log_path}")
    print(f"{'=' * 60}\n")

    logger.info(f"Starting Flask server on {FLASK_HOST}:{FLASK_PORT}")
    logger.info(f"Debug mode: {FLASK_DEBUG}")

    should_open_browser = not FLASK_DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if should_open_browser:
        threading.Thread(target=open_browser, daemon=True).start()

    try:
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise
    finally:
        logger.info("Server shutdown")
