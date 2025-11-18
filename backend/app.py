"""
Flask application for Fitbit Single-User data ingestion.
Handles OAuth flow, dashboard, and data sync.
"""
import logging
import sys
import webbrowser
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
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
from backend.sync_logic import sync_single_user, sync_date_range, export_data

# Configure logging
log_dir = Path(LOG_DIR)
log_dir.mkdir(exist_ok=True)
log_path = log_dir / LOG_FILE

# Create logger
logger = logging.getLogger("fitbit_app")
logger.setLevel(getattr(logging, LOG_LEVEL))

# File handler
file_handler = logging.FileHandler(log_path)
file_handler.setLevel(getattr(logging, LOG_LEVEL))
file_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(file_formatter)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(levelname)s: %(message)s')
console_handler.setFormatter(console_formatter)

# Add handlers
logger.addHandler(file_handler)
logger.addHandler(console_handler)

logger.info("="*60)
logger.info("Fitbit Single-User Data Ingestion App Starting")
logger.info("="*60)
logger.info(f"Log file: {log_path}")
logger.info(f"Log level: {LOG_LEVEL}")

# Initialize Flask app
app = Flask(__name__)
app.secret_key = SECRET_KEY

# Configure session cookies
app.config.update(
    SESSION_COOKIE_SECURE=False,  # Set to True if using HTTPS
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# Initialize database
try:
    init_db()
    logger.info("Database initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize database: {e}", exc_info=True)
    raise


def get_db() -> DBSession:
    """Get a database session."""
    return SessionLocal()


@app.route("/")
def dashboard():
    """
    Dashboard page showing connection status and sync controls.
    """
    logger.debug("Dashboard accessed")
    db = get_db()
    try:
        token = get_single_token(db)
        
        # Check for sync result in query params
        sync_status = request.args.get("sync_status")
        sync_message = request.args.get("sync_message")
        sync_date = request.args.get("sync_date")
        
        if token:
            logger.debug(f"User connected: Fitbit ID {token.fitbit_user_id}")
        else:
            logger.debug("No user connected")
        
        # Default dates for the date picker (yesterday)
        yesterday = date.today() - timedelta(days=1)
        
        return render_template(
            "dashboard.html",
            token=token,
            sync_status=sync_status,
            sync_message=sync_message,
            sync_date=sync_date,
            default_date=yesterday.isoformat(),
        )
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}", exc_info=True)
        raise
    finally:
        db.close()


@app.route("/help")
def help_page():
    """
    Help and setup instructions page.
    """
    return render_template(
        "help.html",
        redirect_uri=REDIRECT_URI,
        scopes=" ".join(SCOPES),
    )


@app.route("/fitbit/authorize")
def fitbit_authorize():
    """
    Initiate Fitbit OAuth authorization flow.
    Redirects user to Fitbit login/consent page.
    """
    logger.info("Initiating Fitbit OAuth authorization")
    
    # Clear any existing session state to prevent conflicts
    session.clear()
    
    try:
        oauth = FitbitOauth2Client(CLIENT_ID, CLIENT_SECRET, redirect_uri=REDIRECT_URI)
        
        url, state = oauth.authorize_token_url(scope=SCOPES)
        
        # Store state in session for validation
        session["oauth_state"] = state
        
        logger.info(f"Redirecting to Fitbit authorization URL (state: {state[:10]}...)")
        return redirect(url)
    except Exception as e:
        logger.error(f"Failed to initiate OAuth: {e}", exc_info=True)
        raise


@app.route("/fitbit/callback")
def fitbit_callback():
    """
    OAuth callback endpoint.
    Exchanges authorization code for access token and stores it.
    """
    logger.info("OAuth callback received")
    
    # Get code and state from query params
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    
    # Check for OAuth errors
    if error:
        error_desc = request.args.get("error_description", "No additional details provided.")
        logger.error(f"Fitbit OAuth error: {error} - {error_desc}")
        return render_template(
            "error.html",
            title="Fitbit Authorization Failed",
            message=f"Fitbit returned an error: {error}",
            details=error_desc,
        ), 400
    
    # Validate state
    stored_state = session.get("oauth_state")
    if not state or not stored_state or state != stored_state:
        logger.error(f"OAuth state mismatch. Received: {state[:10] if state else 'None'}..., Expected: {stored_state[:10] if stored_state else 'None'}...")
        
        # Clear session to force a clean retry
        session.clear()
        
        return render_template(
            "error.html",
            title="OAuth State Mismatch",
            message="Security validation failed. The session state didn't match.",
            details="This usually happens if you went back/forward in browser or had a previous failed attempt. We've cleared your session, so please try connecting again.",
        ), 400
    
    # Validate code
    if not code:
        logger.error("No authorization code received from Fitbit")
        return render_template(
            "error.html",
            title="Missing Authorization Code",
            message="No authorization code received from Fitbit.",
            details="Please try the authorization process again.",
        ), 400
    
    try:
        # Exchange code for token
        logger.info("Exchanging authorization code for access token")
        oauth = FitbitOauth2Client(CLIENT_ID, CLIENT_SECRET, redirect_uri=REDIRECT_URI)
        token = oauth.fetch_access_token(code)
        
        user_id = token.get('user_id', 'unknown')
        logger.info(f"Successfully obtained access token for user: {user_id}")
        
        # Store token in database
        db = get_db()
        try:
            upsert_single_token(db, token)
            logger.info(f"Token stored in database for user: {user_id}")
        finally:
            db.close()
        
        # Clear OAuth state from session
        session.pop("oauth_state", None)
        
        # Show success page
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
    """
    Trigger data sync for the connected user.
    Now supports date range syncing via form parameters.
    """
    logger.info("Data sync triggered")
    db = get_db()
    
    # Get date range from form if available
    start_str = request.form.get("start_date")
    end_str = request.form.get("end_date")
    
    try:
        if start_str and end_str:
            # Date range sync
            start_date = date.fromisoformat(start_str)
            end_date = date.fromisoformat(end_str)
            result = sync_date_range(db, start_date, end_date)
            success_msg = f"Synced {result.get('count', 0)} days from {start_str} to {end_str}"
        else:
            # Fallback to single day (yesterday) sync
            result = sync_single_user(db)
            success_msg = f"Successfully synced data for {result.get('date')}"

        # Log result
        if result["status"] == "ok":
            logger.info(success_msg)
        elif result["status"] == "no_token":
            logger.warning("Sync attempted but no token found")
        else:
            logger.error(f"Sync failed: {result.get('error', 'Unknown error')}")
        
        # Check if client wants JSON response
        if request.headers.get("Accept") == "application/json":
            return jsonify(result)
        
        # Otherwise redirect to dashboard with sync result
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
    except Exception as e:
        logger.error(f"Error during sync: {e}", exc_info=True)
        raise
    finally:
        db.close()


@app.route("/export", methods=["POST"])
def export_data_route():
    """
    Export synced data to CSV or Excel.
    """
    logger.info("Export requested")
    
    start_str = request.form.get("start_date")
    end_str = request.form.get("end_date")
    format_type = request.form.get("format", "csv")
    
    if not start_str or not end_str:
        return redirect(url_for("dashboard", sync_status="error", sync_message="Please select a date range for export."))
        
    try:
        start_date = date.fromisoformat(start_str)
        end_date = date.fromisoformat(end_str)
        
        file_path = export_data(start_date, end_date, format_type)
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=Path(file_path).name
        )
        
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        return redirect(url_for("dashboard", sync_status="error", sync_message=f"Export failed: {e}"))


@app.route("/disconnect", methods=["POST"])
def disconnect():
    """
    Disconnect the Fitbit account by removing the stored token.
    """
    logger.info("Disconnect requested")
    db = get_db()
    try:
        token = get_single_token(db)
        if token:
            user_id = token.fitbit_user_id
            db.delete(token)
            db.commit()
            logger.info(f"Disconnected user: {user_id}")
            
            # Clear session as well
            session.clear()
            
            return redirect(
                url_for(
                    "dashboard",
                    sync_status="info",
                    sync_message="Fitbit account disconnected successfully.",
                )
            )
        else:
            logger.warning("Disconnect attempted but no token found")
            return redirect(
                url_for(
                    "dashboard",
                    sync_status="warning",
                    sync_message="No Fitbit account was connected.",
                )
            )
    except Exception as e:
        logger.error(f"Error during disconnect: {e}", exc_info=True)
        raise
    finally:
        db.close()


@app.route("/reset_session", methods=["GET", "POST"])
def reset_session():
    """
    Helper route to clear session and redirect to dashboard.
    Useful for recovering from stuck OAuth states.
    """
    logger.info("Manual session reset requested")
    session.clear()
    return redirect(url_for("dashboard"))


# Error handlers
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


def open_browser():
    """Open the browser after a short delay to ensure server is ready."""
    time.sleep(1.5)
    url = f"http://{FLASK_HOST}:{FLASK_PORT}/"
    logger.info(f"Opening browser to {url}")
    try:
        webbrowser.open(url)
    except Exception as e:
        logger.warning(f"Could not open browser automatically: {e}")


if __name__ == "__main__":
    print(f"\n{'='*60}")
    print("Fitbit Single-User Data Ingestion App")
    print(f"{'='*60}")
    print(f"Starting server on http://{FLASK_HOST}:{FLASK_PORT}")
    print(f"Dashboard: http://{FLASK_HOST}:{FLASK_PORT}/")
    print(f"Help: http://{FLASK_HOST}:{FLASK_PORT}/help")
    print(f"Logs: {log_path}")
    print(f"{'='*60}\n")
    
    logger.info(f"Starting Flask server on {FLASK_HOST}:{FLASK_PORT}")
    logger.info(f"Debug mode: {FLASK_DEBUG}")
    
    # Open browser in a separate thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    try:
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise
    finally:
        logger.info("Server shutdown")
