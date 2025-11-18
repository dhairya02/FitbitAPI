"""
Flask application for Fitbit Single-User data ingestion.
Handles OAuth flow, dashboard, and data sync.
"""
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
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
)
from backend.db import init_db, SessionLocal, get_single_token, upsert_single_token
from backend.sync_logic import sync_single_user

# Initialize Flask app
app = Flask(__name__)
app.secret_key = SECRET_KEY

# Initialize database
init_db()


def get_db() -> DBSession:
    """Get a database session."""
    return SessionLocal()


@app.route("/")
def dashboard():
    """
    Dashboard page showing connection status and sync controls.
    """
    db = get_db()
    try:
        token = get_single_token(db)
        
        # Check for sync result in query params
        sync_status = request.args.get("sync_status")
        sync_message = request.args.get("sync_message")
        sync_date = request.args.get("sync_date")
        
        return render_template(
            "dashboard.html",
            token=token,
            sync_status=sync_status,
            sync_message=sync_message,
            sync_date=sync_date,
        )
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
    oauth = FitbitOauth2Client(CLIENT_ID, CLIENT_SECRET, redirect_uri=REDIRECT_URI)
    
    url, state = oauth.authorize_token_url(scope=SCOPES)
    
    # Store state in session for validation
    session["oauth_state"] = state
    
    return redirect(url)


@app.route("/fitbit/callback")
def fitbit_callback():
    """
    OAuth callback endpoint.
    Exchanges authorization code for access token and stores it.
    """
    # Get code and state from query params
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    
    # Check for OAuth errors
    if error:
        return render_template(
            "error.html",
            title="Fitbit Authorization Failed",
            message=f"Fitbit returned an error: {error}",
            details=request.args.get("error_description", "No additional details provided."),
        ), 400
    
    # Validate state
    stored_state = session.get("oauth_state")
    if not state or not stored_state or state != stored_state:
        return render_template(
            "error.html",
            title="OAuth State Mismatch",
            message="Security validation failed. The OAuth state parameter doesn't match.",
            details="This could indicate a CSRF attack or a stale authorization attempt. Please try again.",
        ), 400
    
    # Validate code
    if not code:
        return render_template(
            "error.html",
            title="Missing Authorization Code",
            message="No authorization code received from Fitbit.",
            details="Please try the authorization process again.",
        ), 400
    
    try:
        # Exchange code for token
        oauth = FitbitOauth2Client(CLIENT_ID, CLIENT_SECRET, redirect_uri=REDIRECT_URI)
        token = oauth.fetch_access_token(code)
        
        # Store token in database
        db = get_db()
        try:
            upsert_single_token(db, token)
        finally:
            db.close()
        
        # Clear OAuth state from session
        session.pop("oauth_state", None)
        
        # Show success page
        return render_template(
            "success.html",
            title="Fitbit Connected Successfully",
            message="Your Fitbit account has been connected successfully!",
            details=f"User ID: {token.get('user_id', 'unknown')}",
        )
        
    except Exception as e:
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
    Supports both JSON responses (for fetch calls) and HTML redirects (for form posts).
    """
    db = get_db()
    try:
        result = sync_single_user(db)
        
        # Check if client wants JSON response
        if request.headers.get("Accept") == "application/json":
            return jsonify(result)
        
        # Otherwise redirect to dashboard with sync result
        if result["status"] == "ok":
            return redirect(
                url_for(
                    "dashboard",
                    sync_status="success",
                    sync_message=f"Successfully synced data for {result['date']}",
                    sync_date=result["date"],
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


@app.route("/disconnect", methods=["POST"])
def disconnect():
    """
    Disconnect the Fitbit account by removing the stored token.
    """
    db = get_db()
    try:
        token = get_single_token(db)
        if token:
            db.delete(token)
            db.commit()
            return redirect(
                url_for(
                    "dashboard",
                    sync_status="info",
                    sync_message="Fitbit account disconnected successfully.",
                )
            )
        else:
            return redirect(
                url_for(
                    "dashboard",
                    sync_status="warning",
                    sync_message="No Fitbit account was connected.",
                )
            )
    finally:
        db.close()


# Error handlers
@app.errorhandler(404)
def not_found(e):
    return render_template(
        "error.html",
        title="Page Not Found",
        message="The page you're looking for doesn't exist.",
        details="Please check the URL or return to the dashboard.",
    ), 404


@app.errorhandler(500)
def server_error(e):
    return render_template(
        "error.html",
        title="Server Error",
        message="An unexpected error occurred.",
        details=str(e),
    ), 500


if __name__ == "__main__":
    print(f"\n{'='*60}")
    print("Fitbit Single-User Data Ingestion App")
    print(f"{'='*60}")
    print(f"Starting server on http://{FLASK_HOST}:{FLASK_PORT}")
    print(f"Dashboard: http://{FLASK_HOST}:{FLASK_PORT}/")
    print(f"Help: http://{FLASK_HOST}:{FLASK_PORT}/help")
    print(f"{'='*60}\n")
    
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)

