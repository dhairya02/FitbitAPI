#!/usr/bin/env python3
"""
Migration script to convert single-user database to multi-participant.

This script:
1. Creates the new participants table
2. Creates a "default" participant
3. Updates existing tokens to reference "default"
4. Can optionally create additional participants
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from backend.db import (
    engine,
    Base,
    SessionLocal,
    Participant,
    FitbitToken,
    create_participant,
    get_participant,
)
from sqlalchemy import inspect


def migrate():
    """Run migration from single-user to multi-participant."""
    print("=" * 60)
    print("Fitbit App: Migration to Multi-Participant")
    print("=" * 60)
    
    # Create session
    db = SessionLocal()
    
    try:
        # Check if participants table exists
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        print(f"\nExisting tables: {tables}")
        
        # Create all tables (safe if they already exist)
        print("\nCreating/updating tables...")
        Base.metadata.create_all(bind=engine)
        print("✓ Tables created/updated")
        
        # Ensure "default" participant exists
        print("\nChecking for default participant...")
        default_participant = get_participant(db, "default")
        
        if not default_participant:
            print("Creating 'default' participant...")
            create_participant(db, "default", name="Default User")
            print("✓ Default participant created")
        else:
            print("✓ Default participant already exists")
        
        # Check for tokens without participant_id
        print("\nChecking tokens...")
        tokens = db.query(FitbitToken).all()
        print(f"Found {len(tokens)} token(s)")
        
        for token in tokens:
            if not token.participant_id or token.participant_id == "":
                print(f"  Updating token {token.id} to use 'default' participant")
                token.participant_id = "default"
        
        db.commit()
        print("✓ All tokens updated")
        
        # Show current state
        print("\n" + "=" * 60)
        print("Current Participants:")
        print("=" * 60)
        participants = db.query(Participant).all()
        for p in participants:
            token = db.query(FitbitToken).filter_by(participant_id=p.participant_id).first()
            status = "Connected" if token else "Not connected"
            print(f"  • {p.participant_id} ({p.name or 'No name'}) - {status}")
        
        print("\n" + "=" * 60)
        print("Migration Complete!")
        print("=" * 60)
        print("\nYou can now:")
        print("1. Start the app: ./start.sh")
        print("2. Click 'Add Participant' to add more participants")
        print("3. Switch between participants using the dropdown")
        print("4. Connect each participant's Fitbit account separately")
        
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return 1
    finally:
        db.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(migrate())

