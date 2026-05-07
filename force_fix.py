import sqlite3
import os

def fix_database(db_path):
    # Get absolute path to be 100% sure where we are looking
    abs_path = os.path.abspath(db_path)
    print(f"\n🔍 CHECKING DATABASE: {abs_path}")
    
    if not os.path.exists(db_path):
        print(f"   ⚠️ File not found at this path.")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 1. LIST ALL TABLES (To prove we found the real DB)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"   📂 Tables found ({len(tables)}): {', '.join(tables)}")

        if 'student' not in tables:
            print("   ❌ WARNING: This looks like an EMPTY or WRONG database! (No 'student' table found)")
        
        # 2. FORCE CREATE the missing table
        print("   🔨 Attempting to create 'complaint_message'...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS complaint_message (
                id INTEGER PRIMARY KEY,
                complaint_id INTEGER NOT NULL,
                sender VARCHAR(20),
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(complaint_id) REFERENCES complaint(id)
            )
        ''')
        conn.commit()
        
        # 3. VERIFY
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='complaint_message';")
        if cursor.fetchone():
            print(f"   ✅ SUCCESS: 'complaint_message' table is now present.")
        else:
            print(f"   ❌ ERROR: Creation failed.")
            
        conn.close()
    except Exception as e:
        print(f"   ⚠️ Critical Error: {e}")

# Main Execution
if __name__ == "__main__":
    print("--- STARTING DIAGNOSTIC FIX ---")
    
    # Check Root
    fix_database('lasu_data.db')
    
    # Check Instance Folder
    if os.path.exists('instance'):
        fix_database('instance/lasu_data.db')
        
    print("\n--- DONE ---")