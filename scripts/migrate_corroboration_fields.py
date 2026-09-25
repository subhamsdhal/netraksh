import sqlite3
import os
import sys

def migrate():
    db_path = os.path.join(os.getcwd(), 'netraksh.db')
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}. Skipping migration.")
        return
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Check if columns exist
    cur.execute("PRAGMA table_info(events)")
    columns = [row[1] for row in cur.fetchall()]
    
    if "corroborating_camera_id" not in columns:
        print("Adding corroborating_camera_id to events table...")
        cur.execute("ALTER TABLE events ADD COLUMN corroborating_camera_id VARCHAR(36)")
        
    if "corroboration_status" not in columns:
        print("Adding corroboration_status to events table...")
        cur.execute("ALTER TABLE events ADD COLUMN corroboration_status VARCHAR(32)")
        
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
