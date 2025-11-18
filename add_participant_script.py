#!/usr/bin/env python3
"""
Helper script to add participants with custom Fitbit app credentials.
Usage: python add_participant_script.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.db import SessionLocal, create_participant, get_participant


def main():
    print("=" * 60)
    print("Add Participant with Custom Credentials")
    print("=" * 60)
    print()
    
    # Collect participant info
    participant_id = input("Participant ID (e.g., P001, P002): ").strip()
    if not participant_id:
        print("Error: Participant ID is required")
        return 1
    
    name = input("Display Name (optional): ").strip() or None
    email = input("Email (optional): ").strip() or None
    notes = input("Notes (optional): ").strip() or None
    
    print()
    print("Fitbit App Credentials (leave empty to use default from .env):")
    client_id = input("Fitbit Client ID: ").strip() or None
    client_secret = input("Fitbit Client Secret: ").strip() or None
    
    # Create participant
    db = SessionLocal()
    try:
        # Check if exists
        existing = get_participant(db, participant_id)
        if existing:
            print(f"\n✗ Participant '{participant_id}' already exists!")
            return 1
        
        participant = create_participant(
            db,
            participant_id=participant_id,
            name=name,
            email=email,
            notes=notes,
            fitbit_client_id=client_id,
            fitbit_client_secret=client_secret,
        )
        
        print()
        print("=" * 60)
        print("✓ Participant Created Successfully!")
        print("=" * 60)
        print(f"  Participant ID: {participant.participant_id}")
        print(f"  Name: {participant.name or 'N/A'}")
        print(f"  Email: {participant.email or 'N/A'}")
        print(f"  Custom Credentials: {'Yes' if participant.fitbit_client_id else 'No (using default)'}")
        print()
        print("Next steps:")
        print("1. Start the app: ./start.sh")
        print(f"2. Select '{participant_id}' from the participant dropdown")
        print("3. Click 'Connect Fitbit' to link their Fitbit account")
        print()
        
        return 0
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

