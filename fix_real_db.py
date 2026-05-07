from app import app, db
from sqlalchemy import text
import os

def fix_the_real_database():
    print("\n🚀 STARTING DATABASE REPAIR...")
    
    # 1. Load the App Context (This ensures we see what Flask sees)
    with app.app_context():
        # Get the actual database path Flask is using
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
        print(f"📂 Flask is using this database: {db_uri}")
        
        # 2. Force the update using SQLAlchemy
        # This bypasses file path issues by using the engine directly
        with db.engine.connect() as conn:
            # Fix Streak Count
            try:
                print("🔧 Attempting to add 'streak_count'...")
                conn.execute(text("ALTER TABLE student ADD COLUMN streak_count INTEGER DEFAULT 0"))
                print("✅ Success: 'streak_count' added.")
            except Exception as e:
                print(f"ℹ️ Status: Column likely exists already. ({e})")

            # Fix Last Study Date
            try:
                print("🔧 Attempting to add 'last_study_date'...")
                conn.execute(text("ALTER TABLE student ADD COLUMN last_study_date DATE"))
                print("✅ Success: 'last_study_date' added.")
            except Exception as e:
                print(f"ℹ️ Status: Column likely exists already. ({e})")
                
            conn.commit()
            
    print("\n🎉 REPAIR COMPLETE. You can restart 'app.py' now.")

if __name__ == "__main__":
    fix_the_real_database()