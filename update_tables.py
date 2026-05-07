from app import app, db

# 🟢 IMPORT APPEAL TO ENSURE IT IS REGISTERED
# (Try importing from models, if that fails, it assumes it's in app.py)
try:
    from models import Appeal
    print("✅ Found Appeal model in models.py")
except ImportError:
    print("ℹ️ Appeal model not in models.py (assuming it is in app.py)")

print("------------------------------------------------")
print("⏳ Connecting to database...")

with app.app_context():
    # This magic command creates any missing tables
    db.create_all()
    
    print("✅ SUCCESS: Database tables updated!")
    print("------------------------------------------------")
    print("🚀 FIX COMPLETE. You can now restart your server.")