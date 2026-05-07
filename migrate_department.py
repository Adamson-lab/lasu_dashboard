from app import app, db
import sqlalchemy as sa

def inject_department_column():
    with app.app_context():
        # Bind to your existing engine
        engine = db.engine
        inspector = sa.inspect(engine)
        
        # Get current columns in the student table
        columns = [c['name'] for c in inspector.get_columns('student')]
        
        if 'department' not in columns:
            print("🚀 Injecting 'department' column into existing 'student' table...")
            try:
                with engine.begin() as conn:
                    # Adding as NULLABLE so existing data remains safe
                    conn.execute(sa.text('ALTER TABLE student ADD COLUMN department VARCHAR(100)'))
                print("✅ Done! Column added without data loss.")
            except Exception as e:
                print(f"❌ SQL Error: {e}")
        else:
            print("ℹ️ Column 'department' already exists. Your database is already up to date.")

if __name__ == "__main__":
    inject_department_column()