import sqlite3

# Connect to your database
conn = sqlite3.connect('lasu_data.db')
cursor = conn.cursor()

print("🔧 Attempting to patch database schema...")

# 1. Add exam_date column
try:
    cursor.execute("ALTER TABLE course ADD COLUMN exam_date DATE")
    print("✅ Successfully added 'exam_date' column.")
except sqlite3.OperationalError:
    print("ℹ️ 'exam_date' column already exists.")

# 2. Add exam_time column
try:
    cursor.execute("ALTER TABLE course ADD COLUMN exam_time VARCHAR(20)")
    print("✅ Successfully added 'exam_time' column.")
except sqlite3.OperationalError:
    print("ℹ️ 'exam_time' column already exists.")

conn.commit()
conn.close()

print("🎉 Database patch complete! You can now restart app.py.")