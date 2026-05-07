import sqlite3
import os

# Try to locate the database
db_path = 'instance/site.db'
if not os.path.exists(db_path):
    db_path = 'site.db' # Try root folder if not in instance

print(f"🔧 Connecting to database at: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Add the missing 'title' column
    print("👉 Adding 'title' column...")
    try:
        cursor.execute("ALTER TABLE notification ADD COLUMN title VARCHAR(100)")
        print("✅ 'title' column added.")
    except sqlite3.OperationalError:
        print("⚠️ 'title' column already exists.")

    # 2. Add the missing 'course_code' column (just in case)
    print("👉 Adding 'course_code' column...")
    try:
        cursor.execute("ALTER TABLE notification ADD COLUMN course_code VARCHAR(20)")
        print("✅ 'course_code' column added.")
    except sqlite3.OperationalError:
        print("⚠️ 'course_code' column already exists.")

    conn.commit()
    conn.close()
    print("\n🎉 SUCCESS! Database updated. You can run 'python app.py' now.")

except Exception as e:
    print(f"\n❌ Error: {e}")