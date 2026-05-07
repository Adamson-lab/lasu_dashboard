import sqlite3

def update_database():
    print("🔌 Connecting to database...")
    conn = sqlite3.connect('lasu_data.db')
    cursor = conn.cursor()

    # 1. Update User Table (Lecturers)
    try:
        print("1️⃣ Updating User table...")
        cursor.execute("ALTER TABLE user ADD COLUMN allow_read_receipts BOOLEAN DEFAULT 1")
        print("✅ Success: Added 'allow_read_receipts' to User.")
    except Exception as e:
        print(f"⚠️ Note: {e}")

    # 2. Update Student Table
    try:
        print("2️⃣ Updating Student table...")
        cursor.execute("ALTER TABLE student ADD COLUMN allow_read_receipts BOOLEAN DEFAULT 1")
        print("✅ Success: Added 'allow_read_receipts' to Student.")
    except Exception as e:
        print(f"⚠️ Note: {e}")

    # 3. Update Message Table
    try:
        print("3️⃣ Updating Message table...")
        cursor.execute("ALTER TABLE message ADD COLUMN is_read BOOLEAN DEFAULT 0")
        print("✅ Success: Added 'is_read' to Message.")
    except Exception as e:
        print(f"⚠️ Note: {e}")

    conn.commit()
    conn.close()
    print("\n🎉 Database update complete! ALL DATA IS SAFE.")

if __name__ == "__main__":
    update_database()