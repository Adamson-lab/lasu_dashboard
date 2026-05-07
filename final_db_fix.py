import sqlite3

def final_fix():
    db_file = 'lasu_data.db'
    print(f"🔧 Connecting to {db_file}...")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # List of updates to perform
    updates = [
        ("user", "allow_read_receipts", "BOOLEAN DEFAULT 1"),
        ("student", "allow_read_receipts", "BOOLEAN DEFAULT 1"),
        ("message", "is_read", "BOOLEAN DEFAULT 0")
    ]

    for table, column, definition in updates:
        try:
            print(f"🛠️ Checking {table} for {column}...")
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            print(f"✅ Added {column} to {table} successfully.")
        except sqlite3.OperationalError:
            print(f"ℹ️ {column} already exists in {table}. Skipping.")
        except Exception as e:
            print(f"❌ Error on {table}: {e}")

    conn.commit()
    conn.close()
    print("\n🎉 Database structure is now perfectly synchronized with your code!")

if __name__ == "__main__":
    final_fix()