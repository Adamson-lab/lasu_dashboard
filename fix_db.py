import sqlite3
import os

# 1. Locate the Database
db_path = 'lasu_data.db'

# Check if it's inside an 'instance' folder (common in Flask)
if not os.path.exists(db_path):
    if os.path.exists(os.path.join('instance', 'lasu_data.db')):
        db_path = os.path.join('instance', 'lasu_data.db')

print(f"🔧 Connecting to database at: {db_path}...")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 2. Force Create the Missing Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS complaint_message (
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
    print("\n✅ SUCCESS! The 'complaint_message' table has been created.")
    print("🚀 You can now restart your server and use the chat.")

except Exception as e:
    print(f"\n❌ ERROR: {e}")