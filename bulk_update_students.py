from app import app, db
from models import Student

def assign_departments():
    with app.app_context():
        # 1. Fetch all students
        students = Student.query.all()
        
        updated_count = 0
        for student in students:
            # 2. Assign department if it's empty
            # You can customize this logic (e.g., based on matric number prefix)
            if not student.department:
                student.department = "CSC" # Assigning 'CSC' as default for now
                updated_count += 1
        
        db.session.commit()
        print(f"✅ Successfully assigned 'CSC' department to {updated_count} students.")

if __name__ == "__main__":
    assign_departments()