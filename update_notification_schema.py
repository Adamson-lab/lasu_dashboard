import sqlite3
import os

# 1. Define the path to your database
# It is likely inside the 'instance' folder based on your previous errors
db_path = os.path.join('instance', 'site.db')

# Check if file exists first to avoid confusion
if not os.path.exists(db_path):
    # Fallback: Check strictly in the current folder if instance/site.db doesn't exist
    db_path = 'site.db'

print(f"🔌 Connecting to database at: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 2. Add the missing 'title' column
    print("🛠  Adding 'title' column to 'notification' table...")
    cursor.execute("ALTER TABLE notification ADD COLUMN title VARCHAR(100)")
    
    conn.commit()
    conn.close()
    print("✅ Success! The column was added. You can now run 'python app.py'.")

except sqlite3.OperationalError as e:
    if "duplicate column" in str(e):
        print("⚠️  Notice: The 'title' column already exists. You are good to go!")
    else:
        print(f"❌ Database Error: {e}")
except Exception as e:
    print(f"❌ General Error: {e}")