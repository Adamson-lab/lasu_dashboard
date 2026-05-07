import sqlite3
import os

# We know the real DB is likely here based on your previous scan
target_db = os.path.join('instance', 'lasu_data.db')

print(f"🎯 Targeting the real database: {target_db}")

if os.path.exists(target_db):
    try:
        conn = sqlite3.connect(target_db)
        cursor = conn.cursor()
        
        print("🔧 Adding 'application_url' column...")
        cursor.execute("ALTER TABLE exchange_program ADD COLUMN application_url TEXT")
        
        conn.commit()
        conn.close()
        print("✅ SUCCESS! The correct database has been patched.")
        
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print("✅ Good news! This database was already patched/up-to-date.")
        else:
            print(f"⚠️  Error: {e}")
else:
    print("❌ Could not find the database in the 'instance' folder.")