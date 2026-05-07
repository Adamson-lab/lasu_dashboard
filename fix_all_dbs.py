import sqlite3
import os

# Get current directory
current_dir = os.getcwd()
print(f"📂 Scanning for databases in: {current_dir}")

# Find all .db files in root and subfolders (like 'instance')
db_files = []
for root, dirs, files in os.walk(current_dir):
    for file in files:
        if file.endswith(".db") or file.endswith(".sqlite"):
            db_files.append(os.path.join(root, file))

if not db_files:
    print("❌ No database files found! Run 'python app.py' once to create one.")
    exit()

print(f"🔍 Found {len(db_files)} database(s):")
for db in db_files:
    print(f"   - {db}")

print("\n🚀 Starting Repair Job...")

for db_path in db_files:
    print(f"\n🔧 Fixing: {os.path.basename(db_path)}...")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 1. Fix Title
        try:
            cursor.execute("ALTER TABLE notification ADD COLUMN title VARCHAR(100)")
            print("   ✅ Added 'title' column.")
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                print("   ⚠️ Table 'notification' does not exist (Skipping).")
            else:
                print("   ℹ️ 'title' column already exists.")

        # 2. Fix Course Code
        try:
            cursor.execute("ALTER TABLE notification ADD COLUMN course_code VARCHAR(20)")
            print("   ✅ Added 'course_code' column.")
        except sqlite3.OperationalError:
            pass # Ignore if exists

        conn.commit()
        conn.close()
        print("   ✨ Done.")

    except Exception as e:
        print(f"   ❌ Could not open file: {e}")

print("\n🎉 ALL DATABASES FIXED. Run 'python app.py' now!")