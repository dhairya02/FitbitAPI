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
from typing import List

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
from backend.db import init_db, SessionLocal, get_single_token, upsert_single_token
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


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/")
def dashboard():
    logger.debug("Dashboard accessed")
    db = get_db()
    try:
        token = get_single_token(db)
        sync_status = request.args.get("sync_status")
        sync_message = request.args.get("sync_message")
        sync_date = request.args.get("sync_date")

        yesterday = date.today() - timedelta(days=1)
        selected_resources = session.get("selected_resources") or DEFAULT_RESOURCES.copy()

        return render_template(
            "dashboard.html",
            token=token,
            sync_status=sync_status,
            sync_message=sync_message,
            sync_date=sync_date,
            default_date=yesterday.isoformat(),
            resource_options=RESOURCE_OPTIONS,
            selected_resources=selected_resources,
        )
    finally:
        db.close()


@app.route("/help")
def help_page():
    return render_template("help.html", redirect_uri=REDIRECT_URI, scopes=" ".join(SCOPES))


@app.route("/fitbit/authorize")
def fitbit_authorize():
    logger.info("Initiating Fitbit OAuth authorization")
    session.clear()

    try:
        oauth = FitbitOauth2Client(CLIENT_ID, CLIENT_SECRET, redirect_uri=REDIRECT_URI)
        url, state = oauth.authorize_token_url(scope=SCOPES)
        session["oauth_state"] = state
        logger.info(f"Redirecting to Fitbit authorization URL (state: {state[:10]}...)")
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
        oauth = FitbitOauth2Client(CLIENT_ID, CLIENT_SECRET, redirect_uri=REDIRECT_URI)
        token = oauth.fetch_access_token(code)
        user_id = token.get("user_id", "unknown")
        logger.info(f"Successfully obtained access token for user: {user_id}")

        db = get_db()
        try:
            upsert_single_token(db, token)
            logger.info(f"Token stored in database for user: {user_id}")
        finally:
            db.close()

        session.pop("oauth_state", None)
        return render_template(
            "success.html",
            title="Fitbit Connected Successfully",
            message="Your Fitbit account has been connected successfully!",
            details=f"User ID: {user_id}",
        )
    except Exception as e:
        logger.error(f"Token exchange failed: {e}", exc_info=True)
        return render_template(
            "error.html",
            title="Token Exchange Failed",
            message="Failed to exchange authorization code for access token.",
            details=str(e),
        ), 500


@app.route("/sync", methods=["POST"])
def sync_now():
    logger.info("Data sync triggered")
    db = get_db()

    start_str = request.form.get("start_date")
    end_str = request.form.get("end_date")
    raw_resources = get_selected_resources(request.form.getlist("resources"))
    effective_resources = normalize_resources(raw_resources)

    try:
        if start_str and end_str:
            start_date = date.fromisoformat(start_str)
            end_date = date.fromisoformat(end_str)
            result = sync_date_range(db, start_date, end_date, resources=effective_resources)
            success_msg = f"Synced {result.get('count', 0)} days from {start_str} to {end_str}"
        else:
            result = sync_single_user(db, resources=effective_resources)
            success_msg = f"Successfully synced data for {result.get('date')}"

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
    logger.info("Export requested")
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
            export_data(start_date, end_date, format_type, resources=effective_resources)
        ).resolve()

        if not file_path.exists():
            raise FileNotFoundError(f"Export file missing at {file_path}")

        return send_file(file_path, as_attachment=True, download_name=file_path.name)
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        return redirect(url_for("dashboard", sync_status="error", sync_message=f"Export failed: {e}"))


@app.route("/disconnect", methods=["POST"])
def disconnect():
    logger.info("Disconnect requested")
    db = get_db()
    try:
        token = get_single_token(db)
        if token:
            user_id = token.fitbit_user_id
            db.delete(token)
            db.commit()
            session.clear()
            logger.info(f"Disconnected user: {user_id}")
            status, message = "info", "Fitbit account disconnected successfully."
        else:
            status, message = "warning", "No Fitbit account was connected."
        return redirect(url_for("dashboard", sync_status=status, sync_message=message))
    finally:
        db.close()


@app.route("/reset_session", methods=["GET", "POST"])
def reset_session():
    logger.info("Manual session reset requested")
    session.clear()
    return redirect(url_for("dashboard"))


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
