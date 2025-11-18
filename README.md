# Fitbit Single-User Data Ingestion App

A Flask-based web application for syncing Fitbit data for a single user. Built with Python 3.12, Flask, SQLAlchemy, and the python-fitbit library, this app provides a clean dashboard for managing OAuth connections and pulling health data from Fitbit's API.

## 🎯 What This App Does

- **OAuth 2.0 Authentication**: Securely connect your Fitbit account using OAuth 2.0
- **Token Management**: Automatically stores and refreshes access tokens in SQLite
- **Data Sync**: Pulls yesterday's activity data:
  - Steps summary
  - Heart rate intraday (1-minute resolution)
- **Web Dashboard**: User-friendly interface styled with Tailwind CSS
- **Single-User Design**: Optimized for one Fitbit account, but structured for future multi-user expansion

## 📋 Prerequisites

Before you begin, ensure you have:

1. **Python 3.12** installed on your system
2. **A Fitbit account** with a device or mobile app tracking data
3. **A Fitbit Developer account** (free) to create an API application

## 🔧 Setting Up Your Fitbit Developer Application

### Step 1: Create a Fitbit Developer Account

1. Go to [https://dev.fitbit.com](https://dev.fitbit.com)
2. Sign in with your Fitbit account or create a new one
3. Accept the Terms of Service

### Step 2: Register a New Application

1. Navigate to **"Manage My Apps"** and click **"Register a New App"**
2. Fill in the application details:

| Field | Value |
|-------|-------|
| **Application Name** | `My Fitbit Sync App` (or any name you prefer) |
| **Description** | `Personal data sync application` |
| **Application Website** | `http://localhost:5000` |
| **Organization** | Your name or organization |
| **Organization Website** | `http://localhost:5000` |
| **OAuth 2.0 Application Type** | **Personal** (recommended for intraday access) |
| **Callback URL** | `http://localhost:5000/fitbit/callback` |
| **Default Access Type** | Read Only |

3. Agree to the terms and click **"Register"**

### Step 3: Note Your Credentials

After registration, you'll see your app's details page. **Copy these values**:

- **OAuth 2.0 Client ID**: A string like `23ABCD`
- **Client Secret**: A longer string like `1234567890abcdef1234567890abcdef`

⚠️ **Important**: Keep your Client Secret secure! Never commit it to version control or share it publicly.

### Step 4: Configure Scopes

Ensure your app has access to these data scopes (usually granted by default):
- `activity` - Steps and activity data
- `heartrate` - Heart rate data
- `sleep` - Sleep data
- `weight` - Weight and body composition
- `profile` - User profile information

## 🚀 Installation & Setup

### 1. Clone or Download This Project

```bash
cd /path/to/FitbitAPI
```

### 2. Create and Activate a Virtual Environment

```bash
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

You have two options for setting environment variables:

#### Option A: Using a `.env` File (Recommended)

Create a file named `.env` in the project root:

```bash
# Required
FITBIT_CLIENT_ID=your_client_id_here
FITBIT_CLIENT_SECRET=your_client_secret_here

# Optional (these have defaults)
FITBIT_REDIRECT_URI=http://localhost:5000/fitbit/callback
FITBIT_SCOPES=activity heartrate sleep weight profile
FLASK_SECRET_KEY=change-this-to-a-long-random-string
DATABASE_URL=sqlite:///fitbit_singleuser.db
FITBIT_DATA_DIR=fitbit_data
```

#### Option B: Export Environment Variables

```bash
export FITBIT_CLIENT_ID="your_client_id_here"
export FITBIT_CLIENT_SECRET="your_client_secret_here"
export FITBIT_REDIRECT_URI="http://localhost:5000/fitbit/callback"
export FLASK_SECRET_KEY="some-long-random-string"
```

**Generate a secure Flask secret key:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Run the Application

```bash
python -m backend.app
```

You should see output like:
```
============================================================
Fitbit Single-User Data Ingestion App
============================================================
Starting server on http://127.0.0.1:5000
Dashboard: http://127.0.0.1:5000/
Help: http://127.0.0.1:5000/help
============================================================
```

## 📱 Using the Application

### First-Time Setup

1. **Open the dashboard** in your browser: [http://localhost:5000](http://localhost:5000)
2. **Click "Connect Fitbit"** - you'll be redirected to Fitbit's login page
3. **Log in to Fitbit** and authorize the app to access your data
4. **Return to the dashboard** - you should now see "Status: Connected"

### Syncing Your Data

1. On the dashboard, click **"Sync Data Now"**
2. The app will:
   - Pull yesterday's step count summary
   - Pull yesterday's heart rate intraday data (1-minute intervals)
   - Save the data as JSON files
   - Automatically refresh your access token if needed

### Viewing Synced Data

Data is saved in the `fitbit_data/default/` directory:

```
fitbit_data/
└── default/
    ├── 2024-11-17_steps.json
    ├── 2024-11-17_heartrate_1min.json
    ├── 2024-11-18_steps.json
    └── 2024-11-18_heartrate_1min.json
```

Each JSON file contains the raw response from Fitbit's API.

### Disconnecting

Click **"Disconnect"** on the dashboard to remove the stored token. You'll need to reconnect through OAuth to sync data again.

## 🗂️ Project Structure

```
FitbitAPI/
│
├── backend/
│   ├── __init__.py          # Package marker
│   ├── config.py            # Configuration and environment variables
│   ├── db.py                # Database models and utilities
│   ├── sync_logic.py        # Fitbit data syncing logic
│   ├── app.py               # Flask application and routes
│   └── templates/           # HTML templates with Tailwind CSS
│       ├── base.html        # Base template with navbar
│       ├── dashboard.html   # Main dashboard page
│       ├── help.html        # Help and setup instructions
│       ├── success.html     # OAuth success page
│       └── error.html       # Error display page
│
├── requirements.txt         # Python dependencies
├── README.md               # This file
└── .env                    # Environment variables (create this)
```

## 🔍 Technical Details

### Database Schema

The app uses SQLite with a single table `fitbit_tokens`:

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `participant_id` | String | For future multi-user support (currently "default") |
| `fitbit_user_id` | String | Fitbit's user identifier |
| `access_token` | String | OAuth access token |
| `refresh_token` | String | OAuth refresh token |
| `expires_at` | Float | Unix timestamp for token expiry |
| `scope` | String | Granted OAuth scopes |
| `token_type` | String | Token type (usually "Bearer") |
| `created_at` | DateTime | First connection timestamp |
| `updated_at` | DateTime | Last token refresh timestamp |

### API Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Dashboard page |
| `/help` | GET | Help and setup instructions |
| `/fitbit/authorize` | GET | Initiate OAuth flow |
| `/fitbit/callback` | GET | OAuth callback endpoint |
| `/sync` | POST | Trigger data sync |
| `/disconnect` | POST | Remove stored token |

### Data Syncing

The sync process:
1. Retrieves the stored access token from the database
2. Creates a Fitbit API client with automatic token refresh
3. Fetches data for yesterday's date:
   - **Steps**: Daily summary from the `activities/steps` endpoint
   - **Heart Rate**: Intraday data at 1-minute intervals
4. Saves responses as JSON files in `fitbit_data/default/`
5. Updates tokens in the database if refreshed

## 🛠️ Troubleshooting

### "Missing required Fitbit credentials" Error

**Problem**: The app won't start without Client ID and Secret.

**Solution**: Set the `FITBIT_CLIENT_ID` and `FITBIT_CLIENT_SECRET` environment variables or add them to your `.env` file.

### OAuth Redirect Mismatch

**Problem**: After authorizing, you get an error about redirect URI mismatch.

**Solution**: Ensure the **Callback URL** in your Fitbit app settings **exactly matches** the `FITBIT_REDIRECT_URI` (default: `http://localhost:5000/fitbit/callback`). No trailing slashes, exact case, and same protocol.

### Heart Rate Intraday Data Fails

**Problem**: Steps sync works, but heart rate returns an error.

**Solutions**:
1. **Application Type**: Set your Fitbit app to "Personal" (automatic intraday access) rather than "Server"
2. **Scopes**: Ensure `heartrate` is in your `FITBIT_SCOPES` environment variable
3. **Permission**: If using a "Server" app type, you need to request special intraday access from Fitbit

### Token Expired Errors

**Problem**: API calls fail with token expiration errors.

**Solution**: The app automatically refreshes tokens, but if issues persist:
1. Click "Disconnect" on the dashboard
2. Click "Connect Fitbit" to re-authorize
3. Try syncing again

## 🔮 Future Extensions: Multi-User Support

This app is designed for easy extension to multiple users. Here's what would need to change:

### Database
- Use unique `participant_id` values for each user instead of "default"
- Add an index on `participant_id` for faster queries

### Routes
- Add user management endpoints (`/users/add`, `/users/list`)
- Modify OAuth flow to associate tokens with specific users
- Update sync endpoint to accept a `participant_id` parameter

### Storage
- Change data directory structure to `fitbit_data/{participant_id}/`
- Add user selection UI to the dashboard

### Example Code Change

Current (single-user):
```python
token = get_single_token(session)
```

Future (multi-user):
```python
token = get_token_by_participant(session, participant_id="user123")
```

## 📄 License

This project is provided as-is for personal use and learning purposes.

## 🤝 Contributing

This is a single-user application template. Feel free to fork and customize for your needs!

## 📞 Support

For issues with:
- **Fitbit API**: Check the [Fitbit Developer Documentation](https://dev.fitbit.com/build/reference/)
- **OAuth Setup**: Review the Help page in the app (`/help`)
- **Python/Flask**: Consult the respective project documentation

---

**Built with:** Python 3.12 • Flask • SQLAlchemy • Fitbit API • Tailwind CSS

**Happy syncing! 🏃‍♂️💓**

