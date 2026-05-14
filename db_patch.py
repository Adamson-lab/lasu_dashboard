from app import app, db
from sqlalchemy import text

def patch_database():
    print("Initiating Database Patch Protocol...")
    with app.app_context():
        try:
            # Injecting the time_limit column into the existing quiz table
            db.session.execute(text('ALTER TABLE quiz ADD COLUMN time_limit INTEGER DEFAULT 30;'))
            db.session.commit()
            print("✅ SUCCESS: 'time_limit' column successfully added to the Quiz table!")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Notice: {str(e)}")
            print("If the error says 'duplicate column name', it means the patch already ran successfully!")

if __name__ == '__main__':
    patch_database()