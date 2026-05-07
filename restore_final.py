from app import app, db
from models import Student

def restore_original_departments():
    with app.app_context():
        students = Student.query.all()
        restored_count = 0
        
        # Mapping prefixes to the EXACT names used in your project logic
        dept_map = {
            "CSC": "Computer Science",
            "MCB": "Microbiology",
            "BCH": "Biochemistry",
            "ACC": "Accounting",
            "ECN": "Economics",
            "MAC": "Mass Communication",
            "LAW": "Law"
        }
        
        print("Starting restoration...")
        for s in students:
            try:
                # Extracts 'CSC' from 'CSC/2021/001'
                prefix = s.matric_no.split('/')[0].upper().strip()
                
                if prefix in dept_map:
                    s.department = dept_map[prefix]
                    restored_count += 1
                else:
                    # Default safety fallback
                    s.department = "Computer Science"
            except Exception as e:
                print(f"Skipping {s.matric_no}: {e}")
                continue
                
        db.session.commit()
        print(f"✅ SUCCESS: {restored_count} students restored to their actual departments.")

if __name__ == "__main__":
    restore_original_departments()