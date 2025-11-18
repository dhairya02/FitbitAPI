#!/usr/bin/env python3
"""
Reset the database completely.
This will delete all participants, tokens, and data.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Set a dummy env var to avoid .env loading issues
os.environ.setdefault("FITBIT_CLIENT_ID", "dummy")
os.environ.setdefault("FITBIT_CLIENT_SECRET", "dummy")

from backend.config import DATABASE_URL
from backend.db import engine, Base


def main():
    print("=" * 60)
    print("⚠️  RESET DATABASE - ALL DATA WILL BE DELETED")
    print("=" * 60)
    
    db_path = DATABASE_URL.replace("sqlite:///", "")
    
    print(f"\nDatabase: {db_path}")
    print("\nThis will:")
    print("  • Delete all participants")
    print("  • Delete all Fitbit tokens")
    print("  • Recreate empty tables")
    print()
    
    # Check for --force flag
    if "--force" in sys.argv:
        print("Running with --force flag, skipping confirmation...\n")
    else:
        try:
            response = input("Are you sure you want to continue? (yes/no): ").strip().lower()
            if response != "yes":
                print("\nCancelled. No changes made.")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled. No changes made.")
            return 0
    
    try:
        print("\nDropping all tables...")
        Base.metadata.drop_all(bind=engine)
        print("✓ Tables dropped")
        
        print("\nRecreating tables...")
        Base.metadata.create_all(bind=engine)
        print("✓ Tables created")
        
        print("\n" + "=" * 60)
        print("✓ Database Reset Complete!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Start the app: ./start.sh")
        print("2. Click 'Add Participant' to create your first participant")
        print("3. Enter their Fitbit app credentials (Client ID & Secret)")
        print("4. Click 'Connect Fitbit' to link their account")
        print("5. Repeat for additional participants")
        print()
        
        return 0
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

