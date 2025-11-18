#!/usr/bin/env python3
"""
Fix database to allow multiple participants to share the same Fitbit account.
This removes the UNIQUE constraint on fitbit_user_id.
"""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.config import DATABASE_URL


def main():
    print("=" * 60)
    print("Fix Database: Remove UNIQUE Constraint on fitbit_user_id")
    print("=" * 60)
    
    # Extract database path from DATABASE_URL
    db_path = DATABASE_URL.replace("sqlite:///", "")
    
    print(f"\nDatabase: {db_path}")
    
    if not Path(db_path).exists():
        print("✗ Database file not found. Run the app first to create it.")
        return 1
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("\nBacking up current data...")
        # Get existing data
        cursor.execute("SELECT * FROM fitbit_tokens")
        tokens = cursor.fetchall()
        cursor.execute("PRAGMA table_info(fitbit_tokens)")
        columns = [col[1] for col in cursor.fetchall()]
        
        print(f"Found {len(tokens)} token(s)")
        
        # Drop and recreate table without UNIQUE constraint
        print("\nRecreating table without UNIQUE constraint...")
        cursor.execute("DROP TABLE IF EXISTS fitbit_tokens")
        
        cursor.execute("""
            CREATE TABLE fitbit_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id VARCHAR NOT NULL,
                fitbit_user_id VARCHAR NOT NULL,
                access_token VARCHAR NOT NULL,
                refresh_token VARCHAR NOT NULL,
                expires_at FLOAT NOT NULL,
                scope VARCHAR,
                token_type VARCHAR,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                FOREIGN KEY(participant_id) REFERENCES participants (participant_id)
            )
        """)
        
        # Recreate index
        cursor.execute("CREATE INDEX idx_participant_token ON fitbit_tokens (participant_id)")
        
        # Restore data
        if tokens:
            print("Restoring tokens...")
            placeholders = ",".join(["?" for _ in columns])
            cursor.executemany(
                f"INSERT INTO fitbit_tokens ({','.join(columns)}) VALUES ({placeholders})",
                tokens
            )
        
        conn.commit()
        print("✓ Database updated successfully")
        
        print("\n" + "=" * 60)
        print("Done! You can now connect multiple participants to the same Fitbit account.")
        print("=" * 60)
        
        return 0
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

