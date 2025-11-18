#!/bin/bash

# Fitbit API Startup Script
# This script sets up the environment and starts the Flask application

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}Fitbit Single-User Data Ingestion App${NC}"
echo -e "${BLUE}Startup Script${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# Check Python version
echo -e "${YELLOW}Checking Python version...${NC}"
if ! command -v python3.12 &> /dev/null; then
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Error: Python 3.12 or Python 3 is not installed.${NC}"
        echo "Please install Python 3.12 or later."
        exit 1
    fi
    PYTHON_CMD="python3"
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    echo -e "${GREEN}Found Python ${PYTHON_VERSION}${NC}"
else
    PYTHON_CMD="python3.12"
    echo -e "${GREEN}Found Python 3.12${NC}"
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating one...${NC}"
    $PYTHON_CMD -m venv venv
    echo -e "${GREEN}Virtual environment created.${NC}"
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source venv/bin/activate

# Upgrade pip
echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --quiet --upgrade pip

# Install/update dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install --quiet -r requirements.txt
echo -e "${GREEN}Dependencies installed.${NC}"

# Check for required environment variables
echo ""
echo -e "${YELLOW}Checking environment variables...${NC}"

# Load .env file if it exists
if [ -f ".env" ]; then
    echo -e "${GREEN}Found .env file, loading variables...${NC}"
    # Use a more robust method to load .env file
    set -a
    source .env
    set +a
elif [ -f "env-example.txt" ]; then
    echo -e "${YELLOW}No .env file found. You can copy env-example.txt to .env and fill in your values.${NC}"
fi

MISSING_VARS=()

if [ -z "$FITBIT_CLIENT_ID" ]; then
    MISSING_VARS+=("FITBIT_CLIENT_ID")
fi

if [ -z "$FITBIT_CLIENT_SECRET" ]; then
    MISSING_VARS+=("FITBIT_CLIENT_SECRET")
fi

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required environment variables:${NC}"
    for var in "${MISSING_VARS[@]}"; do
        echo -e "${RED}  - $var${NC}"
    done
    echo ""
    echo -e "${YELLOW}Please set these variables:${NC}"
    echo "  1. Create a .env file (see env-example.txt), or"
    echo "  2. Export them in your shell:"
    echo ""
    for var in "${MISSING_VARS[@]}"; do
        echo -e "     ${BLUE}export $var=\"your_value_here\"${NC}"
    done
    echo ""
    echo "See README.md or QUICKSTART.md for detailed instructions."
    exit 1
fi

echo -e "${GREEN}Required environment variables are set.${NC}"

# Set default Flask secret key if not set
if [ -z "$FLASK_SECRET_KEY" ]; then
    echo -e "${YELLOW}FLASK_SECRET_KEY not set, using default (not recommended for production).${NC}"
fi

# Check if database directory needs to be created
if [ ! -d "fitbit_data" ]; then
    echo -e "${YELLOW}Creating fitbit_data directory...${NC}"
    mkdir -p fitbit_data/default
    echo -e "${GREEN}Data directory created.${NC}"
fi

# Display configuration summary
echo ""
echo -e "${BLUE}Configuration Summary:${NC}"
echo -e "  ${GREEN}✓${NC} Python: $($PYTHON_CMD --version)"
echo -e "  ${GREEN}✓${NC} Virtual environment: Active"
echo -e "  ${GREEN}✓${NC} Dependencies: Installed"
echo -e "  ${GREEN}✓${NC} Fitbit Client ID: ${FITBIT_CLIENT_ID:0:10}..."
echo -e "  ${GREEN}✓${NC} Fitbit Client Secret: ${FITBIT_CLIENT_SECRET:0:10}..."
echo -e "  ${GREEN}✓${NC} Redirect URI: ${FITBIT_REDIRECT_URI:-http://localhost:5000/fitbit/callback}"
echo ""

# Start the Flask application
echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}Starting Flask application...${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""
echo -e "${GREEN}Server will be available at:${NC}"
echo -e "  ${BLUE}Dashboard:${NC} http://localhost:5000/"
echo -e "  ${BLUE}Help:${NC}      http://localhost:5000/help"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
echo ""

# Run the Flask app
python -m backend.app

