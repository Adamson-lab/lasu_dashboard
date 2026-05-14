from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# 1. USER (ADMIN) MODEL
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120), nullable=True) # For 2FA

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# 2. STUDENT MODEL
class Student(db.Model):
    # This line tells SQLAlchemy it's okay if the table already exists in MetaData
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    matric_no = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)

    # 🔐 Login Security
    password_hash = db.Column(db.String(200), nullable=True)

    department = db.Column(db.String(100), nullable=True)
    image_file = db.Column(db.String(20), nullable=False, default='default.jpg')
    attendance_pct = db.Column(db.Float, default=0.0)
    has_paid_fees = db.Column(db.Boolean, default=False)
    
    # Bio-Data
    personal_email = db.Column(db.String(120), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    level = db.Column(db.Integer, default=100)
    lecturer_note = db.Column(db.Text, nullable=True)

    # 🔥🔥 NEW: STUDY STREAK TRACKING
    streak_count = db.Column(db.Integer, default=0)
    last_study_date = db.Column(db.Date, nullable=True)

    # 🔐 Password Methods
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    # ========================================================
    # 🧠 INTELLIGENCE: RISK RADAR & STATS (Added Here)
    # ========================================================
    @property
    def average_score(self):
        """Calculates the average score from all quiz results."""
        if not self.quiz_results:
            return 0
        total = sum([q.score for q in self.quiz_results])
        # Avoid division by zero
        return round(total / len(self.quiz_results), 1)

    @property
    def academic_status(self):
        """Determines if student is SAFE, AT RISK, or CRITICAL."""
        # 1. Check Attendance
        total_classes = len(self.attendances)
        if total_classes > 0:
            present = len([a for a in self.attendances if a.status == 'Present'])
            att_pct = (present / total_classes) * 100
        else:
            att_pct = 100 # Default to safe if no data
            
        # 2. Check Scores
        avg = self.average_score
        
        # 3. Verdict Logic
        if att_pct < 50 or avg < 40:
            return "CRITICAL" # 🔴 Red Alert
        elif att_pct < 75 or avg < 50:
            return "AT RISK"  # 🟡 Warning
        else:
            return "SAFE"     # 🟢 Good
    # ========================================================

    # Relationships
    grades = db.relationship('Grade', backref='student', lazy=True)
    # Note: 'complaints' backref is updated in Complaint model below
    payments = db.relationship('Payment', backref='student', lazy=True)
    hostel_allocation = db.relationship('HostelAllocation', backref='student', uselist=False, lazy=True)
    quiz_results = db.relationship('QuizResult', backref='student', lazy=True)
    attendances = db.relationship('Attendance', backref='student', lazy=True)
    submissions = db.relationship('Submission', backref='student', lazy=True)
    evaluations = db.relationship('CourseEvaluation', backref='student', lazy=True)
    borrowings = db.relationship('Borrowing', backref='student', lazy=True)
    # appointments -> via OfficeHour backref

# Association Table
course_student = db.Table('course_student',
    db.Column('student_id', db.Integer, db.ForeignKey('student.id'), primary_key=True),
    db.Column('course_id', db.Integer, db.ForeignKey('course.id'), primary_key=True)
)

# 3. COURSE MODEL
class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    title = db.Column(db.String(100), nullable=False)
    units = db.Column(db.Integer, nullable=False)
    
    # 👇 NEW: EXAM CLASH DETECTOR COLUMNS 👇
    exam_date = db.Column(db.Date, nullable=True)
    exam_time = db.Column(db.String(20), nullable=True)
    exam_venue = db.Column(db.String(100), nullable=True)
    # 👆 --------------------------------- 👆

    # 👇 NEW: Link Course to Lecturer (Added for Virtual Office Hours System) 👇
    lecturer_id = db.Column(db.Integer, db.ForeignKey('lecturer.id'), nullable=True)
    
    students = db.relationship('Student', secondary=course_student, backref=db.backref('registered_courses', lazy=True))
    materials = db.relationship('CourseMaterial', backref='course', lazy=True)
    schedules = db.relationship('ClassSchedule', backref='course', lazy=True)
    quizzes = db.relationship('Quiz', backref='course', lazy=True)
    assignments = db.relationship('Assignment', backref='course', lazy=True)

# 4. GRADE MODEL
class Grade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    course_code = db.Column(db.String(10), nullable=False)
    score = db.Column(db.Integer, nullable=False)

# 5. AUDIT LOG
class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(50))
    action = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# 6. COMPLAINT SYSTEM (FIXED & RENAMED)
class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    matric_no = db.Column(db.String(20))
    student_name = db.Column(db.String(100))
    category = db.Column(db.String(50))
    message = db.Column(db.Text)
    status = db.Column(db.String(20), default='Pending')
    date_lodged = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Link to Student
    student_ref = db.relationship('Student', backref='my_complaints_list', lazy=True)

    # ✅ FIXED RELATIONSHIP: Uses 'ComplaintMessage' and 'back_populates'
    messages = db.relationship('ComplaintMessage', back_populates='complaint', cascade='all, delete-orphan', lazy=True)

class ComplaintMessage(db.Model):
    __tablename__ = 'complaint_message' # Explicit table name matches app.py logic
    
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaint.id'), nullable=False)
    sender = db.Column(db.String(20)) # 'Student' or 'Lecturer'
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # ✅ FIXED RELATIONSHIP: Explicit link back to Complaint
    complaint = db.relationship('Complaint', back_populates='messages')

# 7. ANNOUNCEMENT
class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    content = db.Column(db.Text)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)

# 8. COURSE MATERIALS
class CourseMaterial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    title = db.Column(db.String(100))
    filename = db.Column(db.String(100))
    date_uploaded = db.Column(db.DateTime, default=datetime.utcnow)

# 9. PAYMENT SYSTEM
class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    date_paid = db.Column(db.DateTime, default=datetime.utcnow)

# 10. HOSTEL SYSTEM
class Hostel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    occupied = db.Column(db.Integer, default=0)
    price = db.Column(db.Float, nullable=False)
    allocations = db.relationship('HostelAllocation', backref='hostel', lazy=True)

class HostelAllocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, unique=True)
    hostel_id = db.Column(db.Integer, db.ForeignKey('hostel.id'), nullable=False)
    date_allocated = db.Column(db.DateTime, default=datetime.utcnow)

# 11. TIMETABLE / SCHEDULE
class ClassSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    day = db.Column(db.String(15), nullable=False) # Monday, Tuesday...
    start_time = db.Column(db.String(10), nullable=False) # 09:00
    end_time = db.Column(db.String(10), nullable=False) # 11:00
    venue = db.Column(db.String(50), nullable=False)

# 12. CBT / QUIZ SYSTEM
class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    questions = db.relationship('Question', backref='quiz', lazy=True, cascade="all, delete-orphan")
    # 🟢 ADD THIS LINE:
    time_limit = db.Column(db.Integer, default=30) # Default to 30 minutes

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(200), nullable=False)
    option_b = db.Column(db.String(200), nullable=False)
    option_c = db.Column(db.String(200), nullable=False)
    option_d = db.Column(db.String(200), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False) # A, B, C, or D

class QuizResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    # 🟢 NEW: Track Cheating Attempts
    violations = db.Column(db.Integer, default=0)
    date_taken = db.Column(db.DateTime, default=datetime.utcnow)


# =========================================================
    # 🟢 CRITICAL FIX: ADD THIS RELATIONSHIP
    # This allows 'appeal.quiz_result.quiz.title' to work!
    # =========================================================
    quiz = db.relationship('Quiz', backref='results')

# 13. ATTENDANCE SYSTEM
class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), nullable=False) # Present / Absent

# 14. ASSIGNMENT / HOMEWORK SYSTEM
class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    instruction = db.Column(db.Text, nullable=False)
    points = db.Column(db.Integer, default=100)
    due_date = db.Column(db.DateTime, nullable=False)
    submissions_list = db.relationship('Submission', backref='assignment', lazy=True)

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    file_path = db.Column(db.String(200), nullable=False)
    score = db.Column(db.Integer, nullable=True)
    lecturer_comment = db.Column(db.Text, nullable=True)
    date_submitted = db.Column(db.DateTime, default=datetime.utcnow)

# 15. COURSE EVALUATION
class CourseEvaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    date_submitted = db.Column(db.DateTime, default=datetime.utcnow)

# 16. DIGITAL LIBRARY
class LibraryBook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    cover_image = db.Column(db.String(100), default='default_book.jpg')
    pdf_file = db.Column(db.String(100))
    stock_quantity = db.Column(db.Integer, default=0)
    category = db.Column(db.String(50), default='General')
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    borrowings = db.relationship('Borrowing', backref='book', lazy=True)

class Borrowing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('library_book.id'), nullable=False)
    borrow_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime)
    return_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='Borrowed')

# 17. SYLLABUS TRACKER
class SyllabusTopic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    week_number = db.Column(db.Integer, default=1)
    completions = db.relationship('TopicCompletion', backref='topic', lazy=True)

class TopicCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    topic_id = db.Column(db.Integer, db.ForeignKey('syllabus_topic.id'), nullable=False)
    date_completed = db.Column(db.DateTime, default=datetime.utcnow)

class ChatSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    title = db.Column(db.String(100), default="New Chat")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship('ChatMessage', backref='session', lazy=True, cascade="all, delete-orphan")

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('chat_session.id'), nullable=False)
    role = db.Column(db.String(20)) # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ==========================================
#   VIRTUAL OFFICE HOURS & LECTURER SYSTEM
# ==========================================

# 18. LECTURER MODEL (NEW)
class Lecturer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(20)) # e.g. Dr., Prof., Mr.
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    department = db.Column(db.String(100))
    image_file = db.Column(db.String(20), nullable=False, default='default_lecturer.jpg')
    
    # Security
    password_hash = db.Column(db.String(200), nullable=False)

    # Relationships
    office_hours = db.relationship('OfficeHour', backref='lecturer', lazy=True)
    courses_taught = db.relationship('Course', backref='lecturer', lazy=True) 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# 19. OFFICE HOUR SLOTS (NEW)
class OfficeHour(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    # 1. Foreign Keys
    lecturer_id = db.Column(db.Integer, db.ForeignKey('lecturer.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True)
    
    # 2. Data Columns
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    is_booked = db.Column(db.Boolean, default=False)
    meeting_link = db.Column(db.String(200))
    topic = db.Column(db.String(200))

    # 3. Relationships
    student = db.relationship('Student', backref='appointments')
    course = db.relationship('Course', backref='office_hours')
    attendees = db.relationship('SlotAttendee', backref='slot', cascade="all, delete-orphan")

# ==========================================
# 🆕 NEW TABLE: TRACK MULTIPLE STUDENTS PER SLOT
# ==========================================
class SlotAttendee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.Integer, db.ForeignKey('office_hour.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    
    # Relationships
    student = db.relationship('Student')


# ==========================================
# 🔔 21. NOTIFICATION SYSTEM (INBOX)
# ==========================================
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    title = db.Column(db.String(100), nullable=True) # Subject line
    course_code = db.Column(db.String(20))           # Optional: context
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)


class Appeal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    quiz_result_id = db.Column(db.Integer, db.ForeignKey('quiz_result.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)  # The student's defense
    status = db.Column(db.String(20), default='Pending')  # Pending, Approved, Rejected
    date_submitted = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    student = db.relationship('Student', backref='appeals')
    quiz_result = db.relationship('QuizResult', backref=db.backref('appeals', passive_deletes=True))


class ChangeCourseRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    current_dept = db.Column(db.String(100), nullable=False)
    new_dept = db.Column(db.String(100), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    cgpa_snapshot = db.Column(db.Float, nullable=False)  # Save CGPA at time of application
    status = db.Column(db.String(20), default='Pending') # Pending, Approved, Rejected
    date_submitted = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    student = db.relationship('Student', backref='transfer_requests')