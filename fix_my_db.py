import sqlite3
import os

# 1. Auto-detect where your database is hiding
if os.path.exists('instance/site.db'):
    db_path = 'instance/site.db'
    print(f"✅ Found database at: {db_path}")
elif os.path.exists('site.db'):
    db_path = 'site.db'
    print(f"✅ Found database at: {db_path}")
else:
    print("❌ Could not find site.db! Are you in the 'lasu_dashboard' folder?")
    exit()

# 2. Connect and Fix
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Add 'title' column
    try:
        cursor.execute("ALTER TABLE notification ADD COLUMN title VARCHAR(100)")
        print("✅ Added 'title' column.")
    except sqlite3.OperationalError:
        print("⚠️ 'title' column already exists (Skipping).")

    # Add 'course_code' column
    try:
        cursor.execute("ALTER TABLE notification ADD COLUMN course_code VARCHAR(20)")
        print("✅ Added 'course_code' column.")
    except sqlite3.OperationalError:
        print("⚠️ 'course_code' column already exists (Skipping).")

    conn.commit()
    conn.close()
    print("\n🎉 SUCCESS! Your database is fixed. No data was lost.")

except Exception as e:
    print(f"❌ Something went wrong: {e}")