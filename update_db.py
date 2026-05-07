from app import app, db
# Import ALL models including Hostel and HostelAllocation
from models import Complaint, Announcement, CourseMaterial, Payment, Hostel, HostelAllocation

with app.app_context():
    db.create_all()
    print("✅ Database updated! Hostel tables added.")