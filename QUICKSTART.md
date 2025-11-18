# Quick Start Guide

Get your Fitbit data sync app running in 5 minutes!

## ⚡ Fast Setup

### 1. Install Dependencies

```bash
python3.12 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get Fitbit Credentials

1. Go to [https://dev.fitbit.com/apps](https://dev.fitbit.com/apps)
2. Click "Register a New App"
3. Fill in the form:
   - **Application Type**: Personal
   - **Callback URL**: `http://localhost:5000/fitbit/callback`
4. Copy your **Client ID** and **Client Secret**

### 3. Configure Environment

Create a `.env` file in the project root:

```bash
FITBIT_CLIENT_ID=your_client_id_here
FITBIT_CLIENT_SECRET=your_client_secret_here
FLASK_SECRET_KEY=any-random-string-here
```

Or export directly:
```bash
export FITBIT_CLIENT_ID="your_client_id"
export FITBIT_CLIENT_SECRET="your_client_secret"
export FLASK_SECRET_KEY="random-string"
```

### 4. Run the App

```bash
python -m backend.app
```

### 5. Connect & Sync

1. Open [http://localhost:5000](http://localhost:5000)
2. Click "Connect Fitbit"
3. Log in and authorize
4. Click "Sync Data Now"
5. Find your data in `fitbit_data/default/`

## 🎉 That's It!

Your data is now syncing. Check the [README.md](README.md) for detailed information.

## 🆘 Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| "Missing credentials" error | Set `FITBIT_CLIENT_ID` and `FITBIT_CLIENT_SECRET` |
| "Redirect URI mismatch" | Ensure callback URL is exactly `http://localhost:5000/fitbit/callback` |
| Heart rate fails | Use "Personal" app type in Fitbit settings |

For more help, visit the Help page at [http://localhost:5000/help](http://localhost:5000/help)

