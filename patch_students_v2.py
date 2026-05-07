from app import app, db
from models import Student

def force_patch():
    with app.app_context():
        students = Student.query.all()
        
        if not students:
            print("❌ No students found in the database at all!")
            return

        print(f"Total students found: {len(students)}")
        
        updated_count = 0
        for student in students:
            print(f"Updating Student: {student.name} (Current Dept: '{student.department}')")
            student.department = "CSC"
            updated_count += 1
        
        db.session.commit()
        print(f"✅ Force Patch Complete: {updated_count} students are now in the CSC department.")

if __name__ == "__main__":
    force_patch()