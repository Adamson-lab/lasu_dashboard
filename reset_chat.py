import sqlite3
import os

def hard_reset_db(db_path):
    print(f"🔧 Connecting to: {db_path}")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 1. DROP the broken table (Delete it entirely)
        print("   🗑️ Dropping broken 'complaint_message' table...")
        cursor.execute("DROP TABLE IF EXISTS complaint_message")
        
        # 2. RECREATE it with the correct columns (text, sender, etc.)
        print("   🔨 Recreating table with correct columns...")
        cursor.execute('''
            CREATE TABLE complaint_message (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id INTEGER NOT NULL,
                sender VARCHAR(20),
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(complaint_id) REFERENCES complaint(id)
            )
        ''')
        
        conn.commit()
        conn.close()
        print("   ✅ SUCCESS: Table reset complete.")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    # Check both possible locations
    if os.path.exists('lasu_data.db'):
        hard_reset_db('lasu_data.db')
    if os.path.exists('instance/lasu_data.db'):
        hard_reset_db('instance/lasu_data.db')