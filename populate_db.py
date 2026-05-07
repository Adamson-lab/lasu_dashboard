from app import app, db
from models import User, Course, Student, Grade
import random

def populate():
    with app.app_context():
        db.create_all()
        
        # 1. Create Admin User
        if not User.query.filter_by(username='admin').first():
            user = User(username='admin', email='lecturer@lasu.edu.ng')
            user.set_password('lasu2025')
            db.session.add(user)
            print("✅ Admin User Created.")

        # 2. Create 30 Realistic Courses
        courses_data = [
            ('CSC 101', 'Intro to Computer Science', 3), ('CSC 102', 'Problem Solving', 3),
            ('MTH 101', 'General Maths I', 3), ('MTH 102', 'General Maths II', 3),
            ('PHY 101', 'General Physics I', 3), ('PHY 102', 'General Physics II', 3),
            ('GNS 101', 'Use of English', 2), ('GNS 102', 'Philosophy & Logic', 2),
            ('CSC 201', 'Programming I (C++)', 3), ('CSC 202', 'Programming II (Java)', 3),
            ('CSC 203', 'Operating Systems I', 3), ('CSC 204', 'Data Structures', 3),
            ('MTH 201', 'Mathematical Methods', 3), ('ENT 201', 'Entrepreneurship', 2),
            ('CSC 301', 'Structured Programming', 3), ('CSC 302', 'Object-Oriented Prog', 3),
            ('CSC 304', 'Data Management', 3), ('CSC 305', 'Operating Systems II', 3),
            ('CSC 310', 'Algorithms', 3), ('CSC 332', 'Survey of Languages', 2),
            ('CSC 401', 'Software Engineering', 3), ('CSC 402', 'Computer Graphics', 3),
            ('CSC 403', 'Systems Analysis', 3), ('CSC 404', 'Data Comm & Networks', 3),
            ('CSC 405', 'Artificial Intelligence', 3), ('CSC 411', 'Project Management', 2),
            ('CSC 499', 'Final Year Project', 6), ('BIO 101', 'General Biology', 3),
            ('CHM 101', 'General Chemistry', 3), ('STA 101', 'Statistics', 2)
        ]

        all_courses = []
        for code, title, units in courses_data:
            course = Course.query.filter_by(code=code).first()
            if not course:
                course = Course(code=code, title=title, units=units)
                db.session.add(course)
            all_courses.append(course)
        db.session.commit()
        print(f"✅ Verified {len(courses_data)} Courses.")

        # 3. Generate 50 Students (If not already present)
        if Student.query.count() < 50:
            print("⏳ Generating 50 Students with Bio-Data & Grades... Please wait.")
            
            first_names = ["Oluwaseun", "Chioma", "Ibrahim", "Ngozi", "Yusuf", "Zainab", "Emeka", "Funke", "Emmanuel", "Aisha", "Samuel", "Victoria", "Tunde", "Amarachi", "Musa", "Kehinde", "Blessing", "Yakubu", "Folake", "Chinedu", "David", "Sarah", "Grace", "Daniel", "Favour"]
            last_names = ["Adeyemi", "Okoro", "Bello", "Okafor", "Abubakar", "Williams", "Eze", "Balogun", "Obi", "Usman", "Adeleke", "Igwe", "Sani", "Coker", "Bassey", "Danjuma", "Falana", "Nwosu", "Owolabi", "Yusuf", "Bishop", "King", "Doe", "Johnson", "Smith"]
            departments = ['Computer Science', 'Economics', 'Mathematics', 'Physics', 'Chemistry']
            addresses = ["Ikeja, Lagos", "Yaba, Lagos", "Festac, Lagos", "Ojo Campus", "Epe Campus", "Surulere, Lagos", "Badagry, Lagos", "Lekki, Lagos"]

            # Generate 50 Unique Students
            for i in range(50):
                fname = random.choice(first_names)
                lname = random.choice(last_names)
                full_name = f"{fname} {lname}"
                
                # Ensure unique Matric No
                matric = f"CSC/2021/{1000+i}"
                
                # Check if exists (to avoid duplicates on re-run)
                if not Student.query.filter_by(matric_no=matric).first():
                    student = Student(
                        matric_no=matric,
                        name=full_name,
                        department=random.choice(departments),
                        attendance_pct=random.uniform(50, 100),
                        has_paid_fees=random.choice([True, True, False]), # 66% chance paid
                        level=random.choice([100, 200, 300, 400]),
                        phone_number=f"080{random.randint(10000000, 99999999)}",
                        personal_email=f"{fname.lower()}.{lname.lower()}@lasu.edu.ng",
                        address=random.choice(addresses)
                    )
                    db.session.add(student)
                    db.session.flush() # Get ID for relationships

                    # Add 4-6 Random Grades & Registrations
                    num_courses = random.randint(4, 6)
                    student_courses = random.sample(all_courses, num_courses)
                    
                    for course in student_courses:
                        # 1. Register the course
                        student.registered_courses.append(course)
                        
                        # 2. Assign a Grade (Score between 30 and 90)
                        score = random.randint(30, 95)
                        grade = Grade(student_id=student.id, course_code=course.code, score=score)
                        db.session.add(grade)
            
            db.session.commit()
            print("🎉 Successfully created 50 Students with full Bio-Data & Results!")
        else:
            print("ℹ️ 50+ Students already exist. No new data added.")

if __name__ == '__main__':
    populate()