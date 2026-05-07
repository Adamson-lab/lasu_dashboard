import sqlite3
import os

print("🔍 Scanning for database files...")

# Find all .db files in the current directory and subdirectories
db_files = []
for root, dirs, files in os.walk("."):
    for file in files:
        if file.endswith(".db"):
            full_path = os.path.join(root, file)
            db_files.append(full_path)

if not db_files:
    print("❌ No database file found! Run your app once ('python app.py') to create it.")
else:
    print(f"✅ Found {len(db_files)} database(s):")
    for idx, db_path in enumerate(db_files):
        print(f"   [{idx + 1}] {db_path}")

    # Use the first found database automatically (usually the right one)
    target_db = db_files[0]
    print(f"\n🔧 Patching: {target_db} ...")

    try:
        conn = sqlite3.connect(target_db)
        cursor = conn.cursor()
        
        # Add the missing column
        cursor.execute("ALTER TABLE exchange_program ADD COLUMN application_url TEXT")
        
        conn.commit()
        conn.close()
        print("🎉 SUCCESS! Database patched. You can now use the Study Abroad page.")
        
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print("✅ Good news! The column 'application_url' already exists.")
        else:
            print(f"⚠️  Database Message: {e}")
            print("This usually means the patch worked previously or the table structure is different.")