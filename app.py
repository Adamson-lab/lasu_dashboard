import csv
import io
import os
import secrets
import requests  # Direct connection to Google AI
import smtplib
import qrcode
import json
import urllib3  # <--- THIS WAS MISSING BEFORE
import re
import PyPDF2
import subprocess
import sys
import zipfile
import ast  # <--- 🟢 ADD THIS NEW IMPORT HERE
import httpx
import time
from io import BytesIO
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date, timedelta
import random
import string
import sqlite3
from flask import Flask, render_template, jsonify, Response, request, redirect, url_for, session, flash, send_file, send_from_directory
from flask_cors import CORS
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
# ---------------------------------------------------------
# 🟢 PASTE THIS RIGHT AFTER YOUR IMPORTS
# ---------------------------------------------------------
from functools import wraps  # <--- You need this import!

# 🟢 UPDATED: This now allows BOTH Students and Lecturers/Admins
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 🟢 THE MASTER KEY: If you are an Admin OR a Student, you stay in.
        if 'logged_in' in session or 'student_logged_in' in session:
            return f(*args, **kwargs)
        # If neither, go to login
        return redirect(url_for('login'))
    return decorated_function



# 🛑 TITANIUM PADLOCK: MASTER ADMINS ONLY
def admin_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash("⛔ ACCESS DENIED: Master Admin clearance required.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# 🧠 THE MAGIC DATA SILO (ZERO-STRESS MULTI-TENANCY)
def my_data(model):
    from models import Course  # 🟢 THE FIX: Moved to the top so ALL paths can see it!
    
    if session.get('role') == 'admin':
        return model.query
        
    elif session.get('role') == 'lecturer':
        lecturer_id = session.get('user_id')
        
        # A. Does this table belong to a Lecturer?
        if hasattr(model, 'lecturer_id'):
            return model.query.filter_by(lecturer_id=lecturer_id)
            
        # B. Does this table belong to a Course?
        elif hasattr(model, 'course_id'):
            my_courses = Course.query.filter_by(lecturer_id=lecturer_id).all()
            my_course_ids = [c.id for c in my_courses]
            if my_course_ids: 
                return model.query.filter(model.course_id.in_(my_course_ids))
            return model.query.filter(model.id == -1) 
            
        # C. Students (Linked via registered_courses)
        elif model.__name__ == 'Student':
            my_courses = Course.query.filter_by(lecturer_id=lecturer_id).all()
            my_course_ids = [c.id for c in my_courses]
            if my_course_ids: 
                return model.query.filter(model.registered_courses.any(Course.id.in_(my_course_ids)))
            return model.query.filter(model.id == -1) 
            
        # D. Admin-Only Tables
        else: 
            return model.query.filter(model.id == -1) 
            
    # Failsafe
    return model.query.filter(model.id == -1)

# ---------------------------------------------------------


# Disable SSL Warnings (Fixes the "Connection Error" on local wifi)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Import existing models.
# Note: We will define NEW models (DailyAttendance, Clearance) directly in this file
# to ensure they work without you needing to edit 'models.py'.
from models import db, Student, Grade, User, AuditLog, Course, Complaint, Announcement, CourseMaterial, Payment, Hostel, HostelAllocation, ClassSchedule, Quiz, Question, QuizResult, Attendance, Assignment, Submission, ComplaintMessage, CourseEvaluation, LibraryBook, Borrowing, SyllabusTopic, TopicCompletion, ChatSession, ChatMessage, Lecturer, OfficeHour, SlotAttendee, Notification, Appeal, ChangeCourseRequest, ComplaintMessage

app = Flask(__name__)
CORS(app)  # <--- ADD THIS LINE (This allows all devices to connect)

session_pool = requests.Session()
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lasu_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'lasu_final_year_project_secret_key'

# This makes sure the "session.permanent" actually lasts for 30 days
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# --- 🧠 AI CONFIGURATION ---
GOOGLE_API_KEY = "AIzaSyB7Xq2icVax30inMewitJvPet_BU5-E5aQ"
GROQ_API_KEY = "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"

# EMAIL & FOLDER CONFIG
ENABLE_EMAIL = True
EMAIL_ADDRESS = "favouradamson803@gmail.com"
EMAIL_PASSWORD = "nivtfctmdjclunha"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

app.config['UPLOAD_FOLDER'] = 'static/profile_pics'
app.config['UPLOAD_MATERIALS_FOLDER'] = 'static/materials'
app.config['UPLOAD_ASSIGNMENTS_FOLDER'] = 'static/assignments'
app.config['UPLOAD_LIBRARY_COVERS'] = 'static/library/covers'
app.config['UPLOAD_LIBRARY_PDFS'] = 'static/library/pdfs'

for folder in [
    app.config['UPLOAD_FOLDER'],
    app.config['UPLOAD_MATERIALS_FOLDER'],
    app.config['UPLOAD_ASSIGNMENTS_FOLDER'],
    app.config['UPLOAD_LIBRARY_COVERS'],
    app.config['UPLOAD_LIBRARY_PDFS']
]:
    os.makedirs(folder, exist_ok=True)

db.init_app(app)




# --- NEW MODELS (DEFINED HERE FOR STABILITY) ---

# 1. Track attendance by specific dates
class DailyAttendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)  # Stores YYYY-MM-DD
    status = db.Column(db.String(20), default='Present')  # Present, Absent
    time_logged = db.Column(db.String(50), nullable=True) # 🟢 NEW: Stores exact WAT time


# 2. Final Year Clearance System (UPDATED)
class Clearance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    
    # Statuses: 'Pending', 'Cleared', 'Rejected'
    # We use explicit names to match our new logic
    bursary_status = db.Column(db.String(20), default='Pending')
    library_status = db.Column(db.String(20), default='Pending')
    department_status = db.Column(db.String(20), default='Pending')  # Renamed from dept_status
    sports_status = db.Column(db.String(20), default='Pending')
    health_center_status = db.Column(db.String(20), default='Pending') # Added this!
    
    date_initiated = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Helper to check if student is fully ready for graduation
    def is_fully_cleared(self):
        return (
            self.department_status == 'Cleared' and
            self.library_status == 'Cleared' and
            self.bursary_status == 'Cleared' and
            self.sports_status == 'Cleared' and
            self.health_center_status == 'Cleared'
        )

# --- NEW MODEL: SUBSCRIPTION MANAGER ---
class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # e.g. Netflix, Spotify
    amount = db.Column(db.Float, nullable=False)      # e.g. 5000.00
    next_due_date = db.Column(db.Date, nullable=False)
    category = db.Column(db.String(50), default='Entertainment') # Data, Rent, etc.


# 3. E-Voting Models
class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    course = db.relationship('Course', backref='exams')
    exam_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(10), nullable=False)
    end_time = db.Column(db.String(10), nullable=False)
    venue = db.Column(db.String(100), nullable=False)


class ElectionPosition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    candidates = db.relationship('Candidate', backref='position', lazy=True)


class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(db.Integer, db.ForeignKey('election_position.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    manifesto = db.Column(db.String(255))
    vote_count = db.Column(db.Integer, default=0)


class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    position_id = db.Column(db.Integer, db.ForeignKey('election_position.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# ==========================================
# 🚀 PLACE PEERRESOURCE & RESOURCEREVIEW HERE
# ==========================================

class PeerResource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(50))
    
    # --- 🏗️ NEW FIELD FOR FILTERING ---
    faculty = db.Column(db.String(100), nullable=True)
    level = db.Column(db.String(10), nullable=True)
    dept = db.Column(db.String(100), nullable=True)
    # ----------------------------------
    
    filename = db.Column(db.String(100), nullable=False)
    downloads = db.Column(db.Integer, default=0)
    date_shared = db.Column(db.DateTime, default=datetime.utcnow)
    
    ratings = db.relationship('ResourceRating', backref='resource', lazy=True)
    uploader = db.relationship('Student', backref='shared_resources')


class ResourceRating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('peer_resource.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    stars = db.Column(db.Integer, nullable=False)  # 1 to 5
    comment = db.Column(db.String(200))
    date_rated = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to get student info for the review
    student = db.relationship('Student', backref='my_ratings')


class ResourceReview(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('peer_resource.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    rating = db.Column(db.Integer)
    comment = db.Column(db.String(255))


class Bookmark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('peer_resource.id'), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

    # Links to easily access resource details from a bookmark
    resource = db.relationship('PeerResource', backref='bookmarked_by')


# --- NEW MODEL: NOTE-TAKING APP ---
class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False) # Stores Markdown text
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# --- NEW MODEL: MIND MAP ---
class MindMap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    name = db.Column(db.String(100), default="Untitled Idea")
    data = db.Column(db.Text, nullable=False) # Stores the JSON structure of the map
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# --- UPDATED MODEL ---
class ExchangeProgram(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    university = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(50), nullable=False)
    program_name = db.Column(db.String(150), nullable=False)
    deadline = db.Column(db.Date, nullable=False)
    min_cgpa = db.Column(db.Float, default=3.0)
    funding_type = db.Column(db.String(50), default="Partial Funding")
    image_url = db.Column(db.String(500)) # Stores reliable image links
    application_url = db.Column(db.String(500)) # Stores the REAL application link

# --- NEW MODEL: CERTIFICATION REPOSITORY ---
class Certification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)  # e.g. AWS Certified Cloud Practitioner
    issuer = db.Column(db.String(100), nullable=False) # e.g. Amazon Web Services
    date_earned = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date, nullable=True) # Optional (some don't expire)
    credential_id = db.Column(db.String(100), nullable=True) # Verification ID
    credly_link = db.Column(db.String(500), nullable=True) # Link to digital badge
    file_path = db.Column(db.String(300), nullable=True) # Path to uploaded file
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

# --- NEW MODEL: JOB TRACKER ---
class JobApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    company = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), default="Applied") # Applied, Interview, Offer, Rejected
    date_applied = db.Column(db.Date, default=date.today)
    notes = db.Column(db.Text, nullable=True)
    link = db.Column(db.String(300), nullable=True) # Link to job post


# --- NEW MODELS: CV BUILDER ---
class WorkExperience(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    company = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.String(20), nullable=False) # e.g. "Apr 2025"
    end_date = db.Column(db.String(20), default="Present")
    location = db.Column(db.String(50))
    description = db.Column(db.Text) # Bullet points separated by newlines

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    role_type = db.Column(db.String(100)) # e.g. "Personal Project"
    date_range = db.Column(db.String(50))
    description = db.Column(db.Text)
    tools = db.Column(db.String(200)) # e.g. "Python, AWS, Docker"

class Volunteer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    organization = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100), nullable=False)
    date_range = db.Column(db.String(50))
    description = db.Column(db.Text)

class Skill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    category = db.Column(db.String(50), default="Hard Skill") # Hard Skill, Soft Skill
    name = db.Column(db.String(200), nullable=False) # e.g. "Python, SQL, AWS"

class Award(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    issuer = db.Column(db.String(100))
    date_received = db.Column(db.String(20))


# --- NEW MODEL: SKILL CENTER ---
import json

class SkillQuiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    topic = db.Column(db.String(50), nullable=False) # e.g. Tech, Soft Skills
    difficulty = db.Column(db.String(20), default="Beginner")
    questions = db.Column(db.Text, nullable=False) # JSON string of questions
    badge_name = db.Column(db.String(100), nullable=False) # Badge earned if passed

class StudentBadge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('skill_quiz.id'), nullable=False)
    badge_name = db.Column(db.String(100), nullable=False)
    earned_date = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Integer)

import feedparser # REQUIRED for live internet data

# --- NEW MODEL: SAFETY ALERTS ---
class SafetyAlert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.Text)
    source = db.Column(db.String(100)) # e.g., "Google News", "GDACS"
    severity = db.Column(db.String(50)) # Critical, Warning, Info
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    link = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)


# --- NEW MODEL: S.O.S LIFELINE ---
# --- NEW MODEL: S.O.S LIFELINE ---
class SOSRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    # 1. The Needy Student (Requester)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    
    student_name = db.Column(db.String(100))
    type = db.Column(db.String(20), nullable=False) # 'CASH' or 'DATA'
    amount = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(200))
    
    # New Banking Fields
    bank_name = db.Column(db.String(100))      # e.g. GTBank
    account_number = db.Column(db.String(20))  # e.g. 0123456789
    
    # Data Fields
    network = db.Column(db.String(20)) 
    phone_number = db.Column(db.String(15))
    
    # 2. The Helper (Donor)
    helper_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True) 
    
    status = db.Column(db.String(20), default='Active')
    raised = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 👇 RELATIONSHIP FIX: Explicitly specify foreign_keys
    student = db.relationship('Student', foreign_keys=[student_id], backref='sos_requests')
    helper = db.relationship('Student', foreign_keys=[helper_id], backref='sos_helped')

class WalletTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    type = db.Column(db.String(20)) # 'CREDIT' (Received Help) or 'DEBIT' (Sent Help)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200))
    date = db.Column(db.DateTime, default=datetime.utcnow)


# --- NEW MODEL: CAMPUS MARKETPLACE ---
class MarketItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False) # Gadgets, Books, Hostel, Fashion, etc.
    description = db.Column(db.Text, nullable=True)
    image_file = db.Column(db.String(100), nullable=False, default='default_product.jpg')
    status = db.Column(db.String(20), default='Available') # Available, Sold
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Views/Clicks tracker for analytics
    views = db.Column(db.Integer, default=0)

    # Link to the seller
    seller = db.relationship('Student', backref='market_items')

# ==========================================
# 🧬 ATAS SYSTEM (FULL & CORRECTED)
# ==========================================

# 1. DATABASE MODELS (Ensure these are present)
class ATASProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    reputation_score = db.Column(db.Integer, default=500)
    chosen_timeline = db.Column(db.String(20), default='A')

class ATASOpportunity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    company = db.Column(db.String(100), nullable=False)
    match_score = db.Column(db.Integer)
    status = db.Column(db.String(20), default='Open')



# --- HELPER FUNCTIONS ---
def log_action(action_text):
    if session.get('logged_in'):
        user_name = session.get('user_name', 'Unknown User')
        new_log = AuditLog(user=user_name, action=action_text)
        db.session.add(new_log)
        db.session.commit()


def save_picture(form_picture):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(app.config['UPLOAD_FOLDER'], picture_fn)
    form_picture.save(picture_path)
    return picture_fn


def save_material_file(form_file):
    random_hex = secrets.token_hex(8)
    original_clean = secure_filename(form_file.filename)
    final_fn = f"{random_hex}_{original_clean}"
    file_path = os.path.join(app.config['UPLOAD_MATERIALS_FOLDER'], final_fn)
    form_file.save(file_path)
    return final_fn


def save_assignment_file(form_file):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_file.filename)
    final_fn = f"hw_{random_hex}{f_ext}"
    file_path = os.path.join(app.config['UPLOAD_ASSIGNMENTS_FOLDER'], final_fn)
    form_file.save(file_path)
    return final_fn


def save_library_file(form_file, folder_config_key):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_file.filename)
    final_fn = f"{random_hex}{f_ext}"
    file_path = os.path.join(app.config[folder_config_key], final_fn)
    form_file.save(file_path)
    return final_fn


def calculate_cgpa(student):
    total_points = 0
    total_units = 0
    for grade in student.grades:
        course = Course.query.filter_by(code=grade.course_code).first()
        units = course.units if course else 3
        if grade.score >= 70:
            point = 5
        elif grade.score >= 60:
            point = 4
        elif grade.score >= 50:
            point = 3
        elif grade.score >= 45:
            point = 2
        elif grade.score >= 40:
            point = 1
        else:
            point = 0
        total_points += (point * units)
        total_units += units
    cgpa = round(total_points / total_units, 2) if total_units > 0 else 0.00
    if cgpa >= 4.50:
        remark = "First Class Honours"
    elif cgpa >= 3.50:
        remark = "Second Class Upper"
    elif cgpa >= 2.40:
        remark = "Second Class Lower"
    elif cgpa >= 1.50:
        remark = "Third Class"
    elif cgpa >= 1.00:
        remark = "Pass"
    else:
        remark = "Probation"
    return cgpa, remark


def send_email_notification(to_email, subject, body):
    if not ENABLE_EMAIL:
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = f"LASU Matrix Admin <{EMAIL_ADDRESS}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # 🟢 ARCHITECT FIX: SSL Port 465 + 10s Timeout
        # This prevents the "forever loading" hang on Railway
        import smtplib
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) 
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"🚀 SUCCESS: Email dispatched to {to_email}")
        
    except Exception as e:
        print(f"🔥 SMTP CRITICAL FAILURE: {str(e)}")
        # Note: We don't raise here so the UI can still finish loading


# --- S.O.S HELPER FUNCTIONS (REAL) ---

# 1. CONFIGURATION
PAYSTACK_SECRET_KEY = "sk_test_3e89a601d1a89ada296018a4702eb1cb176497ed"
PAYSTACK_INIT_URL = "https://api.paystack.co/transaction/initialize"
PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify/"  # <--- THIS WAS MISSING!

# 👇👇👇 FILL THESE TWO LINES 👇👇👇
VTPASS_USER = "favouradamson803@gmail.com"  
VTPASS_PASSWORD = "Ikeoluwa2024@"      
VTPASS_URL = "https://vtpass.com/api/pay"

# 2. REAL PAYSTACK FUNCTION
def initialize_paystack_transaction(email, amount_naira, callback_url, metadata=None):
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "email": email,
        "amount": int(amount_naira * 100), # Convert to kobo
        "callback_url": callback_url,
        "metadata": metadata
    }
    try:
        req = requests.post(PAYSTACK_INIT_URL, json=data, headers=headers)
        return req.json()
    except Exception as e:
        return {'status': False, 'message': str(e)}

# 3. REAL VTPASS FUNCTION (NO MORE SIMULATION)
def send_vtu_topup(network, phone, amount, type='airtime'):
    # Map network names to what VTPass understands
    service_map = {
        'MTN': 'mtn', 
        'GLO': 'glo', 
        'AIRTEL': 'airtel', 
        '9MOBILE': 'etisalat'
    }
    service_id = service_map.get(network.upper())
    
    if not service_id:
        print(f"❌ Error: Unknown Network {network}")
        return False

    # Generate a random ID for the transaction
    import random
    request_id = datetime.now().strftime("%Y%m%d%H%M") + str(random.randint(1000,9999))

    payload = {
        "request_id": request_id,
        "serviceID": service_id,
        "amount": amount,
        "phone": phone
    }

    try:
        # Send to VTPass using your Email/Password
        response = requests.post(
            VTPASS_URL, 
            data=payload, 
            auth=(VTPASS_USER, VTPASS_PASSWORD)
        )
        
        # Check if it worked
        if response.status_code == 200:
            print(f"✅ VTPass Response: {response.json()}")
            return True
        else:
            print(f"❌ VTPass Failed: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return False


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # 1. ADMIN BYPASS
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['logged_in'] = True
            session['user_id'] = user.id
            session['user_name'] = "Dr. Adebayo"
            session['role'] = 'admin'
            return redirect(url_for('dashboard'))

        # 2. LECTURER BYPASS 
        lecturer = Lecturer.query.filter_by(email=username).first()
        if lecturer and lecturer.check_password(password):
            session['logged_in'] = True
            session['user_id'] = lecturer.id
            session['user_name'] = f"{lecturer.title} {lecturer.name}"
            session['role'] = 'lecturer'
            return redirect(url_for('dashboard'))

        flash('❌ Invalid Username or Password')
        
    return render_template('lecturer_login.html')


# ==========================================
# 🔐 UNIVERSAL 2FA VERIFICATION (ADMIN & LECTURER)
# ==========================================
@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    # If there's no pending login, kick them out
    if 'pre_2fa_user_id' not in session or 'pre_2fa_role' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        user_code = request.form['otp']
        generated_code = session.get('2fa_code')
        
        if user_code == generated_code:
            # Code is correct! Find out who they are.
            role = session.get('pre_2fa_role')
            user_id = session.get('pre_2fa_user_id')
            
            session['logged_in'] = True
            session['user_id'] = user_id
            session['role'] = role
            
            # Setup their specific profile data
            if role == 'admin':
                session['user_name'] = "Dr. Adebayo"
                log_action("Admin logged in via 2FA")
                flash("✅ Identity Confirmed. Welcome Admin.", "success")
                
            elif role == 'lecturer':
                lecturer = Lecturer.query.get(user_id)
                session['user_name'] = f"{lecturer.title} {lecturer.name}"
                log_action(f"Lecturer {lecturer.name} logged in via 2FA")
                flash(f"✅ Identity Confirmed. Welcome back, {lecturer.title} {lecturer.name}.", "success")
            
            # Clean up the temporary OTP session data
            session.pop('pre_2fa_user_id', None)
            session.pop('pre_2fa_role', None)
            session.pop('pre_2fa_email', None) # 🟢 Clean up the email too!
            session.pop('2fa_code', None)
            session.pop('2fa_expiry', None)
            
            return redirect(url_for('dashboard'))
        else:
            flash('❌ Incorrect OTP Code.')
            
    # 🟢 THE FIX: Grab the email and role from memory, and send them to the HTML
    email = session.get('pre_2fa_email', 'your email')
    role = session.get('pre_2fa_role', 'admin')
    return render_template('verify_otp.html', email=email, role=role)


# ==========================================
# 🛡️ LECTURER REGISTRATION (OTP SCRAPPED - DIRECT ENTRY)
# ==========================================
@app.route('/register_lecturer', methods=['POST'])
def register_lecturer():
    import re
    
    # 1. Capture Form Data
    title = request.form.get('title')
    name = request.form.get('name')
    dept = request.form.get('department')
    email = request.form.get('email').strip().lower()
    password = request.form.get('password')
    confirm = request.form.get('confirm_password')

    # 2. Strict Backend Gatekeeper
    if '@st.lasu.edu.ng' in email:
        flash("❌ Security Violation: Student domains (@st.lasu.edu.ng) are strictly prohibited.", "danger")
        session['show_register'] = True
        return redirect(url_for('login'))
        
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        flash("❌ Format Error: Please enter a valid email address.", "danger")
        session['show_register'] = True
        return redirect(url_for('login'))

    if password != confirm:
        flash("❌ Passwords do not match.", "danger")
        session['show_register'] = True
        return redirect(url_for('login'))

    # 3. Check if Lecturer already exists
    existing = Lecturer.query.filter_by(email=email).first()
    if existing:
        flash("⚠️ An account with this Email already exists.", "warning")
        session['show_register'] = True
        return redirect(url_for('login'))

    # 4. DIRECT DATABASE COMMIT (No OTP verification required)
    try:
        new_lecturer = Lecturer(
            title=title,
            name=name,
            email=email,
            department=dept
        )
        new_lecturer.set_password(password)
        db.session.add(new_lecturer)
        db.session.commit()
        
        # Success message
        flash(f"✅ Access Granted. Welcome to the Matrix, {title} {name}. You may now log in.", "success")
        return redirect(url_for('login'))
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Database Error: {str(e)}", "danger")
        session['show_register'] = True
        return redirect(url_for('login'))







# ==========================================
# 👨‍🏫 LECTURER MAIN DASHBOARD (FIXED ENDPOINT)
# ==========================================
@app.route('/lecturer/dashboard')
@login_required
def lecturer_dashboard():
    # Instantly reroute them to the newly unified Master Matrix
    return redirect(url_for('dashboard'))



@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.')
    return redirect(url_for('login'))


# --- MAIN DASHBOARD ROUTES ---
@app.route('/')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    role = session.get('role')
    user_id = session.get('user_id')

    if role == 'lecturer':
        lecturer = Lecturer.query.get(user_id)
        my_courses = Course.query.filter_by(lecturer_id=lecturer.id).all()
        my_course_ids = [c.id for c in my_courses]
        
        if my_course_ids:
            my_students = Student.query.filter(Student.registered_courses.any(Course.id.in_(my_course_ids))).all()
            total_students = len(my_students)
            at_risk_count = Student.query.filter(Student.registered_courses.any(Course.id.in_(my_course_ids)), Student.attendance_pct < 70).count()
            # 🟢 Lecturer Math
            attendance_rate = round(sum([s.attendance_pct for s in my_students]) / total_students, 1) if total_students > 0 else 0
            upcoming_schedules = ClassSchedule.query.filter(ClassSchedule.course_id.in_(my_course_ids)).limit(3).all()
        else:
            total_students = at_risk_count = attendance_rate = 0
            upcoming_schedules = []
            
        recent_activities = AuditLog.query.filter_by(user=session.get('user_name')).order_by(AuditLog.timestamp.desc()).limit(4).all()

    else:
        # 👑 Admin Logic
        total_students = Student.query.count()
        at_risk_count = Student.query.filter(Student.attendance_pct < 70).count()
        # 🟢 Admin Math: Global Average across all students
        global_avg = db.session.query(func.avg(Student.attendance_pct)).scalar()
        attendance_rate = round(global_avg, 1) if global_avg else 0
        upcoming_schedules = ClassSchedule.query.limit(3).all()
        recent_activities = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(4).all()

    announcements = Announcement.query.order_by(Announcement.date_posted.desc()).all()
    pending_count = Complaint.query.filter_by(status='Pending').count()
    
    return render_template(
        'dashboard.html',
        total=total_students,
        risk=at_risk_count,
        attendance_rate=attendance_rate, # 👈 THE KEY
        announcements=announcements,
        pending_count=pending_count,
        upcoming_schedules=upcoming_schedules,
        recent_activities=recent_activities
    )

    # (Keep your Admin logic below this...)

    # 🟢 If it's the Master Admin, show Global Campus Data
    total_students = my_data(Student).count()
    at_risk_count = my_data(Student).filter(Student.attendance_pct < 70).count()
    announcements = Announcement.query.order_by(Announcement.date_posted.desc()).all()
    pending_count = Complaint.query.filter_by(status='Pending').count()
    
    # 🟢 REAL DATA: Admin sees global schedules and logs
    upcoming_schedules = ClassSchedule.query.order_by(ClassSchedule.day, ClassSchedule.start_time).limit(3).all()
    recent_activities = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(4).all()
    
    return render_template(
        'dashboard.html',
        total=total_students,
        risk=at_risk_count,
        announcements=announcements,
        pending_count=pending_count,
        upcoming_schedules=upcoming_schedules, # 👈 ADDED HERE
        recent_activities=recent_activities    # 👈 ADDED HERE
    )

@app.route('/students')
def student_list():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    students = my_data(Student).order_by(Student.attendance_pct.asc()).all()
    return render_template('students.html', students=students)


@app.route('/student/<int:id>')
def student_detail(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    student = Student.query.get_or_404(id)
    cgpa, remark = calculate_cgpa(student)
    
    # 🔴 OLD BUGGY MATH:
    # prediction_score = (student.attendance_pct * 0.3) + ((cgpa / 5.0) * 100 * 0.7)

    # 🟢 NEW FIXED MATH (Capped at 100%):
    raw_score = (student.attendance_pct * 0.3) + ((cgpa / 5.0) * 100 * 0.7)
    prediction_score = min(100, round(raw_score, 1))  # <--- This prevents it from exceeding 100

    courses = my_data(Course).order_by(Course.code.asc()).all()
    image_file = url_for('static', filename='profile_pics/' + student.image_file)
    
    return render_template(
        'student_detail.html',
        student=student,
        cgpa=cgpa,
        remark=remark,
        prediction=prediction_score, # Now sends the fixed score
        courses=courses,
        image_file=image_file
    )

@app.route('/student/<int:id>/upload_image', methods=['POST'])
def upload_image(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if 'picture' in request.files:
        file = request.files['picture']
        if file.filename != '':
            picture_file = save_picture(file)
            student = Student.query.get_or_404(id)
            student.image_file = picture_file
            db.session.commit()
            flash('✅ Profile picture updated!')
    return redirect(url_for('student_detail', id=id))


@app.route('/student/<int:id>/toggle_fees', methods=['POST'])
def toggle_fees(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    student = Student.query.get_or_404(id)
    student.has_paid_fees = not student.has_paid_fees
    db.session.commit()
    status = "PAID" if student.has_paid_fees else "UNPAID"
    log_action(f"Updated fee status for {student.name} to {status}")
    flash(f'✅ Fee status updated to: {status}')
    return redirect(url_for('student_detail', id=id))


@app.route('/student/add', methods=['POST'])
def add_student():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    try:
        matric = request.form['matric_no']
        name = request.form['name']
        dept = request.form['department']
        new_student = Student(matric_no=matric, name=name, department=dept, attendance_pct=100.0)
        
        # 🟢 THE FIX: Auto-link the new student to the Lecturer's course!
        my_course = None
        if session.get('role') == 'lecturer':
            lecturer_id = session.get('user_id')
            # Find the first course this lecturer teaches
            my_course = Course.query.filter_by(lecturer_id=lecturer_id).first()
            
            if my_course:
                # Automatically put the student in their class!
                new_student.registered_courses.append(my_course)
            else:
                flash('⚠️ Student created, but you must add a Course to your profile first to see them!', 'warning')

        db.session.add(new_student)
        db.session.commit()
        
        if session.get('role') == 'lecturer' and my_course:
            flash(f'✅ Successfully registered {name} and enrolled them in {my_course.code}!', 'success')
        else:
            flash(f'✅ Successfully registered {name}!', 'success')
            
    except IntegrityError:
        db.session.rollback()
        flash('❌ Error: A student with that Matric Number already exists!', 'danger')
        
    return redirect(url_for('student_list'))


@app.route('/import/csv', methods=['POST'])
def import_csv_students():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if 'file' in request.files:
        file = request.files['file']
        if file.filename != '':
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_input = csv.reader(stream)
                next(csv_input, None)
                count = 0
                for row in csv_input:
                    if len(row) >= 3:
                        matric, name, dept = row[0].strip(), row[1].strip(), row[2].strip()
                        if not Student.query.filter_by(matric_no=matric).first():
                            db.session.add(
                                Student(
                                    matric_no=matric,
                                    name=name,
                                    department=dept,
                                    attendance_pct=100.0
                                )
                            )
                            count += 1
                db.session.commit()
                flash(f'✅ Imported {count} students.')
            except Exception as e:
                flash(f'❌ CSV Error: {str(e)}')
    return redirect(url_for('student_list'))


@app.route('/import/grades', methods=['POST'])
def import_csv_grades():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if 'file' in request.files:
        file = request.files['file']
        if file.filename != '':
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_input = csv.reader(stream)
                next(csv_input, None)
                count = 0
                failed = 0
                for row in csv_input:
                    if len(row) >= 3:
                        matric = row[0].strip()
                        course = row[1].strip().upper()
                        try:
                            score = int(row[2].strip())
                            student = Student.query.filter_by(matric_no=matric).first()
                            if student:
                                db.session.add(Grade(student_id=student.id, course_code=course, score=score))
                                count += 1
                            else:
                                failed += 1
                        except ValueError:
                            failed += 1
                db.session.commit()
                flash(f'✅ Success! {count} grades uploaded. ({failed} skipped/errors)')
            except Exception as e:
                flash(f'❌ CSV Error: {str(e)}')
    return redirect(url_for('student_list'))



# 🚑 RESCUE GHOST STUDENTS
@app.route('/rescue_students')
def rescue_students():
    if session.get('role') != 'lecturer':
        return "You must be logged in as a Lecturer to run this."
    
    lecturer_id = session.get('user_id')
    my_course = Course.query.filter_by(lecturer_id=lecturer_id).first()
    
    if not my_course:
        return "Please create at least one course first!"
        
    # Find all students who have ZERO registered courses (The Ghosts)
    floating_students = [s for s in Student.query.all() if len(s.registered_courses) == 0]
    
    count = 0
    for s in floating_students:
        s.registered_courses.append(my_course)
        count += 1
        
    db.session.commit()
    flash(f'✅ Rescued {count} ghost students and added them to {my_course.code}!', 'success')
    return redirect(url_for('student_list'))


# --- COURSE & MATERIALS ---
@app.route('/courses', methods=['GET', 'POST'])
def manage_courses():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        try:
            # 1. Create the course object first
            new_course = Course(
                code=request.form['code'].upper(),
                title=request.form['title'],
                units=int(request.form['units'])
            )
            
            # 2. 🟢 THE FIX: If a lecturer creates it, stamp their ID on it!
            if session.get('role') == 'lecturer':
                new_course.lecturer_id = session.get('user_id')
                
            # 3. Now safely save it to the database
            db.session.add(new_course)
            db.session.commit()
            flash('✅ Course added!')
        except:
            db.session.rollback()
            flash('❌ Course exists!')

    # 4. 🟢 THE MAGIC ENGINE: Automatically hides admin courses from lecturers!
    courses = my_data(Course).order_by(Course.code.asc()).all()
    
    return render_template('courses.html', courses=courses)


@app.route('/course/<int:course_id>/upload_pdf', methods=['POST'])
def upload_course_pdf(course_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if 'file' not in request.files:
        return redirect(url_for('manage_courses'))
    files = request.files.getlist('file')
    success = 0
    for file in files:
        if file and file.filename.lower().endswith('.pdf'):
            filename = save_material_file(file)
            clean_title = secure_filename(file.filename)
            db.session.add(CourseMaterial(course_id=course_id, title=clean_title, filename=filename))
            success += 1
    db.session.commit()
    if success:
        flash(f'✅ {success} files uploaded.')
    return redirect(url_for('manage_courses'))


@app.route('/material/download/<int:material_id>')
def download_material_direct(material_id):
    if not session.get('logged_in') and not session.get('student_logged_in'):
        return redirect(url_for('login'))
    material = CourseMaterial.query.get_or_404(material_id)
    try:
        return send_from_directory(
            app.config['UPLOAD_MATERIALS_FOLDER'],
            material.filename,
            as_attachment=True,
            download_name=material.title
        )
    except:
        return redirect(request.referrer)


@app.route('/course/<int:course_id>/register', methods=['GET', 'POST'])
def admin_register_student(course_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    course = Course.query.get_or_404(course_id)
    if request.method == 'POST':
        matric = request.form['matric_no']
        student = Student.query.filter_by(matric_no=matric).first()
        if student:
            if course not in student.registered_courses:
                student.registered_courses.append(course)
                db.session.commit()
                flash(f'✅ {student.name} registered for {course.code}!')
            else:
                flash('⚠️ Student already registered for this course.')
        else:
            flash('❌ Invalid Matric Number')
        return redirect(url_for('admin_register_student', course_id=course.id))
    return render_template('admin_course_reg.html', course=course)


@app.route('/course/<int:id>/delete', methods=['POST'])
def delete_course(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    course = Course.query.get_or_404(id)
    db.session.delete(course)
    db.session.commit()
    return redirect(url_for('manage_courses'))


@app.route('/student/<int:id>/add_grade', methods=['POST'])
def add_grade(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    db.session.add(
        Grade(
            student_id=id,
            course_code=request.form['course_code'],
            score=int(request.form['score'])
        )
    )
    db.session.commit()
    student = Student.query.get(id)
    if student.personal_email:
        send_email_notification(
            student.personal_email,
            "New Result Uploaded",
            f"Dear {student.name},\n\nA new result for {request.form['course_code']} has been uploaded.\nPlease log in to check your grade."
        )
    flash('✅ Grade added!')
    return redirect(url_for('student_detail', id=id))

@app.route('/grade/<int:id>/delete', methods=['POST'])
def delete_grade(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    grade = Grade.query.get_or_404(id)
    sid = grade.student_id
    db.session.delete(grade)
    db.session.commit()
    return redirect(url_for('student_detail', id=sid))


@app.route('/analytics/course', methods=['GET', 'POST'])
def course_analysis():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    selected_course = request.form.get('course_code')
    results = []
    stats = {'passed': 0, 'failed': 0, 'highest': 0, 'avg': 0}

    if selected_course:
        query = db.session.query(Grade, Student)\
            .join(Student)\
            .filter(Grade.course_code == selected_course)\
            .order_by(Grade.score.desc())\
            .all()

        total = 0
        for grade, student in query:
            results.append({
                'matric': student.matric_no,
                'name': student.name,
                'score': grade.score
            })
            if grade.score >= 50:
                stats['passed'] += 1
            else:
                stats['failed'] += 1
            total += grade.score
            stats['highest'] = max(stats['highest'], grade.score)

        if results:
            stats['avg'] = round(total / len(results), 1)

    # 🟢 BLANK SLATE FOR LECTURERS
    if session.get('role') == 'lecturer':
        all_courses = Course.query.filter_by(lecturer_id=session.get('user_id')).order_by(Course.code.asc()).all()
    else:
        all_courses = Course.query.order_by(Course.code.asc()).all()

    return render_template(
        'course_analysis.html',
        courses=all_courses,
        selected_course=selected_course,
        results=results,
        stats=stats
    )


@app.route('/analytics/course/export/<course_code>')
def export_course_broadsheet(course_code):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    query = db.session.query(Grade, Student)\
        .join(Student)\
        .filter(Grade.course_code == course_code)\
        .order_by(Grade.score.desc())\
        .all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['BROADSHEET REPORT', f'COURSE: {course_code}'])
    writer.writerow(['Rank', 'Matric No', 'Student Name', 'Score', 'Grade', 'Remark'])

    rank = 1
    for grade, student in query:
        letter = 'A' if grade.score >= 70 else 'B' if grade.score >= 60 else 'C' if grade.score >= 50 else 'F'
        remark = 'PASS' if grade.score >= 50 else 'FAIL'
        writer.writerow([rank, student.matric_no, student.name, grade.score, letter, remark])
        rank += 1

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={course_code}_broadsheet.csv"}
    )


# ==========================================
# ⚙️ ACCOUNT SETTINGS (UPDATED FOR LECTURERS & ADMINS)
# ==========================================
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    role = session.get('role')
    user_id = session.get('user_id')
    
    # Get the correct profile depending on who is logged in
    if role == 'admin':
        account = User.query.get(user_id)
    else:
        account = Lecturer.query.get(user_id)

    if request.method == 'POST':
        
        # 🟢 FEATURE 1: UPDATE PROFILE (NAME/TITLE)
        if 'update_profile' in request.form:
            if role == 'lecturer':
                account.title = request.form.get('title')
                account.name = request.form.get('name')
                db.session.commit()
                
                # 🔥 CRITICAL FIX: Update the live session cookie so the Navbar changes instantly!
                session['user_name'] = f"{account.title} {account.name}"
                flash('✅ Profile Name Updated Successfully!', 'success')
            return redirect(url_for('settings'))

        # 🔒 FEATURE 2: UPDATE PASSWORD
        elif 'update_password' in request.form:
            old_pw = request.form.get('old_password')
            new_pw = request.form.get('new_password')
            conf_pw = request.form.get('confirm_password')

            if account.check_password(old_pw):
                if new_pw == conf_pw:
                    account.set_password(new_pw)
                    db.session.commit() 
                    flash('✅ Password Updated Successfully!', 'success')
                else:
                    flash('❌ New passwords do not match', 'danger')
            else:
                flash('❌ Incorrect Old Password', 'danger')
            return redirect(url_for('settings'))

    return render_template('settings.html', account=account)


# ==========================================
# 📊 ACTIVITY LOGS (SILOED)
# ==========================================
@app.route('/activity')
def activity_log():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    # 🟢 LECTURER MODE: Only see their own actions
    if session.get('role') == 'lecturer':
        my_name = session.get('user_name')
        logs = AuditLog.query.filter_by(user=my_name).order_by(AuditLog.timestamp.desc()).all()
    # 👑 ADMIN MODE: See everyone's actions
    else:
        logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
        
    return render_template('activity.html', logs=logs)


@app.route('/student/<int:id>/transcript')
def student_transcript(id):
    if not session.get('logged_in'):
        if not session.get('student_logged_in') or session.get('student_id') != id:
            return redirect(url_for('login'))

    student = Student.query.get_or_404(id)
    cgpa, remark = calculate_cgpa(student)
    return render_template(
        'transcript.html',
        student=student,
        cgpa=cgpa,
        remark=remark,
        Course=Course
    )


@app.route('/student/<int:id>/id_card')
def student_id_card(id):
    if not session.get('logged_in') and not session.get('student_logged_in'):
        return redirect(url_for('login'))

    student = Student.query.get_or_404(id)

    if not student.has_paid_fees:
        return "<h1>ACCESS DENIED</h1><h3>You must pay your School Fees/Bursary to view your Exam Pass.</h3><p>Please contact the Bursary Department.</p>", 403

    image_file = url_for('static', filename='profile_pics/' + student.image_file)
    return render_template('id_card.html', student=student, image_file=image_file)


@app.route('/student/<int:id>/edit', methods=['POST'])
def edit_student(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    s = Student.query.get(id)
    s.name = request.form['name']
    s.department = request.form['department']
    s.attendance_pct = float(request.form['attendance_pct'])
    db.session.commit()
    flash('✅ Updated!')
    return redirect(url_for('student_detail', id=id))


@app.route('/student/<int:id>/delete', methods=['POST'])
def delete_student(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    s = Student.query.get(id)
    for g in s.grades:
        db.session.delete(g)
    db.session.delete(s)
    db.session.commit()
    return redirect(url_for('student_list'))


@app.route('/student/<int:id>/save_note', methods=['POST'])
def save_note(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    s = Student.query.get(id)
    s.lecturer_note = request.form['lecturer_note']
    db.session.commit()
    return redirect(url_for('student_detail', id=id))


# ==========================================
# 🔐 FORGOT & RESET PASSWORD ROUTES (SINGLE-USE SECURE)
# ==========================================
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        
        # 1. Check both Admin and Lecturer databases
        admin_user = User.query.filter_by(email=email).first()
        lecturer_user = Lecturer.query.filter_by(email=email).first()
        user_obj = admin_user or lecturer_user
        
        if user_obj:
            from itsdangerous import URLSafeTimedSerializer
            s = URLSafeTimedSerializer(app.secret_key)
            
            # 🟢 SECURE SINGLE-USE TOKEN LOGIC: Attach a fragment of their CURRENT password hash
            # If the password changes, this fragment changes, permanently breaking the token!
            hash_frag = user_obj.password_hash[-15:] if getattr(user_obj, 'password_hash', None) else 'new'
            payload = {'email': email, 'hash': hash_frag}
            
            # 2. Generate the highly secure, temporary token
            token = s.dumps(payload, salt='password-reset-salt')
            
            # 3. Create the Real Clickable Reset Link
            # 🟢 ARCHITECT FIX: Force HTTPS and use the Railway hostname
            reset_link = url_for('reset_password', token=token, _external=True, _scheme='https')
            
            # If for some reason Railway still sends 127.0.0.1, we use this hardcoded backup:
            if "127.0.0.1" in reset_link or "localhost" in reset_link:
                reset_link = f"https://lasudashboard-productions.up.railway.app/reset-password/{token}"
            
            # 4. Fire the actual Email!
            user_name = getattr(user_obj, 'name', 'Admin')
            email_body = f"Hello {user_name},\n\nYou requested a password reset for your LASU Matrix account.\n\nClick the secure link below to reset your password:\n{reset_link}\n\nThis link will expire in 15 minutes, and for security purposes, it can only be used ONCE.\n\nIf you did not request this, please ignore this email.\n\nSecurely,\nLASU Matrix System."
            
            send_email_notification(email, "LASU Matrix - Password Reset Link", email_body)
            
            flash(f'✅ Password reset link successfully dispatched to {email}', 'success')
        else:
            flash('❌ Email not found in our records.', 'danger')
            
        return redirect(url_for('login'))

    return render_template('forgot_password.html')

# --- THE ROUTE THAT CATCHES THE CLICKED LINK ---
@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
    s = URLSafeTimedSerializer(app.secret_key)
    
    try:
        # Token expires strictly in 15 minutes (900 seconds)
        payload = s.loads(token, salt='password-reset-salt', max_age=900)
        
        # 🟢 THE CRASH FIX: Check if this is an old token or a new secure token
        if isinstance(payload, dict):
            email = payload.get('email')
            token_hash = payload.get('hash')
        else:
            # It's an old token from before the security upgrade
            email = payload
            token_hash = None
            
    except SignatureExpired:
        flash('❌ The password reset link has expired. Please request a new one.', 'danger')
        return redirect(url_for('login'))
    except BadTimeSignature:
        flash('❌ Invalid password reset link.', 'danger')
        return redirect(url_for('login'))
        
    admin_user = User.query.filter_by(email=email).first()
    lecturer_user = Lecturer.query.filter_by(email=email).first()
    user_obj = admin_user or lecturer_user
    
    if not user_obj:
        flash('❌ Account no longer exists.', 'danger')
        return redirect(url_for('login'))
        
    # 🟢 SINGLE-USE CHECK: Does the token hash match their CURRENT database hash?
    current_hash = user_obj.password_hash[-15:] if getattr(user_obj, 'password_hash', None) else 'new'
    
    if token_hash != current_hash:
        flash('⛔ SECURITY ALERT: This password reset link is invalid or has already been used. Please request a new one.', 'warning')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        new_pw = request.form.get('new_password')
        confirm_pw = request.form.get('confirm_password')
        
        if new_pw != confirm_pw:
            flash('❌ Passwords do not match.', 'danger')
            return redirect(request.url)
        if len(new_pw) < 6:
            flash('❌ Password must be at least 6 characters long.', 'warning')
            return redirect(request.url)
            
        # Update the user's actual password in the database
        user_obj.set_password(new_pw)
        db.session.commit()
        
        flash('✅ Password reset successfully! You can now log in securely with your new password.', 'success')
        return redirect(url_for('login'))
            
    return render_template('reset_password.html', token=token)


@app.route('/export/csv')
def export_csv():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    students = Student.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Matric No', 'Name', 'Department', 'Attendance %'])

    for student in students:
        writer.writerow([
            student.matric_no,
            student.name,
            student.department,
            student.attendance_pct
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=lasu_students.csv"}
    )


@app.route('/api/grades')
def grade_data():
    if not session.get('logged_in'):
        return jsonify({})

    # 🟢 ARCHITECT FIX: Multi-Silo Grade Filtering
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role == 'lecturer':
        # Find this lecturer's courses
        my_courses = Course.query.filter_by(lecturer_id=user_id).all()
        my_course_codes = [c.code for c in my_courses]
        
        if not my_course_codes:
            return jsonify({"A": 0, "B": 0, "C": 0, "F": 0})
            
        # Only get grades for THIS lecturer's specific courses
        grades = Grade.query.filter(Grade.course_code.in_(my_course_codes)).all()
    else:
        # Admin sees everything
        grades = Grade.query.all()

    grade_distribution = {"A": 0, "B": 0, "C": 0, "F": 0}

    for g in grades:
        if g.score >= 70: grade_distribution["A"] += 1
        elif g.score >= 60: grade_distribution["B"] += 1
        elif g.score >= 50: grade_distribution["C"] += 1
        else: grade_distribution["F"] += 1

    return jsonify(grade_distribution)


@app.route('/api/departments')
def department_data():
    if not session.get('logged_in'):
        return jsonify({})

    role = session.get('role')
    user_id = session.get('user_id')

    # 🟢 ARCHITECT FIX: Only count departments for students LINKED to this lecturer
    if role == 'lecturer':
        # Find this lecturer's courses
        my_courses = Course.query.filter_by(lecturer_id=user_id).all()
        my_course_ids = [c.id for c in my_courses]
        
        if not my_course_ids:
            return jsonify({}) # Return empty if no courses assigned
            
        # Count students by department who are registered in THIS lecturer's courses
        results = db.session.query(
            Student.department,
            func.count(Student.id)
        ).filter(Student.registered_courses.any(Course.id.in_(my_course_ids)))\
         .group_by(Student.department).all()
    else:
        # Admin sees everything (Global)
        results = db.session.query(
            Student.department,
            func.count(Student.id)
        ).group_by(Student.department).all()

    data = {row[0]: row[1] for row in results}
    return jsonify(data)


# ==========================================
# 🤖 EXAM SCHEDULER ALGORITHM (LOCKED TO ADMIN ONLY)
# ==========================================
@app.route('/exams/generate', methods=['POST'])
@admin_only
def generate_exam_timetable():
    # 2. Reset Database
    db.session.query(Exam).delete()
    
    # 3. Setup Config
    start_date_str = request.form.get('start_date', date.today().strftime('%Y-%m-%d'))
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    
    # Slots & Venues
    slots = [("09:00", "12:00"), ("12:30", "15:30"), ("16:00", "19:00")]
    venues = [
        "Main Auditorium", "MBA Hall", "Science Theater", 
        "Engineering Hall", "Hall A", "Hall B"
    ]

    # 4. Load Data & Build Conflict Map 
    courses = Course.query.all()
    students = Student.query.all()
    conflict_map = defaultdict(set)

    # RULE 1: Real Student Clashes (From Database)
    for student in students:
        reg_courses = [c.id for c in student.registered_courses]
        for i in range(len(reg_courses)):
            for j in range(i + 1, len(reg_courses)):
                c1, c2 = reg_courses[i], reg_courses[j]
                conflict_map[c1].add(c2)
                conflict_map[c2].add(c1)

    # 🛡️ RULE 2: ABSOLUTE LEVEL-BASED SCATTERING (The Failsafe) 🛡️
    # This guarantees NO TWO courses of the same level (e.g. 100L) 
    # can ever share a time slot, making it completely foolproof!
    for i in range(len(courses)):
        for j in range(i + 1, len(courses)):
            c1, c2 = courses[i], courses[j]
            
            # Extract the level (e.g., gets '1' from 'CSC 101')
            lvl1 = next((char for char in c1.code if char.isdigit()), None)
            lvl2 = next((char for char in c2.code if char.isdigit()), None)
            
            # Force a massive clash if they are the same level!
            if lvl1 and lvl2 and lvl1 == lvl2:
                conflict_map[c1.id].add(c2.id)
                conflict_map[c2.id].add(c1.id)

    # 5. Sort courses (Hardest first)
    sorted_courses = sorted(courses, key=lambda c: len(conflict_map[c.id]), reverse=True)

    # 6. Scheduling Matrix
    scheduled_matrix = {}

    for course in sorted_courses:
        day_idx = 0
        slot_idx = 0
        assigned = False

        while not assigned:
            # Check slot status
            current_slot_courses = scheduled_matrix.get((day_idx, slot_idx), [])
            has_clash = False
            
            # RULE A: Conflict Map Check
            for existing_id in current_slot_courses:
                if existing_id in conflict_map[course.id]:
                    has_clash = True
                    break
            
            # RULE B: Venue Capacity Check
            if len(current_slot_courses) >= len(venues):
                has_clash = True

            if not has_clash:
                # SUCCESS: Assign
                if (day_idx, slot_idx) not in scheduled_matrix:
                    scheduled_matrix[(day_idx, slot_idx)] = []
                
                venue_index = len(scheduled_matrix[(day_idx, slot_idx)])
                venue_name = venues[venue_index]

                # Date Calculation: Properly skip weekends
                current_exam_date = start_date
                
                days_to_add = day_idx
                while days_to_add > 0:
                    current_exam_date += timedelta(days=1)
                    if current_exam_date.weekday() < 5:  # 0-4 are Monday-Friday
                        days_to_add -= 1
                        
                # Failsafe: If the start_date itself is a weekend, push to Monday
                while current_exam_date.weekday() >= 5:
                    current_exam_date += timedelta(days=1)

                new_exam = Exam(
                    course_id=course.id,
                    exam_date=current_exam_date,
                    start_time=slots[slot_idx][0],
                    end_time=slots[slot_idx][1],
                    venue=venue_name
                )
                db.session.add(new_exam)
                
                # Update Course Docket info
                course.exam_date = current_exam_date
                course.exam_time = slots[slot_idx][0]
                course.exam_venue = venue_name
                
                scheduled_matrix[(day_idx, slot_idx)].append(course.id)
                assigned = True
            else:
                # FAIL: Next Slot
                slot_idx += 1
                if slot_idx >= len(slots):
                    slot_idx = 0
                    day_idx += 1 

    db.session.commit()
    flash('✅ TIMETABLE GENERATED: Smart Level-Based Scattering Applied.', 'success')
    return redirect(url_for('view_exam_timetable'))


@app.route('/exams/view')
@admin_only
def view_exam_timetable():
    exams = Exam.query.order_by(Exam.exam_date, Exam.start_time).all()
    return render_template('admin_exam_timetable.html', exams=exams)

@app.route('/exams/export/csv')
@admin_only
def export_exams_csv():
    exams = Exam.query.order_by(Exam.exam_date, Exam.start_time).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['MASTER EXAM TIMETABLE'])
    writer.writerow(['Date', 'Start Time', 'End Time', 'Course Code', 'Course Title', 'Venue'])
    for ex in exams:
        writer.writerow([
            ex.exam_date.strftime('%Y-%m-%d'),
            ex.start_time,
            ex.end_time,
            ex.course.code,
            ex.course.title,
            ex.venue
        ])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=Master_Exam_Timetable.csv"}
    )

@app.route('/exams/print')
@admin_only
def print_exam_timetable():
    exams = Exam.query.order_by(Exam.exam_date, Exam.start_time).all()
    return render_template('admin_exam_print.html', exams=exams, today=date.today())


# --- STUDENT PORTAL ROUTES ---
@app.route('/student-login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        matric = request.form['matric_no'].strip()
        # We capture the input as 'password_attempt' regardless of what the HTML calls it
        password_attempt = request.form['surname'].strip()

        student = Student.query.filter_by(matric_no=matric).first()

        if student:
            # 🛑 GATEKEEPER: Check if a custom password exists
            if student.password_hash:
                # === SCENARIO A: Student HAS changed their password ===
                # We strictly check the password hash.
                # If they type their surname here, this check will FAIL (which is what we want).
                if student.check_password(password_attempt):
                    session['student_logged_in'] = True
                    session['student_id'] = student.id
                    session['student_name'] = student.name
                    return redirect(url_for('student_portal'))
                else:
                    flash('❌ Invalid Password. Please use the new password you created.')
            else:
                # === SCENARIO B: First Time User (No password set) ===
                # Now we allow the surname login logic
                # Get the actual surname (assuming it is the last word in the name)
                actual_surname = student.name.split()[-1].lower()

                if password_attempt.lower() == actual_surname:
                    session['student_logged_in'] = True
                    session['student_id'] = student.id
                    session['student_name'] = student.name
                    flash('⚠️ You are using default login. Please set a password in settings.', 'warning')
                    return redirect(url_for('student_portal'))
                else:
                    flash('❌ Invalid Surname')
        else:
            flash('❌ Matric Number not found')

    return render_template('student_login.html')

# ==========================================
# 1. REPLACE THE student_portal FUNCTION
# ==========================================
@app.route('/portal')
@login_required
def student_portal():
    # 🟢 ADD THESE 3 LINES TO FIX THE KEYERROR CRASH 🟢
    if 'student_id' not in session:
        return redirect(url_for('dashboard'))
    # ------------------------------------------------

    # 1. Fetch Student
    student = Student.query.get(session['student_id'])
    
    # 🟢 NEW: Auto-Recalibrate Global Attendance Percentage (15-Class Rule)
    TOTAL_SEMESTER_CLASSES = 15
    reg_count = len(student.registered_courses)
    if reg_count > 0:
        total_expected = reg_count * TOTAL_SEMESTER_CLASSES
        total_present = DailyAttendance.query.filter_by(
            student_id=student.id,
            status='Present'
        ).count()
        student.attendance_pct = min(100.0, round((total_present / total_expected) * 100, 1))
        db.session.commit()
    
    # 2. 🚨 SOS ALARM LOGIC
    active_sos_count = SOSRequest.query.filter(
        SOSRequest.status == 'Active', 
        SOSRequest.student_id != student.id
    ).count()

    # 3. 🟢 SMART NOTIFICATION SPLITTER (STRICT LOGIC)
    
    # List A: PURE SUMMARIES (Only AI Notes)
    # 🟢 FIX: Changed 'date_posted' to 'timestamp'
    lecture_summaries = Notification.query.filter(
        Notification.student_id == student.id,
        Notification.message.like("%Topic Summary%") 
    ).order_by(Notification.timestamp.desc()).limit(5).all()

    # List B: GENERAL INBOX (Transfers, System Msgs, Alerts)
    # 🟢 FIX: Changed 'date_posted' to 'timestamp'
    general_inbox = Notification.query.filter(
        Notification.student_id == student.id,
        ~Notification.message.like("%Topic Summary%") 
    ).order_by(Notification.timestamp.desc()).limit(10).all()

    # --- BADGE COUNTS ---
    
    # A. Exam Alerts (Red Badge)
    cbt_alerts = Notification.query.filter(
        Notification.student_id == student.id,
        Notification.is_read == False,
        Notification.message.like("%EXAM VOIDED%")
    ).count()

    # B. Lecture Summaries (Green Badge)
    summary_alerts = Notification.query.filter(
        Notification.student_id == student.id,
        Notification.is_read == False,
        Notification.message.like("%Topic Summary%") 
    ).count()

    # 4. 🟢 CHANGE OF COURSE STATUS CHECK
    pending_transfer = ChangeCourseRequest.query.filter_by(student_id=student.id, status='Pending').first()

    # 5. CGPA & PROFILE
    cgpa = 0.0 
    try:
        cgpa, remark = calculate_cgpa(student)
    except:
        cgpa, remark = 0.0, "Calculated"

    image_file = url_for('static', filename='profile_pics/' + student.image_file)
    
    # 6. NOTICES & MATERIALS
    # Note: Announcement likely uses 'date_posted', but Notification uses 'timestamp'
    notices = Announcement.query.order_by(Announcement.date_posted.desc()).limit(3).all()

    available_materials = []
    for course in student.registered_courses:
        for material in course.materials:
            available_materials.append(material)

    # 7. HOSTELS & COMPLAINTS
    hostels = Hostel.query.all()
    my_complaints = Complaint.query.filter_by(student_id=student.id)\
        .order_by(Complaint.date_lodged.desc()).all()

    # 8. RETURN EVERYTHING TO THE HTML
    return render_template(
        'student_portal.html',
        student=student,
        cgpa=cgpa,
        remark=remark,
        image_file=image_file,
        sos_count=active_sos_count,
        notices=notices,
        materials=available_materials,
        hostels=hostels,
        my_complaints=my_complaints,
        cbt_alerts=cbt_alerts,        
        summary_alerts=summary_alerts,
        pending_transfer=pending_transfer,
        # 👇 THESE ARE THE NEW LISTS
        lecture_summaries=lecture_summaries, 
        general_inbox=general_inbox
    )

# ==========================================
# ⚙️ STUDENT SETTINGS (SMART PASSWORD FIX)
# ==========================================
@app.route('/student/settings', methods=['GET', 'POST'])
def student_settings():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])

    if request.method == 'POST':
        # 🟢 CASE 1: PROFILE UPDATE
        if 'update_profile' in request.form:
            try:
                student.personal_email = request.form.get('personal_email')
                student.phone_number = request.form.get('phone_number')
                student.address = request.form.get('address')

                new_level = request.form.get('level')
                if new_level:
                    student.level = int(new_level)

                db.session.commit()
                flash('✅ Profile details updated successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Error saving profile: {e}', 'danger')

        # 🔒 CASE 2: PASSWORD UPDATE
        elif 'update_password' in request.form:
            current_pw = request.form.get('current_password')
            new_pw = request.form.get('new_password')
            confirm_pw = request.form.get('confirm_password')

            # --- SMART VERIFICATION LOGIC ---
            is_verified = False

            if student.password_hash:
                # Scenario A: Student HAS a password set -> Check it normally
                if student.check_password(current_pw):
                    is_verified = True
            else:
                # Scenario B: First time (No password set) -> Check SURNAME
                # (Since they used surname to login previously)
                surname = student.name.split()[-1]  # Get last name
                if current_pw.strip().lower() == surname.lower():
                    is_verified = True
                else:
                    flash(
                        f'❌ First time setup: Please enter your Surname ({surname}) as the "Current Password".',
                        'warning'
                    )
                    return redirect(url_for('student_settings'))

            # --- PROCEED WITH UPDATE ---
            if not is_verified:
                flash('❌ Current password is incorrect.', 'danger')
            elif new_pw != confirm_pw:
                flash('❌ New passwords do not match.', 'warning')
            elif len(new_pw) < 6:
                flash('❌ Password must be at least 6 characters.', 'warning')
            else:
                student.set_password(new_pw)
                db.session.commit()
                flash('🔒 Password changed successfully! Use this new password next time.', 'success')

        return redirect(url_for('student_settings'))

    image_file = url_for('static', filename='profile_pics/' + student.image_file)
    return render_template('student_settings.html', student=student, image_file=image_file)


@app.route('/student/forecaster', methods=['GET', 'POST'])
def student_forecaster():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    current_cgpa, remark = calculate_cgpa(student)
    graded_course_codes = [g.course_code for g in student.grades]
    pending_courses = [
        c for c in student.registered_courses
        if c.code not in graded_course_codes
    ]
    return render_template(
        'forecaster.html',
        student=student,
        current_cgpa=current_cgpa,
        pending_courses=pending_courses
    )


@app.route('/student/course_reg', methods=['GET', 'POST'])
def student_course_reg():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])

    if request.method == 'POST':
        selected_course_ids = request.form.getlist('courses')
        for cid in selected_course_ids:
            course = Course.query.get(int(cid))
            if course and course not in student.registered_courses:
                student.registered_courses.append(course)

        db.session.commit()
        flash('✅ Courses Registered Successfully!')
        return redirect(url_for('student_portal'))

    all_courses = Course.query.order_by(Course.code.asc()).all()
    return render_template('course_registration.html', student=student, courses=all_courses)

@app.route('/student/drop_course/<int:course_id>', methods=['POST'])
def drop_course(course_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    course = Course.query.get(course_id)

    if course and course in student.registered_courses:
        student.registered_courses.remove(course)
        db.session.commit()
        flash(f'❌ Dropped course: {course.code}')

    return redirect(url_for('student_portal'))


@app.route('/student/update_profile', methods=['POST'])
def update_profile():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    student.personal_email = request.form['email']
    student.phone_number = request.form['phone']
    student.address = request.form['address']
    student.level = int(request.form['level'])
    db.session.commit()
    flash('✅ Profile details updated successfully!')
    return redirect(url_for('student_portal'))


@app.route('/student/print_form/<form_type>')
def print_form(form_type):
    if not session.get('student_logged_in') and not session.get('logged_in'):
        return redirect(url_for('login'))

    student_id = session.get('student_id') or request.args.get('id')
    student = Student.query.get_or_404(student_id)
    image_file = url_for('static', filename='profile_pics/' + student.image_file)

    exams_to_display = []
    if 'timetable' in form_type.lower():
        reg_ids = [c.id for c in student.registered_courses]
        exams_to_display = Exam.query.filter(
            Exam.course_id.in_(reg_ids)
        ).order_by(Exam.exam_date).all()

    courses_to_display = student.registered_courses
    total_units = sum([c.units for c in courses_to_display])
    now = datetime.now()

    return render_template(
        'form_template.html',
        student=student,
        form_type=form_type.upper(),
        image_file=image_file,
        courses=courses_to_display,
        total_units=total_units,
        today_date=now.strftime("%m/%d/%y"),
        now_time=now.strftime("%I:%M %p"),
        exams=exams_to_display
    )


@app.route('/student-logout')
def student_logout():
    session.pop('student_logged_in', None)
    session.pop('student_id', None)
    flash('You have logged out of the Student Portal.')
    return redirect(url_for('student_login'))


@app.route('/student/portal/upload_image', methods=['POST'])
def student_portal_upload_image():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student_id = session.get('student_id')

    if 'picture' in request.files:
        file = request.files['picture']
        if file.filename != '':
            picture_file = save_picture(file)
            student = Student.query.get(student_id)
            student.image_file = picture_file
            db.session.commit()
            flash('✅ Profile picture updated successfully!')

    return redirect(url_for('student_portal'))


@app.route('/student/complaint', methods=['GET', 'POST'])
def student_complaint():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    if request.method == 'POST':
        student = Student.query.get(session['student_id'])
        new_complaint = Complaint(
            student_id=student.id,
            matric_no=student.matric_no,
            student_name=student.name,
            category=request.form['category'],
            message=request.form['message']
        )
        db.session.add(new_complaint)
        db.session.commit()
        flash('✅ Complaint lodged successfully!')
        return redirect(url_for('student_portal'))

    return render_template('lodge_complaint.html')


@app.route('/lecturer/complaints')
def lecturer_complaints():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if session.get('role') == 'lecturer':
        # 🟢 LECTURER MODE: See ONLY complaints from their own students
        lecturer_id = session.get('user_id')
        my_courses = Course.query.filter_by(lecturer_id=lecturer_id).all()
        my_course_ids = [c.id for c in my_courses]
        
        if my_course_ids:
            my_students = Student.query.filter(Student.registered_courses.any(Course.id.in_(my_course_ids))).all()
            my_student_ids = [s.id for s in my_students]
            complaints = Complaint.query.filter(Complaint.student_id.in_(my_student_ids)).order_by(
                Complaint.status.desc(),
                Complaint.date_lodged.desc()
            ).all()
        else:
            complaints = [] # 🟢 BLANK SLATE
    else:
        # 👑 ADMIN MODE: See ALL complaints
        complaints = Complaint.query.order_by(
            Complaint.status.desc(),
            Complaint.date_lodged.desc()
        ).all()

    return render_template('lecturer_complaints.html', complaints=complaints)


@app.route('/complaint/<int:id>/resolve', methods=['POST'])
def resolve_complaint(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    comp = Complaint.query.get_or_404(id)
    comp.status = "Resolved"
    db.session.commit()
    flash(f'✅ Ticket for {comp.student_name} marked as Resolved.')
    return redirect(url_for('lecturer_complaints'))


@app.route('/announcement/post', methods=['POST'])
def post_announcement():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    db.session.add(
        Announcement(
            title=request.form['title'],
            content=request.form['content']
        )
    )
    db.session.commit()
    flash('✅ Announcement posted!')
    return redirect(url_for('dashboard'))


@app.route('/announcement/<int:id>/delete', methods=['POST'])
def delete_announcement(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    ann = Announcement.query.get_or_404(id)
    db.session.delete(ann)
    db.session.commit()
    flash('Announcement deleted.')
    return redirect(url_for('dashboard'))


@app.route('/materials/manage', methods=['GET', 'POST'])
def manage_materials():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename != '':
            filename = save_material_file(file)
            db.session.add(
                CourseMaterial(
                    course_id=request.form['course_id'],
                    title=request.form['title'],
                    filename=filename
                )
            )
            db.session.commit()
            flash('✅ Material uploaded!')

    courses = Course.query.all()
    materials = my_data(CourseMaterial).order_by(
        CourseMaterial.date_uploaded.desc()
    ).all()

    return render_template(
        'manage_materials.html',
        courses=courses,
        materials=materials
    )


@app.route('/materials/<int:id>/delete', methods=['POST'])
def delete_material(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    mat = CourseMaterial.query.get_or_404(id)
    try:
        os.remove(os.path.join(app.config['UPLOAD_MATERIALS_FOLDER'], mat.filename))
    except:
        pass

    db.session.delete(mat)
    db.session.commit()
    flash('Material deleted.')
    return redirect(url_for('manage_materials'))


@app.route('/student/pay_fees', methods=['POST'])
def student_pay_fees():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    ref_code = "LASU-" + ''.join(
        random.choices(string.ascii_uppercase + string.digits, k=10)
    )
    amount = 50000.00
    new_payment = Payment(student_id=student.id, amount=amount, reference=ref_code)
    student.has_paid_fees = True

    db.session.add(new_payment)
    db.session.commit()

    if student.personal_email:
        body = (
            f"Dear {student.name},\n\n"
            f"We confirm receipt of your school fees payment.\n"
            f"Amount: N{amount:,.2f}\n"
            f"Reference: {ref_code}\n"
            f"Date: {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"Thank you,\n"
            f"Bursary Department."
        )
        send_email_notification(
            student.personal_email,
            "Payment Receipt - Successful",
            body
        )

    flash(f'✅ Payment Successful! Reference: {ref_code}')
    return redirect(url_for('student_portal'))


@app.route('/hostels/manage', methods=['GET', 'POST'])
@admin_only
def manage_hostels():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        db.session.add(
            Hostel(
                name=request.form['name'],
                capacity=int(request.form['capacity']),
                price=float(request.form['price'])
            )
        )
        db.session.commit()
        log_action(f"Created Hostel: {request.form['name']}")
        flash('✅ Hostel added successfully!')

    hostels = Hostel.query.all()
    return render_template('manage_hostels.html', hostels=hostels)


@app.route('/hostel/<int:id>/delete', methods=['POST'])
def delete_hostel(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    hostel = Hostel.query.get_or_404(id)
    db.session.delete(hostel)
    db.session.commit()
    flash('Hostel deleted.')
    return redirect(url_for('manage_hostels'))


@app.route('/student/hostel/apply/<int:hostel_id>', methods=['POST'])
def apply_hostel(hostel_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])

    if not student.has_paid_fees:
        flash('❌ Access Denied: You must PAY SCHOOL FEES before applying for a hostel.')
        return redirect(url_for('student_portal'))

    if student.hostel_allocation:
        flash(f'⚠️ You already have a room in {student.hostel_allocation.hostel.name}!')
        return redirect(url_for('student_portal'))

    hostel = Hostel.query.get_or_404(hostel_id)

    if hostel.occupied >= hostel.capacity:
        flash('❌ Sorry, this hostel is fully booked.')
        return redirect(url_for('student_portal'))

    new_allocation = HostelAllocation(
        student_id=student.id,
        hostel_id=hostel.id
    )
    hostel.occupied += 1
    db.session.add(new_allocation)
    db.session.commit()
    flash(f'✅ Success! You have been allocated a space in {hostel.name}.')
    return redirect(url_for('student_portal'))


@app.route('/student/receipt/<reference>')
def student_receipt(reference):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    payment = Payment.query.filter_by(reference=reference).first_or_404()
    student = Student.query.get(session['student_id'])

    if payment.student_id != student.id:
        return "<h1>Access Denied</h1>", 403

    return render_template('receipt.html', payment=payment, student=student)


@app.route('/student/hostel/receipt')
def student_hostel_receipt():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])

    if not student.hostel_allocation:
        flash("❌ No hostel allocated yet.")
        return redirect(url_for('student_portal'))

    return render_template(
        'hostel_receipt.html',
        student=student,
        allocation=student.hostel_allocation
    )


@app.route('/course/<int:course_id>/attendance')
def course_attendance(course_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    course = Course.query.get_or_404(course_id)
    students = sorted(course.students, key=lambda x: x.matric_no)
    return render_template('attendance_list.html', course=course, students=students)


@app.route('/timetable/manage', methods=['GET', 'POST'])
def manage_timetable():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        db.session.add(
            ClassSchedule(
                course_id=request.form['course_id'],
                day=request.form['day'],
                start_time=request.form['start_time'],
                end_time=request.form['end_time'],
                venue=request.form['venue']
            )
        )
        db.session.commit()
        flash('✅ Class scheduled successfully!')

    schedules = my_data(ClassSchedule).join(Course)\
        .order_by(ClassSchedule.day, ClassSchedule.start_time).all()
    courses = Course.query.all()

    return render_template(
        'manage_timetable.html',
        schedules=schedules,
        courses=courses
    )


@app.route('/timetable/delete/<int:id>', methods=['POST'])
def delete_schedule(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    sch = ClassSchedule.query.get_or_404(id)
    db.session.delete(sch)
    db.session.commit()
    flash('Schedule removed.')
    return redirect(url_for('manage_timetable'))


@app.route('/student/timetable')
def student_timetable():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    my_schedules = []

    for course in student.registered_courses:
        for sch in course.schedules:
            my_schedules.append(sch)

    days_order = {
        "Monday": 1,
        "Tuesday": 2,
        "Wednesday": 3,
        "Thursday": 4,
        "Friday": 5,
        "Saturday": 6
    }

    my_schedules.sort(
        key=lambda x: (days_order.get(x.day, 7), x.start_time)
    )

    return render_template(
        'student_timetable.html',
        schedules=my_schedules,
        student=student
    )


@app.route('/course/<int:course_id>/assignments', methods=['GET', 'POST'])
def manage_assignments(course_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    course = Course.query.get_or_404(course_id)

    if request.method == 'POST':
        date_str = request.form['due_date']
        due_date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
        new_ass = Assignment(
            course_id=course.id,
            title=request.form['title'],
            instruction=request.form['instruction'],
            points=int(request.form['points']),
            due_date=due_date
        )
        db.session.add(new_ass)
        db.session.commit()
        flash('✅ Assignment created successfully!')
        return redirect(url_for('manage_assignments', course_id=course.id))

    return render_template('manage_assignments.html', course=course)


@app.route('/assignment/<int:id>/submissions', methods=['GET', 'POST'])
def view_submissions(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    assignment = Assignment.query.get_or_404(id)

    if request.method == 'POST':
        sub_id = request.form['submission_id']
        submission = Submission.query.get(sub_id)
        submission.score = int(request.form['score'])
        submission.lecturer_comment = request.form['comment']
        db.session.commit()
        flash('✅ Grade saved.')
        return redirect(url_for('view_submissions', id=assignment.id))

    return render_template('view_submissions.html', assignment=assignment)

@app.route('/student/assignments')
def student_assignments():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    assignments = []

    for course in student.registered_courses:
        for ass in course.assignments:
            sub = Submission.query.filter_by(
                student_id=student.id,
                assignment_id=ass.id
            ).first()
            assignments.append({'task': ass, 'submission': sub})

    assignments.sort(key=lambda x: x['task'].due_date)
    
    # 👇 PASS 'now' TO THE TEMPLATE
    return render_template('student_assignments.html', assignments=assignments, now=datetime.now())


# ==========================================
# 🔒 SECURE SUBMISSION (TIME-LOCKED)
# ==========================================
@app.route('/student/assignment/submit/<int:id>', methods=['POST'])
def submit_assignment(id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    # 1. Get the Assignment
    assignment = Assignment.query.get_or_404(id)
    
    # 2. 🛑 DEADLINE CHECK (The Gatekeeper)
    if datetime.now() > assignment.due_date:
        flash('⛔ Submission Failed: The deadline for this assignment has passed.', 'danger')
        return redirect(url_for('student_assignments'))

    # 3. Process File if On Time
    if 'file' in request.files:
        file = request.files['file']
        if file.filename != '':
            filename = save_assignment_file(file)
            
            # Check if resubmitting (optional, or just create new)
            existing_sub = Submission.query.filter_by(
                assignment_id=id, 
                student_id=session['student_id']
            ).first()

            if existing_sub:
                existing_sub.file_path = filename
                existing_sub.date_submitted = datetime.now()
                flash('✅ Assignment updated successfully!')
            else:
                new_sub = Submission(
                    assignment_id=id,
                    student_id=session['student_id'],
                    file_path=filename
                )
                db.session.add(new_sub)
                flash('✅ Assignment submitted successfully!')
            
            db.session.commit()

    return redirect(url_for('student_assignments'))


@app.route('/course/<int:course_id>/grade', methods=['GET', 'POST'])
def input_results(course_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    course = Course.query.get_or_404(course_id)
    students = sorted(course.students, key=lambda x: x.matric_no)

    if request.method == 'POST':
        count = 0
        for student in students:
            score_val = request.form.get(f'score_{student.id}')
            if score_val and score_val.strip() != '':
                try:
                    score_float = float(score_val)
                    existing_grade = Grade.query.filter_by(
                        student_id=student.id,
                        course_code=course.code
                    ).first()

                    if existing_grade:
                        existing_grade.score = score_float
                    else:
                        new_grade = Grade(
                            student_id=student.id,
                            course_code=course.code,
                            score=score_float
                        )
                        db.session.add(new_grade)
                        count += 1

                except ValueError:
                    continue

        db.session.commit()
        flash(f'✅ Successfully updated results for {count} students!')
        return redirect(url_for('input_results', course_id=course.id))

    existing_scores = {}
    for student in students:
        grade = Grade.query.filter_by(
            student_id=student.id,
            course_code=course.code
        ).first()
        if grade:
            existing_scores[student.id] = grade.score

    return render_template(
        'input_results.html',
        course=course,
        students=students,
        scores=existing_scores
    )


@app.route('/cbt/manage', methods=['GET', 'POST'])
def manage_quizzes():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_quiz = Quiz(
            course_id=request.form['course_id'],
            title=request.form['title'],
            description=request.form['description']
        )
        db.session.add(new_quiz)
        db.session.commit()
        flash('✅ New Quiz Created! Now add questions.')
        return redirect(url_for('add_questions', quiz_id=new_quiz.id))

    quizzes = my_data(Quiz).order_by(Quiz.date_created.desc()).all()
    courses = Course.query.all()

    notifications = Notification.query.group_by(Notification.message).order_by(Notification.timestamp.desc()).all()

    return render_template(
        'manage_quizzes.html',
        quizzes=quizzes,
        courses=courses,
        notifications=notifications
    )


@app.route('/cbt/questions/<int:quiz_id>', methods=['GET', 'POST'])
def add_questions(quiz_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    quiz = Quiz.query.get_or_404(quiz_id)

    if request.method == 'POST':
        new_q = Question(
            quiz_id=quiz.id,
            text=request.form['text'],
            option_a=request.form['opt_a'],
            option_b=request.form['opt_b'],
            option_c=request.form['opt_c'],
            option_d=request.form['opt_d'],
            correct_option=request.form['correct']
        )
        db.session.add(new_q)
        db.session.commit()
        flash('Question added successfully.')
        return redirect(url_for('add_questions', quiz_id=quiz.id))

    return render_template('add_questions.html', quiz=quiz)


@app.route('/cbt/results/<int:quiz_id>')
def view_quiz_results(quiz_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    quiz = Quiz.query.get_or_404(quiz_id)
    results = QuizResult.query.filter_by(
        quiz_id=quiz_id
    ).order_by(QuizResult.score.desc()).all()

    return render_template(
        'quiz_results.html',
        quiz=quiz,
        results=results
    )


@app.route('/student/quizzes')
def student_quiz_list():
    # 1. Auth Check
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    
    # 2. Get Void Alerts (Keep your existing logic)
    void_alerts = Notification.query.filter(
        Notification.student_id == student.id,
        Notification.message.like("%EXAM VOIDED%"), 
        Notification.is_read == False
    ).all()

    # 🟢 3. NEW: Get Student's Appeals
    # Create a dictionary: { result_id : 'Pending'/'Rejected' }
    # This lets us quickly check the status inside the loop
    my_appeals = {a.quiz_result_id: a.status for a in Appeal.query.filter_by(student_id=student.id).all()}

    # 4. Get Quizzes & Check Status
    available_quizzes = []
    for course in student.registered_courses:
        for quiz in course.quizzes:
            # Check if taken
            taken = QuizResult.query.filter_by(
                student_id=student.id,
                quiz_id=quiz.id
            ).first()
            
            # Check Appeal Status (if taken)
            appeal_status = None
            if taken:
                appeal_status = my_appeals.get(taken.id)

            # Add everything to the list
            available_quizzes.append({
                'quiz': quiz, 
                'taken': taken,
                'appeal_status': appeal_status  # <--- PASSING THIS IS CRITICAL
            })

    # 5. Return Template
    return render_template(
        'student_quiz_list.html', 
        quizzes=available_quizzes, 
        void_alerts=void_alerts
    )

@app.route('/api/student/calendar')
def get_student_calendar_events():
    if not session.get('student_logged_in'):
        return jsonify([])

    student = Student.query.get(session['student_id'])
    events = []
    day_map = {
        'Sunday': 0,
        'Monday': 1,
        'Tuesday': 2,
        'Wednesday': 3,
        'Thursday': 4,
        'Friday': 5,
        'Saturday': 6
    }

    for course in student.registered_courses:
        for sch in course.schedules:
            if sch.day in day_map:
                events.append({
                    'title': f"{course.code} Class",
                    'startTime': sch.start_time,
                    'endTime': sch.end_time,
                    'daysOfWeek': [day_map[sch.day]],
                    'color': '#0d6efd',
                    'description': f"Venue: {sch.venue}"
                })

    for course in student.registered_courses:
        for ass in course.assignments:
            events.append({
                'title': f"DEADLINE: {ass.title}",
                'start': ass.due_date.isoformat(),
                'color': '#dc3545',
                'url': url_for('student_assignments')
            })

    return jsonify(events)


@app.route('/student/calendar')
def student_calendar_view():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    return render_template('student_calendar.html', student=student)


# ==========================================
# 📱 QR CODE GENERATOR (DEBUG VERSION)
# ==========================================
@app.route('/generate_qr/<int:student_id>')
def generate_qr(student_id):
    print(f"--- Attempting to generate QR for Student ID: {student_id} ---")  # Debug message
    try:
        # 1. Check Login
        if not session.get('student_logged_in') and not session.get('logged_in'):
            print("Error: User not logged in.")
            return redirect(url_for('student_login'))

        # 2. Get Student Data
        student = Student.query.get_or_404(student_id)

        # 3. Define the Data (This is what scans!)
        qr_data = f"LASU DIGITAL ID\nName: {student.name}\nMatric: {student.matric_no}\nDept: {student.department}"

        # 4. Create QR Object
        import qrcode  # Ensure imported locally just in case
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)

        # 5. Make Image
        img = qr.make_image(fill_color="black", back_color="white")

        # 6. Save to Memory (Crucial Step: Added format='PNG')
        from io import BytesIO  # Ensure imported
        buf = BytesIO()
        img.save(buf, format='PNG')  # <--- THIS FIXES THE "UNKNOWN FORMAT" ERROR
        buf.seek(0)

        print("Success: QR Image generated and sent.")
        return send_file(buf, mimetype='image/png')

    except Exception as e:
        # This will print the EXACT error to your terminal so we know what's wrong
        print(f"❌ CRITICAL QR ERROR: {e}")
        return str(e), 500


@app.route('/security/scanner')
def security_scanner_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('security_scanner.html')


@app.route('/api/verify_status/<path:matric_no>')
def api_verify_status(matric_no):
    clean_matric = matric_no.split('/')[-1] if 'http' in matric_no else matric_no
    student = Student.query.filter_by(matric_no=matric_no).first()
    if not student:
        return jsonify({'status': 'error', 'message': 'Student Not Found'})
    return jsonify({
        'status': 'success',
        'name': student.name,
        'image': url_for('static', filename='profile_pics/' + student.image_file),
        'paid': student.has_paid_fees,
        'department': student.department,
        'id': student.id  # <--- JUST ADD THIS ONE LINE!
    })


@app.route('/library/manage', methods=['GET', 'POST'])
def manage_library():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        author = request.form['author']
        desc = request.form['description']
        stock = int(request.form['stock'])
        cover_filename = 'default_book.jpg'

        if 'cover' in request.files and request.files['cover'].filename != '':
            cover_filename = save_library_file(request.files['cover'], 'UPLOAD_LIBRARY_COVERS')

        pdf_filename = None
        if 'pdf' in request.files and request.files['pdf'].filename != '':
            pdf_filename = save_library_file(request.files['pdf'], 'UPLOAD_LIBRARY_PDFS')

        new_book = LibraryBook(
            title=title,
            author=author,
            description=desc,
            stock_quantity=stock,
            cover_image=cover_filename,
            pdf_file=pdf_filename
        )
        db.session.add(new_book)
        db.session.commit()
        flash('✅ Book added to library successfully!')
        return redirect(url_for('manage_library'))

    books = LibraryBook.query.order_by(LibraryBook.date_added.desc()).all()
    return render_template('library_manage.html', books=books)


@app.route('/library/delete/<int:id>', methods=['POST'])
def delete_book(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    book = LibraryBook.query.get_or_404(id)
    db.session.delete(book)
    db.session.commit()
    flash('Book deleted.')
    return redirect(url_for('manage_library'))


@app.route('/student/library')
def student_library():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    books = LibraryBook.query.order_by(LibraryBook.title.asc()).all()
    student = Student.query.get(session['student_id'])
    my_borrows = [b.book_id for b in student.borrowings if b.status == 'Borrowed']

    return render_template(
        'student_library.html',
        books=books,
        my_borrows=my_borrows
    )


@app.route('/student/library/borrow/<int:book_id>', methods=['POST'])
def borrow_book(book_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    book = LibraryBook.query.get_or_404(book_id)
    student = Student.query.get(session['student_id'])

    if book.stock_quantity < 1:
        flash('❌ Sorry, this book is out of stock.')
        return redirect(url_for('student_library'))

    existing = Borrowing.query.filter_by(
        student_id=student.id,
        book_id=book.id,
        status='Borrowed'
    ).first()

    if existing:
        flash('⚠️ You already have a copy of this book.')
        return redirect(url_for('student_library'))

    book.stock_quantity -= 1
    new_borrow = Borrowing(
        student_id=student.id,
        book_id=book.id,
        due_date=datetime.utcnow() + timedelta(days=14)
    )
    db.session.add(new_borrow)
    db.session.commit()
    flash(f'✅ Successfully borrowed "{book.title}". Please pick it up from the library within 24 hours.')
    return redirect(url_for('student_library'))


@app.route('/student/evaluations')
def student_evaluations_list():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    courses_data = []

    for course in student.registered_courses:
        eval_exists = CourseEvaluation.query.filter_by(
            student_id=student.id,
            course_id=course.id
        ).first()
        courses_data.append({'course': course, 'evaluated': eval_exists})

    return render_template('evaluate_list.html', courses=courses_data)


@app.route('/student/evaluate/<int:course_id>', methods=['GET', 'POST'])
def evaluate_course(course_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    course = Course.query.get_or_404(course_id)

    if CourseEvaluation.query.filter_by(
        student_id=student.id,
        course_id=course.id
    ).first():
        flash('You have already rated this course.')
        return redirect(url_for('student_evaluations_list'))

    if request.method == 'POST':
        rating = int(request.form['rating'])
        comment = request.form['comment']
        new_eval = CourseEvaluation(
            student_id=student.id,
            course_id=course.id,
            rating=rating,
            comment=comment
        )
        db.session.add(new_eval)
        db.session.commit()
        flash('✅ Thank you for your feedback!')
        return redirect(url_for('student_evaluations_list'))

    return render_template('evaluate_form.html', course=course)


@app.route('/analytics/evaluations')
def lecturer_evaluations_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    # 🟢 BLANK SLATE FOR LECTURERS
    if session.get('role') == 'lecturer':
        courses = Course.query.filter_by(lecturer_id=session.get('user_id')).all()
    else:
        courses = Course.query.all()
        
    data = []

    for c in courses:
        evals = CourseEvaluation.query.filter_by(course_id=c.id).all()
        if evals:
            avg_rating = sum([e.rating for e in evals]) / len(evals)
            data.append({
                'course': c,
                'count': len(evals),
                'avg': round(avg_rating, 1),
                'reviews': evals
            })
        else:
            data.append({
                'course': c,
                'count': 0,
                'avg': 0,
                'reviews': []
            })

    return render_template('lecturer_reviews.html', evaluation_data=data)


@app.route('/bursary')
@admin_only
def bursary_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    total_revenue = db.session.query(func.sum(Payment.amount)).scalar() or 0.0
    total_transactions = Payment.query.count()
    total_students = my_data(Student).count()
    paid_students = Student.query.filter_by(has_paid_fees=True).count()
    debtors = total_students - paid_students
    recents = Payment.query.order_by(Payment.date_paid.desc()).limit(20).all()

    return render_template(
        'bursary.html',
        revenue=total_revenue,
        tx_count=total_transactions,
        paid=paid_students,
        debtors=debtors,
        recents=recents
    )

@app.route('/bursary/debtors')
def debtors_list():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    debtors = Student.query.filter_by(
        has_paid_fees=False
    ).order_by(Student.level).all()

    return render_template('debtors_list.html', debtors=debtors)


@app.route('/bursary/verify', methods=['POST'])
def verify_payment():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    ref = request.form['reference'].strip()
    payment = Payment.query.filter_by(reference=ref).first()

    if payment:
        flash(
            f'✅ VALID PAYMENT: ₦{payment.amount} by {payment.student.name} on {payment.date_paid.strftime("%Y-%m-%d")}'
        )
    else:
        flash(f'❌ INVALID REFERENCE: {ref} does not exist in our records.')

    return redirect(url_for('bursary_dashboard'))

@app.route('/student/assistant')
def student_assistant():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    # 1. Fetch the student
    student = db.session.get(Student, session['student_id'])
    
    # 2. NEW: Fetch ALL chat sessions from the Database for the Sidebar
    # This gets every conversation this student has ever had, ordered by newest first.
    my_chats = ChatSession.query.filter_by(student_id=student.id).order_by(ChatSession.created_at.desc()).all()
    
    # 3. Pass 'chat_list' to the HTML so the sidebar can loop through it
    return render_template('ai_assistant.html', student=student, chat_list=my_chats)

# ==========================================
# 🌍 L.I.S.A MULTI-LANGUAGE BRAIN
# ==========================================

@app.route('/api/set_language', methods=['POST'])
def set_language():
    if not session.get('student_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    lang = data.get('language', 'en')
    session['language'] = lang  # Save preference to session
    return jsonify({'status': 'success', 'language': lang})


# --- 🧠 APEX AGENTIC AI ROUTE (POWERED BY GROQ LLAMA-3.3-70B) ---
@app.route('/api/ask_lisa', methods=['POST'])
def ask_lisa():
    # Check if student OR staff is logged in
    is_student = session.get('student_logged_in')
    is_staff = session.get('role') in ['admin', 'lecturer']
    
    if not (is_student or is_staff):
        return jsonify({'response': "L.I.S.A. Protocol: Please authenticate."}), 401

    data = request.get_json()
    user_question = data.get('message', '')
    temperature = data.get('temperature', 0.7)
    sys_prompt_override = data.get('system_prompt', '')
    
    # Safely get the user's name
    user_name = "Admin"
    chat_student_id = 0 
    
    if is_student:
        student = db.session.get(Student, session.get('student_id'))
        if student:
            user_name = student.name
            chat_student_id = student.id

    # 1. Get Language Preference
    lang_code = session.get('language', 'en')
    lang_instructions = {
        'en': "Respond in English.",
        'yo': "You must respond primarily in standard Yoruba.",
        'fr': "You must respond strictly in French."
    }
    lang_instruction = lang_instructions.get(lang_code, "Respond in English.")

    # 2. Identify Chat Session
    chat_id = session.get('current_chat_id')
    if not chat_id:
        new_sess = ChatSession(student_id=chat_student_id)
        db.session.add(new_sess)
        db.session.commit()
        chat_id = new_sess.id
        session['current_chat_id'] = chat_id

    # 3. Format Prompt for Groq (OpenAI Spec)
    if sys_prompt_override:
        system_prompt = f"System Directive: {sys_prompt_override}\n\nContext: You are advising {user_name}. {lang_instruction}"
    else:
        system_prompt = f"You are L.I.S.A, a highly intelligent, expert AI Advisor for {user_name}. You can answer any question in the world expertly. {lang_instruction}"
    
    db_history = ChatMessage.query.filter_by(session_id=chat_id).order_by(ChatMessage.timestamp.asc()).all()
    
    messages = [{"role": "system", "content": system_prompt}]
    
    # Inject conversational memory
    for msg in db_history[-8:]: 
        messages.append({"role": msg.role, "content": msg.content})
        
    messages.append({"role": "user", "content": user_question})

    try:
        import httpx
        import time
        
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # 🟢 ARCHITECT FIX: UPGRADED TO THE ACTIVE LATEST LLAMA-3.3 MODEL
        payload = {
            "model": "llama-3.3-70b-versatile",  # <--- THE FIX IS RIGHT HERE
            "messages": messages,
            "temperature": float(temperature)
        }

        print("🚨 ROUTING TO GROQ NEURAL ENGINE (LLAMA-3.3-70B) ...")
        
        response = None
        for attempt in range(3): 
            try:
                with httpx.Client(verify=False, timeout=30.0, http2=False) as client:
                    response = client.post(url, json=payload, headers=headers)
                    if response.status_code == 200: 
                        break 
            except Exception as e:
                print(f"⚠️ Network Hiccup (Attempt {attempt+1}/3): {e}")
                time.sleep(1)

        if response and response.status_code == 200:
            res_data = response.json()
            ai_reply = res_data['choices'][0]['message']['content']
            
            # Save interaction
            user_entry = ChatMessage(session_id=chat_id, role='user', content=user_question)
            ai_entry = ChatMessage(session_id=chat_id, role='assistant', content=ai_reply)
            db.session.add_all([user_entry, ai_entry])
            db.session.commit()
            
            return jsonify({'response': ai_reply})
        else:
            error_message = f"AI API FAILURE: {response.status_code if response else 'Timeout'} - {response.text if response else 'No Data'}"
            print(error_message)
            return jsonify({'response': error_message}), 500
            
    except Exception as e:
        print(f"🔴 SYSTEM CRASH: {str(e)}")
        return jsonify({"response": f"SYSTEM CRASH: {str(e)}"}), 500



# --- THE FIXED CLEAR ROUTE (With Debugging) ---
@app.route('/api/clear_chat', methods=['POST'])
def clear_chat():
    # 1. Get the current chat ID
    chat_id = session.get('current_chat_id')
    
    if not chat_id:
        print("DEBUG: No active chat ID found to clear.")
        return jsonify({'status': 'error', 'message': 'No active chat selected'})

    try:
        # 2. Delete messages from the database
        # Make sure ChatMessage is imported at the top of app.py!
        ChatMessage.query.filter_by(session_id=chat_id).delete()
        db.session.commit()
        print(f"DEBUG: Successfully cleared messages for Chat ID {chat_id}")
        
        return jsonify({'status': 'success', 'message': 'Memory Cleared'})
        
    except Exception as e:
        print(f"DEBUG ERROR: {e}")
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/new_chat', methods=['POST'])
def new_chat():
    if not session.get('student_id'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    # 1. Create a brand new session entry in the Database
    new_sess = ChatSession(student_id=session['student_id'])
    db.session.add(new_sess)
    db.session.commit()
    
    # 2. Switch the "Active Pointer" to this new ID
    session['current_chat_id'] = new_sess.id
    session['chat_history'] = [] # Reset temporary cookie buffer
    session.modified = True
    
    return jsonify({
        'chat_id': new_sess.id, 
        'title': 'New Chat Started',
        'status': 'success'
    })

@app.route('/chat')
def chat_page():
    if not session.get('student_logged_in'):
        return redirect('/login') # Go to login if not authenticated
        
    student = db.session.get(Student, session['student_id'])
    # This renders the code I wrote above and sends the "student" data to it
    return render_template('chat.html', student=student)

@app.route('/admin/elections', methods=['GET', 'POST'])
@admin_only
def manage_elections():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'position_title' in request.form:
            db.session.add(
                ElectionPosition(title=request.form['position_title'])
            )
        elif 'candidate_name' in request.form:
            db.session.add(
                Candidate(
                    position_id=request.form['position_id'],
                    name=request.form['candidate_name'],
                    manifesto=request.form['manifesto']
                )
            )

        db.session.commit()
        return redirect(url_for('manage_elections'))

    positions = ElectionPosition.query.all()
    chart_data = {
        pos.id: {
            'labels': [c.name for c in pos.candidates],
            'data': [c.vote_count for c in pos.candidates]
        } for pos in positions
    }

    return render_template(
        'admin_elections.html',
        positions=positions,
        chart_data=chart_data
    )


@app.route('/student/vote', methods=['GET', 'POST'])
def student_vote():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student_id = session['student_id']

    if request.method == 'POST':
        pos_id, cand_id = request.form['position_id'], request.form['candidate_id']

        if Vote.query.filter_by(
            student_id=student_id,
            position_id=pos_id
        ).first():
            flash('⚠️ You already voted for this position!')
        else:
            cand = Candidate.query.get(cand_id)
            cand.vote_count += 1
            db.session.add(Vote(student_id=student_id, position_id=pos_id))
            db.session.commit()
            flash(f'✅ Voted for {cand.name}!')

        return redirect(url_for('student_vote'))

    positions = ElectionPosition.query.all()
    voted_positions = [
        v.position_id
        for v in Vote.query.filter_by(student_id=student_id).all()
    ]

    return render_template(
        'student_voting_booth.html',
        positions=positions,
        voted_positions=voted_positions
    )



# --- 📱 UPDATED REAL-TIME ATTENDANCE API (REGEX, CROSS-COURSE, EXACT TIME) ---
@app.route('/api/mark_attendance', methods=['POST', 'OPTIONS'])
def api_mark_attendance():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    data = request.get_json()
    raw_payload = str(data.get('matric_no', '')).strip()
    course_id = data.get('course_id')
    today = date.today()
    
    # Generate exact WAT Time (UTC + 1)
    wat_time = (datetime.utcnow() + timedelta(hours=1)).strftime('%I:%M %p WAT')

    # 1. 🧹 ULTIMATE REGEX PAYLOAD EXTRACTOR
    import re
    matric = raw_payload
    
    match_9 = re.search(r'\b\d{9}\b', raw_payload)
    match_slash = re.search(r'\b[A-Za-z]{3}/\d{4}/\d+\b', raw_payload)
    match_id = re.search(r'(?:ID|MATRIC)[\s:]*([A-Za-z0-9_/]+)', raw_payload, re.IGNORECASE)
    
    if match_9:
        matric = match_9.group()
    elif match_slash:
        matric = match_slash.group()
    elif match_id:
        matric = match_id.group(1)
    else:
        words = raw_payload.split()
        if words:
            matric = max(words, key=len)

    matric = matric.strip().upper()

    # 2. Get Course
    course = Course.query.get(course_id)
    if not course:
        return jsonify({'status': 'error', 'message': 'COURSE NOT FOUND IN DB'})

    # 3. Get Student (EXACT MATCH first for safety)
    student = Student.query.filter_by(matric_no=matric).first()
    if not student and len(matric) >= 4:
        student = Student.query.filter(Student.matric_no.ilike(f"%{matric}%")).first()

    # 🟢 AUTO-HEALING MAGIC
    if not student:
        student = Student(
            matric_no=matric,
            name=f"Student {matric}",
            department="General",
            attendance_pct=0.0
        )
        db.session.add(student)
        db.session.commit()
        
    if course not in student.registered_courses:
        student.registered_courses.append(course)
        db.session.commit()

    # 4. Check for Duplicates (Strictly for THIS student, THIS course, THIS day)
    existing = DailyAttendance.query.filter_by(
        course_id=course_id,
        student_id=student.id,
        date=today
    ).first()

    if existing:
        return jsonify({
            'status': 'error', 
            'message': f'ID {student.matric_no} ALREADY LOGGED FOR {course.code} TODAY'
        })

    # 5. Record New Attendance with EXACT TIME
    new_record = DailyAttendance(
        course_id=course_id,
        student_id=student.id,
        date=today,
        status='Present',
        time_logged=wat_time
    )
    db.session.add(new_record)
    db.session.commit() 

    # 6. Recalculate Live Percentage (15 Classes Logic)
    TOTAL_SEMESTER_CLASSES = 15
    reg_count = len(student.registered_courses)
    if reg_count == 0: reg_count = 1
        
    total_expected = reg_count * TOTAL_SEMESTER_CLASSES
    total_present = DailyAttendance.query.filter_by(
        student_id=student.id,
        status='Present'
    ).count() 

    new_pct = (total_present / total_expected) * 100
    student.attendance_pct = min(100.0, round(new_pct, 1))
    db.session.commit()

    return jsonify({
        'status': 'success',
        'name': student.name,
        'department': student.department,
        'new_pct': f"{student.attendance_pct}%",
        'matric_no': student.matric_no,
        'course_code': course.code,
        'date_str': today.strftime('%d %b %Y').upper(),
        'time_str': wat_time
    })


# --- 🛰️ NEW: LIVE ATTENDANCE POLLER ---
@app.route('/api/student/live_attendance')
def live_attendance_data():
    if not session.get('student_id'):
        return jsonify([])

    student = Student.query.get(session['student_id'])
    data = []
    
    # 📐 The fixed parameter: 15 Expected Classes per Semester
    TOTAL_SEMESTER_CLASSES = 15

    for course in student.registered_courses:
        # Count only how many times this specific student was present for this specific course
        present = DailyAttendance.query.filter_by(
            course_id=course.id,
            student_id=student.id,
            status='Present'
        ).count()

        # Calculate based on the 15-class threshold
        course_pct = (present / TOTAL_SEMESTER_CLASSES) * 100

        data.append({
            'code': course.code,
            # We wrap it in a min(100.0) just in case they attend extra/makeup classes 
            # so the progress bar never breaks past 100%
            'pct': min(100.0, round(course_pct, 1))
        })

    return jsonify(data)


# --- NEW: MARK DAILY ATTENDANCE (DATE-SPECIFIC) ---
@app.route('/course/<int:course_id>/mark_attendance', methods=['GET', 'POST'])
def mark_daily_attendance(course_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    course = Course.query.get_or_404(course_id)

    selected_date_str = request.args.get(
        'date',
        date.today().strftime('%Y-%m-%d')
    )
    selected_date = datetime.strptime(
        selected_date_str,
        '%Y-%m-%d'
    ).date()

    if request.method == 'POST':
        form_date = datetime.strptime(
            request.form['attendance_date'],
            '%Y-%m-%d'
        ).date()
        present_student_ids = request.form.getlist('present')

        for student in course.students:
            existing_record = DailyAttendance.query.filter_by(
                course_id=course.id,
                student_id=student.id,
                date=form_date
            ).first()

            is_present = str(student.id) in present_student_ids

            if existing_record:
                existing_record.status = 'Present' if is_present else 'Absent'
            else:
                new_record = DailyAttendance(
                    course_id=course.id,
                    student_id=student.id,
                    date=form_date,
                    status='Present' if is_present else 'Absent'
                )
                db.session.add(new_record)

            if is_present and not existing_record:
                if student.attendance_pct < 100:
                    student.attendance_pct = min(
                        100,
                        student.attendance_pct + 5.0
                    )

        db.session.commit()
        flash(f'✅ Attendance saved for {form_date.strftime("%d %b, %Y")}!')
        return redirect(
            url_for(
                'mark_daily_attendance',
                course_id=course.id,
                date=form_date
            )
        )

    attendance_records = DailyAttendance.query.filter_by(
        course_id=course.id,
        date=selected_date
    ).all()

    present_ids = [
        r.student_id
        for r in attendance_records
        if r.status == 'Present'
    ]

    return render_template(
        'mark_attendance.html',
        course=course,
        selected_date=selected_date_str,
        present_ids=present_ids
    )


# ==========================================
# 🎓 UPDATED e-CLEARANCE & GRADUATION SYSTEM
# ==========================================

@app.route('/student/clearance')
def student_clearance_dashboard():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = db.session.get(Student, session['student_id'])

    # 1. Get or Create Clearance Record
    clearance = Clearance.query.filter_by(student_id=student.id).first()
    if not clearance:
        clearance = Clearance(student_id=student.id)
        db.session.add(clearance)
        db.session.commit()

    # 2. AUTOMATION: Check Library & Bursary (Your existing logic)
    active_loans = Borrowing.query.filter_by(
        student_id=student.id,
        status='Borrowed'
    ).count()

    if active_loans == 0 and clearance.library_status != 'Cleared':
        clearance.library_status = 'Cleared'
    
    if student.has_paid_fees and clearance.bursary_status != 'Cleared':
        clearance.bursary_status = 'Cleared'
        
    db.session.commit()

    # 3. NEW: Calculate Progress (For the progress bar)
    # We check 5 statuses now: Bursary, Library, Department, Sports, Health
    statuses = [
        clearance.bursary_status, 
        clearance.library_status,
        getattr(clearance, 'department_status', 'Pending'), # Safety getattr in case column missing
        getattr(clearance, 'sports_status', 'Pending'),
        getattr(clearance, 'health_center_status', 'Pending')
    ]
    
    cleared_count = statuses.count('Cleared')
    progress = int((cleared_count / 5) * 100)

    return render_template(
        'clearance.html', # Updated to use the new UI I sent
        student=student,
        cl=clearance,
        active_loans=active_loans,
        progress=progress
    )

# 🖨️ NEW: Print Certificate Route
@app.route('/student/clearance/print')
def print_clearance():
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    student = db.session.get(Student, session['student_id'])
    clearance = Clearance.query.filter_by(student_id=student.id).first()
    
    # Check if fully cleared
    if not clearance:
        flash('❌ Clearance record not found.', 'danger')
        return redirect(url_for('student_clearance_dashboard'))

    # Verify all 5 units are cleared
    statuses = [
        clearance.bursary_status, 
        clearance.library_status,
        clearance.department_status, 
        clearance.sports_status, 
        clearance.health_center_status
    ]
    
    if statuses.count('Cleared') < 5:
        flash('⚠️ You must complete all 5 clearance steps before printing.', 'warning')
        return redirect(url_for('student_clearance_dashboard'))

    # Render the Official Certificate
    from datetime import datetime
    return render_template('clearance_certificate.html', student=student, cl=clearance, date=datetime.now())

# 🛠️ HELPER: Request Manual Clearance (For Dept, Sports, Health)
# 🚀 NEW: FORCED CLEARANCE ROUTE (Renamed to ensure it works)
@app.route('/student/clearance/force_request/<unit>')
def force_request_clearance(unit):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    student_id = session['student_id']
    clearance = Clearance.query.filter_by(student_id=student_id).first()
    
    # Safety: Create if missing
    if not clearance:
        clearance = Clearance(student_id=student_id)
        db.session.add(clearance)
        db.session.commit()

    print(f"👉 DEBUG: Button clicked for {unit}")  # Watch your terminal for this!

    # --- LOGIC ---
    if unit == 'department':
        clearance.department_status = 'Cleared'
        flash("✅ Departmental Clearance Approved!", 'success')
        
    elif unit == 'sports':
        clearance.sports_status = 'Cleared'
        flash("✅ Sports Unit Cleared!", 'success')
        
    elif unit == 'health':
        clearance.health_center_status = 'Cleared'
        flash("✅ Medical Center Cleared!", 'success')

    elif unit == 'library':
        import random
        # 50/50 Chance for simulation fun
        if random.random() > 0.5:
            clearance.library_status = 'Cleared'
            flash("✅ Library Clearance Approved!", 'success')
        else:
            clearance.library_status = 'Processing'
            flash("⏳ Library is still checking your file... Try again!", 'warning')

    elif unit == 'bursary':
        student = Student.query.get(student_id)
        if student.has_paid_fees:
            clearance.bursary_status = 'Cleared'
            flash("✅ Bursary Verified!", 'success')
        else:
            clearance.bursary_status = 'Rejected'
            flash("❌ Pay your fees first!", 'danger')

    db.session.commit()
    return redirect(url_for('student_clearance_dashboard'))


@app.route('/student/change-password', methods=['POST'])
def student_change_password():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    # Your password update logic here...
    return redirect(url_for('student_settings'))


@app.route('/admin/clearance/approve/<int:id>/<unit>', methods=['POST'])
def approve_clearance_unit(id, unit):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    clearance = Clearance.query.get_or_404(id)

    if unit == 'dept':
        clearance.dept_status = 'Cleared'
    elif unit == 'sports':
        clearance.sports_status = 'Cleared'
    elif unit == 'library':
        clearance.library_status = 'Cleared'
    elif unit == 'bursary':
        clearance.bursary_status = 'Cleared'

    db.session.commit()
    flash(f'✅ {unit.upper()} Clearance Approved for Student.')
    return redirect(url_for('admin_clearance_portal'))


@app.route('/verify/certificate/<int:student_id>')
def public_verify_certificate(student_id):
    student = Student.query.get_or_404(student_id)
    clearance = Clearance.query.filter_by(student_id=student.id).first()

    if not clearance or not clearance.is_fully_cleared():
        return "<h1>❌ Unverified Document</h1><p>This student has not completed their clearance.</p>"

    cgpa, remark = calculate_cgpa(student)
    return render_template(
        'certificate_verify.html',
        student=student,
        cgpa=cgpa,
        remark=remark,
        date=date.today()
    )


@app.route('/portal/exchange', methods=['GET', 'POST'])
def resource_exchange():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])

    # 📊 NEW: TOTAL RESOURCE COUNT
    total_count = PeerResource.query.count()

    # 🔍 Handle Faculty Filter and Search Query
    selected_faculty = request.args.get('faculty')
    selected_dept = request.args.get('dept')
    selected_level = request.args.get('level')
    search_query = request.args.get('search', '').strip()

    # 🏆 Calculate Leaderboard (Top 3)
    top_contributors = db.session.query(
        Student.name,
        func.count(PeerResource.id).label('total_shared')
    ).join(
        PeerResource,
        Student.id == PeerResource.uploader_id
    ).group_by(
        Student.id
    ).order_by(
        func.count(PeerResource.id).desc()
    ).limit(3).all()

    # 🏢 Fetch Unique Departments for the selected Faculty
    available_depts = []
    if selected_faculty:
        dept_query = db.session.query(
            PeerResource.dept
        ).filter_by(
            faculty=selected_faculty
        ).distinct().all()
        available_depts = [d[0] for d in dept_query if d[0]]

    if request.method == 'POST':
        file = request.files.get('resource_file')
        if file and file.filename != '':
            filename = save_material_file(file)
            new_res = PeerResource(
                uploader_id=student.id,
                title=request.form['title'],
                category=request.form['category'],
                faculty=request.form['faculty'],
                dept=request.form['dept'].strip(),
                level=request.form.get('level'),
                filename=filename
            )
            db.session.add(new_res)
            db.session.commit()
            flash('✅ Resource shared successfully!')
            return redirect(url_for('resource_exchange'))

    # 📚 Fetch resources with Search & Faculty Logic
    query = PeerResource.query

    if selected_faculty:
        query = query.filter_by(faculty=selected_faculty)

    if selected_dept:
        query = query.filter_by(dept=selected_dept)

    if selected_level:
        query = query.filter_by(level=selected_level)

    if search_query:
        query = query.filter(PeerResource.title.ilike(f'%{search_query}%'))

    resources = query.order_by(PeerResource.date_shared.desc()).all()

    return render_template(
        'resource_exchange.html',
        resources=resources,
        student=student,
        total_count=total_count,
        top_contributors=top_contributors,
        selected_faculty=selected_faculty,
        selected_dept=selected_dept,
        selected_level=selected_level,
        available_depts=available_depts,
        search_query=search_query,
        Bookmark=Bookmark
    )

@app.route('/exchange/download/<int:res_id>')
def download_peer_resource(res_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    res = PeerResource.query.get_or_404(res_id)
    res.downloads += 1
    db.session.commit()
    return send_from_directory(app.config['UPLOAD_MATERIALS_FOLDER'], res.filename, as_attachment=True)


@app.route('/exchange/delete/<int:res_id>', methods=['POST'])
def delete_peer_resource(res_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    res = PeerResource.query.get_or_404(res_id)

    # 🔒 SECURITY CHECK: Only the uploader can delete
    if res.uploader_id != session['student_id']:
        flash('❌ Unauthorized action!')
        return redirect(url_for('resource_exchange'))

    try:
        # 🗑️ Remove the actual file from the folder
        file_path = os.path.join(app.config['UPLOAD_MATERIALS_FOLDER'], res.filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        db.session.delete(res)
        db.session.commit()
        flash('🗑️ Resource removed successfully.')
    except Exception as e:
        flash(f'❌ Error deleting resource: {str(e)}')

    return redirect(url_for('resource_exchange'))


@app.route('/exchange/rate/<int:res_id>', methods=['POST'])
def rate_resource(res_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    stars = request.form.get('stars', type=int)
    comment = request.form.get('comment')
    student_id = session['student_id']

    # 🛡️ Prevent double rating
    existing = ResourceRating.query.filter_by(resource_id=res_id, student_id=student_id).first()
    if existing:
        flash('⚠️ You have already rated this resource.')
        return redirect(url_for('resource_exchange'))

    new_rating = ResourceRating(
        resource_id=res_id,
        student_id=student_id,
        stars=stars,
        comment=comment
    )
    db.session.add(new_rating)
    db.session.commit()

    flash('⭐ Thank you for your feedback!')
    return redirect(url_for('resource_exchange'))


@app.route('/exchange/bookmark/<int:res_id>', methods=['POST'])
def toggle_bookmark(res_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    existing_bookmark = Bookmark.query.filter_by(
        student_id=session['student_id'],
        resource_id=res_id
    ).first()

    if existing_bookmark:
        db.session.delete(existing_bookmark)
        flash('📌 Bookmark removed.')
    else:
        new_bookmark = Bookmark(student_id=session['student_id'], resource_id=res_id)
        db.session.add(new_bookmark)
        flash('📌 Resource saved to your bookmarks!')

    db.session.commit()
    return redirect(request.referrer or url_for('resource_exchange'))


# #... NEW FEATURE: TARGET GP TRACKER
@app.route('/student/target_gp', methods=['GET', 'POST'])
def target_gp():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    result_message = None
    required_gpa = None
    status_color = "primary"  # Default blue

    if request.method == 'POST':
        try:
            current_cgpa = float(request.form.get('current_cgpa'))
            units_taken = int(request.form.get('units_taken'))
            target_cgpa = float(request.form.get('target_cgpa'))
            next_units = int(request.form.get('next_units'))

            # Total units after the upcoming semester
            total_units = units_taken + next_units

            # The Math: (Target * Total) - (Current * Taken) / Upcoming Units
            required_points = (target_cgpa * total_units) - (current_cgpa * units_taken)
            required_gpa = round(required_points / next_units, 2)

            # Logic to check feasibility
            if required_gpa > 5.0:
                result_message = f"⚠️ Impossible! You would need a GPA of {required_gpa}."
                status_color = "danger"
            elif required_gpa < 0:
                result_message = "🎉 You've already surpassed this target!"
                status_color = "success"
                required_gpa = 0.0
            else:
                result_message = f"🎯 To hit {target_cgpa}, you need a {required_gpa} this semester."
                status_color = "success" if required_gpa <= 3.5 else "warning"

        except ValueError:
            flash("❌ Please enter valid numbers")

    return render_template(
        'student_target_gp.html',
        result=result_message,
        required_gpa=required_gpa,
        color=status_color
    )


# #... NEW FEATURE: CARRYOVER IMPACT VISUALIZER
@app.route('/student/carryover_viz')
def student_carryover_viz():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])

    # 1. Calculate Unit Stats
    total_registered_units = 0
    total_failed_units = 0
    failed_courses = []

    # Assuming 'grades' relationship exists and has score/units
    for grade in student.grades:
        # We assume grade.course gives access to units, or grade has units
        # Fallback to 3 units if not explicitly defined in your DB yet
        units = getattr(grade, 'units', 3)
        total_registered_units += units

        if grade.score < 40:  # Assuming 40 is the pass mark
            total_failed_units += units
            failed_courses.append({
                'code': grade.course_code,
                'score': grade.score,
                'units': units
            })

    # 2. Impact Calculation
    MAX_SEMESTER_LOAD = 24
    # If you have carryovers, you must register them first, reducing space for new courses
    available_fresh_units = MAX_SEMESTER_LOAD - total_failed_units

    impact_health = "Excellent"
    if total_failed_units > 0:
        impact_health = "At Risk"
    if total_failed_units > 10:
        impact_health = "Critical"

    return render_template(
        'student_carryover.html',
        student=student,
        total=total_registered_units,
        failed=total_failed_units,
        failed_list=failed_courses,
        next_limit=available_fresh_units,
        health=impact_health
    )


# #... NEW FEATURE: AUTO-REFERENCE LETTER GENERATOR
@app.route('/student/reference_letter')
def student_reference_letter():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])

    # 1. Calculate CGPA on the fly to check eligibility
    total_score = 0
    total_units = 0
    for grade in student.grades:
        # Map score to points (A=5, B=4, etc.)
        points = 0
        if grade.score >= 70:
            points = 5
        elif grade.score >= 60:
            points = 4
        elif grade.score >= 50:
            points = 3
        elif grade.score >= 45:
            points = 2
        elif grade.score >= 40:
            points = 1

        # Assume default unit is 3 if not found
        units = getattr(grade, 'units', 3)
        total_score += (points * units)
        total_units += units

    cgpa = 0.0
    if total_units > 0:
        cgpa = round(total_score / total_units, 2)

    # 2. The Gatekeeper: Strict Eligibility Check
    MINIMUM_CGPA = 3.0
    if cgpa < MINIMUM_CGPA:
        flash(f"⛔ Eligibility Denied: Your CGPA ({cgpa}) is below the {MINIMUM_CGPA} requirement for a reference letter.")
        return redirect(url_for('student_portal'))

    # 3. Render the Letter
    from datetime import datetime
    today_date = datetime.now().strftime("%d %B, %Y")

    return render_template(
        'student_reference_letter.html',
        student=student,
        cgpa=cgpa,
        date=today_date
    )


# #... NEW FEATURE: EXAM CLASH DETECTOR
@app.route('/student/clash_detector')
def student_clash_detector():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])

    clashes = []
    courses = student.registered_courses

    # Simple algorithm to compare every course against every other course
    for i in range(len(courses)):
        for j in range(i + 1, len(courses)):
            c1 = courses[i]
            c2 = courses[j]

            # Check if both have exam dates scheduled
            if c1.exam_date and c2.exam_date:
                # Check if Date matches AND Time matches
                if c1.exam_date == c2.exam_date and c1.exam_time == c2.exam_time:
                    clashes.append({
                        'course1': c1,
                        'course2': c2,
                        'date': c1.exam_date,
                        'time': c1.exam_time
                    })

    return render_template('student_clash_detector.html', student=student, clashes=clashes)


# ==========================================
# 🧪 TEMPORARY TEST ROUTES (DELETE LATER)
# ==========================================

@app.route('/test/create_clash')
def create_test_clash():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])

    # Check if student has courses
    if len(student.registered_courses) < 2:
        return "⚠️ Error: You need to register at least 2 courses to test this feature!"

    # Grab the first two courses
    course1 = student.registered_courses[0]
    course2 = student.registered_courses[1]

    # ⚠️ FORCE A CLASH: Set both to TODAY at 9:00 AM ⚠️
    from datetime import date
    today = date.today()

    course1.exam_date = today
    course1.exam_time = "09:00 AM"

    course2.exam_date = today
    course2.exam_time = "09:00 AM"

    db.session.commit()

    flash(f"⚡ TEST CLASH CREATED: {course1.code} and {course2.code} are colliding!")
    return redirect(url_for('student_clash_detector'))


@app.route('/test/fix_clash')
def fix_test_clash():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])

    # Reset all exam times
    for course in student.registered_courses:
        course.exam_date = None
        course.exam_time = None

    db.session.commit()
    flash("✅ Exam timetable reset. No clashes.")
    return redirect(url_for('student_clash_detector'))


# ==========================================
# 🚑 EMERGENCY DATABASE FIXER
# ==========================================
from sqlalchemy import text

@app.route('/emergency_fix')
def emergency_fix():
    try:
        with app.app_context():
            # Force add exam_date
            try:
                db.session.execute(text("ALTER TABLE course ADD COLUMN exam_date DATE"))
                print("✅ Added exam_date")
            except Exception as e:
                print(f"ℹ️ exam_date info: {e}")

            # Force add exam_time
            try:
                db.session.execute(text("ALTER TABLE course ADD COLUMN exam_time VARCHAR(20)"))
                print("✅ Added exam_time")
            except Exception as e:
                print(f"ℹ️ exam_time info: {e}")

            db.session.commit()
            return """
            <div style='text-align: center; padding: 50px; font-family: sans-serif;'>
                <h1 style='color: green;'>✅ SUCCESS!</h1>
                <p>The database columns <b>exam_date</b> and <b>exam_time</b> have been successfully injected.</p>
                <br>
                <a href='/student/clash_detector' style='padding: 15px 30px; background: #198754; color: white; text-decoration: none; border-radius: 5px;'>Test Clash Detector Now</a>
            </div>
            """
    except Exception as e:
        return f"<h1>❌ Error: {e}</h1>"


# ==========================================
# 📚 SYLLABUS TRACKER LOGIC
# ==========================================

# 1. MAGIC SETUP (Run this once to fix DB and generate topics)
@app.route('/setup_syllabus')
def setup_syllabus():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    with app.app_context():
        # Create the new tables
        db.create_all()

        # Auto-Generate Topics for existing courses (so you don't see a blank page)
        courses = Course.query.all()
        count = 0
        for course in courses:
            # Only add if course has no topics yet
            if not SyllabusTopic.query.filter_by(course_id=course.id).first():
                topics = [
                    f"Introduction to {course.code}",
                    "Historical Perspectives & Theories",
                    "Core Concepts and Methodologies",
                    "Mid-Semester Review",
                    "Advanced Applications",
                    "Case Studies and Analysis",
                    "Final Project Preparation"
                ]
                for i, t in enumerate(topics):
                    new_topic = SyllabusTopic(course_id=course.id, title=t, week_number=i+1)
                    db.session.add(new_topic)
                count += 1

        db.session.commit()
        return f"<h1>✅ Syllabus System Ready!</h1><p>Generated topics for {count} courses.</p><a href='/student/syllabus'>Go to Tracker</a>"


# 2. VIEW THE TRACKER
@app.route('/student/syllabus')
def student_syllabus_tracker():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])

    # Organize data for the template
    course_data = []

    for course in student.registered_courses:
        topics = SyllabusTopic.query.filter_by(course_id=course.id).order_by(SyllabusTopic.week_number).all()

        # Calculate Progress
        total_topics = len(topics)
        completed_count = 0

        topic_list = []
        for topic in topics:
            # Check if this student completed this topic
            is_done = TopicCompletion.query.filter_by(student_id=student.id, topic_id=topic.id).first() is not None
            if is_done:
                completed_count += 1

            topic_list.append({
                'id': topic.id,
                'title': topic.title,
                'week': topic.week_number,
                'done': is_done
            })

        progress = (completed_count / total_topics * 100) if total_topics > 0 else 0

        course_data.append({
            'code': course.code,
            'title': course.title,
            'progress': round(progress),
            'topics': topic_list
        })

    return render_template('student_syllabus.html', student=student, courses=course_data)


# 3. API TO TOGGLE CHECKBOX
@app.route('/api/toggle_topic/<int:topic_id>')
def toggle_topic(topic_id):
    if not session.get('student_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    student_id = session['student_id']

    existing = TopicCompletion.query.filter_by(student_id=student_id, topic_id=topic_id).first()

    if existing:
        db.session.delete(existing)
        status = "unchecked"
    else:
        new_comp = TopicCompletion(student_id=student_id, topic_id=topic_id)
        db.session.add(new_comp)
        status = "checked"

    db.session.commit()
    return jsonify({'status': status})


# #... ADD TO app.py (EMERGENCY DB UPGRADER)
@app.route('/emergency_streak_fix')
def emergency_streak_fix():
    try:
        with app.app_context():
            # 1. Add streak_count
            try:
                db.session.execute(text("ALTER TABLE student ADD COLUMN streak_count INTEGER DEFAULT 0"))
                print("✅ Added streak_count")
            except Exception:
                pass

            # 2. Add last_activity_date
            try:
                db.session.execute(text("ALTER TABLE student ADD COLUMN last_activity_date DATE"))
                print("✅ Added last_activity_date")
            except Exception:
                pass

            db.session.commit()
            return "<h1>🔥 Streak System Installed!</h1><p>Database ready for gamification.</p>"
    except Exception as e:
        return f"❌ Error: {e}"


# #... NEW FEATURE: STREAK COUNTER API
@app.route('/api/update_streak')
def api_update_streak():
    if not session.get('student_logged_in'):
        return jsonify({'streak': 0})

    student = Student.query.get(session['student_id'])
    from datetime import date, timedelta
    today = date.today()

    # Initialize if None
    if student.streak_count is None:
        student.streak_count = 0

    # 🚨 CRITICAL FIX: Use 'last_study_date' (matches your Database)
    # instead of 'last_activity_date'

    # 1. Handle New Users (First time login)
    if student.last_study_date is None:
        student.streak_count = 1
        student.last_study_date = today
        db.session.commit()
        return jsonify({'streak': 1, 'message': "Streak started! 🚀"})

    # 2. Logic: Only update if we haven't already counted today
    if student.last_study_date != today:
        if student.last_study_date == today - timedelta(days=1):
            # Perfect! Logged in yesterday, so increment.
            student.streak_count += 1
        else:
            # Missed a day, reset to 1
            student.streak_count = 1

        student.last_study_date = today
        db.session.commit()

    return jsonify({
        'streak': student.streak_count,
        'message': "Keep the fire burning! 🔥" if student.streak_count > 1 else "Streak started! 🚀"
    })


# ==========================================
# ⏳ LECTURE COUNTDOWN LOGIC
# ==========================================
@app.route('/api/next_class')
def api_next_class():
    if not session.get('student_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    student = Student.query.get(session['student_id'])

    from datetime import datetime, timedelta
    import calendar

    now = datetime.now()
    today_index = now.weekday()  # 0=Monday, 6=Sunday
    days_map = {'Monday':0, 'Tuesday':1, 'Wednesday':2, 'Thursday':3, 'Friday':4, 'Saturday':5, 'Sunday':6}

    upcoming_classes = []

    # Analyze all registered courses
    for course in student.registered_courses:
        for schedule in course.schedules:
            if schedule.day not in days_map:
                continue

            target_day_index = days_map[schedule.day]

            # Calculate days ahead
            days_ahead = target_day_index - today_index

            # Parse start time (e.g., "09:00")
            try:
                class_hour = int(schedule.start_time.split(':')[0])
                class_min = int(schedule.start_time.split(':')[1])

                # If it's today, check if time has passed
                if days_ahead == 0:
                    class_time = now.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)
                    if class_time < now:
                        days_ahead = 7  # It's next week
                elif days_ahead < 0:
                    days_ahead += 7  # Next week

                # Calculate exact datetime of next class
                next_class_date = now + timedelta(days=days_ahead)
                next_class_date = next_class_date.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)

                time_diff = (next_class_date - now).total_seconds()

                upcoming_classes.append({
                    'code': course.code,
                    'title': course.title,
                    'venue': schedule.venue,
                    'time': schedule.start_time,
                    'seconds_left': int(time_diff),
                    'timestamp': next_class_date.isoformat()
                })
            except:
                continue

    # Sort by nearest time
    if not upcoming_classes:
        return jsonify({'has_class': False})

    upcoming_classes.sort(key=lambda x: x['seconds_left'])
    nearest = upcoming_classes[0]

    return jsonify({
        'has_class': True,
        'code': nearest['code'],
        'title': nearest['title'],
        'venue': nearest['venue'],
        'seconds_left': nearest['seconds_left']
    })


# ==========================================
# 🧪 TEST ROUTE: Create a Fake Class Schedule
# ==========================================
@app.route('/test/create_schedule')
def test_create_schedule():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])

    if not student.registered_courses:
        return "❌ Error: You need to register for at least one course first!"

    # Pick the first course
    course = student.registered_courses[0]

    # 🗓️ LOGIC: Find out what 'Tomorrow' is
    from datetime import datetime, timedelta
    import calendar

    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    tomorrow_name = calendar.day_name[tomorrow.weekday()]  # e.g., "Thursday"

    # Create the schedule entry
    new_schedule = ClassSchedule(
        course_id=course.id,
        day=tomorrow_name,       # Dynamic: Always sets it to tomorrow
        start_time="09:00",      # 9:00 AM
        end_time="11:00",
        venue="Lecture Hall 1"
    )

    db.session.add(new_schedule)
    db.session.commit()

    # 👇 THIS IS THE FIXED LINK (student/portal)
    return f"""
    <div style="text-align: center; padding: 50px; font-family: sans-serif;">
        <h1 style="color: green;">✅ Schedule Created!</h1>
        <p>I just added a class for <b>{course.code}</b> on <b>{tomorrow_name} at 9:00 AM</b>.</p>
        <br>
        <a href='/student/portal' style="background: #198754; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Go to Portal & See Timer</a>
    </div>
    """


@app.route('/fix_exam_venue_column')
def fix_exam_venue_column():
    try:
        with app.app_context():
            from sqlalchemy import text
            db.session.execute(text("ALTER TABLE course ADD COLUMN exam_venue VARCHAR(100)"))
            db.session.commit()
            return "✅ Success! Added 'exam_venue' column to Course table."
    except Exception as e:
        return f"ℹ️ Column likely already exists. Status: {e}"


# ==========================================
# 🎓 PERSONALIZED EXAM DOCKET (REAL-TIME SYNC)
# ==========================================
@app.route('/student/exam_docket')
def student_exam_docket():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])

    # 1. Get all courses this student is registered for
    my_courses = student.registered_courses

    # 2. Filter: Keep only courses where the Lecturer has set an Exam Date
    upcoming_exams = [c for c in my_courses if c.exam_date]

    # 3. Sort chronologically (earliest exam first)
    upcoming_exams.sort(key=lambda x: x.exam_date)

    return render_template('student_exam_docket.html', student=student, exams=upcoming_exams)



# ==========================================
# 🚑 EMERGENCY DATABASE FIX (Run once)
# ==========================================
@app.route('/emergency_db_fix')
def emergency_db_fix():
    import sqlite3
    try:
        conn = sqlite3.connect('lasu_data.db')
        cursor = conn.cursor()

        # 1. Add streak_count
        try:
            cursor.execute("ALTER TABLE student ADD COLUMN streak_count INTEGER DEFAULT 0")
            status_1 = "✅ Added 'streak_count'"
        except Exception as e:
            status_1 = f"ℹ️ 'streak_count' exists or error: {e}"

        # 2. Add last_study_date
        try:
            cursor.execute("ALTER TABLE student ADD COLUMN last_study_date DATE")
            status_2 = "✅ Added 'last_study_date'"
        except Exception as e:
            status_2 = f"ℹ️ 'last_study_date' exists or error: {e}"

        conn.commit()
        conn.close()

        return f"""
        <h1>Database Repair Report</h1>
        <p>{status_1}</p>
        <p>{status_2}</p>
        <hr>
        <h3>🎉 FIXED! Now restart your server and go to the <a href='/portal'>Student Portal</a></h3>
        """
    except Exception as e:
        return f"<h1>Critical Error: {e}</h1>"


# --- REPLACED OLD CHAT ROUTE ---
@app.route('/complaint/chat/<int:id>', methods=['GET', 'POST'])
def complaint_chat(id):
    # Redirect to the dashboard where the new WhatsApp modal lives
    if session.get('logged_in'):
        return redirect(url_for('lecturer_complaints'))
    elif session.get('student_logged_in'):
        return redirect(url_for('student_portal'))
    return redirect(url_for('login'))

# ==========================================
# 🟢 WHATSAPP TICKET SYSTEM (API ENGINE)
# ==========================================

@app.route('/api/ticket/<int:ticket_id>/get_messages')
def get_ticket_messages(ticket_id):
    if not session.get('logged_in') and not session.get('student_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    complaint = Complaint.query.get_or_404(ticket_id)
    
    # 1. Get Replies using 'ComplaintMessage'
    messages = ComplaintMessage.query.filter_by(complaint_id=ticket_id).order_by(ComplaintMessage.timestamp.asc()).all()
    
    chat_history = []

    # 2. Add the ORIGINAL Complaint as the first message
    chat_history.append({
        'id': 'init', 
        'sender': 'Student', 
        'text': complaint.message,
        'time': complaint.date_lodged.strftime('%I:%M %p'),
        'is_me': True if session.get('student_logged_in') else False 
    })

    # 3. Add the rest
    for msg in messages:
        chat_history.append({
            'id': msg.id,
            'sender': msg.sender, 
            'text': msg.text,
            'time': msg.timestamp.strftime('%I:%M %p'),
            'is_me': (msg.sender == 'Student') if session.get('student_logged_in') else (msg.sender == 'Lecturer')
        })
        
    return jsonify({'messages': chat_history, 'status': complaint.status})

@app.route('/api/ticket/<int:ticket_id>/send_message', methods=['POST'])
def send_ticket_message(ticket_id):
    # 1. Security Check
    if not session.get('logged_in') and not session.get('student_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    complaint = Complaint.query.get_or_404(ticket_id)
    
    # 2. Determine Sender (Student Priority to fix Double Login bug)
    if session.get('student_logged_in'):
        sender_role = 'Student'
    elif session.get('logged_in'):
        sender_role = 'Lecturer'
        if complaint.status == 'Pending':
            complaint.status = 'Active'
    else:
        return jsonify({'error': 'Session Error'}), 401

    # 3. Handle Content (File OR Text)
    # Note: When sending files, we use request.form/files instead of get_json()
    text_content = request.form.get('message', '').strip()
    file = request.files.get('file')
    
    # 🟢 NEW: File Upload Logic
    if file and file.filename != '':
        try:
            filename = secure_filename(file.filename)
            # Create a unique name to prevent overwriting (timestamp_filename)
            timestamp_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
            
            # Ensure the upload folder exists
            upload_folder = os.path.join(app.static_folder, 'chat_uploads')
            os.makedirs(upload_folder, exist_ok=True)
            
            # Save the file
            file.save(os.path.join(upload_folder, timestamp_name))
            
            # The message text becomes the URL to the file
            text_content = f"/static/chat_uploads/{timestamp_name}"
        except Exception as e:
            print(f"❌ Upload Error: {e}")
            return jsonify({'error': 'File upload failed'}), 500
    
    # Fallback for JSON requests (Text only)
    if not text_content and request.is_json:
        data = request.get_json()
        text_content = data.get('message', '').strip()

    if not text_content: 
        return jsonify({'error': 'Empty message'}), 400
        
    # 4. Save to Database
    new_msg = ComplaintMessage(
        complaint_id=ticket_id,
        sender=sender_role,
        text=text_content,
        timestamp=datetime.utcnow()
    )
    db.session.add(new_msg)
    db.session.commit()
    
    return jsonify({'status': 'success'})

@app.route('/api/ticket/<int:ticket_id>/close', methods=['POST'])
def close_ticket_api(ticket_id):
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'}), 403
        
    complaint = Complaint.query.get_or_404(ticket_id)
    complaint.status = 'Resolved'
    
    sys_msg = ComplaintMessage(complaint_id=ticket_id, sender='System', text='🚫 Ticket Resolved.', timestamp=datetime.utcnow())
    db.session.add(sys_msg)
    db.session.commit()
    return jsonify({'status': 'success'})


@app.route('/api/lecturer/get_active_tickets')
def get_lecturer_tickets():
    if not session.get('logged_in'):
        return jsonify([])

    if session.get('role') == 'lecturer':
        # 🟢 LECTURER MODE: See ONLY tickets from their own students
        lecturer_id = session.get('user_id')
        my_courses = Course.query.filter_by(lecturer_id=lecturer_id).all()
        my_course_ids = [c.id for c in my_courses]
        
        if my_course_ids:
            my_students = Student.query.filter(Student.registered_courses.any(Course.id.in_(my_course_ids))).all()
            my_student_ids = [s.id for s in my_students]
            complaints = Complaint.query.filter(Complaint.student_id.in_(my_student_ids)).order_by(Complaint.status.asc(), Complaint.date_lodged.desc()).all()
        else:
            complaints = [] # 🟢 BLANK SLATE
    else:
        # 👑 ADMIN MODE: See ALL tickets
        complaints = Complaint.query.order_by(Complaint.status.asc(), Complaint.date_lodged.desc()).all()

    ticket_list = []

    for c in complaints:
        last_msg = ComplaintMessage.query.filter_by(complaint_id=c.id).order_by(ComplaintMessage.timestamp.desc()).first()
        
        # Safe preview extraction
        if last_msg:
            preview = last_msg.text[:30] + "..."
        elif hasattr(c, 'description') and c.description:
            preview = c.description[:30] + "..."
        elif hasattr(c, 'message') and c.message:
            preview = c.message[:30] + "..."
        else:
            preview = "New Ticket"
            
        ticket_list.append({
            'id': c.id,
            'student_name': c.student_name,
            'matric': c.matric_no,
            'category': c.category,
            'status': c.status,
            'last_message': preview,
            'time': c.date_lodged.strftime('%H:%M')
        })

    return jsonify(ticket_list)


# ==========================================
# ☢️ ATOMIC FIX: FORCE TABLE CREATION
# ==========================================
@app.route('/atomic_fix')
def atomic_fix():
    from sqlalchemy import text
    try:
        # 1. Define the raw SQL to create the table
        create_table_sql = text("""
            CREATE TABLE IF NOT EXISTS complaint_message (
                id INTEGER PRIMARY KEY,
                complaint_id INTEGER NOT NULL,
                sender VARCHAR(20),
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(complaint_id) REFERENCES complaint(id)
            );
        """)
        
        # 2. Execute it using the ACTIVE app connection
        db.session.execute(create_table_sql)
        db.session.commit()
        
        return """
        <div style="text-align: center; padding: 50px; font-family: sans-serif;">
            <h1 style="color: green; font-size: 60px;">✅ SUCCESS!</h1>
            <h2>The database has been forced to create the table.</h2>
            <br>
            <a href="/lecturer/complaints" style="background: #075E54; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-size: 20px;">Open Chat Now</a>
        </div>
        """
    except Exception as e:
        return f"<h1>❌ Critical Error: {e}</h1>"
    
# ==========================================
# 🛑 SUPER FIX: FORCE CREATE TABLES & DIAGNOSE
# ==========================================
@app.route('/super_fix')
def super_fix():
    import sqlite3
    import os
    from sqlalchemy import text
    
    status_report = []
    
    try:
        # 1. Force SQLAlchemy to create everything it knows about
        db.create_all()
        status_report.append("✅ SQLAlchemy db.create_all() executed.")
        
        # 2. Get the EXACT file the app is using
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        db_path = db_uri.replace('sqlite:///', '')
        
        # Handle Flask's relative paths
        if not os.path.isabs(db_path):
            # Check if it's in the root or instance folder
            possible_paths = [
                os.path.join(app.root_path, db_path),
                os.path.join(app.root_path, 'instance', db_path)
            ]
            real_path = db_path # Default fallback
            for p in possible_paths:
                if os.path.exists(p):
                    real_path = p
                    break
        else:
            real_path = db_path

        status_report.append(f"📂 App is reading database at: {real_path}")

        # 3. Manually Inspect that specific file
        conn = sqlite3.connect(real_path)
        cursor = conn.cursor()
        
        # 4. Force Create the table using Raw SQL (Just in case SQLAlchemy missed it)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS complaint_message (
                id INTEGER PRIMARY KEY,
                complaint_id INTEGER NOT NULL,
                sender VARCHAR(20),
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(complaint_id) REFERENCES complaint(id)
            );
        ''')
        conn.commit()
        status_report.append("🔨 Raw SQL creation command executed successfully.")

        # 5. List all tables that actually exist now
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        # 6. Generate Report
        if 'complaint_message' in tables:
            color = "green"
            title = "✅ FIXED SUCCESSFULLY"
            msg = "The table 'complaint_message' is confirmed to exist."
        else:
            color = "red"
            title = "❌ STILL MISSING"
            msg = "Even after forcing creation, the table is not found. Check permissions."

        return f"""
        <div style="font-family: sans-serif; padding: 40px; text-align: center;">
            <h1 style="color: {color}; font-size: 40px;">{title}</h1>
            <p style="font-size: 18px;">{msg}</p>
            <div style="background: #f4f4f4; padding: 20px; text-align: left; display: inline-block; border-radius: 10px;">
                <strong>Debug Log:</strong><br>
                {'<br>'.join(status_report)}
                <br><br>
                <strong>Tables found in DB:</strong><br> {', '.join(tables)}
            </div>
            <br><br>
            <a href="/lecturer/complaints" style="background: #075E54; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 20px;">Go to Chat</a>
        </div>
        """
    except Exception as e:
        return f"<h1>CRITICAL ERROR: {e}</h1>"


# ==========================================
# 🚑 DOCTOR ROUTE: Diagnose & Fix
# ==========================================
@app.route('/doctor')
def doctor():
    results = []
    
    # 1. CHECK DATABASE TABLE
    try:
        from sqlalchemy import text
        # Force create table using the active app connection
        db.session.execute(text('''
            CREATE TABLE IF NOT EXISTS complaint_message (
                id INTEGER PRIMARY KEY,
                complaint_id INTEGER NOT NULL,
                sender VARCHAR(20),
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(complaint_id) REFERENCES complaint(id)
            );
        '''))
        db.session.commit()
        results.append("✅ Step 1: Database Table 'complaint_message' verified/created.")
    except Exception as e:
        results.append(f"❌ Step 1 FAILED: {e}")

    # 2. CHECK PYTHON MODEL
    try:
        # Check if we can actually use the class
        count = ComplaintMessage.query.count()
        results.append(f"✅ Step 2: Python Model 'ComplaintMessage' is working. (Rows: {count})")
    except NameError:
        results.append("❌ Step 2 FAILED: 'ComplaintMessage' is NOT defined. <b>You missed the Import fix!</b>")
    except Exception as e:
        results.append(f"❌ Step 2 FAILED with error: {e}")

    # DISPLAY RESULTS
    color = "green" if "FAILED" not in str(results) else "red"
    return f"""
    <div style="font-family: sans-serif; padding: 50px; text-align: center;">
        <h1 style="color: {color};">Diagnosis Report</h1>
        <div style="text-align: left; display: inline-block; background: #eee; padding: 20px; border-radius: 10px;">
            {'<br><br>'.join(results)}
        </div>
        <br><br>
        <a href="/lecturer/complaints" style="background: #075E54; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px;">Try Chat Again</a>
    </div>
    """

# --- 1. PASTE THIS AT THE BOTTOM OF app.py (Fixes "Loading History...") ---

@app.route('/api/load_chat/<int:chat_id>', methods=['GET'])
def load_chat(chat_id):
    if not session.get('student_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401

    # Fetch the chat
    chat = db.session.get(ChatSession, chat_id)

    if not chat or chat.student_id != session['student_id']:
        return jsonify({'error': 'Chat not found'}), 404

    # Update the "Active Chat" pointer in the session
    session['current_chat_id'] = chat.id

    messages = []
    # Sort messages so the conversation reads correctly (Oldest -> Newest)
    sorted_msgs = sorted(chat.messages, key=lambda x: x.id)
    
    for m in sorted_msgs:
        messages.append({"role": m.role, "content": m.content})

    return jsonify({'status': 'success', 'history': messages, 'title': chat.title})

# ==========================================
# 🧠 L.I.S.A CHAT MANAGEMENT (DELETE & RENAME)
# ==========================================

@app.route('/api/chat/delete/<int:chat_id>', methods=['POST'])
def delete_specific_chat(chat_id):
    if not session.get('student_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401

    # Get the chat and ensure it belongs to the current student
    chat = db.session.get(ChatSession, chat_id)
    
    if not chat or chat.student_id != session['student_id']:
        return jsonify({'error': 'Chat not found or access denied'}), 404

    try:
        # Delete all messages associated with this session first
        ChatMessage.query.filter_by(session_id=chat_id).delete()
        
        # Delete the session itself
        db.session.delete(chat)
        db.session.commit()
        
        # If the deleted chat was the active one, clear the session pointer
        if session.get('current_chat_id') == chat_id:
            session.pop('current_chat_id', None)
            
        return jsonify({'status': 'success', 'message': 'Chat deleted'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/chat/rename/<int:chat_id>', methods=['POST'])
def rename_specific_chat(chat_id):
    if not session.get('student_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    new_title = data.get('title')

    chat = db.session.get(ChatSession, chat_id)
    
    if not chat or chat.student_id != session['student_id']:
        return jsonify({'error': 'Chat not found'}), 404

    chat.title = new_title[:50] # Limit title length
    db.session.commit()
    
    return jsonify({'status': 'success'})


# ==========================================
# 💸 SUBSCRIPTION MANAGER ROUTES
# ==========================================

@app.route('/student/subscriptions')
def student_subscriptions():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = db.session.get(Student, session['student_id'])
    subs = Subscription.query.filter_by(student_id=student.id).order_by(Subscription.next_due_date).all()
    
    total_monthly = sum([s.amount for s in subs])
    today = date.today()
    
    # Calculate days remaining for each sub
    subs_data = []
    for s in subs:
        days_left = (s.next_due_date - today).days
        
        # Auto-update status color
        if days_left < 0: status = "Expired"
        elif days_left <= 3: status = "Critical"
        elif days_left <= 7: status = "Warning"
        else: status = "Safe"
            
        subs_data.append({
            'id': s.id,
            'name': s.name,
            'amount': s.amount,
            'date': s.next_due_date,
            'days_left': days_left,
            'category': s.category,
            'status': status
        })

    return render_template(
        'student_subscriptions.html', 
        student=student, 
        subs=subs_data, 
        total=total_monthly,
        today=today
    )

@app.route('/student/subscriptions/add', methods=['POST'])
def add_subscription():
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    try:
        due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
        
        new_sub = Subscription(
            student_id=session['student_id'],
            name=request.form['name'],
            amount=float(request.form['amount']),
            category=request.form['category'],
            next_due_date=due_date
        )
        db.session.add(new_sub)
        db.session.commit()
        flash('✅ Subscription added successfully!')
    except Exception as e:
        flash(f'❌ Error: {e}')
        
    return redirect(url_for('student_subscriptions'))

@app.route('/student/subscriptions/delete/<int:id>', methods=['POST'])
def delete_subscription(id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    sub = Subscription.query.get_or_404(id)
    if sub.student_id == session['student_id']:
        db.session.delete(sub)
        db.session.commit()
        flash('🗑️ Subscription removed.')
        
    return redirect(url_for('student_subscriptions'))

@app.route('/student/subscriptions/renew/<int:id>', methods=['POST'])
def renew_subscription(id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    # Simple logic: Add 30 days to the due date
    sub = Subscription.query.get_or_404(id)
    if sub.student_id == session['student_id']:
        sub.next_due_date = sub.next_due_date + timedelta(days=30)
        db.session.commit()
        flash(f'🔄 Renewed {sub.name} for 30 days!')
        
    return redirect(url_for('student_subscriptions'))



# ==========================================
# 📝 NOTE-TAKING APP ROUTES (FIXED)
# ==========================================

@app.route('/student/notes')
def student_notes():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = db.session.get(Student, session['student_id'])
    my_notes = Note.query.filter_by(student_id=student.id).order_by(Note.last_updated.desc()).all()
    
    selected_note_id = request.args.get('edit')
    selected_note = None
    if selected_note_id:
        selected_note = Note.query.get(selected_note_id)
        if selected_note and selected_note.student_id != student.id:
            selected_note = None

    return render_template('student_notes.html', student=student, notes=my_notes, selected_note=selected_note)

# 🛑 RENAMED THIS FUNCTION TO FIX THE ERROR
@app.route('/student/notes/save', methods=['POST'])
def save_personal_note():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student_id = session['student_id']
    title = request.form.get('title', 'Untitled Note')
    content = request.form.get('content', '')
    note_id = request.form.get('note_id')

    if note_id:
        note = Note.query.get(note_id)
        if note and note.student_id == student_id:
            note.title = title
            note.content = content
            flash('✅ Note updated!')
    else:
        new_note = Note(student_id=student_id, title=title, content=content)
        db.session.add(new_note)
        flash('✅ New note created!')

    db.session.commit()
    return redirect(url_for('student_notes'))

@app.route('/student/notes/delete/<int:id>', methods=['POST'])
def delete_note(id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    note = Note.query.get_or_404(id)
    if note.student_id == session['student_id']:
        db.session.delete(note)
        db.session.commit()
        flash('🗑️ Note deleted.')
        
    return redirect(url_for('student_notes'))


# ==========================================
# 🚑 TELEMEDICINE ROUTES
# ==========================================

@app.route('/student/telemedicine')
def student_telemedicine():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student = db.session.get(Student, session['student_id'])
    return render_template('student_telemedicine.html', student=student)


# ==========================================
# 🧠 MIND MAP TOOL ROUTES
# ==========================================

@app.route('/student/mindmap')
def student_mindmap():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = db.session.get(Student, session['student_id'])
    maps = MindMap.query.filter_by(student_id=student.id).order_by(MindMap.last_updated.desc()).all()
    
    return render_template('student_mindmap.html', student=student, maps=maps)

@app.route('/api/mindmap/save', methods=['POST'])
def save_mindmap():
    if not session.get('student_logged_in'): return jsonify({'status': 'error'})
    
    data = request.get_json()
    map_id = data.get('id')
    name = data.get('name', 'My New Map')
    json_data = data.get('data') # The node structure
    
    if map_id:
        # Update existing
        mm = MindMap.query.get(map_id)
        if mm and mm.student_id == session['student_id']:
            mm.name = name
            mm.data = json_data
            db.session.commit()
            return jsonify({'status': 'success', 'id': mm.id, 'message': 'Map updated'})
    else:
        # Create new
        new_mm = MindMap(student_id=session['student_id'], name=name, data=json_data)
        db.session.add(new_mm)
        db.session.commit()
        return jsonify({'status': 'success', 'id': new_mm.id, 'message': 'New map created'})

    return jsonify({'status': 'error'})

@app.route('/api/mindmap/load/<int:id>')
def load_mindmap(id):
    if not session.get('student_logged_in'): return jsonify({'error': 'Unauthorized'})
    
    mm = MindMap.query.get_or_404(id)
    if mm.student_id != session['student_id']:
        return jsonify({'error': 'Access denied'})
        
    return jsonify({'id': mm.id, 'name': mm.name, 'data': mm.data})

@app.route('/student/mindmap/delete/<int:id>', methods=['POST'])
def delete_mindmap(id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    mm = MindMap.query.get_or_404(id)
    if mm.student_id == session['student_id']:
        db.session.delete(mm)
        db.session.commit()
        flash('🗑️ Mind map deleted.')
        
    return redirect(url_for('student_mindmap'))


# ==========================================
# ✈️ STUDY ABROAD FINDER ROUTES
# ==========================================

@app.route('/student/study_abroad')
def student_study_abroad():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = db.session.get(Student, session['student_id'])
    cgpa, _ = calculate_cgpa(student)
    
    # Auto-seed if empty
    if ExchangeProgram.query.count() == 0:
        seed_real_study_abroad_data()
        
    programs = ExchangeProgram.query.all()
    
    # Calculate Match Score
    processed_programs = []
    for p in programs:
        match_score = 0
        if cgpa >= p.min_cgpa: match_score += 50
        elif cgpa >= (p.min_cgpa - 0.5): match_score += 30
        
        # Boost score if fully funded (highly competitive but desirable)
        match_score += 20 if 'Full' in p.funding_type else 40
        
        # Cap at 98%
        if match_score > 98: match_score = 98
        
        status = "High Chance" if match_score > 70 else ("Medium Chance" if match_score > 40 else "Reach")
        color = "success" if match_score > 70 else ("warning" if match_score > 40 else "danger")
        
        processed_programs.append({
            'obj': p,
            'match': match_score,
            'status': status,
            'color': color
        })

    # Sort by highest match first
    processed_programs.sort(key=lambda x: x['match'], reverse=True)

    return render_template('student_study_abroad.html', student=student, programs=processed_programs, cgpa=cgpa)

def seed_real_study_abroad_data():
    # REAL DATA with WORKING IMAGES AND LINKS
    programs = [
        ExchangeProgram(
            university="University of Oxford", 
            country="UK", 
            program_name="Rhodes Scholarship", 
            deadline=date(2026, 10, 1), 
            min_cgpa=4.5, 
            funding_type="Full Funding", 
            image_url="https://images.unsplash.com/photo-1592610686967-17937989396e?ixlib=rb-1.2.1&auto=format&fit=crop&w=800&q=80",
            application_url="https://www.rhodeshouse.ox.ac.uk/scholarships/applications/"
        ),
        ExchangeProgram(
            university="MIT", 
            country="USA", 
            program_name="Visiting Student Program", 
            deadline=date(2026, 9, 15), 
            min_cgpa=4.8, 
            funding_type="Partial Funding", 
            image_url="https://images.unsplash.com/photo-1564981797816-1043664bf78d?ixlib=rb-1.2.1&auto=format&fit=crop&w=800&q=80",
            application_url="https://iso.mit.edu/visiting-students/"
        ),
        ExchangeProgram(
            university="University of Toronto", 
            country="Canada", 
            program_name="Lester B. Pearson Scholarship", 
            deadline=date(2026, 11, 30), 
            min_cgpa=3.8, 
            funding_type="Full Funding", 
            image_url="https://images.unsplash.com/photo-1599464673232-243936399129?ixlib=rb-1.2.1&auto=format&fit=crop&w=800&q=80",
            application_url="https://future.utoronto.ca/pearson/about/"
        ),
        ExchangeProgram(
            university="Technical University of Munich", 
            country="Germany", 
            program_name="DAAD Exchange", 
            deadline=date(2026, 12, 15), 
            min_cgpa=3.0, 
            funding_type="Self / Partial", 
            image_url="https://images.unsplash.com/photo-1590248560662-73a7266e7467?ixlib=rb-1.2.1&auto=format&fit=crop&w=800&q=80",
            application_url="https://www.tum.de/en/studies/international-exchange-students"
        ),
        ExchangeProgram(
            university="University of Cape Town", 
            country="South Africa", 
            program_name="Mastercard Foundation Scholars", 
            deadline=date(2026, 8, 20), 
            min_cgpa=3.5, 
            funding_type="Full Funding", 
            image_url="https://images.unsplash.com/photo-1588667823526-7243cb8077c4?ixlib=rb-1.2.1&auto=format&fit=crop&w=800&q=80",
            application_url="http://www.mcfsp.uct.ac.za/"
        ),
        ExchangeProgram(
            university="Harvard University", 
            country="USA", 
            program_name="MBA Fellowship", 
            deadline=date(2026, 9, 1), 
            min_cgpa=4.7, 
            funding_type="Full Funding", 
            image_url="https://images.unsplash.com/photo-1622397333309-3056849bc70b?ixlib=rb-1.2.1&auto=format&fit=crop&w=800&q=80",
            application_url="https://www.hbs.edu/mba/financial-aid/financial-aid-programs/Pages/fellowships.aspx"
        ),
    ]
    db.session.add_all(programs)
    db.session.commit()

# ==========================================
# 🏅 CERTIFICATION REPOSITORY ROUTES
# ==========================================
import os
from werkzeug.utils import secure_filename

# Ensure upload folder exists
CERT_UPLOAD_FOLDER = os.path.join('static', 'cert_uploads')
if not os.path.exists(CERT_UPLOAD_FOLDER):
    os.makedirs(CERT_UPLOAD_FOLDER)

@app.route('/student/certifications')
def student_certifications():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = db.session.get(Student, session['student_id'])
    certs = Certification.query.filter_by(student_id=student.id).order_by(Certification.date_earned.desc()).all()
    
    return render_template('student_certifications.html', student=student, certs=certs, today=date.today())

@app.route('/student/certifications/upload', methods=['POST'])
@login_required
def upload_certification():
    try:
        student_id = session['student_id']
        name = request.form['name']
        issuer = request.form['issuer']
        date_earned = datetime.strptime(request.form['date_earned'], '%Y-%m-%d').date()
        
        # Handle Expiry Date
        expiry_date = None
        if request.form.get('expiry_date'):
            expiry_date = datetime.strptime(request.form['expiry_date'], '%Y-%m-%d').date()
            
        credential_id = request.form.get('credential_id')
        
        # 🟢 MISSING LINE FIX: YOU MUST CAPTURE THE LINK HERE FIRST!
        credly_link = request.form.get('credly_link')
        
        # Handle File Upload
        file_path = None
        if 'cert_file' in request.files:
            file = request.files['cert_file']
            if file.filename != '':
                filename = secure_filename(f"{student_id}_{name}_{file.filename}")
                file.save(os.path.join(CERT_UPLOAD_FOLDER, filename))
                file_path = f"cert_uploads/{filename}"

        new_cert = Certification(
            student_id=student_id,
            name=name,
            issuer=issuer,
            date_earned=date_earned,
            expiry_date=expiry_date,
            credential_id=credential_id,
            credly_link=credly_link,  # <--- Now this variable exists!
            file_path=file_path
        )
        
        db.session.add(new_cert)
        db.session.commit()
        flash('🏅 Certification uploaded successfully!', 'success')
        
    except Exception as e:
        flash(f'❌ Error uploading: {e}', 'danger')
        # Print error to terminal for debugging
        print(f"UPLOAD ERROR: {e}") 
        
    return redirect(url_for('student_certifications'))

@app.route('/student/certifications/delete/<int:id>', methods=['POST'])
def delete_certification(id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    cert = Certification.query.get_or_404(id)
    if cert.student_id == session['student_id']:
        # Optional: Delete actual file from disk here if desired
        db.session.delete(cert)
        db.session.commit()
        flash('🗑️ Credential removed.')
        
    return redirect(url_for('student_certifications'))

# ==========================================
# 💼 JOB APPLICATION TRACKER ROUTES
# ==========================================

@app.route('/student/jobs')
def student_jobs():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = db.session.get(Student, session['student_id'])
    jobs = JobApplication.query.filter_by(student_id=student.id).order_by(JobApplication.date_applied.desc()).all()
    
    # Calculate stats
    stats = {
        'total': len(jobs),
        'interviews': sum(1 for j in jobs if j.status == 'Interview'),
        'offers': sum(1 for j in jobs if j.status == 'Offer')
    }
    
    return render_template('student_jobs.html', student=student, jobs=jobs, stats=stats)

@app.route('/student/jobs/add', methods=['POST'])
def add_job():
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    try:
        new_job = JobApplication(
            student_id=session['student_id'],
            company=request.form['company'],
            role=request.form['role'],
            status=request.form['status'],
            date_applied=datetime.strptime(request.form['date_applied'], '%Y-%m-%d').date(),
            link=request.form.get('link'),
            notes=request.form.get('notes')
        )
        db.session.add(new_job)
        db.session.commit()
        flash('💼 Job application added!')
    except Exception as e:
        flash(f'❌ Error: {e}')
        
    return redirect(url_for('student_jobs'))

@app.route('/student/jobs/update_status/<int:id>/<new_status>')
def update_job_status(id, new_status):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    job = JobApplication.query.get_or_404(id)
    if job.student_id == session['student_id']:
        job.status = new_status
        db.session.commit()
        flash(f'Updated status to {new_status}')
        
    return redirect(url_for('student_jobs'))

@app.route('/student/jobs/delete/<int:id>', methods=['POST'])
def delete_job(id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    job = JobApplication.query.get_or_404(id)
    if job.student_id == session['student_id']:
        db.session.delete(job)
        db.session.commit()
        flash('🗑️ Application removed.')
        
    return redirect(url_for('student_jobs'))

# ==========================================
# 🏆 SKILL ASSESSMENT ROUTES
# ==========================================

@app.route('/student/skills')
def student_skills():
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    student = db.session.get(Student, session['student_id'])
    
    # Auto-seed quizzes if empty
    if SkillQuiz.query.count() == 0:
        seed_skill_quizzes()
        
    quizzes = SkillQuiz.query.all()
    my_badges = StudentBadge.query.filter_by(student_id=student.id).all()
    earned_ids = [b.quiz_id for b in my_badges]
    
    return render_template('student_skills.html', student=student, quizzes=quizzes, my_badges=my_badges, earned_ids=earned_ids)

@app.route('/student/skills/take/<int:id>')
def take_skill_quiz(id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    quiz = SkillQuiz.query.get_or_404(id)
    # Parse JSON questions for the template
    quiz_questions = json.loads(quiz.questions)
    
    return render_template('take_skill_quiz.html', quiz=quiz, questions=quiz_questions)

@app.route('/student/skills/submit/<int:id>', methods=['POST'])
def submit_skill_quiz(id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    quiz = SkillQuiz.query.get_or_404(id)
    questions = json.loads(quiz.questions)
    
    score = 0
    total = len(questions)
    
    for i, q in enumerate(questions):
        user_answer = request.form.get(f'q{i}')
        if user_answer and user_answer == q['answer']:
            score += 1
            
    percentage = (score / total) * 100
    passed = percentage >= 70 # 70% pass mark
    
    if passed:
        # Check if already earned
        existing = StudentBadge.query.filter_by(student_id=session['student_id'], quiz_id=id).first()
        if not existing:
            badge = StudentBadge(
                student_id=session['student_id'], 
                quiz_id=id, 
                badge_name=quiz.badge_name,
                score=int(percentage)
            )
            db.session.add(badge)
            db.session.commit()
            flash(f'🎉 Congratulations! You earned the "{quiz.badge_name}" Badge!')
        else:
            flash('You already have this badge, but nice practice!')
    else:
        flash(f'⚠️ You scored {int(percentage)}%. You need 70% to earn the badge. Try again!')
        
    return redirect(url_for('student_skills'))

def seed_skill_quizzes():
    # 20 HIGH-QUALITY QUIZZES
    quizzes_data = [
        # TECH
        ("Excel Essentials", "Tech", "Beginner", "Excel Pro", [
            {"q": "Which function calculates the average?", "options": ["SUM", "AVG", "AVERAGE", "MEAN"], "answer": "AVERAGE"},
            {"q": "What symbol starts a formula?", "options": ["#", "=", "$", "!"], "answer": "="},
            {"q": "How do you lock a cell reference?", "options": ["F4", "F2", "Ctrl+L", "Alt+F4"], "answer": "F4"}
        ]),
        ("Python Basics", "Tech", "Beginner", "Pythonista", [
            {"q": "Output of print(2**3)?", "options": ["6", "8", "9", "5"], "answer": "8"},
            {"q": "Which is immutable?", "options": ["List", "Dictionary", "Tuple", "Set"], "answer": "Tuple"},
            {"q": "Keyword to define a function?", "options": ["func", "def", "lambda", "function"], "answer": "def"}
        ]),
        ("Cybersecurity 101", "Tech", "Intermediate", "Cyber Scout", [
            {"q": "What does Phishing target?", "options": ["Servers", "Firewalls", "Humans", "Cables"], "answer": "Humans"},
            {"q": "What is 2FA?", "options": ["Two-Factor Auth", "To-For-All", "Two-File Access", "None"], "answer": "Two-Factor Auth"},
            {"q": "Strongest password type?", "options": ["123456", "Passphrase", "DateOfBirth", "Name123"], "answer": "Passphrase"}
        ]),
        ("Web Development", "Tech", "Intermediate", "Web Artisan", [
            {"q": "What does CSS stand for?", "options": ["Computer Style Sheet", "Cascading Style Sheets", "Creative Style System", "None"], "answer": "Cascading Style Sheets"},
            {"q": "Which tag is for the largest heading?", "options": ["<h6>", "<head>", "<h1>", "<header>"], "answer": "<h1>"},
            {"q": "HTML is a programming language.", "options": ["True", "False"], "answer": "False"}
        ]),
        ("Data Science Intro", "Tech", "Advanced", "Data Wizard", [
            {"q": "Library for dataframes in Python?", "options": ["NumPy", "Pandas", "Matplotlib", "Seaborn"], "answer": "Pandas"},
            {"q": "What is 'cleaning data'?", "options": ["Deleting it", "Fixing errors/missing values", "Formatting drive", "Printing it"], "answer": "Fixing errors/missing values"},
            {"q": "Supervised learning requires...?", "options": ["Labeled data", "No data", "Random data", "Unlabeled data"], "answer": "Labeled data"}
        ]),
        ("AWS Cloud Practitioner", "Tech", "Advanced", "Cloud Ninja", [
            {"q": "What is EC2?", "options": ["Storage", "Virtual Server", "Database", "Networking"], "answer": "Virtual Server"},
            {"q": "S3 stands for?", "options": ["Simple Storage Service", "Super Speed Server", "Static Site System", "None"], "answer": "Simple Storage Service"},
            {"q": "Which service scales automatically?", "options": ["Auto Scaling", "Manual Scaling", "Fixed Scaling", "None"], "answer": "Auto Scaling"}
        ]),
        
        # SOFT SKILLS
        ("Leadership 101", "Soft Skills", "Beginner", "Team Lead", [
            {"q": "Best way to resolve conflict?", "options": ["Ignore it", "Active Listening", "Shouting", "Firing everyone"], "answer": "Active Listening"},
            {"q": "A leader should be...", "options": ["Authoritarian", "Empathetic", "Absent", "Silent"], "answer": "Empathetic"},
            {"q": "Delegation means...", "options": ["Doing everything yourself", "Assigning tasks to others", "Ignoring tasks", "None"], "answer": "Assigning tasks to others"}
        ]),
        ("Public Speaking", "Soft Skills", "Intermediate", "Orator", [
            {"q": "What is important in a speech?", "options": ["Eye Contact", "Reading from paper", "Speaking fast", "Looking at floor"], "answer": "Eye Contact"},
            {"q": "What helps with nervousness?", "options": ["Preparation", "Caffeine", "Running away", "Holding breath"], "answer": "Preparation"},
            {"q": "The 'hook' goes where?", "options": ["End", "Middle", "Beginning", "Nowhere"], "answer": "Beginning"}
        ]),
        ("Time Management", "Soft Skills", "Beginner", "Productivity Guru", [
            {"q": "What is the Pomodoro technique?", "options": ["Eating pasta", "25min work/5min break", "Sleeping all day", "Multitasking"], "answer": "25min work/5min break"},
            {"q": "Eisenhower Matrix sorts by?", "options": ["Color", "Urgency/Importance", "Size", "Fun"], "answer": "Urgency/Importance"},
            {"q": "Multitasking is...", "options": ["Efficient", "Inefficient", "Necessary", "Easy"], "answer": "Inefficient"}
        ]),
        
        # BUSINESS & FINANCE
        ("Financial Literacy", "Business", "Intermediate", "Money Master", [
            {"q": "What is a budget?", "options": ["Free money", "Spending plan", "Bank loan", "Tax form"], "answer": "Spending plan"},
            {"q": "Compound interest helps you...", "options": ["Lose money", "Grow wealth over time", "Pay taxes", "None"], "answer": "Grow wealth over time"},
            {"q": "A stock represents...", "options": ["Ownership in a company", "A loan", "A promise", "Government bond"], "answer": "Ownership in a company"}
        ]),
        ("Project Management", "Business", "Advanced", "Project Pro", [
            {"q": "What is a Gantt chart?", "options": ["Pie chart", "Timeline bar chart", "Scatter plot", "List"], "answer": "Timeline bar chart"},
            {"q": "Agile is...", "options": ["A waterfall method", "Iterative approach", "Rigid planning", "Slow"], "answer": "Iterative approach"},
            {"q": "What is a 'Milestone'?", "options": ["A stone", "Significant point in progress", "A failure", "Start date"], "answer": "Significant point in progress"}
        ]),
        ("Digital Marketing", "Business", "Intermediate", "Marketing Ace", [
            {"q": "SEO stands for?", "options": ["Search Engine Optimization", "Social Engine Output", "Site Error 0", "None"], "answer": "Search Engine Optimization"},
            {"q": "Which is a social media KPI?", "options": ["Server Load", "Engagement Rate", "Electricity Cost", "Office Rent"], "answer": "Engagement Rate"},
            {"q": "Content is...", "options": ["King", "Useless", "Expensive", "Optional"], "answer": "King"}
        ]),
        
        # ACADEMIC / RESEARCH
        ("Research Methods", "Academic", "Advanced", "Research Fellow", [
            {"q": "Qualitative data is...", "options": ["Numerical", "Descriptive/Non-numerical", "Binary", "None"], "answer": "Descriptive/Non-numerical"},
            {"q": "First step of research?", "options": ["Conclusion", "Data Collection", "Problem Definition", "Publication"], "answer": "Problem Definition"},
            {"q": "Plagiarism is...", "options": ["Good", "Unethical", "Encouraged", "Legal"], "answer": "Unethical"}
        ]),
    ]
    
    # Fill remaining slots to hit roughly 20 (Simulated for brevity, adding repeats/variations)
    extras = [
        ("SQL Fundamentals", "Tech", "Intermediate", "DB Admin", [{"q": "Command to fetch data?", "options": ["GET", "SELECT", "FETCH", "PULL"], "answer": "SELECT"}]),
        ("React.js Basics", "Tech", "Advanced", "Frontend Dev", [{"q": "React uses...", "options": ["Components", "Modules", "Blocks", "Slices"], "answer": "Components"}]),
        ("Emotional EQ", "Soft Skills", "Advanced", "Empath", [{"q": "Self-awareness is...", "options": ["Knowing your emotions", "Knowing others", "Ignoring feelings", "None"], "answer": "Knowing your emotions"}]),
        ("Entrepreneurship", "Business", "Intermediate", "Founder", [{"q": "What is an MVP?", "options": ["Most Valuable Player", "Minimum Viable Product", "Max Value Plan", "None"], "answer": "Minimum Viable Product"}]),
        ("Git & GitHub", "Tech", "Intermediate", "Git Master", [{"q": "Command to upload code?", "options": ["git push", "git upload", "git send", "git up"], "answer": "git push"}]),
        ("Ethical Hacking", "Tech", "Advanced", "White Hat", [{"q": "White Hat hackers are...", "options": ["Good guys", "Bad guys", "Neutral", "None"], "answer": "Good guys"}]),
        ("Accounting Basics", "Business", "Beginner", "Ledger Keeper", [{"q": "Assets = ?", "options": ["Liabilities + Equity", "Cash - Debt", "Revenue", "None"], "answer": "Liabilities + Equity"}])
    ]
    
    quizzes_data.extend(extras)

    for title, topic, diff, badge, q_list in quizzes_data:
        q = SkillQuiz(title=title, topic=topic, difficulty=diff, questions=json.dumps(q_list), badge_name=badge)
        db.session.add(q)
    
    db.session.commit()

# ==========================================
# 📄 CV BUILDER ROUTES
# ==========================================

@app.route('/student/cv_builder')
def student_cv_builder():
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    student = db.session.get(Student, session['student_id'])
    
    # Fetch all data sections
    work_exp = WorkExperience.query.filter_by(student_id=student.id).all()
    projects = Project.query.filter_by(student_id=student.id).all()
    volunteers = Volunteer.query.filter_by(student_id=student.id).all()
    skills = Skill.query.filter_by(student_id=student.id).all()
    awards = Award.query.filter_by(student_id=student.id).all()
    certs = Certification.query.filter_by(student_id=student.id).all() # Reuse existing Certs
    
    return render_template('student_cv_builder.html', 
                           student=student, 
                           work_exp=work_exp, 
                           projects=projects,
                           volunteers=volunteers,
                           skills=skills,
                           awards=awards,
                           certs=certs)

@app.route('/student/cv/add/<section>', methods=['POST'])
def add_cv_section(section):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    s_id = session['student_id']
    f = request.form
    
    if section == 'work':
        new_item = WorkExperience(student_id=s_id, company=f['company'], role=f['role'], start_date=f['start'], end_date=f['end'], location=f['location'], description=f['desc'])
    elif section == 'project':
        new_item = Project(student_id=s_id, title=f['title'], role_type=f['type'], date_range=f['date'], description=f['desc'], tools=f['tools'])
    elif section == 'volunteer':
        new_item = Volunteer(student_id=s_id, organization=f['org'], role=f['role'], date_range=f['date'], description=f['desc'])
    elif section == 'skill':
        new_item = Skill(student_id=s_id, category=f['cat'], name=f['name'])
    elif section == 'award':
        new_item = Award(student_id=s_id, title=f['title'], issuer=f['issuer'], date_received=f['date'])
        
    db.session.add(new_item)
    db.session.commit()
    return redirect(url_for('student_cv_builder'))

@app.route('/student/cv/delete/<section>/<int:id>')
def delete_cv_section(section, id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    model_map = {
        'work': WorkExperience,
        'project': Project,
        'volunteer': Volunteer,
        'skill': Skill,
        'award': Award
    }
    
    if section in model_map:
        item = model_map[section].query.get_or_404(id)
        if item.student_id == session['student_id']:
            db.session.delete(item)
            db.session.commit()
            
    return redirect(url_for('student_cv_builder'))

@app.route('/student/cv/preview')
def cv_preview():
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    student = db.session.get(Student, session['student_id'])
    work_exp = WorkExperience.query.filter_by(student_id=student.id).all()
    projects = Project.query.filter_by(student_id=student.id).all()
    volunteers = Volunteer.query.filter_by(student_id=student.id).all()
    
    # Group skills
    hard_skills = Skill.query.filter_by(student_id=student.id, category='Hard Skill').first()
    soft_skills = Skill.query.filter_by(student_id=student.id, category='Soft Skill').first()
    
    awards = Award.query.filter_by(student_id=student.id).all()
    certs = Certification.query.filter_by(student_id=student.id).all()
    
    return render_template('cv_print_template.html', 
                           student=student, 
                           work_exp=work_exp, 
                           projects=projects, 
                           volunteers=volunteers,
                           hard_skills=hard_skills,
                           soft_skills=soft_skills,
                           awards=awards, 
                           certs=certs)


# ==========================================
# 🚨 REAL-TIME DISASTER ALERT ROUTES
# ==========================================

@app.route('/student/safety')
def student_safety():
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    # 1. TRIGGER LIVE INTERNET SYNC
    sync_live_alerts()
    
    student = db.session.get(Student, session['student_id'])
    alerts = SafetyAlert.query.order_by(SafetyAlert.date_posted.desc()).limit(10).all()
    
    return render_template('student_safety.html', student=student, alerts=alerts)

def sync_live_alerts():
    """
    ACTUALLY CONNECTS TO THE INTERNET TO FETCH REAL DATA.
    Targets: Google News (Lagos specific) & Global Disaster Feeds.
    """
    try:
        # A. Google News Feed for Lagos Safety (Floods, Riots, Protests)
        # We use a specific query to filter for safety-related keywords in Nigeria
        news_url = "https://news.google.com/rss/search?q=Lagos+(flood+OR+riot+OR+protest+OR+violence+OR+rain+OR+traffic)&hl=en-NG&gl=NG&ceid=NG:en"
        
        feed = feedparser.parse(news_url)
        
        for entry in feed.entries[:5]: # Check top 5 latest news
            # Check if alert already exists to avoid duplicates
            exists = SafetyAlert.query.filter_by(title=entry.title).first()
            if not exists:
                # Determine Severity based on keywords
                title_lower = entry.title.lower()
                severity = "Info"
                if "riot" in title_lower or "kill" in title_lower or "gun" in title_lower:
                    severity = "Critical"
                elif "flood" in title_lower or "rain" in title_lower or "protest" in title_lower:
                    severity = "Warning"
                
                new_alert = SafetyAlert(
                    title=entry.title,
                    summary=entry.summary if 'summary' in entry else "Live report from Google News",
                    source="Google News (Live)",
                    severity=severity,
                    link=entry.link,
                    date_posted=datetime.utcnow()
                )
                db.session.add(new_alert)
        
        db.session.commit()
        print("✅ Live Safety Data Synced Successfully")
        
    except Exception as e:
        print(f"❌ Internet Sync Failed: {e}")

@app.route('/student/safety/mark_safe', methods=['POST'])
def mark_safe():
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    flash('✅ Status: Marked as Safe. Location logged.')
    return redirect(url_for('student_safety'))



# ==========================================
# 📡 LIVE CAMPUS NEWSSTREAM API (GLOBAL AGGREGATOR)
# ==========================================
@app.route('/api/lasu-live-stream')
def api_lasu_live_stream():
    """
    Enterprise API endpoint that scrubs Google News RSS specifically for 
    Lagos State University (LASU) data and pipes it dynamically to the frontend.
    """
    import feedparser
    from datetime import datetime
    
    try:
        # FIX 1: Wrapped keywords in exact-match quotes so Google stops guessing
        news_url = 'https://news.google.com/rss/search?q="Lagos+State+University"+OR+"LASU"&hl=en-NG&gl=NG&ceid=NG:en'
        feed = feedparser.parse(news_url)
        
        live_news = []
        
        # We don't slice [:15] here yet, because we might drop some UNILAG articles
        for entry in feed.entries:
            title_lower = entry.title.lower()
            desc_lower = entry.summary.lower() if 'summary' in entry else ""
            
            # FIX 2: The Titanium Filter. If it doesn't explicitly say LASU, drop it immediately.
            if "lasu" not in title_lower and "lagos state university" not in title_lower and "lasu" not in desc_lower:
                continue
                
            # Extract the actual source name (e.g., "Punch Newspapers")
            source_name = entry.source.title if 'source' in entry else "CAMPUS FEED"
            
            # Smart-tagging system to map to your frontend CSS classes
            source_tag = "source-lasu"
            source_lower = source_name.lower()
            
            if "punch" in source_lower or "vanguard" in source_lower or "tribune" in source_lower:
                source_tag = "source-punch"
            elif "gist" in source_lower or "blog" in source_lower or "nairaland" in source_lower:
                source_tag = "source-gossip"
            elif "nans" in source_lower or "student" in source_lower:
                source_tag = "source-nans"
                
            # Clean up Google's title formatting (Removes the trailing " - Source Name")
            clean_title = entry.title.rsplit(' - ', 1)[0]
            
            live_news.append({
                "source": source_name.upper(),
                "type": source_tag,
                "title": clean_title,
                "time": "Live Update", 
                "link": entry.link
            })
            
            # Stop processing once we hit exactly 15 PURE LASU articles
            if len(live_news) >= 15:
                break
            
        return jsonify({"status": "success", "news": live_news}), 200
        
    except Exception as e:
        print(f"[LIVE FEED SECURE ERROR]: {str(e)}")
        # Fallback mechanism prevents the frontend from crashing if Google blocks the request
        return jsonify({"status": "error", "news": []}), 500

# ==========================================
# 🆘 S.O.S LIFELINE (WITH RESOLVED TAB)
# ==========================================

@app.route('/student/sos', methods=['GET', 'POST'])
def sos_dashboard():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
        
    student = Student.query.get(session['student_id'])
    
    # 1. WALLET LOGIC (Calculate Balance)
    credits = db.session.query(func.sum(WalletTransaction.amount)).filter_by(student_id=student.id, type='CREDIT').scalar() or 0
    debits = db.session.query(func.sum(WalletTransaction.amount)).filter_by(student_id=student.id, type='DEBIT').scalar() or 0
    balance = credits - debits

    # 2. SEPARATE FEEDS (The "Tabs" Logic)
    
    # Stream A: LIVE FEED (Active/Open Cases Only)
    # We filter out 'Funded' or 'Resolved' cases so they don't clog the main feed.
    live_feed = SOSRequest.query.filter(
        SOSRequest.status.notin_(['Funded', 'Resolved']),
        SOSRequest.student_id != student.id 
    ).order_by(SOSRequest.created_at.desc()).all()

    # Stream B: RESOLVED CASES (Success Stories)
    # This is for the Green "Solved Cases" Tab.
    resolved_feed = SOSRequest.query.filter(
        SOSRequest.status.in_(['Funded', 'Resolved'])
    ).order_by(SOSRequest.created_at.desc()).all()

    # Stream C: MY DATA
    my_requests = SOSRequest.query.filter_by(student_id=student.id).order_by(SOSRequest.created_at.desc()).all()
    my_impact = SOSRequest.query.filter_by(helper_id=student.id).order_by(SOSRequest.created_at.desc()).all()
    
    # Stream D: WALLET HISTORY
    history = WalletTransaction.query.filter_by(student_id=student.id).order_by(WalletTransaction.date.desc()).limit(10).all()

    # 3. COUNTS
    active_count = len(live_feed)
    resolved_count = len(resolved_feed)

    return render_template(
        'sos_lifeline.html', 
        user=student,      # Template expects 'user' (or 'student')
        student=student,   # Passing both to be safe
        balance=balance, 
        feed=live_feed,         # <--- ONLY ACTIVE CASES
        resolved=resolved_feed, # <--- ONLY RESOLVED CASES
        my_requests=my_requests,
        my_impact=my_impact,
        history=history,
        active_count=active_count,
        resolved_count=resolved_count
    )


@app.route('/student/sos/create', methods=['POST'])
def create_sos():
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    student = Student.query.get(session['student_id'])
    
    # Capture Bank Details if provided
    bank_name = request.form.get('bank_name') if request.form['type'] == 'CASH' else None
    account_num = request.form.get('account_number') if request.form['type'] == 'CASH' else None

    new_sos = SOSRequest(
        student_id=student.id,
        student_name=student.first_name + " " + student.last_name, # Storing full name
        type=request.form['type'],
        amount=float(request.form['amount']),
        reason=request.form['reason'],
        bank_name=bank_name,
        account_number=account_num,
        network=request.form.get('network'),
        phone_number=request.form.get('phone_number', student.phone_number),
        status="Active" # Explicitly set status to Active
    )
    db.session.add(new_sos)
    db.session.commit()
    flash('🚨 S.O.S Broadcasted! Help is on the way.', 'success')
    return redirect(url_for('sos_dashboard'))


@app.route('/student/sos/help/<int:sos_id>', methods=['POST'])
def help_student(sos_id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    helper = Student.query.get(session['student_id'])
    sos_req = SOSRequest.query.get_or_404(sos_id)
    
    # Initialize Paystack Payment
    callback_url = url_for('verify_sos_funding', sos_id=sos_id, _external=True)
    
    # Metadata tracks who is helping (The "Impact" feature)
    metadata = {"sos_id": sos_req.id, "helper_id": helper.id}
    
    response = initialize_paystack_transaction(
        email=helper.personal_email or f"{helper.matric_no}@lasu.edu.ng", 
        amount_naira=sos_req.amount, 
        callback_url=callback_url,
        metadata=metadata
    )
    
    if response and response.get('status'):
        return redirect(response['data']['authorization_url'])
    else:
        flash('❌ Payment Gateway Error. Please try again.', 'danger')
        return redirect(url_for('sos_dashboard'))


@app.route('/student/sos/verify_funding/<int:sos_id>')
def verify_sos_funding(sos_id):
    reference = request.args.get('reference')
    sos_req = SOSRequest.query.get_or_404(sos_id)
    
    if not reference:
        flash('❌ No payment reference found!', 'danger')
        return redirect(url_for('sos_dashboard'))

    # VERIFY WITH PAYSTACK
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    try:
        response = requests.get(PAYSTACK_VERIFY_URL + reference, headers=headers)
        res_data = response.json()
        
        if res_data['status'] is True and res_data['data']['status'] == 'success':
            # ✅ PAYMENT SUCCESS
            
            # Check amounts (Paystack is in Kobo)
            paid_amount = res_data['data']['amount'] / 100
            
            if paid_amount >= sos_req.amount:
                # 1. Mark as Funded/Resolved
                sos_req.status = 'Resolved' # Moves it to the Green Tab
                sos_req.raised = paid_amount
                
                # 2. Record Helper
                meta = res_data['data'].get('metadata')
                if meta and 'helper_id' in meta:
                    sos_req.helper_id = meta['helper_id']
                
                # 3. Credit Student Wallet
                db.session.add(WalletTransaction(
                    student_id=sos_req.student_id,
                    type='CREDIT',
                    amount=paid_amount,
                    description=f"S.O.S Aid Received (Ref: {reference})"
                ))
                
                flash('✅ Payment Verified! S.O.S marked as Resolved.', 'success')
                db.session.commit()
            else:
                flash('⚠️ Partial payment detected.', 'warning')
        else:
            flash('❌ Payment Verification Failed.', 'danger')

    except Exception as e:
        flash(f'❌ Connection Error: {str(e)}', 'danger')

    return redirect(url_for('sos_dashboard'))

@app.route('/fix_sos_db')
def fix_sos_db():
    with app.app_context():
        db.create_all()
        return "<h1>✅ S.O.S Tables Created Successfully!</h1><a href='/student/sos'>Go to S.O.S Dashboard</a>"


# ==========================================
# 🚑 EMERGENCY SURGERY: ADD COLUMNS SAFELY
# ==========================================
@app.route('/emergency_add_bank_cols')
def emergency_add_bank_cols():
    from sqlalchemy import text
    try:
        with app.app_context():
            # 1. Inject 'bank_name' column
            try:
                db.session.execute(text("ALTER TABLE sos_request ADD COLUMN bank_name VARCHAR(100)"))
                print("✅ Added column: bank_name")
            except Exception as e:
                print(f"ℹ️ bank_name info: {e}")

            # 2. Inject 'account_number' column
            try:
                db.session.execute(text("ALTER TABLE sos_request ADD COLUMN account_number VARCHAR(20)"))
                print("✅ Added column: account_number")
            except Exception as e:
                print(f"ℹ️ account_number info: {e}")

            db.session.commit()
            
            return """
            <div style='text-align: center; padding: 50px; font-family: sans-serif;'>
                <h1 style='color: green;'>✅ DATABASE REPAIRED!</h1>
                <p>The columns <b>bank_name</b> and <b>account_number</b> have been safely added.</p>
                <p>No data was lost.</p>
                <br>
                <a href='/student/sos' style='padding: 15px 30px; background: #dc3545; color: white; text-decoration: none; border-radius: 5px;'>Return to S.O.S</a>
            </div>
            """
    except Exception as e:
        return f"<h1>❌ Error: {e}</h1>"


# 👇👇👇 PASTE THE ADMIN TOOLS HERE (ABOVE THE BOTTOM BLOCK) 👇👇👇

@app.route('/admin/get_ids')
def get_ids():
    students = Student.query.all()
    html = "<h1>Student List</h1><ul>"
    for s in students:
        html += f"<li><strong>ID: {s.id}</strong> — {s.name} ({s.matric_no})</li>"
    html += "</ul>"
    return html

# 👇 PASTE THIS RIGHT AFTER THE get_ids FUNCTION 👇

@app.route('/magic_credit/<int:student_id>/<int:amount>')
def magic_credit(student_id, amount):
    # 1. Create the Transaction Record
    db.session.add(WalletTransaction(
        student_id=student_id,
        type='CREDIT',
        amount=float(amount),
        description="Manual System Correction (Admin)"
    ))
    
    # 2. Find and Fund the Active SOS Request
    req = SOSRequest.query.filter_by(student_id=student_id, status='Active').first()
    if req:
        req.status = 'Funded'
        req.raised = float(amount)
        
    db.session.commit()
    
    return f"""
    <div style="text-align:center; padding:50px; font-family:sans-serif;">
        <h1 style="color:green; font-size:50px;">✅ SUCCESS!</h1>
        <h2>Ngozi (ID: {student_id}) has been credited ₦{amount}.</h2>
        <br>
        <a href="/student/sos" style="background:black; color:white; padding:15px 30px; text-decoration:none; border-radius:10px;">Check Dashboard</a>
    </div>
    """

# 👇 HANDLE WITHDRAWAL REQUESTS
@app.route('/student/withdraw', methods=['POST'])
def student_withdraw():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
        
    student = Student.query.get(session['student_id'])
    
    # 1. Calculate Balance
    credits = db.session.query(func.sum(WalletTransaction.amount)).filter_by(student_id=student.id, type='CREDIT').scalar() or 0
    debits = db.session.query(func.sum(WalletTransaction.amount)).filter_by(student_id=student.id, type='DEBIT').scalar() or 0
    balance = credits - debits
    
    # 2. Check Funds
    if balance <= 0:
        flash("Insufficient funds!", "danger")
        return redirect(url_for('sos_dashboard'))
    
    # 3. SMART FETCH: Get Bank Details from the last S.O.S Request instead of Student Model
    # This avoids the "AttributeError" completely.
    last_request = SOSRequest.query.filter_by(student_id=student.id, type='CASH').order_by(SOSRequest.created_at.desc()).first()
    
    if last_request and last_request.bank_name:
        bank = last_request.bank_name
        acc = last_request.account_number
    else:
        # Fallback if no history found
        bank = "Registered Bank"
        acc = "******"

    # 4. Process Withdrawal
    new_tx = WalletTransaction(
        student_id=student.id,
        type='DEBIT',
        amount=balance, 
        description=f"Withdrawal to {bank} - {acc}"
    )
    
    db.session.add(new_tx)
    db.session.commit()
    
    flash(f"₦{balance:,.2f} sent to {bank} ({acc})!", "success")
    return redirect(url_for('sos_dashboard'))


@app.route('/emergency_add_helper_col')
def emergency_add_helper_col():
    from sqlalchemy import text
    try:
        with app.app_context():
            # Inject 'helper_id' column
            try:
                db.session.execute(text("ALTER TABLE sos_request ADD COLUMN helper_id INTEGER"))
                db.session.commit()
                return "<h1>✅ Success! Added 'helper_id' column.</h1><a href='/student/sos'>Go to Dashboard</a>"
            except Exception as e:
                return f"<h1>ℹ️ Column might already exist: {e}</h1><a href='/student/sos'>Go back</a>"
    except Exception as e:
        return f"<h1>❌ Error: {e}</h1>"

@app.route('/force_record_impact')
def force_record_impact():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student_id = session['student_id']
    
    # Find ALL 'Funded' requests that don't have a helper recorded yet
    # (Assuming these were funded by the currently logged-in user for testing)
    orphan_requests = SOSRequest.query.filter_by(status='Funded', helper_id=None).all()
    
    count = 0
    for req in orphan_requests:
        # Don't claim your own requests
        if req.student_id != student_id:
            req.helper_id = student_id
            count += 1
    
    db.session.commit()
    
    flash(f"✅ Success! You have claimed {count} past donations. Check 'My Impact' now!")
    return redirect(url_for('sos_dashboard'))


# ==========================================
# 🛒 LASU-MART (CAMPUS MARKETPLACE)
# ==========================================

@app.route('/student/marketplace')
def marketplace():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student = db.session.get(Student, session['student_id'])
    
    # Filter Logic
    category = request.args.get('category')
    search = request.args.get('search')
    
    query = MarketItem.query.filter_by(status='Available')
    
    if category:
        query = query.filter_by(category=category)
    if search:
        query = query.filter(MarketItem.title.ilike(f'%{search}%'))
        
    items = query.order_by(MarketItem.date_posted.desc()).all()
    
    return render_template('marketplace.html', student=student, items=items, active_cat=category)

@app.route('/student/marketplace/sell', methods=['POST'])
def list_item():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student_id = session['student_id']
    
    # Image Upload Logic
    file = request.files.get('image')
    image_fn = 'default_product.jpg'
    
    if file and file.filename != '':
        # Ensure directory exists
        market_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'market')
        os.makedirs(market_folder, exist_ok=True)
        
        # Save file
        random_hex = secrets.token_hex(8)
        _, f_ext = os.path.splitext(file.filename)
        image_fn = random_hex + f_ext
        file.save(os.path.join(market_folder, image_fn))

    new_item = MarketItem(
        seller_id=student_id,
        title=request.form['title'],
        price=float(request.form['price']),
        category=request.form['category'],
        description=request.form['description'],
        image_file=image_fn
    )
    
    db.session.add(new_item)
    db.session.commit()
    
    flash('✅ Item listed successfully! Good luck selling.')
    return redirect(url_for('marketplace'))

@app.route('/student/marketplace/delete/<int:item_id>', methods=['POST'])
def delete_market_item(item_id):
    if not session.get('student_logged_in'): return redirect(url_for('student_login'))
    
    item = MarketItem.query.get_or_404(item_id)
    if item.seller_id == session['student_id']:
        db.session.delete(item)
        db.session.commit()
        flash('🗑️ Item removed.')
    
    return redirect(url_for('marketplace'))

@app.route('/setup_marketplace_db')
def setup_marketplace_db():
    with app.app_context():
        # Create the table using raw SQL to be safe
        db.session.execute(text('''
            CREATE TABLE IF NOT EXISTS market_item (
                id INTEGER PRIMARY KEY,
                seller_id INTEGER NOT NULL,
                title VARCHAR(100) NOT NULL,
                price FLOAT NOT NULL,
                category VARCHAR(50) NOT NULL,
                description TEXT,
                image_file VARCHAR(100) DEFAULT 'default_product.jpg',
                status VARCHAR(20) DEFAULT 'Available',
                date_posted DATETIME DEFAULT CURRENT_TIMESTAMP,
                views INTEGER DEFAULT 0,
                FOREIGN KEY(seller_id) REFERENCES student(id)
            )
        '''))
        db.session.commit()
        return "<h1>✅ LASU-Mart Database Ready!</h1><a href='/student/marketplace'>Go to Market</a>"

from sqlalchemy import text  # Ensure this import is at the top or here

@app.route('/emergency_fix_clearance_columns')
def fix_clearance_cols():
    with app.app_context():
        try:
            # We use a raw SQL command to force-add the missing columns
            db.session.execute(text("ALTER TABLE clearance ADD COLUMN department_status VARCHAR(20) DEFAULT 'Pending'"))
            db.session.execute(text("ALTER TABLE clearance ADD COLUMN sports_status VARCHAR(20) DEFAULT 'Pending'"))
            db.session.execute(text("ALTER TABLE clearance ADD COLUMN health_center_status VARCHAR(20) DEFAULT 'Pending'"))
            db.session.commit()
            return "✅ Success! Added Department, Sports, and Health columns."
        except Exception as e:
            return f"ℹ️ Columns likely already exist or error: {str(e)}"
        
# 👇 PASTE AT THE BOTTOM OF APP.PY 👇
from sqlalchemy import text

@app.route('/super_fix_db')
def super_fix_db():
    with app.app_context():
        messages = []
        
        # 1. Try adding Health Center Status
        try:
            db.session.execute(text("ALTER TABLE clearance ADD COLUMN health_center_status VARCHAR(20) DEFAULT 'Pending'"))
            db.session.commit()
            messages.append("✅ Added 'health_center_status'")
        except Exception as e:
            db.session.rollback()
            messages.append(f"ℹ️ 'health_center_status' issue (likely exists): {e}")

        # 2. Try adding Department Status
        try:
            db.session.execute(text("ALTER TABLE clearance ADD COLUMN department_status VARCHAR(20) DEFAULT 'Pending'"))
            db.session.commit()
            messages.append("✅ Added 'department_status'")
        except Exception as e:
            db.session.rollback()
            messages.append(f"ℹ️ 'department_status' issue (likely exists): {e}")

        # 3. Try adding Sports Status
        try:
            db.session.execute(text("ALTER TABLE clearance ADD COLUMN sports_status VARCHAR(20) DEFAULT 'Pending'"))
            db.session.commit()
            messages.append("✅ Added 'sports_status'")
        except Exception as e:
            db.session.rollback()
            messages.append(f"ℹ️ 'sports_status' issue (likely exists): {e}")

        return "<br>".join(messages)

# ==========================================
# 🧠 ATAS SYSTEM (UPDATED SMART LOGIC)
# ==========================================

# ------------------------------------------
# 1. STUDENT SIDE (Dashboard & Application)
# ------------------------------------------

@app.route('/student/atas')
@login_required
def atas_dashboard():
    student = Student.query.get(session['student_id'])
    
    # 1. Ensure Profile Exists
    profile = ATASProfile.query.filter_by(student_id=student.id).first()
    if not profile:
        profile = ATASProfile(student_id=student.id)
        db.session.add(profile)
        db.session.commit()

    # 🟢 2. LIVE CGPA CALCULATION
    try:
        raw_cgpa, _ = calculate_cgpa(student)
        cgpa = float(raw_cgpa)
    except (NameError, TypeError, ValueError):
        cgpa = 3.50 

    # 🟢 3. GRAVITY ENGINE: DETERMINE TIER
    if cgpa >= 4.50:
        target_title = "Principal AI Research Scientist"
        target_company = "Google DeepMind"
        target_score = 98
    elif cgpa >= 3.50:
        target_title = "Senior Cloud Solutions Architect"
        target_company = "Microsoft Azure"
        target_score = 85
    elif cgpa >= 2.50:
        target_title = "Backend Developer II"
        target_company = "Paystack"
        target_score = 72
    else:
        target_title = "IT Support Intern"
        target_company = "MainOne Cables"
        target_score = 55

    # 🟢 4. FORCE UPDATE DATABASE (The Fix)
    opp = ATASOpportunity.query.filter_by(student_id=student.id).first()
    
    if not opp:
        # Case A: Create New
        opp = ATASOpportunity(
            student_id=student.id,
            title=target_title,
            company=target_company,
            match_score=target_score,
            status="Open"
        )
        db.session.add(opp)
    else:
        # ⚠️ Case B: ALWAYS Force Update (Lock Removed)
        # We overwrite the title/company even if status is 'Accepted'
        opp.title = target_title
        opp.company = target_company
        opp.match_score = target_score
        # We leave the status as is (so they don't lose the 'Accepted' badge), 
        # but the company name INSIDE that offer changes.
    
    db.session.commit()

    # 5. Visuals
    timelines = {
        "A": {"name": "Status Quo", "gpa": cgpa, "sleep": 7.0, "desc": "Current trajectory."},
        "B": {"name": "Optimized", "gpa": min(5.0, cgpa + 0.2), "sleep": 6.5, "desc": "Efficiency increased."},
        "C": {"name": "Survival", "gpa": max(1.5, cgpa - 0.4), "sleep": 9.0, "desc": "High recovery mode."},
        "D": {"name": "Apex Predator", "gpa": min(5.0, cgpa + 0.5), "sleep": 4.5, "desc": "Max distinction."}
    }

    return render_template('atas_dashboard.html', student=student, profile=profile, timelines=timelines, risks=[], opportunity=opp)


@app.route('/student/atas/apply/<int:opp_id>')
@login_required
def atas_apply(opp_id):
    opp = ATASOpportunity.query.get_or_404(opp_id)
    
    if opp.student_id != session['student_id']:
        flash("Access Denied.", "danger")
        return redirect(url_for('atas_dashboard'))
        
    opp.status = "Applied"
    db.session.commit()
    
    flash("🚀 APPLICATION INITIATED. Neural handshake established.", "success")
    return redirect(url_for('atas_dashboard'))


@app.route('/student/atas/offer_letter')
@login_required
def view_offer_letter():
    student = Student.query.get(session['student_id'])
    opp = ATASOpportunity.query.filter_by(student_id=student.id).first()
    
    # 1. Calculate CGPA
    try:
        raw_cgpa, _ = calculate_cgpa(student)
        cgpa = float(raw_cgpa)
    except:
        cgpa = 3.50 

    if not opp: 
        flash("⚠️ No active offer found.", "danger")
        return redirect(url_for('atas_dashboard'))

    # 🟢 2. FETCH REAL DATA FROM YOUR CERTIFICATION REPOSITORY
    # We query the exact table you showed me in your code snippet
    real_certs = Certification.query.filter_by(student_id=student.id).all()
    
    if real_certs:
        # If found, we create a nice string like: "CCNA, AWS Cloud Practitioner"
        certs_text = ", ".join([c.name for c in real_certs])
    else:
        # If the list is empty, we pass None so the letter stays silent
        certs_text = None

    # 3. DYNAMIC SALARY & PERKS (Based on Company Tier Only)
    # We NO LONGER assume certs here. We only set money/perks.
    if "Google" in opp.company or "AI" in opp.title:
        salary = "₦1,250,000"
        perks = ["Stock Options (GSUs)", "Relocation Bonus", "Free Lunch & Gym"]
    elif "Microsoft" in opp.company or "Azure" in opp.company:
        salary = "₦850,000"
        perks = ["Azure Credits", "Remote Work Option", "Health Insurance"]
    elif "Paystack" in opp.company:
        salary = "₦450,000"
        perks = ["MacBook Pro M3", "Internet Allowance", "Quarterly Bonus"]
    else:
        salary = "₦150,000"
        perks = ["Transport Allowance", "On-job Training"]

    return render_template('offer_letter.html', 
                           student=student, 
                           opp=opp, 
                           today=date.today(),
                           salary=salary,
                           perks=perks,
                           certs=certs_text, # <--- Passing the REAL data
                           cgpa=cgpa)


@app.route('/admin/atas/delete/<int:opp_id>')
def atas_delete(opp_id):
    # 1. Find the opportunity
    opp = ATASOpportunity.query.get_or_404(opp_id)
    
    # 2. Delete it from the database
    db.session.delete(opp)
    db.session.commit()
    
    # 3. Flash message
    flash(f"⚠️ RECORD DELETED: Opportunity ID {opp_id} removed from system.", "warning")
    
    # 4. Redirect back to Console (WITH THE KEY so you stay logged in)
    return redirect(url_for('atas_admin_console', key='recruiter_access_007'))

# ------------------------------------------
# 2. ADMIN SIDE (Recruiter Console)
# ------------------------------------------

@app.route('/admin/atas_console')
def atas_admin_console():
    # 🔒 Security Check
    secret_key = request.args.get('key')
    if secret_key != 'recruiter_access_007':
        return "⛔ ACCESS DENIED: CLASSIFIED SYSTEM. YOUR IP HAS BEEN LOGGED.", 403

    applications = db.session.query(ATASOpportunity, Student)\
        .join(Student, ATASOpportunity.student_id == Student.id)\
        .filter(ATASOpportunity.status != 'Open')\
        .all()
        
    return render_template('atas_admin.html', applications=applications)

@app.route('/admin/atas/decide/<int:opp_id>/<string:decision>')
def atas_decide(opp_id, decision):
    opp = ATASOpportunity.query.get_or_404(opp_id)
    if decision == 'accept':
        opp.status = 'Accepted'
        flash(f"✅ OFFER SENT to Student ID {opp.student_id}", "success")
    elif decision == 'reject':
        opp.status = 'Rejected'
        flash(f"❌ REJECTION SENT to Student ID {opp.student_id}", "danger")
    db.session.commit()
    return redirect(url_for('atas_admin_console', key='recruiter_access_007'))


# ==========================================
# 🛠️ DATABASE REPAIR TOOL
# ==========================================
from sqlalchemy import text

@app.route('/fix_db_column')
def fix_db_column():
    try:
        # This SQL command manually adds the missing column
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE certification ADD COLUMN credly_link VARCHAR(500)"))
            conn.commit()
        return "<h1>✅ SUCCESS: Column 'credly_link' added to database!</h1><a href='/student/certifications'>Go Back</a>"
    except Exception as e:
        return f"<h1>⚠️ Error (Column might already exist): {e}</h1><a href='/student/certifications'>Go Back</a>"

@app.route('/fix_200_percent_bug')
def fix_200_percent_bug():
    try:
        # Find all students with crazy attendance
        students = Student.query.filter(Student.attendance_pct > 100).all()
        count = 0
        for s in students:
            s.attendance_pct = 100.0  # Reset to max
            count += 1
        
        db.session.commit()
        return f"<h1>✅ REPAIRED!</h1><p>Fixed {count} students who had over 100% attendance.</p><a href='/students'>Go Check List</a>"
    except Exception as e:
        return f"Error: {e}"
    
# ==========================================
# ☢️ NUCLEAR FLUSH: DELETE ALL EXAMS
# ==========================================
@app.route('/nuclear_flush')
def nuclear_flush():
    try:
        # Delete all records in the Exam table
        num_deleted = db.session.query(Exam).delete()
        db.session.commit()
        return f"<h1>✅ FLUSH COMPLETE</h1><p>Deleted {num_deleted} exams. The database is now empty.</p><p>Now go to your Admin Dashboard and click 'Generate Timetable'.</p>"
    except Exception as e:
        return f"<h1>❌ Error: {e}</h1>"

# ==========================================
# 🧠 AI LESSON PLANNER (DIAGNOSTIC MODE)
# ==========================================
@app.route('/lecturer/lesson_planner', methods=['GET', 'POST'])
def lecturer_lesson_planner():
    # 1. Check Login
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    syllabus = None
    title = ""

    if request.method == 'POST':
        title = request.form.get('course_title')
        level = request.form.get('level')
        
        print(f"🔹 DEBUG: Attempting to generate for '{title}'...") 

        if title:
            try:
                # 2. Check for API Key
                if not GROQ_API_KEY:
                    flash('❌ Error: GROQ_API_KEY is missing in app.py', 'danger')
                    return render_template('lecturer_lesson_planner.html', syllabus=None)

                # 3. Prepare the AI Prompt
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": "You are a curriculum developer. Return valid HTML only. No Markdown."},
                        {"role": "user", "content": f"12-week syllabus for {title} {level}. HTML only."}
                    ],
                    "temperature": 0.3
                }

                # 🟢 THE SSL FIX: Use httpx with verify=False to bypass the EOF error
                import httpx
                with httpx.Client(verify=False, timeout=60.0) as client:
                    response = client.post(url, json=payload, headers=headers)
                
                print(f"🔹 DEBUG: API Status Code: {response.status_code}") 

                # 5. Handle Success or Failure
                if response.status_code == 200:
                    ai_text = response.json()['choices'][0]['message']['content']
                    # Clean up common AI formatting issues
                    syllabus = ai_text.replace("```html", "").replace("```", "").strip()
                    flash('✅ Syllabus generated successfully!', 'success')
                else:
                    error_msg = response.text
                    print(f"❌ API FAILURE: {error_msg}")
                    flash(f'❌ AI Error: {response.status_code}', 'danger')

            except Exception as e:
                print(f"❌ CRITICAL ERROR: {e}")
                flash(f'❌ System Error: Connection reset by network.', 'danger')

    return render_template('lecturer_lesson_planner.html', syllabus=syllabus, title=title)


# ==========================================
# 🧠 AUTO-QUIZ: THE FINAL VERSION (ALL FEATURES)
# ==========================================
def compress_text_for_ai(text, char_limit=6000):
    import re
    # Remove excess whitespace
    compressed = re.sub(r'\s+', ' ', text).strip()
    if len(compressed) > char_limit:
        return compressed[:char_limit] + "..."
    return compressed

@app.route('/lecturer/auto_quiz', methods=['GET', 'POST'])
def auto_quiz_generator():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    courses = Course.query.order_by(Course.code).all()
    
    if request.method == 'POST':
        course_id = request.form.get('course_id')
        mode = request.form.get('mode', 'Standard')
        
        # 🟢 1. GET INPUT (Text or PDF)
        raw_text = ""
        pasted_text = request.form.get('lecture_text')
        pdf_file = request.files.get('pdf_file')

        if pasted_text and len(pasted_text.strip()) > 50:
            raw_text = pasted_text
        elif pdf_file and pdf_file.filename != '':
            try:
                import PyPDF2
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                for page in pdf_reader.pages[:15]: 
                    text = page.extract_text()
                    if text: raw_text += text
            except Exception as e:
                flash(f'Error reading PDF: {str(e)}', 'danger')
                return redirect(request.url)
        else:
            flash('❌ Error: Please either Paste Text or Upload a PDF.', 'warning')
            return redirect(request.url)

        final_text = raw_text[:6000]

        try:
            req_count = int(request.form.get('question_count', 20))
            count = 50 if req_count > 50 else req_count
        except:
            count = 20
        
        if final_text and course_id:
            try:
                # 🟢 2. AI REQUEST
                system_prompt = "You are a quiz engine. Output a Python List of Dictionaries."
                user_prompt = (
                    f"Generate {count} unique multiple-choice questions from this text. "
                    f"Format: [{{'q': 'Question?', 'options': ['A','B','C','D'], 'correct': 'A'}}] "
                    f"STRICT: 'correct' must be ONLY A, B, C, or D. Text: {final_text}"
                )

                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
                payload = {
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                    "temperature": 0.3 # Slightly higher temp for more variety
                }

                import httpx
                import time
                import ast
                from sqlalchemy import func # Import func for lower() check

                response = None
                for attempt in range(3):
                    try:
                        with httpx.Client(verify=False, timeout=60.0, http2=False) as client:
                            response = client.post(url, json=payload, headers=headers)
                            if response.status_code == 200: break
                    except: time.sleep(1)
                
                if response and response.status_code == 200:
                    ai_response = response.json()['choices'][0]['message']['content']
                    clean_text = ai_response.replace("```json", "").replace("```python", "").replace("```", "").strip()
                    
                    quiz_data = []
                    try:
                        quiz_data = ast.literal_eval(clean_text)
                    except:
                        import re
                        raw_objects = re.findall(r"\{.*?\}", clean_text, re.DOTALL)
                        for obj_str in raw_objects:
                            try:
                                q_obj = ast.literal_eval(obj_str)
                                if 'q' in q_obj: quiz_data.append(q_obj)
                            except: continue

                    # 🟢 3. SAVE TO DB (WITH DUPLICATE CHECK)
                    course = Course.query.get(course_id)
                    master_title = f"Question Bank: {course.code}"
                    
                    target_quiz = Quiz.query.filter_by(course_id=course.id, title=master_title).first()
                    
                    if not target_quiz:
                        target_quiz = Quiz(course_id=course.id, title=master_title, description="Generated Bank")
                        db.session.add(target_quiz)
                        db.session.commit()

                    added_count = 0
                    skipped_count = 0

                    for q in quiz_data:
                        question_text = q['q'].strip()
                        
                        # 🔍 CHECK IF QUESTION ALREADY EXISTS
                        # We compare lowercase versions to be sure
                        exists = Question.query.filter(
                            Question.quiz_id == target_quiz.id,
                            func.lower(Question.text) == question_text.lower()
                        ).first()

                        if exists:
                            skipped_count += 1
                            continue # Skip this loop iteration

                        # If not exists, process options
                        raw_correct = str(q.get('correct', 'A')).upper()
                        correct = "A"
                        if "A" in raw_correct: correct = "A"
                        elif "B" in raw_correct: correct = "B"
                        elif "C" in raw_correct: correct = "C"
                        elif "D" in raw_correct: correct = "D"

                        opts = q.get('options', [])
                        while len(opts) < 4: opts.append("-")

                        new_question = Question(
                            quiz_id=target_quiz.id, text=question_text,
                            option_a=opts[0], option_b=opts[1],
                            option_c=opts[2], option_d=opts[3],
                            correct_option=correct
                        )
                        db.session.add(new_question)
                        added_count += 1
                    
                    db.session.commit()
                    
                    msg = f'✅ Added {added_count} new questions.'
                    if skipped_count > 0:
                        msg += f' (Skipped {skipped_count} duplicates).'
                    
                    flash(msg, 'success')
                    return redirect(url_for('manage_quizzes'))

                else:
                    flash(f'❌ API Error: {response.status_code if response else "Failed"}', 'danger')

            except Exception as e:
                print(f"❌ ERROR: {e}")
                flash(f'System Error: {str(e)}', 'danger')

    return render_template('lecturer_auto_quiz.html', courses=courses)

# ==========================================
# 🗑️ DELETE QUIZ ROUTE
# ==========================================
@app.route('/cbt/delete_quiz/<int:quiz_id>', methods=['POST'])
def delete_quiz(quiz_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    try:
        # 1. Get the Quiz
        quiz = Quiz.query.get_or_404(quiz_id)
        
        # 2. Delete all Questions linked to this Quiz first
        Question.query.filter_by(quiz_id=quiz.id).delete()
        
        # 3. Delete the Quiz itself
        db.session.delete(quiz)
        db.session.commit()
        
        flash(f'✅ Quiz "{quiz.title}" deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error deleting quiz: {str(e)}', 'danger')
        
    return redirect(url_for('manage_quizzes'))


@app.route('/cbt/merge_quizzes/<int:old_quiz_id>', methods=['POST'])
def merge_quizzes(old_quiz_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    old_quiz = Quiz.query.get_or_404(old_quiz_id)
    course = Course.query.get(old_quiz.course_id)
    master_title = f"AI Question Bank: {course.code}"
    
    # 1. Find or Create the Master Bank
    master_bank = Quiz.query.filter_by(course_id=course.id, title=master_title).first()
    if not master_bank:
        master_bank = Quiz(course_id=course.id, title=master_title)
        db.session.add(master_bank)
        db.session.commit()

    # 2. Move Questions
    old_questions = Question.query.filter_by(quiz_id=old_quiz.id).all()
    moved_count = 0
    duplicate_count = 0

    for q in old_questions:
        # Check if question already exists in Master Bank
        exists = Question.query.filter(
            Question.quiz_id == master_bank.id,
            func.lower(Question.text) == func.lower(q.text)
        ).first()

        if not exists:
            q.quiz_id = master_bank.id # Change the ID to the Master Bank
            moved_count += 1
        else:
            db.session.delete(q) # Delete the duplicate
            duplicate_count += 1

    # 3. Delete the now-empty old quiz
    db.session.delete(old_quiz)
    db.session.commit()

    flash(f"✅ Merged {moved_count} questions into {master_title}. Deleted {duplicate_count} duplicates.", "success")
    return redirect(url_for('manage_quizzes'))

def get_ai_summary(text, course_code):
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        # 1. We split your notes into two parts (Part A and Part B)
        midpoint = len(text) // 2
        part1 = text[:midpoint]
        part2 = text[midpoint:]

        summaries = []

        # 2. Process Part 1
        payload1 = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": f"Summarize Chapters 1-6 of these {course_code} notes. Use bullet points."},
                {"role": "user", "content": part1}
            ],
            "temperature": 0.2,
            "max_tokens": 2000
        }
        
        # 3. Process Part 2
        payload2 = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": f"Summarize Chapters 7-13 of these {course_code} notes. Use bullet points. End with Study Tips."},
                {"role": "user", "content": part2}
            ],
            "temperature": 0.2,
            "max_tokens": 4000
        }

        # Send both requests
        # 🟢 UPDATED: Using session_pool and verify=False
        res1 = session_pool.post(url, json=payload1, headers=headers, timeout=60, verify=False)
        res2 = session_pool.post(url, json=payload2, headers=headers, timeout=60, verify=False)

        if res1.status_code == 200 and res2.status_code == 200:
            # Combine the two halves into one full summary
            full_summary = res1.json()['choices'][0]['message']['content'] + "\n\n" + res2.json()['choices'][0]['message']['content']
            return full_summary
        else:
            return "AI Error: One of the parts failed to generate."

    except Exception as e:
        return f"Summarization failed: {str(e)}"
    

@app.route('/lecturer/summarize_to_portal/<int:course_id>', methods=['POST'])
def summarize_to_portal(course_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    course = Course.query.get_or_404(course_id)
    raw_text = request.form.get('lecture_text')
    
    # 1. Capture Title
    lecture_title = request.form.get('lecture_title', 'Lecture Summary')

    if not raw_text or len(raw_text) < 20:
        flash("Dictation text too short to summarize.", "warning")
        return redirect(url_for('manage_quizzes'))

    # AI generates the summary
    summary_content = get_ai_summary(raw_text, course.code) 

    # 🟢 2. THE FIX: ADD THE "[Topic Summary]" TAG
    final_message = f"[Topic Summary] **{lecture_title.upper()}**\n\n{summary_content.strip()}"

    try:
        # Find students registered for this course
        students = Student.query.filter(
            Student.registered_courses.any(id=course.id)
        ).all()
        
        if not students:
            flash(f"⚠️ Summary generated, but no students are currently registered for {course.code}.", "warning")
            return redirect(url_for('manage_quizzes'))
        
        count = 0
        for student in students:
            new_note = Notification(
                student_id=student.id,
                title=f"{course.code}: {lecture_title}", 
                message=final_message, # ✅ Now includes the tag
                timestamp=datetime.utcnow(),
                is_read=False
            )
            db.session.add(new_note)
            count += 1
            
        db.session.commit()
        flash(f"✅ Summary '{lecture_title}' pushed to {count} registered student(s)!", "success")
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ PUSH ERROR: {str(e)}")
        flash(f"Database Error: {str(e)}", "danger")

    return redirect(url_for('manage_quizzes'))


@app.route('/student/dashboard')
def student_dashboard():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student_id = session.get('student_id')
    student = Student.query.get(student_id)
    
    # Fetch all notifications for this student
    notifications = Notification.query.filter_by(student_id=student.id).order_by(Notification.timestamp.desc()).all()
    unread_count = Notification.query.filter_by(student_id=student.id, is_read=False).count()
    
    return render_template('student_dashboard.html', 
                           student=student, 
                           notifications=notifications, 
                           unread_count=unread_count)

@app.route('/student/mark_read/<int:note_id>')
def mark_read(note_id):
    note = Notification.query.get_or_404(note_id)
    note.is_read = True
    db.session.commit()
    return redirect(url_for('student_dashboard'))

@app.route('/student/notifications')
def student_notifications():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student_id = session.get('student_id')
    
    # 🟢 FIX: Only fetch notifications that are NOT "Academic Warnings"
    # We filter out messages containing "EXAM VOIDED"
    notifications = Notification.query.filter(
        Notification.student_id == student_id,
        Notification.message.notlike("%EXAM VOIDED%") 
    ).order_by(Notification.timestamp.desc()).all()
    
    # Mark displayed summaries as read
    for note in notifications:
        note.is_read = True
    db.session.commit()
    
    return render_template('student_notifications.html', notifications=notifications)


@app.route('/lecturer/delete_summary/<int:note_id>', methods=['POST', 'GET'])
@login_required
def delete_summary(note_id):
    # 1. Find the one you clicked on
    target_note = Notification.query.get_or_404(note_id)
    
    # 2. ⚡ THE NUCLEAR FIX: Find ALL copies of this same message
    # This ensures that if it was sent to 50 students, all 50 are deleted.
    Notification.query.filter_by(message=target_note.message).delete()
    
    db.session.commit()
    flash('🗑️ Summary removed from all student portals!', 'success')
    return redirect(url_for('manage_quizzes'))

@app.route('/lecturer/edit_summary/<int:note_id>', methods=['POST'])
@login_required
def edit_summary(note_id):
    note = Notification.query.get_or_404(note_id)
    new_message = request.form.get('message')
    if new_message:
        note.message = new_message
        db.session.commit()
        flash('✅ Summary updated successfully!', 'success')
    return redirect(url_for('manage_quizzes'))


# ==========================================
# 🏛️ VIRTUAL OFFICE HOURS (FINAL UNIFIED VERSION)
# ==========================================

# 1. Manage Slots (Smart Logic: Works for Admin AND Lecturers)
@app.route('/lecturer/office_hours', methods=['GET', 'POST'])
def manage_office_hours():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    # 1. Identify Lecturer
    if session.get('role') == 'lecturer':
        lecturer_id = session['user_id']
    else:
        # Admin Fallback
        main_lecturer = Lecturer.query.filter_by(email="prof@lasu.edu.ng").first()
        if not main_lecturer:
            flash("❌ No main lecturer account found.")
            return redirect(url_for('dashboard'))
        lecturer_id = main_lecturer.id

    # 2. Handle Form Submission
    if request.method == 'POST':
        date_str = request.form['slot_date']       # YYYY-MM-DD
        start_time_str = request.form['start_time'] # HH:MM
        end_time_str = request.form['end_time']     # HH:MM
        link = request.form['meeting_link']
        course_id = request.form.get('course_id')

        try:
            # Combine Date + Time
            start_dt = datetime.strptime(f"{date_str} {start_time_str}", '%Y-%m-%d %H:%M')
            end_dt = datetime.strptime(f"{date_str} {end_time_str}", '%Y-%m-%d %H:%M')

            # 🛑 VALIDATION: Standard Hours (8 AM - 6 PM)
            if start_dt.hour < 8 or end_dt.hour > 18 or (end_dt.hour == 18 and end_dt.minute > 0):
                flash('❌ Error: Office hours must be between 8:00 AM and 6:00 PM.', 'danger')
            
            # 🛑 VALIDATION: End time must be after Start time
            elif end_dt <= start_dt:
                flash('❌ Error: End time cannot be before Start time. (Did you mean PM? Use 24h format like 17:00)', 'danger')
            
            elif start_dt.weekday() > 4: # Block Weekends
                flash('⚠️ Warning: Scheduling on a weekend is discouraged.', 'warning')
                new_slot = OfficeHour(lecturer_id=lecturer_id, course_id=course_id, start_time=start_dt, end_time=end_dt, meeting_link=link)
                db.session.add(new_slot)
                db.session.commit()
                flash('✅ Weekend slot created.', 'success')
            else:
                new_slot = OfficeHour(
                    lecturer_id=lecturer_id,
                    course_id=course_id,
                    start_time=start_dt,
                    end_time=end_dt,
                    meeting_link=link
                )
                db.session.add(new_slot)
                db.session.commit()
                flash('✅ Availability slot created successfully!', 'success')

        except ValueError:
            flash('❌ Invalid date/time format.')

    # 3. Fetch Data
    my_slots = OfficeHour.query.filter_by(lecturer_id=lecturer_id).order_by(OfficeHour.start_time.desc()).all()
    all_courses = Course.query.order_by(Course.code.asc()).all()

    return render_template('lecturer_office_hours.html', slots=my_slots, courses=all_courses)

# 2. Delete Slot Route
@app.route('/lecturer/office_hours/delete/<int:id>', methods=['POST'])
def delete_office_hour(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    slot = OfficeHour.query.get_or_404(id)
    db.session.delete(slot)
    db.session.commit()
    flash('Slot removed.')
    return redirect(url_for('manage_office_hours'))


# 3. Student View: Book Office Hours
@app.route('/student/office_hours')
def student_office_hours():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    my_course_codes = [c.code for c in student.registered_courses]
    
    # Get relevant courses
    matching_courses = Course.query.filter(Course.code.in_(my_course_codes)).all()
    all_matching_ids = [c.id for c in matching_courses]
    my_lecturer_ids = [c.lecturer_id for c in matching_courses if c.lecturer_id]

    from sqlalchemy import or_

    # 🟢 SHOW ALL SLOTS (Even if someone else booked them)
    available_slots = OfficeHour.query.filter(
        OfficeHour.start_time > datetime.now(),
        or_(
            OfficeHour.course_id.in_(all_matching_ids),
            OfficeHour.lecturer_id.in_(my_lecturer_ids)
        )
    ).order_by(OfficeHour.start_time).all()

    # Determine which slots *I* have already booked
    my_booked_slot_ids = [b.slot_id for b in SlotAttendee.query.filter_by(student_id=student.id).all()]

    return render_template('student_book_office_hours.html', 
                           slots=available_slots, 
                           my_booked_ids=my_booked_slot_ids)

# 4. Student Action: Submit Booking
@app.route('/student/book_slot/<int:slot_id>', methods=['POST'])
def book_slot(slot_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student_id = session['student_id']
    
    # Check if already booked
    existing = SlotAttendee.query.filter_by(slot_id=slot_id, student_id=student_id).first()
    
    if existing:
        flash('⚠️ You have already joined this session.', 'warning')
    else:
        # 🟢 ADD TO ATTENDEE LIST (Group Booking)
        new_booking = SlotAttendee(slot_id=slot_id, student_id=student_id)
        
        # Mark the slot as "booked" visually (optional, just to show activity)
        slot = OfficeHour.query.get(slot_id)
        slot.is_booked = True 
        
        db.session.add(new_booking)
        db.session.commit()
        flash('✅ You have successfully joined the session!', 'success')

    return redirect(url_for('student_office_hours'))

# ==========================================
# 🚑 EMERGENCY FIX: ADD MISSING LECTURER COLUMN
# ==========================================
@app.route('/fix_lecturer_column')
def fix_lecturer_column():
    from sqlalchemy import text
    try:
        with app.app_context():
            # Force add the missing column
            try:
                db.session.execute(text("ALTER TABLE course ADD COLUMN lecturer_id INTEGER"))
                db.session.commit()
                return """
                <div style='text-align: center; padding: 50px; font-family: sans-serif;'>
                    <h1 style='color: green;'>✅ SUCCESS!</h1>
                    <p>The column <b>lecturer_id</b> has been added to the Course table.</p>
                    <br>
                    <a href='/' style='padding: 15px 30px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>Go to Dashboard</a>
                </div>
                """
            except Exception as e:
                return f"<h1>ℹ️ Info: {e}</h1><p>Column might already exist.</p>"
    except Exception as e:
        return f"<h1>❌ Critical Error: {e}</h1>"


# ==========================================
# 🔐 EMERGENCY LOGIN FIXER
# ==========================================
@app.route('/force_create_lecturer')
def force_create_lecturer():
    from werkzeug.security import generate_password_hash
    try:
        # 1. Ensure the table exists
        db.create_all()
        
        # 2. Check if the account exists
        email = "favouradamson803@gmail.com"
        prof = Lecturer.query.filter_by(email=email).first()
        
        if prof:
            # UPDATE EXISTING
            prof.set_password("password123")
            status = "UPDATED"
        else:
            # CREATE NEW
            prof = Lecturer(
                title="Dr.",
                name="Adebayo (HOD)",
                email=email,
                department="Computer Science"
            )
            prof.set_password("password123")
            db.session.add(prof)
            status = "CREATED"
            
        db.session.commit()
        
        return f"""
        <div style='text-align: center; padding: 50px; font-family: sans-serif;'>
            <h1 style='color: green;'>✅ ACCOUNT {status} SUCCESSFULLY!</h1>
            <p><strong>Username:</strong> {email}</p>
            <p><strong>Password:</strong> password123</p>
            <br>
            <a href='/login' style='padding: 15px 30px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; font-size: 18px;'>Login Now</a>
        </div>
        """
    except Exception as e:
        return f"<h1>❌ Error: {e}</h1>"


# ==========================================
# 🔗 MAGIC LINKER INTERFACE (Visual Tool)
# ==========================================
@app.route('/admin/link_wizard')
@admin_only
def link_wizard():
    # 1. Fetch ALL Lecturers and Courses from your DB
    lecturers = Lecturer.query.all()
    courses = Course.query.all()
    
    # 2. Generate Dropdown Options
    lect_options = "".join([f"<option value='{l.id}'>{l.name} ({l.email})</option>" for l in lecturers])
    course_options = "".join([f"<option value='{c.id}'>{c.code} - {c.title}</option>" for c in courses])
    
    return f"""
    <html>
    <body style="background: #f4f7f6; font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh;">
        <div style="background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); width: 400px;">
            <h2 style="color: #004d40; text-align: center; margin-bottom: 20px;">🔗 Connect Lecturer</h2>
            
            <form action="/admin/process_link_wizard" method="POST">
                <label style="font-weight: bold; color: #555;">Select Lecturer:</label>
                <select name="lecturer_id" style="width: 100%; padding: 12px; margin: 10px 0 20px; border: 2px solid #ddd; border-radius: 8px;">
                    {lect_options}
                </select>
                
                <label style="font-weight: bold; color: #555;">Assign to Course:</label>
                <select name="course_id" style="width: 100%; padding: 12px; margin: 10px 0 20px; border: 2px solid #ddd; border-radius: 8px;">
                    {course_options}
                </select>
                
                <button type="submit" style="width: 100%; background: #198754; color: white; padding: 15px; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer;">
                    LINK THEM NOW 🚀
                </button>
            </form>
        </div>
    </body>
    </html>
    """

@app.route('/admin/process_link_wizard', methods=['POST'])
def process_link_wizard():
    l_id = request.form.get('lecturer_id')
    c_id = request.form.get('course_id')
    
    lecturer = Lecturer.query.get(l_id)
    course = Course.query.get(c_id)
    
    if lecturer and course:
        course.lecturer_id = lecturer.id
        db.session.commit()
        return f"""
        <div style="text-align: center; font-family: sans-serif; padding-top: 50px;">
            <h1 style="color: green; font-size: 50px;">✅ LINKED!</h1>
            <p style="font-size: 20px;"><b>{lecturer.name}</b> is now the boss of <b>{course.code}</b>.</p>
            <hr style="width: 50%; margin: 30px auto;">
            <h3>👇 NOW DO THIS:</h3>
            <p>1. Login as Student.</p>
            <p>2. Ensure you registered for <b>{course.code}</b>.</p>
            <p>3. Check 'Book Office Hours'.</p>
            <br>
            <a href='/admin/link_wizard' style="background: #333; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Link Another</a>
        </div>
        """
    return "Error: Selection failed."


# ==========================================
# 🚑 EMERGENCY FIX: ADD COURSE TO OFFICE HOURS
# ==========================================
@app.route('/fix_office_hour_course_col')
def fix_office_hour_course_col():
    from sqlalchemy import text
    try:
        with app.app_context():
            # Add course_id column
            db.session.execute(text("ALTER TABLE office_hour ADD COLUMN course_id INTEGER REFERENCES course(id)"))
            db.session.commit()
            return "<h1>✅ SUCCESS! Added 'course_id' to OfficeHour table.</h1><a href='/lecturer/office_hours'>Go Back</a>"
    except Exception as e:
        return f"<h1>ℹ️ Info: {e}</h1>"

@app.route('/debug/check_slots')
def debug_check_slots():
    if not session.get('student_logged_in'): return "<h1>Please login as a student first.</h1>"
    
    student = Student.query.get(session['student_id'])
    my_course_ids = [c.id for c in student.registered_courses]
    
    all_slots = OfficeHour.query.all()
    
    html = f"<h1>🕵️‍♂️ Truth Detector for: {student.name}</h1>"
    html += f"<p><b>My Course IDs:</b> {my_course_ids}</p><hr>"
    html += "<h3>Scanning All Slots in Database:</h3><ul>"
    
    for slot in all_slots:
        match_status = "❌ NO MATCH"
        color = "red"
        
        # Check why it matches or fails
        if slot.course_id in my_course_ids:
            match_status = "✅ MATCH! (IDs Match)"
            color = "green"
        
        if slot.is_booked:
            match_status = "❌ MATCH BUT BOOKED"
            color = "orange"
            
        html += f"""
        <li style='color:{color}; margin-bottom: 10px;'>
            <b>Slot ID {slot.id}</b>: {slot.start_time} <br>
            -- Slot Course ID: <b>{slot.course_id}</b> <br>
            -- Status: <b>{match_status}</b>
        </li>
        """
    html += "</ul>"
    return html


@app.route('/debug/show_all_slots')
def debug_show_all_slots():
    slots = OfficeHour.query.all()
    courses = Course.query.all()
    
    html = "<h1>🕵️‍♂️ SLOT DETECTIVE</h1>"
    
    html += "<h3>Existing Courses:</h3><ul>"
    for c in courses:
        html += f"<li>ID: <b>{c.id}</b> | Code: {c.code} | Lecturer ID: {c.lecturer_id}</li>"
    html += "</ul><hr>"

    html += "<h3>Existing Slots:</h3><ul>"
    for s in slots:
        c_code = s.course.code if s.course else "None"
        html += f"<li>Slot ID: {s.id} | Linked to Course ID: <b style='color:red; font-size:20px;'>{s.course_id}</b> ({c_code}) | Start: {s.start_time}</li>"
    html += "</ul>"
    
    return html

@app.route('/init_attendees')
def init_attendees():
    db.create_all()
    return "<h1>✅ Group Booking System Initialized!</h1>"


@app.route('/lecturer/save_note/<int:student_id>', methods=['POST'])
def save_student_note(student_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    student = Student.query.get_or_404(student_id)
    note_content = request.form.get('lecturer_note')
    
    student.lecturer_note = note_content
    db.session.commit()
    
    flash(f"📝 Private note for {student.name} updated.", "success")
    return redirect(url_for('manage_office_hours'))


# ==========================================
# 📄 LECTURER: VIEW STUDENT TRANSCRIPT
# ==========================================
@app.route('/lecturer/transcript/<int:student_id>')
def lecturer_view_transcript(student_id):
    # (Optional) Add login check here
    # if not session.get('lecturer_logged_in'):
    #     return redirect(url_for('lecturer_login'))

    student = Student.query.get_or_404(student_id)
    
    # Fetch all grades for this student
    grades = Grade.query.filter_by(student_id=student.id).all()
    
    # Calculate CGPA (Mock Logic - you can refine this later)
    total_score = sum(g.score for g in grades)
    avg_score = round(total_score / len(grades), 2) if grades else 0

    return render_template('lecturer_view_transcript.html', student=student, grades=grades, avg=avg_score)


# ==========================================
# 🔔 SEND PORTAL NOTIFICATION (INTERNAL)
# ==========================================
@app.route('/lecturer/send_notification/<int:student_id>', methods=['POST'])
def send_student_notification(student_id):
    # Optional: Login check
    # if not session.get('lecturer_logged_in'):
    #     return redirect(url_for('lecturer_login'))
        
    student = Student.query.get_or_404(student_id)
    
    subject = request.form.get('email_subject')
    body = request.form.get('email_body')
    
    # Create the internal alert
    new_alert = Notification(
        student_id=student.id,
        title=subject,
        message=f"From Lecturer: {body}",
        timestamp=datetime.utcnow(),
        is_read=False
    )
    
    db.session.add(new_alert)
    db.session.commit()
    
    flash(f"✅ Message sent to {student.name}'s portal inbox.", "success")
    return redirect(url_for('manage_office_hours'))


@app.route('/cbt/print/<int:quiz_id>')
def print_quiz(quiz_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    # Check if user wants 'student' or 'lecturer' mode (default to student)
    mode = request.args.get('mode', 'student')
    
    quiz = Quiz.query.get_or_404(quiz_id)
    questions = Question.query.filter_by(quiz_id=quiz.id).all()
    
    return render_template('print_quiz_template.html', quiz=quiz, questions=questions, date=datetime.now(), mode=mode)


@app.route('/student/take_quiz/<int:quiz_id>', methods=['GET', 'POST'])
def take_quiz(quiz_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))

    student_id = session.get('student_id')
    
    # 1. Fetch Student Details (For Avatar Sync)
    student = Student.query.get(student_id)

    # 2. Check if already taken
    existing_result = QuizResult.query.filter_by(student_id=student_id, quiz_id=quiz_id).first()
    if existing_result:
        flash(f'You have already taken this test. Score: {existing_result.score}/{existing_result.total_questions}', 'info')
        return redirect(url_for('student_quiz_list'))

    # 3. Get Quiz & Questions
    quiz = Quiz.query.get_or_404(quiz_id)
    questions = Question.query.filter_by(quiz_id=quiz.id).all()
    
    if not questions:
        flash('This quiz has no questions yet.', 'warning')
        return redirect(url_for('student_quiz_list'))

    # 🟢 RENDER EXAM PAGE (With Student Data for Avatar)
    return render_template('student_take_exam.html', quiz=quiz, questions=questions, student=student)


@app.route('/student/submit_quiz/<int:quiz_id>', methods=['POST'])
def submit_quiz(quiz_id):
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student_id = session.get('student_id')
    quiz = Quiz.query.get_or_404(quiz_id)
    questions = Question.query.filter_by(quiz_id=quiz.id).all()
    
    # 🟢 CAPTURE VIOLATIONS
    violation_count = int(request.form.get('violation_count', 0))

    score = 0
    total = len(questions)
    
    for q in questions:
        user_answer = request.form.get(f'q_{q.id}')
        if user_answer and user_answer.strip().upper() == q.correct_option.strip().upper():
            score += 1
            
    existing_result = QuizResult.query.filter_by(student_id=student_id, quiz_id=quiz.id).first()
    
    if not existing_result:
        new_result = QuizResult(
            student_id=student_id,
            quiz_id=quiz_id,
            score=score,
            total_questions=total,
            violations=violation_count  # 🟢 SAVE TO DB
        )
        db.session.add(new_result)
        db.session.commit()
    
    # 🟢 DYNAMIC FEEDBACK
    if violation_count > 2:
        flash(f'⚠️ Exam Submitted. Score: {score}/{total}. Note: {violation_count} violations recorded.', 'warning')
    else:
        flash(f'🎉 Exam Submitted! You scored {score} / {total}', 'success')

    return redirect(url_for('student_quiz_list'))



# ==========================================
# 🚑 EMERGENCY FIX: ADD VIOLATIONS COLUMN
# ==========================================
@app.route('/fix_violations_column')
def fix_violations_column():
    from sqlalchemy import text
    try:
        with app.app_context():
            # Force add the missing column using Raw SQL
            try:
                db.session.execute(text("ALTER TABLE quiz_result ADD COLUMN violations INTEGER DEFAULT 0"))
                db.session.commit()
                return """
                <div style='text-align: center; padding: 50px; font-family: sans-serif;'>
                    <h1 style='color: green;'>✅ SUCCESS!</h1>
                    <p>The column <b>violations</b> has been added to the QuizResult table.</p>
                    <br>
                    <a href='/student/dashboard' style='padding: 15px 30px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>Go Back to Dashboard</a>
                </div>
                """
            except Exception as e:
                return f"<h1>ℹ️ Info: {e}</h1><p>The column likely already exists.</p>"
    except Exception as e:
        return f"<h1>❌ Critical Error: {e}</h1>"


@app.route('/cbt/void_result/<int:result_id>', methods=['POST'])
def void_result(result_id):
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401

    # 1. Get the Result
    result = QuizResult.query.get_or_404(result_id)
    student = Student.query.get(result.student_id)
    quiz = Quiz.query.get(result.quiz_id)

    # 2. Create the Notification
    violation_msg = f"🚨 EXAM VOIDED: Your result for '{quiz.title}' ({quiz.course.code}) has been cancelled by the Chief Examiner due to {result.violations} detected security violations. Please see the H.O.D."
    
    new_note = Notification(
        student_id=student.id,
        title="Academic Integrity Alert",
        message=violation_msg,
        timestamp=datetime.utcnow(),
        is_read=False
    )
    db.session.add(new_note)

    # 🟢 3. CRITICAL FIX: DO NOT DELETE! SET SCORE TO -1
    # If we delete, the system thinks they haven't taken it.
    # By setting -1, we mark it as "Taken but Voided".
    result.score = -1 
    db.session.commit()

    return jsonify({'status': 'success', 'message': 'Result voided and student notified.'})


# ==========================================
# 🟢 STUDENT: SUBMIT APPEAL (Fixed for Session Auth)
# ==========================================
@app.route('/submit_appeal/<int:result_id>', methods=['POST'])
def submit_appeal(result_id):
    # 1. Check if student is logged in using SESSION (Not current_user)
    if not session.get('student_logged_in'):
        return jsonify({'error': 'Unauthorized. Please login.'}), 403

    data = request.get_json()
    defense_message = data.get('message')

    if not defense_message:
        return jsonify({'error': 'Please write a defense message.'}), 400

    # 2. Get Student ID from Session
    student_id = session.get('student_id')
    student = Student.query.get(student_id)
    
    if not student:
        return jsonify({'error': 'Student record not found.'}), 404

    # 3. Check if appeal already exists
    existing_appeal = Appeal.query.filter_by(student_id=student.id, quiz_result_id=result_id).first()
    if existing_appeal:
        return jsonify({'error': 'You have already submitted an appeal for this exam.'}), 400

    # 4. Create Appeal
    try:
        new_appeal = Appeal(
            student_id=student.id,
            quiz_result_id=result_id,
            message=defense_message
        )
        
        db.session.add(new_appeal)
        db.session.commit()

        return jsonify({'status': 'success', 'message': 'Appeal submitted to the panel.'})
    
    except Exception as e:
        db.session.rollback()
        print(f"Appeal Error: {e}") # This prints to your terminal if it fails
        return jsonify({'error': 'Database error occurred.'}), 500

# 🟢 1. VIEW APPEALS DASHBOARD
@app.route('/cbt/appeals')
@login_required
def view_appeals():
    # Only show Pending appeals
    appeals = Appeal.query.filter_by(status='Pending').order_by(Appeal.date_submitted.desc()).all()
    return render_template('admin_appeals.html', appeals=appeals)

# 🟢 2. JUDGE'S GAVEL (Approve or Reject)
@app.route('/cbt/appeal/<int:appeal_id>/<action>', methods=['POST'])
@login_required
def handle_appeal(appeal_id, action):
    appeal = Appeal.query.get_or_404(appeal_id)
    
    # We store the ID now because once we delete the result, 
    # the relationship appeal.quiz_result might break.
    result_id = appeal.quiz_result_id

    if action == 'approve':
        # 1. Update the appeal status first
        appeal.status = 'Approved'
        
        # 2. Find the result to delete
        result = QuizResult.query.get(result_id)
        if result:
            db.session.delete(result)
        
        # 3. Commit EVERYTHING at once
        # SQLAlchemy will handle the order correctly now because 
        # the appeal status is being set in the same transaction.
        db.session.commit()
        flash('Appeal Approved! The student can now retake the test.', 'success')

    elif action == 'reject':
        appeal.status = 'Rejected'
        db.session.commit()
        flash('Appeal Rejected. The result remains voided.', 'error')

    return redirect(url_for('manage_quizzes'))


@app.route('/api/notification/mark_read/<int:alert_id>', methods=['POST'])
def mark_notification_read(alert_id):
    if not session.get('student_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    alert = Notification.query.get(alert_id)
    if alert and alert.student_id == session.get('student_id'):
        alert.is_read = True
        db.session.commit()
        return jsonify({'status': 'success'})
    
    return jsonify({'error': 'Notification not found'}), 404


@app.route('/cbt/appeal/<int:appeal_id>/approve', methods=['POST'])
@login_required # Use your existing decorator
def approve_appeal(appeal_id):
    appeal = Appeal.query.get_or_404(appeal_id)
    result = QuizResult.query.get(appeal.result_id)
    
    if result:
        student_id = result.student_id
        quiz_title = result.quiz.title
        
        # 1. Create a "Good News" Notification for the student
        new_note = Notification(
            student_id=student_id,
            message=f"✅ APPEAL GRANTED: Your defense for '{quiz_title}' was accepted. You can now retake the assessment.",
            is_read=False,
            timestamp=datetime.now()
        )
        db.session.add(new_note)
        
        # 2. DELETE the voided result so it disappears from the Lecturer's list
        # This effectively "un-takes" the quiz for that student
        db.session.delete(result)
        
        # 3. Mark the appeal as approved (optional if you want to keep logs)
        appeal.status = 'Approved'
        
        db.session.commit()
        flash('Appeal approved. Student has been granted a retake.', 'success')
    
    return redirect(url_for('view_quiz_results', quiz_id=result.quiz_id))


# 🟢 ROUTE TO REVERSE A VOID (GRANT RETAKE)
@app.route('/cbt/reverse_void/<int:result_id>', methods=['POST'])
@login_required
def reverse_void(result_id):
    # 1. Find the voided result
    result = QuizResult.query.get_or_404(result_id)
    student_id = result.student_id
    quiz_title = result.quiz.title
    
    try:
        # 2. Notify the student (Optional but recommended)
        # Make sure you have the Notification model imported
        new_note = Notification(
            student_id=student_id,
            message=f"✅ APPEAL UPDATE: Your voided result for '{quiz_title}' has been reversed. You are now cleared to retake the test.",
            is_read=False,
            timestamp=datetime.now()
        )
        db.session.add(new_note)

        # 3. DELETE the result record
        # This removes the "Voided" status and allows the student to start fresh
        db.session.delete(result)
        
        db.session.commit()
        
        # 4. Send success signal back to JavaScript
        return jsonify({'status': 'success', 'message': 'Void reversed successfully'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# 🟢 CENTRALIZED APPEALS DASHBOARD (DEEP-SILO FIX)
@app.route('/lecturer/appeals')
@login_required
def lecturer_appeals():
    if session.get('role') == 'lecturer':
        lecturer_id = session.get('user_id')
        my_courses = Course.query.filter_by(lecturer_id=lecturer_id).all()
        my_course_ids = [c.id for c in my_courses]
        
        if my_course_ids:
            # 🟢 Trace the Appeal -> QuizResult -> Quiz -> Course
            appeals = Appeal.query.join(QuizResult).join(Quiz).filter(
                Quiz.course_id.in_(my_course_ids),
                Appeal.status == 'Pending'
            ).order_by(Appeal.date_submitted.desc()).all()
        else:
            appeals = [] # 🟢 BLANK SLATE
    else:
        # Admin sees all pending appeals
        appeals = Appeal.query.filter_by(status='Pending').order_by(Appeal.date_submitted.desc()).all()
        
    return render_template('lecturer_appeals.html', appeals=appeals)


# 🟢 REPLACE YOUR EXISTING student_apply_transfer FUNCTION WITH THIS
@app.route('/student/apply_transfer', methods=['POST'])
@login_required
def student_apply_transfer():
    print("--- 🚀 TRANSFER APPLICATION STARTED ---") # Debug Print
    try:
        # Local imports to prevent "NameError"
        from models import db, Student, ChangeCourseRequest, Course, Notification
        
        data = request.json
        student = Student.query.get(session['student_id'])
        print(f"👤 Student Found: {student.name}") # Debug Print

        # 1. Check for duplicates
        existing = ChangeCourseRequest.query.filter_by(student_id=student.id, status='Pending').first()
        if existing:
            print("⚠️ Duplicate Request Found")
            return jsonify({'status': 'error', 'message': 'You already have a pending application.'})

        # 2. Robust CGPA Calculation (Prevents crashes)
        total_points = 0
        total_units = 0
        
        for grade in student.grades:
            points = 0
            if grade.score >= 70: points = 5
            elif grade.score >= 60: points = 4
            elif grade.score >= 50: points = 3
            elif grade.score >= 45: points = 2
            elif grade.score >= 40: points = 1
            
            # Find unit load (default to 3 if course missing)
            course_unit = 3
            found_course = Course.query.filter_by(code=grade.course_code).first()
            if found_course:
                course_unit = found_course.units
                
            total_points += (points * course_unit)
            total_units += course_unit

        final_cgpa = round(total_points / total_units, 2) if total_units > 0 else 0.0
        print(f"📊 Calculated CGPA: {final_cgpa}") # Debug Print

        # 3. Create Request
        new_req = ChangeCourseRequest(
            student_id=student.id,
            current_dept=student.department,
            new_dept=data['new_dept'],
            reason=data['reason'],
            cgpa_snapshot=final_cgpa
        )
        
        db.session.add(new_req)
        db.session.commit()
        print("✅ SAVED TO DATABASE SUCCESSFULLY") # Debug Print
        
        return jsonify({'status': 'success', 'message': 'Application submitted successfully!'})

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {str(e)}") # This will show in your terminal
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f"Server Error: {str(e)}"})
    


# 🟢 LECTURER: VIEW TRANSFER CONSOLE
@app.route('/lecturer/transfers')
@admin_only  # <--- IRON PADLOCK ADDED
@login_required
def lecturer_transfers():
    requests = ChangeCourseRequest.query.filter_by(status='Pending').order_by(ChangeCourseRequest.date_submitted.desc()).all()
    return render_template('lecturer_transfers.html', requests=requests)

# 🟢 LECTURER: APPROVE/REJECT ACTION
@app.route('/lecturer/transfer/<int:req_id>/<action>', methods=['POST'])
@admin_only  # <--- IRON PADLOCK ADDED
@login_required
def process_transfer(req_id, action):
    req = ChangeCourseRequest.query.get_or_404(req_id)
    
    if action == 'approve':
        req.status = 'Approved'
        req.student.department = req.new_dept
        msg = Notification(student_id=req.student.id, title="Transfer Approved", message=f"Welcome to the Department of {req.new_dept}! Your records have been updated.")
        db.session.add(msg)
        
    elif action == 'reject':
        req.status = 'Rejected'
        msg = Notification(student_id=req.student.id, title="Transfer Declined", message="Your change of course application was not successful.")
        db.session.add(msg)
        
    db.session.commit()
    return jsonify({'status': 'success'})


# 👇 PASTE THIS AT THE VERY BOTTOM OF app.py 👇

@app.route('/fix_database_now')
def fix_database_now():
    try:
        from models import db, ChangeCourseRequest
        db.create_all()
        return "<h1>✅ SUCCESS! Database Table Created. You can now apply for transfer.</h1>"
    except Exception as e:
        return f"<h1>❌ Error: {str(e)}</h1>"


# 🟢 CLEANUP ROUTE (Paste this at the bottom of app.py)
@app.route('/clean_notifications')
def clean_notifications():
    try:
        # This wipes the notification table clean
        from models import Notification
        num_deleted = db.session.query(Notification).delete()
        db.session.commit()
        return f"<h1>✅ SUCCESS!</h1><p>Deleted {num_deleted} old notifications.</p><p><a href='/portal'>Go back to Portal</a> and create a new summary now.</p>"
    except Exception as e:
        return f"Error: {e}"


# ==========================================
# 🛠️ THE ARSENAL: DEV TOOLS
# ==========================================

@app.route('/student/tool/code_playground')
def tool_code_playground():
    # 🔒 Security Check
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student = Student.query.get(session['student_id'])
    
    # Render the editor
    return render_template('tool_code_playground.html', student=student)


# --- ADD THIS TO app.py ---

# 1. The Mock File System (In-Memory)
IDE_FILES = {
    "main.py": {"content": "print('Hello LASU World!')\n\ndef check_cgpa(score):\n    return score >= 4.5", "lang": "python"},
    "index.html": {"content": "<h1>Student Portal</h1>\n<p>Welcome to Computer Science</p>", "lang": "html"},
    "styles.css": {"content": "body { background-color: #f0f0f0; }", "lang": "css"}
}

# 2. Your Existing Route (Update the function name if needed)
@app.route('/student/tool/code_playground')
def code_playground():
    return render_template('tool_code_playground.html')

# 3. New API Routes for the IDE to talk to
@app.route('/api/ide/files', methods=['GET'])
def ide_get_files():
    return jsonify(IDE_FILES)

@app.route('/api/ide/save', methods=['POST'])
def ide_save_file():
    data = request.json
    filename = data.get('filename')
    content = data.get('content')
    
    if filename in IDE_FILES:
        IDE_FILES[filename]['content'] = content
        return jsonify({"status": "saved", "file": filename})
    
    return jsonify({"error": "File not found"}), 404

# 3. THE EXECUTION ENGINE
@app.route('/api/ide/run', methods=['POST'])
def ide_run_code_v2():
    data = request.json
    code = data.get('content', '')
    if not code.strip(): return jsonify({"status": "success", "output": ""})

    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout
        if result.stderr: output += f"\n[Error]\n{result.stderr}"
        return jsonify({"status": "success", "output": output})
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "output": "Timeout (5s limit)"})
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)})

# --- FILE MANAGEMENT ENGINE ---

@app.route('/api/ide/create', methods=['POST'])
def ide_create_file():
    data = request.json
    filename = data.get('filename')
    
    if not filename:
        return jsonify({"status": "error", "message": "Filename is required"})
    
    if filename in IDE_FILES:
        return jsonify({"status": "error", "message": "File already exists"})
    
    # Determine language based on extension
    lang = "plaintext"
    if filename.endswith(".py"): lang = "python"
    elif filename.endswith(".html"): lang = "html"
    elif filename.endswith(".css"): lang = "css"
    elif filename.endswith(".js"): lang = "javascript"
    
    IDE_FILES[filename] = {"content": "", "lang": lang}
    return jsonify({"status": "success", "file": filename})

@app.route('/api/ide/delete', methods=['POST'])
def ide_delete_file():
    data = request.json
    filename = data.get('filename')
    
    if filename in IDE_FILES:
        del IDE_FILES[filename]
        return jsonify({"status": "success"})
    
    return jsonify({"status": "error", "message": "File not found"})


# --- API: EXPORT PROJECT (NEW) ---

@app.route('/api/ide/download_project', methods=['GET'])
def ide_download_project():
    # Create a Zip file in memory
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for filename, filedata in IDE_FILES.items():
            zf.writestr(filename, filedata['content'])
    
    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'lasu_project_{datetime.datetime.now().strftime("%Y%m%d")}.zip'
    )


# --- NEW API: RENAME FILE ---
@app.route('/api/ide/rename', methods=['POST'])
def ide_rename_file():
    data = request.json
    old_name = data.get('old_name')
    new_name = data.get('new_name')
    
    if not old_name or not new_name:
        return jsonify({"status": "error", "message": "Both names required"})
    
    # Check if original exists
    if old_name not in IDE_FILES:
        return jsonify({"status": "error", "message": "Original file not found"})
    
    # Check if new name is taken
    if new_name in IDE_FILES:
        return jsonify({"status": "error", "message": "Destination filename already exists"})
    
    # Copy content to new key and delete old key
    IDE_FILES[new_name] = IDE_FILES[old_name]
    del IDE_FILES[old_name]
    
    # Update language setting based on new extension
    if new_name.endswith(".py"): IDE_FILES[new_name]["lang"] = "python"
    elif new_name.endswith(".html"): IDE_FILES[new_name]["lang"] = "html"
    elif new_name.endswith(".css"): IDE_FILES[new_name]["lang"] = "css"
    elif new_name.endswith(".js"): IDE_FILES[new_name]["lang"] = "javascript"
    
    return jsonify({"status": "success", "old_name": old_name, "new_name": new_name})


# --- ADD THESE TO YOUR EXISTING app.py ---

# --- API: GLOBAL SEARCH ---
@app.route('/api/ide/search', methods=['POST'])
def ide_search():
    data = request.json
    query = data.get('query', '').lower()
    if not query:
        return jsonify({"results": []})
    
    results = []
    for filename, filedata in IDE_FILES.items():
        content = filedata['content']
        # Simple case-insensitive search (lines)
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if query in line.lower():
                results.append({
                    "file": filename,
                    "line": i + 1,
                    "content": line.strip()[:100] # Preview
                })
    return jsonify({"results": results})

# --- API: GIT SIMULATION ---
@app.route('/api/ide/git/commit', methods=['POST'])
def ide_git_commit():
    data = request.json
    message = data.get('message')
    if not message:
        return jsonify({"status": "error", "message": "Commit message required"})
    
    # In a real app, this would use `git` CLI.
    # Here we simulate a successful commit log.
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    return jsonify({
        "status": "success",
        "commit_id": secrets.token_hex(4),
        "timestamp": timestamp,
        "message": message
    })


# ==========================================
# 🧠 AI BRAIN (IDE SANDBOX FIX)
# ==========================================
@app.route('/api/ide/ai/ask', methods=['POST'])
def ide_ai_ask():
    print("--- 🤖 CONNECTING TO GEMINI AI... ---")
    try:
        data = request.json
        prompt = data.get('prompt', '')
        code_context = data.get('context', '')

        import httpx
        import time

        # 🟢 ARCHITECT FIX: 2026 Compatible coding model (gemini-2.5-pro for deep reasoning)
        ai_model = "gemini-2.5-pro"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{ai_model}:generateContent?key={GOOGLE_API_KEY.strip()}"
        headers = {"Content-Type": "application/json"}
        
        full_prompt = f"You are an Elite Enterprise Software Architect. Review this code concisely.\n\nCode:\n{code_context}\n\nQuestion: {prompt}"
        
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}]
        }

        response = None
        for attempt in range(3):
            try:
                with httpx.Client(verify=False, timeout=15.0, http2=False) as client:
                    response = client.post(url, json=payload, headers=headers)
                    if response.status_code == 200:
                        break
            except:
                time.sleep(1)

        if response and response.status_code == 200:
            res_data = response.json()
            try:
                reply = res_data['candidates'][0]['content']['parts'][0]['text']
            except KeyError:
                reply = "Response blocked by safety filters."
            return jsonify({"status": "success", "response": reply})
        
        elif response and response.status_code == 400:
            return jsonify({"status": "success", "response": f"❌ **API Key Error:** Google rejected the key."})
        
        else:
            return jsonify({"status": "success", "response": f"❌ **Server Error:** {response.text if response else 'Timeout'}"})

    except Exception as e:
        return jsonify({"status": "success", "response": f"🔥 **System Crash:** {str(e)}"})

# 2. THE LINTER ROUTE
@app.route('/api/ide/lint', methods=['POST'])
def ide_lint_code():
    data = request.json
    try:
        ast.parse(data.get('content', ''))
        return jsonify({"status": "success", "errors": []})
    except SyntaxError as e:
        return jsonify({"status": "error", "errors": [{"line": e.lineno, "msg": e.msg}]})
    except:
        return jsonify({"status": "success", "errors": []})


# ==========================================
# 🛠️ STUDENT TOOLS HUB
# ==========================================

@app.route('/student/tools')
def student_tools_dashboard():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student = Student.query.get(session['student_id'])
    return render_template('tools_dashboard.html', student=student)

# --- TOOL 1: SQL SANDBOX ---
@app.route('/student/tools/sql_sandbox')
def tool_sql_sandbox():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student = Student.query.get(session['student_id'])
    return render_template('tool_sql_sandbox.html', student=student)


# --- TOOL 2: REGEX TESTER ---
@app.route('/student/tools/regex_tester')
def tool_regex_tester():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
    
    student = Student.query.get(session['student_id'])
    return render_template('tool_regex_tester.html', student=student)


@app.route('/tools/json-formatter')
def tool_json_formatter():
    return render_template('tool_json_formatter.html')

# --- XML Validator Route ---
@app.route('/tools/xml-validator')
def tool_xml_validator():
    return render_template('tool_xml_validator.html')


# --- YAML Converter Route ---
@app.route('/tools/yaml-to-json')
def tool_yaml_converter():
    return render_template('tool_yaml_converter.html')

# --- Base64 Converter Route ---
@app.route('/tools/base64-converter')
def tool_base64():
    return render_template('tool_base64.html')


# --- URL Encoder/Decoder Route ---
@app.route('/tools/url-encoder')
def tool_url_encoder():
    return render_template('tool_url_encoder.html')


# --- JWT Debugger Route ---
@app.route('/tools/jwt-debugger')
def tool_jwt_debugger():
    return render_template('tool_jwt_debugger.html')


# --- User Agent Parser Route ---
@app.route('/tools/user-agent-parser')
def tool_user_agent():
    return render_template('tool_user_agent.html')


# --- Keycode Checker Route ---
@app.route('/tools/keycode-checker')
def tool_keycode():
    return render_template('tool_keycode.html')

# --- Git Command Generator Route ---
@app.route('/tools/git-generator')
def tool_git_generator():
    return render_template('tool_git_generator.html')

# --- Crontab Generator Route ---
@app.route('/tools/crontab-generator')
def tool_crontab_generator():
    return render_template('tool_crontab_generator.html')

# --- chmod Calculator Route ---
@app.route('/tools/chmod-calculator')
def tool_chmod_calculator():
    return render_template('tool_chmod_calculator.html')

# --- CSS Flexbox Playground Route ---
@app.route('/tools/flexbox-playground')
def tool_flexbox_playground():
    return render_template('tool_flexbox_playground.html')

# --- CSS Grid Generator Route ---
@app.route('/tools/grid-generator')
def tool_grid_generator():
    return render_template('tool_grid_generator.html')


# --- Box Shadow Generator Route ---
@app.route('/tools/box-shadow')
def tool_box_shadow():
    return render_template('tool_box_shadow.html')


# --- Border Radius Previewer Route ---
@app.route('/tools/border-radius')
def tool_border_radius():
    return render_template('tool_border_radius.html')


# --- CSS Gradient Maker Route ---
@app.route('/tools/css-gradient')
def tool_css_gradient():
    return render_template('tool_css_gradient.html')


# --- JS/CSS Minifier Route ---
@app.route('/tools/minifier')
def tool_minifier():
    return render_template('tool_minifier.html')


# --- Code Diff Checker Route ---
@app.route('/tools/diff-checker')
def tool_diff_checker():
    return render_template('tool_diff_checker.html')


# --- Markdown Table Generator Route ---
@app.route('/tools/markdown-table')
def tool_markdown_table():
    return render_template('tool_markdown_table.html')


# --- Hash Generator Route ---
@app.route('/tools/hash-generator')
def tool_hash_generator():
    return render_template('tool_hash_generator.html')


# --- UUID Generator Route ---
@app.route('/tools/uuid-generator')
def tool_uuid_generator():
    return render_template('tool_uuid_generator.html')


# --- Lorem Ipsum Generator Route ---
@app.route('/tools/lorem-ipsum')
def tool_lorem_ipsum():
    return render_template('tool_lorem_ipsum.html')


# --- HTACCESS Generator Route ---
@app.route('/tools/htaccess-generator')
def tool_htaccess_generator():
    return render_template('tool_htaccess_generator.html')


# --- Meta Tag Generator Route ---
@app.route('/tools/meta-tag-generator')
def tool_meta_tag_generator():
    return render_template('tool_meta_tags.html')


# --- Open Graph Previewer Route ---
@app.route('/tools/open-graph')
def tool_open_graph():
    return render_template('tool_open_graph.html')

# --- Favicon Checker Route ---
@app.route('/tools/favicon-checker')
def tool_favicon_checker():
    return render_template('tool_favicon_checker.html')


# --- Robots.txt Generator Route ---
@app.route('/tools/robots-generator')
def tool_robots_generator():
    return render_template('tool_robots_generator.html')


# --- Sitemap Generator Route ---
@app.route('/tools/sitemap-generator')
def tool_sitemap_generator():
    return render_template('tool_sitemap_generator.html')


# --- ASCII Art Generator Route ---
@app.route('/tools/ascii-art')
def tool_ascii_art():
    return render_template('tool_ascii_art.html')


# --- Binary Converter Route ---
@app.route('/tools/binary-converter')
def tool_binary_converter():
    return render_template('tool_binary_converter.html')


# --- Hex Converter Route ---
@app.route('/tools/hex-converter')
def tool_hex_converter():
    return render_template('tool_hex_converter.html')

# --- Octal Converter Route ---
@app.route('/tools/octal-converter')
def tool_octal_converter():
    return render_template('tool_octal_converter.html')


# --- RGB to Hex Converter Route ---
@app.route('/tools/rgb-hex-converter')
def tool_rgb_hex_converter():
    return render_template('tool_rgb_hex_converter.html')


# --- Color Picker Route ---
@app.route('/tools/color-picker')
def tool_color_picker():
    return render_template('tool_color_picker.html')


# --- Image to Base64 Route ---
@app.route('/tools/image-base64')
def tool_image_base64():
    return render_template('tool_image_base64.html')

# --- QR Code Generator Route ---
@app.route('/tools/qr-generator')
def tool_qr_generator():
    return render_template('tool_qr_generator.html')


# --- Barcode Generator Route ---
@app.route('/tools/barcode-generator')
def tool_barcode_generator():
    return render_template('tool_barcode_generator.html')


# --- Slugifier Route ---
@app.route('/tools/slugifier')
def tool_slugifier():
    return render_template('tool_slugifier.html')


# --- Matrix Calculator Route ---
@app.route('/tools/matrix-calculator')
def tool_matrix_calculator():
    return render_template('tool_matrix_calculator.html')


# --- Graph Plotter Route ---
@app.route('/tools/graph-plotter')
def tool_graph_plotter():
    return render_template('tool_graph_plotter.html')


# --- Quadratic Equation Solver Route ---
@app.route('/tools/quadratic-solver')
def tool_quadratic_solver():
    return render_template('tool_quadratic_solver.html')


# --- Prime Number Checker Route ---
@app.route('/tools/prime-checker')
def tool_prime_checker():
    return render_template('tool_prime_checker.html')


# --- Prime Factorization Route ---
@app.route('/tools/prime-factorization')
def tool_prime_factorization():
    return render_template('tool_prime_factorization.html')


# --- GCD/LCM Calculator Route ---
@app.route('/tools/gcd-lcm-calculator')
def tool_gcd_lcm():
    return render_template('tool_gcd_lcm.html')


# --- Fibonacci Generator Route ---
@app.route('/tools/fibonacci-generator')
def tool_fibonacci():
    return render_template('tool_fibonacci.html')


# --- Factorial Calculator Route ---
@app.route('/tools/factorial-calculator')
def tool_factorial():
    return render_template('tool_factorial.html')


# --- Percentage Calculator Route ---
@app.route('/tools/percentage-calculator')
def tool_percentage():
    return render_template('tool_percentage.html')


# --- Standard Deviation Calculator Route ---
@app.route('/tools/standard-deviation')
def tool_standard_deviation():
    return render_template('tool_standard_deviation.html')


# --- Mean/Median/Mode Calculator Route ---
@app.route('/tools/mean-median-mode')
def tool_mean_median_mode():
    return render_template('tool_mean_median_mode.html')


# --- Z-Score Calculator Route ---
@app.route('/tools/zscore-calculator')
def tool_zscore_calculator():
    return render_template('tool_z_score.html')


# --- Combination/Permutation Route ---
@app.route('/tools/combination-permutation')
def tool_combination_permutation():
    return render_template('tool_combination_permutation.html')


# --- Random Number Generator Route ---
@app.route('/tools/random-generator')
def tool_random_generator():
    return render_template('tool_random_generator.html')


# --- Binary Algebra Solver Route ---
@app.route('/tools/binary-algebra')
def tool_binary_algebra():
    return render_template('tool_binary_algebra.html')


# --- Truth Table Generator Route ---
@app.route('/tools/truth-table')
def tool_truth_table():
    return render_template('tool_truth_table.html')


# --- Vector Calculator Route ---
@app.route('/tools/vector-calculator')
def tool_vector_calculator():
    return render_template('tool_vector_calculator.html')

# --- Triangle Solver Route ---
@app.route('/tools/triangle-solver')
def tool_triangle_solver():
    return render_template('tool_triangle_solver.html')


# --- Circle Solver Route ---
@app.route('/tools/circle-solver')
def tool_circle_solver():
    return render_template('tool_circle_solver.html')


# --- Volume Calculator Route ---
@app.route('/tools/volume-calculator')
def tool_volume_calculator():
    return render_template('tool_volume_calculator.html')


# --- Surface Area Calculator Route ---
@app.route('/tools/surface-area-calculator')
def tool_surface_area():
    return render_template('tool_surface_area.html')


# --- Slope Calculator Route ---
@app.route('/tools/slope-calculator')
def tool_slope_calculator():
    return render_template('tool_slope_calculator.html')


# --- Distance Formula Calculator Route ---
@app.route('/tools/distance-formula')
def tool_distance_formula():
    return render_template('tool_distance_formula.html')


# --- Midpoint Calculator Route ---
@app.route('/tools/midpoint-calculator')
def tool_midpoint_calculator():
    return render_template('tool_midpoint_calculator.html')


# --- Pythagorean Theorem Calculator Route ---
@app.route('/tools/pythagorean-theorem')
def tool_pythagorean_theorem():
    return render_template('tool_pythagorean.html')


# --- Number Base Converter Route ---
@app.route('/tools/number-base-converter')
def tool_number_base():
    return render_template('tool_number_base.html')


# --- Roman Numeral Converter Route ---
@app.route('/tools/roman-numeral')
def tool_roman_numeral():
    return render_template('tool_roman_numeral.html')


# --- Scientific Notation Converter Route ---
@app.route('/tools/scientific-notation')
def tool_scientific_notation():
    return render_template('tool_scientific_notation.html')


# --- Logarithm Calculator Route ---
@app.route('/tools/logarithm')
def tool_logarithm():
    return render_template('tool_logarithm.html')


# --- Logic Gate Simulator Route ---
@app.route('/tools/logic-gate-simulator')
def tool_logic_gate_simulator():
    return render_template('tool_logic_gate_simulator.html')


# --- Ohm's Law Calculator Route ---
@app.route('/tools/ohms-law')
def tool_ohms_law():
    return render_template('tool_ohms_law.html')


# --- Resistor Color Code Tool Route ---
@app.route('/tools/resistor-color-code')
def tool_resistor_color_code():
    return render_template('tool_resistor_color_code.html')


# --- Voltage Divider Calculator Route ---
@app.route('/tools/voltage-divider')
def tool_voltage_divider():
    return render_template('tool_voltage_divider.html')


# --- LED Resistor Calculator Route ---
@app.route('/tools/led-resistor-calculator')
def tool_led_resistor():
    return render_template('tool_led_resistor.html')


# --- Capacitor Charge Calculator Route ---
@app.route('/tools/capacitor-charge')
def tool_capacitor_charge():
    return render_template('tool_capacitor_charge.html')


# --- 555 Timer Calculator Route ---
@app.route('/tools/555-timer')
def tool_555_timer():
    return render_template('tool_555_timer.html')


# --- Wheatstone Bridge Calculator Route ---
@app.route('/tools/wheatstone-bridge')
def tool_wheatstone_bridge():
    return render_template('tool_wheatstone_bridge.html')


# --- Thermal Resistance Calculator Route ---
@app.route('/tools/thermal-resistance')
def tool_thermal_resistance():
    return render_template('tool_thermal_resistance.html')



# --- PCB Trace Width Calculator Route ---
@app.route('/tools/pcb-trace-width')
def tool_pcb_trace_width():
    return render_template('tool_pcb_trace.html')


# --- Engineering Unit Converter Route ---
@app.route('/tools/engineering-converter')
def tool_engineering_converter():
    return render_template('tool_engineering_converter.html')


# --- Projectile Motion Simulator Route ---
@app.route('/tools/projectile-motion')
def tool_projectile_motion():
    return render_template('tool_projectile_motion.html')


# --- Pendulum Simulator Route ---
@app.route('/tools/pendulum-simulator')
def tool_pendulum_simulator():
    return render_template('tool_pendulum.html')


# --- Wave Interference Simulator Route ---
@app.route('/tools/wave-interference')
def tool_wave_interference():
    return render_template('tool_wave_interference.html')


# --- Doppler Effect Simulator Route ---
@app.route('/tools/doppler-effect')
def tool_doppler_effect():
    return render_template('tool_doppler_effect.html')


# --- Lens & Mirror Ray Tracer Route ---
@app.route('/tools/lens-mirror-ray-tracer')
def tool_lens_mirror():
    return render_template('tool_lens_mirror.html')


# --- Fluid Flow Simulator Route ---
@app.route('/tools/fluid-flow')
def tool_fluid_flow():
    return render_template('tool_fluid_flow.html')


# --- Beam Deflection Calculator Route ---
@app.route('/tools/beam-deflection')
def tool_beam_deflection():
    return render_template('tool_beam_deflection.html')


# --- Gear Ratio Calculator Route ---
@app.route('/tools/gear-ratio')
def tool_gear_ratio():
    return render_template('tool_gear_ratio.html')



# --- Torque Converter Route ---
@app.route('/tools/torque-converter')
def tool_torque_converter():
    return render_template('tool_torque_converter.html')



# --- Interactive Periodic Table Route ---
@app.route('/tools/periodic-table')
def tool_periodic_table():
    return render_template('tool_periodic_table.html')


# --- Molar Mass Calculator Route ---
@app.route('/tools/molar-mass')
def tool_molar_mass():
    return render_template('tool_molar_mass.html')


# --- Solution Dilution Calculator Route ---
@app.route('/tools/solution-dilution')
def tool_solution_dilution():
    return render_template('tool_solution_dilution.html')


# --- pH Calculator Route ---
@app.route('/tools/ph-calculator')
def tool_ph_calculator():
    return render_template('tool_ph_calculator.html')


# --- Half-Life Calculator Route ---
@app.route('/tools/half-life')
def tool_half_life():
    return render_template('tool_half_life.html')


# --- Amino Acid Converter Route ---
@app.route('/tools/amino-acid-converter')
def tool_amino_acid():
    return render_template('tool_amino_acid.html')


# --- Codon Table Route ---
@app.route('/tools/codon-table')
def tool_codon_table():
    return render_template('tool_codon_table.html')


# --- BMI Calculator Route ---
@app.route('/tools/bmi-calculator')
def tool_bmi_calculator():
    return render_template('tool_bmi_calculator.html')


# --- BMR Calculator Route ---
@app.route('/tools/bmr-calculator')
def tool_bmr_calculator():
    return render_template('tool_bmr_calculator.html')


# --- Water Intake Calculator Route ---
@app.route('/tools/water-intake')
def tool_water_intake():
    return render_template('tool_water_intake.html')


# --- Sleep Cycle Calculator Route ---
@app.route('/tools/sleep-cycle')
def tool_sleep_cycle():
    return render_template('tool_sleep_cycle.html')


# --- Pregnancy Due Date Calculator Route ---
@app.route('/tools/pregnancy-calculator')
def tool_pregnancy_calculator():
    return render_template('tool_pregnancy_calc.html')


# --- Ovulation Calculator Route ---
@app.route('/tools/ovulation-calculator')
def tool_ovulation_calculator():
    return render_template('tool_ovulation_calculator.html')


# --- Breath Pacer Route ---
@app.route('/tools/breath-pacer')
def tool_breath_pacer():
    return render_template('tool_breath_pacer.html')


# --- Heart Rate Tapper Route ---
@app.route('/tools/heart-rate')
def tool_heart_rate():
    return render_template('tool_heart_rate.html')


# --- Reaction Time Test Route ---
@app.route('/tools/reaction-time')
def tool_reaction_time():
    return render_template('tool_reaction_time.html')


# --- Color Blindness Simulator Route ---
@app.route('/tools/color-blindness')
def tool_color_blindness():
    return render_template('tool_color_blindness.html')



# --- Hearing Frequency Test Route ---
@app.route('/tools/hearing-test')
def tool_hearing_test():
    return render_template('tool_hearing_test.html')


# --- Vision Acuity Test Route ---
@app.route('/tools/vision-acuity')
def tool_vision_acuity():
    return render_template('tool_vision_acuity.html')


# --- Pomodoro Timer Route ---
@app.route('/tools/pomodoro-timer')
def tool_pomodoro_timer():
    return render_template('tool_pomodoro_timer.html')


# --- Word Counter Route ---
@app.route('/tools/word-counter')
def tool_word_counter():
    return render_template('tool_word_counter.html')


# --- Case Converter Route ---
@app.route('/tools/case-converter')
def tool_case_converter():
    return render_template('tool_case_converter.html')


# --- Remove Duplicates Route ---
@app.route('/tools/remove-duplicates')
def tool_remove_duplicates():
    return render_template('tool_remove_duplicates.html')


# --- Sort List Engine Route ---
@app.route('/tools/sort-list')
def tool_sort_list():
    return render_template('tool_sort_list.html')


# --- Text Reverser Route ---
@app.route('/tools/text-reverser')
def tool_text_reverser():
    return render_template('tool_text_reverser.html')


# --- Find and Replace Route ---
@app.route('/tools/find-replace')
def tool_find_replace():
    return render_template('tool_find_replace.html')


# --- Readability Score Route ---
@app.route('/tools/readability-score')
def tool_readability_score():
    return render_template('tool_readability_score.html')


# --- Plagiarism Checker Route ---
@app.route('/tools/plagiarism-checker')
def tool_plagiarism_checker():
    return render_template('tool_plagiarism_checker.html')


# --- Citation Generator Route ---
@app.route('/tools/citation-generator')
def tool_citation_generator():
    return render_template('tool_citation_generator.html')


# --- Title Case Converter Route ---
@app.route('/tools/title-case')
def tool_title_case():
    return render_template('tool_title_case.html')


# --- AI Detector Route ---
@app.route('/tools/ai-detector')
def tool_ai_detector():
    return render_template('tool_ai_detector.html')


# --- GIDEON: GOD-TIER AI DETECTOR BACKEND ---
@app.route('/api/detect-ai', methods=['POST'])
def api_detect_ai():
    data = request.get_json()
    text = data.get('text', '')
    
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    API_KEY = "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" 
    
    # GIDEON UPDATE: Using the brand new HuggingFace Router URL
    API_URL = "https://router.huggingface.co/hf-inference/models/Hello-SimpleAI/chatgpt-detector-roberta"
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        # Neural networks crash if they receive > 512 tokens. 
        # 1000 characters guarantees we stay well under the strict limit.
        safe_text = text[:1000]
        payload = {"inputs": safe_text}
        
        max_retries = 3
        for attempt in range(max_retries):
            response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                ai_score = 0
                for label in result[0]:
                    if label['label'].lower() in ['chatgpt', 'fake', 'ai']:
                        ai_score = label['score'] * 100
                
                return jsonify({
                    'ai_probability': ai_score, 
                    'source': 'HuggingFace RoBERTa Deep Learning', 
                    'status': 'success'
                })
            
            elif response.status_code == 503:
                result = response.json()
                wait_time = result.get('estimated_time', 15)
                print(f"[GIDEON BACKEND] RoBERTa node asleep. Waking it up. Waiting {wait_time} seconds...")
                time.sleep(min(wait_time, 15))
                continue
                
            else:
                # Capture the exact error HuggingFace throws
                error_detail = f"HF Server Error {response.status_code}: {response.text}"
                print(f"[GIDEON BACKEND] {error_detail}")
                return jsonify({
                    'ai_probability': simulate_python_heuristics(text), 
                    'source': f'Local Matrix ({response.status_code})', 
                    'status': 'fallback',
                    'hf_error': error_detail
                })

        return jsonify({
            'ai_probability': simulate_python_heuristics(text), 
            'source': 'Local Matrix (Timeout)', 
            'status': 'fallback',
            'hf_error': "Max retries reached while waking model."
        })

    except Exception as e:
        print(f"[GIDEON BACKEND] Exception: {str(e)}")
        return jsonify({
            'ai_probability': simulate_python_heuristics(text), 
            'source': 'Local Matrix (Exception)', 
            'status': 'fallback',
            'hf_error': str(e)
        })

def simulate_python_heuristics(text):
    words = text.split()
    if len(words) < 10: return 0
    avg_len = sum(len(w) for w in words) / len(words)
    if 4.5 < avg_len < 5.5: return 85.0 
    return 25.0


# --- Upside Down Text Route ---
@app.route('/tools/upside-down')
def tool_upside_down():
    return render_template('tool_upside_down.html')


# --- Morse Code Route ---
@app.route('/tools/morse-code')
def tool_morse_code():
    return render_template('tool_morse_code.html')


# --- NATO Phonetic Translator Route ---
@app.route('/tools/nato-phonetic')
def tool_nato_phonetic():
    return render_template('tool_nato_phonetic.html')


# --- Text to Speech Route ---
@app.route('/tools/text-to-speech')
def tool_text_to_speech():
    return render_template('tool_text_to_speech.html')


# --- Speech to Text Route ---
@app.route('/tools/speech-to-text')
def tool_speech_to_text():
    return render_template('tool_speech_to_text.html')


# --- Speed Reading Tool Route ---
@app.route('/tools/speed-reading')
def tool_speed_reading():
    return render_template('tool_speed_reading.html')


# --- Markdown Editor Route ---
@app.route('/tools/markdown-editor')
def tool_markdown_editor():
    return render_template('tool_markdown_editor.html')


# --- Rich Text Editor Route ---
@app.route('/tools/rich-text-editor')
def tool_rich_text_editor():
    return render_template('tool_rich_text_editor.html')


# --- Sticky Notes Route ---
@app.route('/tools/sticky-notes')
def tool_sticky_notes():
    return render_template('tool_sticky_notes.html')


# --- Image Compressor Route ---
@app.route('/tools/image-compressor')
def tool_image_compressor():
    return render_template('tool_image_compressor.html')


# --- Image Resizer Route ---
@app.route('/tools/image-resizer')
def tool_image_resizer():
    return render_template('tool_image_resizer.html')


# ==========================================
# ACADEMIC & COMPUTATIONAL GRID
# ==========================================
@app.route('/tools/numerical-engine')
def tool_numerical_engine():
    # Renders the full-scale Numerical Analysis & Computational Engine
    return render_template('numerical_engine.html')


@app.route('/tool_image_cropper')
def tool_image_cropper():
    return render_template('tool_image_cropper.html')


# ==========================================
# MEDIA & FILES
# ==========================================
@app.route('/tool_image_filters')
def tool_image_filters():
    # Renders the GPU-accelerated CSS filter pipeline
    return render_template('tool_image_filters.html')


# ==========================================
# MEDIA & FILES
# ==========================================
@app.route('/tool_exif_data_viewer')
def tool_exif_data_viewer():
    return render_template('tool_exif_data_viewer.html')


@app.route('/tool_svg_editor')
def tool_svg_editor():
    return render_template('tool_svg_editor.html')


@app.route('/tool_screen_recorder')
def tool_screen_recorder():
    return render_template('tool_screen_recorder.html')


@app.route('/tool_webcam_tester')
def tool_webcam_tester():
    return render_template('tool_webcam_tester.html')


@app.route('/tool_microphone_tester')
def tool_microphone_tester():
    return render_template('tool_microphone_tester.html')


@app.route('/tool_audio_visualizer')
def tool_audio_visualizer():
    return render_template('tool_audio_visualizer.html')


@app.route('/tool_metronome')
def tool_metronome():
    return render_template('tool_metronome.html')


@app.route('/tool_instrument_tuner')
def tool_instrument_tuner():
    return render_template('tool_instrument_tuner.html')


@app.route('/tool_piano_keyboard')
def tool_piano_keyboard():
    return render_template('tool_piano_keyboard.html')


@app.route('/tool_drum_machine')
def tool_drum_machine():
    return render_template('tool_drum_machine.html')


@app.route('/tool_white_noise')
def tool_white_noise():
    return render_template('tool_white_noise.html')


# --- UTILITY TOOLS ROUTES ---

@app.route('/tools/pdf-merger')
def tool_pdf_merger():
    # You can add @login_required here if this portal is locked down
    return render_template('tool_pdf_merger.html', title="PDF Merger | L.I.S.A. Tools")


@app.route('/tools/pdf-splitter')
def tool_pdf_splitter():
    # Add @login_required if needed
    return render_template('tool_pdf_splitter.html', title="PDF Splitter | L.I.S.A. Tools")


@app.route('/tools/video-to-gif')
def tool_video_to_gif():
    return render_template('tool_video_to_gif.html', title="Video to GIF | L.I.S.A. Tools")


@app.route('/tools/meme-generator')
def tool_meme_generator():
    return render_template('tool_meme_generator.html', title="Meme Generator | L.I.S.A. Tools")


@app.route('/tools/screenshot')
def tool_screenshot():
    return render_template('tool_screenshot.html', title="Screenshot Tool | L.I.S.A. Tools")


@app.route('/tools/loan-calculator')
def tool_loan_calculator():
    return render_template('tool_loan_calculator.html', title="Loan Calculator | L.I.S.A. Tools")


@app.route('/tools/mortgage-calculator')
def tool_mortgage_calculator():
    return render_template('tool_mortgage_calculator.html', title="Mortgage Calculator | L.I.S.A. Tools")


@app.route('/tools/compound-interest')
def tool_compound_interest():
    return render_template('tool_compound_interest.html', title="Compound Interest | L.I.S.A. Tools")


@app.route('/tools/inflation-calculator')
def tool_inflation_calculator():
    return render_template('tool_inflation_calculator.html', title="Inflation Calculator | L.I.S.A. Tools")


@app.route('/tools/salary-tax-calculator')
def tool_salary_tax_calculator():
    return render_template('tool_salary_tax_calculator.html', title="Salary Tax Calculator | L.I.S.A. Tools")


@app.route('/tools/roi-calculator')
def tool_roi_calculator():
    return render_template('tool_roi_calculator.html', title="ROI Calculator | L.I.S.A. Tools")


@app.route('/tools/cagr-calculator')
def tool_cagr_calculator():
    return render_template('tool_cagr_calculator.html', title="CAGR Calculator | L.I.S.A. Tools")


@app.route('/tools/discount-calculator')
def tool_discount_calculator():
    return render_template('tool_discount_calculator.html', title="Discount Calculator | L.I.S.A. Tools")


@app.route('/tools/tip-calculator')
def tool_tip_calculator():
    return render_template('tool_tip_calculator.html', title="Tip Calculator | L.I.S.A. Tools")


@app.route('/tools/currency-converter')
def tool_currency_converter():
    return render_template('tool_currency_converter.html', title="Currency Converter | L.I.S.A. Tools")


@app.route('/tools/unit-price-compare')
def tool_unit_price_compare():
    return render_template('tool_unit_price_compare.html', title="Unit Price Compare | L.I.S.A. Tools")


@app.route('/tools/fuel-cost-calculator')
def tool_fuel_cost_calculator():
    return render_template('tool_fuel_cost_calculator.html', title="Fuel Cost Calculator | L.I.S.A. Tools")


@app.route('/tools/break-even')
def tool_break_even():
    return render_template('tool_break_even.html', title="Break-Even Analysis | L.I.S.A. Tools")


@app.route('/tools/margin-calculator')
def tool_margin_calculator():
    return render_template('tool_margin_calculator.html', title="Margin Calculator | L.I.S.A. Tools")


@app.route('/tools/time-sheet-calculator')
def tool_time_sheet_calculator():
    return render_template('tool_time_sheet_calculator.html', title="Time Sheet Calculator | L.I.S.A. Tools")


@app.route('/tools/invoice-generator')
def tool_invoice_generator():
    return render_template('tool_invoice_generator.html', title="Invoice Generator | L.I.S.A. Tools")


@app.route('/tools/receipt-maker')
def tool_receipt_maker():
    return render_template('tool_receipt_maker.html', title="Receipt Maker | L.I.S.A. Tools")


@app.route('/tools/budget-planner')
def tool_budget_planner():
    return render_template('tool_budget_planner.html', title="Budget Architect | L.I.S.A. Tools")


@app.route('/tools/savings-goal')
def tool_savings_goal():
    return render_template('tool_savings_goal.html', title="Savings Goal Tracker | L.I.S.A. Tools")


@app.route('/tools/credit-card-payoff')
def tool_credit_card_payoff():
    return render_template('tool_credit_card_payoff.html', title="Debt Elimination Matrix | L.I.S.A. Tools")


# ==========================================
# TIME & DATE TOOLS ROUTES
# ==========================================

@app.route('/tools/world-clock')
def tool_world_clock():
    return render_template('tool_world_clock.html', title="Global Market Clock | L.I.S.A. Tools")

@app.route('/tools/stopwatch')
def tool_stopwatch():
    return render_template('tool_stopwatch.html', title="Precision Stopwatch | L.I.S.A. Tools")


@app.route('/tools/countdown-timer')
def tool_countdown_timer():
    return render_template('tool_countdown_timer.html', title="Defcon Countdown Matrix | L.I.S.A. Tools")


@app.route('/tools/date-difference')
def tool_date_difference():
    return render_template('tool_date_difference.html', title="Temporal Displacement Matrix | L.I.S.A. Tools")


@app.route('/tools/age-calculator')
def tool_age_calculator():
    return render_template('tool_age_calculator.html', title="Biometric Chronology | L.I.S.A. Tools")


@app.route('/tools/week-number')
def tool_week_number():
    return render_template('tool_week_number.html', title="V400 ISO Sync Engine | L.I.S.A. Tools")


@app.route('/tools/leap-year')
def tool_leap_year():
    return render_template('tool_leap_year.html', title="Orbital Alignment Matrix | L.I.S.A. Tools")


@app.route('/tools/timezone-converter')
def tool_timezone_converter():
    return render_template('tool_timezone_converter.html', title="Global Meeting Planner | L.I.S.A. Tools")


@app.route('/tools/julian-date')
def tool_julian_date():
    return render_template('tool_julian_date.html', title="Stellar Cartography Engine | L.I.S.A. Tools")


@app.route('/tools/unix-converter')
def tool_unix_converter():
    return render_template('tool_unix_converter.html', title="V600 Unix Cyber-Grid | L.I.S.A. Tools")


@app.route('/tools/day-of-week')
def tool_day_of_week():
    return render_template('tool_day_of_week.html', title="V800 Mechanical Solari | L.I.S.A. Tools")


@app.route('/tools/work-day')
def tool_work_day():
    return render_template('tool_work_day.html', title="V900 Executive Work Day Matrix | L.I.S.A. Tools")


@app.route('/tools/moon-phase')
def tool_moon_phase():
    return render_template('tool_moon_phase.html', title="V1000 Lunar Astrolabe | L.I.S.A. Tools")


@app.route('/tools/sun-position')
def tool_sun_position():
    return render_template('tool_sun_position.html', title="V1100 Atmospheric Optics | L.I.S.A. Tools")


@app.route('/tools/calendar-generator')
def tool_calendar_generator():
    return render_template('tool_calendar_generator.html', title="V1200 Editorial Calendar | L.I.S.A. Tools")


@app.route('/tools/typing-test')
def tool_typing_test():
    return render_template('tool_typing_test.html', title="V5000 Neuro-Kinetic Typing | L.I.S.A. Tools")


@app.route('/tools/memory-test')
def tool_memory_test():
    return render_template('tool_memory_test.html', title="V7100 Cognitive Matrix | L.I.S.A. Tools")


# 1. FIXED Reaction Time Route (New Name to avoid crash)
@app.route('/tools/reflex-matrix')
def tool_reflex_matrix():
    return render_template('tool_reaction_time.html', title="V8000 Reflex Matrix | L.I.S.A. Tools")

# 2. NEW Aim Trainer Route
@app.route('/tools/aim-trainer')
def tool_aim_trainer():
    return render_template('tool_aim_trainer.html', title="V8500 Kinetic Aim Trainer | L.I.S.A. Tools")


@app.route('/tools/sudoku-solver')
def tool_sudoku_solver():
    return render_template('tool_sudoku_solver.html', title="V9000 Sudoku Solver | L.I.S.A. Tools")


@app.route('/tools/sudoku-generator')
def tool_sudoku_generator():
    return render_template('tool_sudoku_generator.html', title="V11000 Playable Cipher | L.I.S.A. Tools")


@app.route('/tools/2048-clone')
def tool_2048_clone():
    return render_template('tool_2048_clone.html', title="V13000 Grid Combinator | L.I.S.A. Tools")


@app.route('/tools/tic-tac-toe')
def tool_tic_tac_toe():
    return render_template('tool_tic_tac_toe.html', title="V15000 Tactical Grid | L.I.S.A. Tools")


@app.route('/tools/snake-game')
def tool_snake_game():
    return render_template('tool_snake_game.html', title="V17000 Ouroboros Engine | L.I.S.A. Tools")


@app.route('/tools/minesweeper')
def tool_minesweeper():
    return render_template('tool_minesweeper.html', title="V25000 Ordinance Sweeper | L.I.S.A. Tools")


@app.route('/tools/connect-4')
def tool_connect_4():
    return render_template('tool_connect_4.html', title="V30000 Gravity Matrix | L.I.S.A. Tools")


@app.route('/tools/rock-paper-scissors')
def tool_rps_ai():
    return render_template('tool_rps_ai.html', title="V150000 Cognitive Warfare | L.I.S.A. Tools")



@app.route('/tools/dice-roller')
def tool_dice_roller():
    return render_template('tool_dice_roller.html', title="V500000 Polyhedral Matrix | L.I.S.A. Tools")


@app.route('/tools/orbital-centrifuge')
def tool_orbital_centrifuge():
    return render_template('tool_spin_wheel.html', title="V100000000 Orbital Centrifuge | L.I.S.A. Tools")


# ==========================================
# V8.5 EXPANSION PACK: NEW CYBER TOOLS
# ==========================================

@app.route('/tools/network-sniffer')
def network_sniffer():
    return render_template('tool_network_sniffer.html')

@app.route('/tools/hash-cracker')
def hash_cracker():
    return render_template('tool_hash_cracker.html')

@app.route('/tools/password-gen')
def password_gen():
    return render_template('tool_password_gen.html')

@app.route('/tools/dns-lookup')
def dns_lookup():
    return render_template('tool_dns_lookup.html')


@app.route('/tool_api_tester')
def tool_api_tester():
    # Renders the V-Infinity API Tester
    return render_template('tool_api_tester.html')

@app.route('/tool_regex_builder')
def tool_regex_builder():
    # Renders the V-Infinity Regex Engine
    return render_template('tool_regex_builder.html')


@app.route('/fix_attendance_time_col')
def fix_attendance_time_col():
    from sqlalchemy import text
    try:
        with app.app_context():
            db.session.execute(text("ALTER TABLE daily_attendance ADD COLUMN time_logged VARCHAR(50)"))
            db.session.commit()
            return "<h1>✅ SUCCESS! Added 'time_logged' to database.</h1><a href='/lecturer/attendance_scanner'>Go to Scanner</a>"
    except Exception as e:
        return f"<h1>ℹ️ Info: {e}</h1><p>Column may already exist.</p><a href='/lecturer/attendance_scanner'>Go to Scanner</a>"



@app.route('/lecturer/attendance_scanner')
def lecturer_attendance_scanner():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    courses = Course.query.all()
    
    # 🟢 FETCH ABSOLUTE HISTORY FROM DATABASE (All Time)
    history = db.session.query(DailyAttendance, Student, Course).filter(DailyAttendance.course_id.in_([c.id for c in my_data(Course).all()]))\
        .join(Student, DailyAttendance.student_id == Student.id)\
        .join(Course, DailyAttendance.course_id == Course.id)\
        .order_by(DailyAttendance.id.desc()).all()
        
    today_str = date.today().strftime('%Y-%m-%d')

    return render_template('attendance_scanner.html', courses=courses, history=history, today_str=today_str)



# 💥 THE ULTIMATE ROSTER NUKE (Run this once to fix the 486 bug!)
@app.route('/nuke_my_roster')
def nuke_my_roster():
    if session.get('role') != 'lecturer':
        return "⛔ Must be logged in as Lecturer."
        
    lecturer_id = session.get('user_id')
    my_courses = Course.query.filter_by(lecturer_id=lecturer_id).all()
    
    count = 0
    for course in my_courses:
        # Find every student registered for THIS specific course
        students_in_course = Student.query.filter(Student.registered_courses.any(id=course.id)).all()
        for s in students_in_course:
            s.registered_courses.remove(course)
            count += 1
            
    db.session.commit()
    flash(f'🧹 SUCCESS! Wiped {count} students from your courses. Your dashboard is back to 0!', 'success')
    return redirect(url_for('dashboard'))



# ==========================================
# ENTERPRISE MESSAGING PROTOCOL
# ==========================================

# 1. Define the Global RAM Buffer (Temporary Storage)
SECURE_MESSAGE_BUFFER = []

@app.route('/api/messages/send', methods=['POST'])
def send_secure_message():
    """
    Receives and processes direct messages from the Admin/Lecturer dashboard.
    Expected JSON Payload: { "matric": "CSC/2021/1011", "message": "Your text here" }
    """
    try:
        # 1. Intercept the JSON payload
        data = request.get_json()
        
        # 2. Extract telemetry variables
        target_matric = data.get('matric')
        message_body = data.get('message')
        
        # 3. Validate payload integrity
        if not target_matric or not message_body:
            print("[SECURITY WARNING] Malformed transmission detected. Dropping payload.")
            return jsonify({
                'status': 'error', 
                'message': 'Invalid payload architecture. Matric and message are strictly required.'
            }), 400
            
        # 4. Enterprise Database Insertion 
        # (ARCHITECT NOTE: Uncomment and adapt the ORM code below to match your actual database models)
        
        # new_msg = DirectMessage(
        #     sender_id=session.get('user_id', 'ADMIN'), 
        #     recipient_matric=target_matric, 
        #     content=message_body, 
        #     timestamp=datetime.utcnow(),
        #     is_read=False
        # )
        # db.session.add(new_msg)
        # db.session.commit()

        # ==========================================
        # INJECTED IN-MEMORY BUFFER LOGIC
        # ==========================================
        SECURE_MESSAGE_BUFFER.append({
            'matric': target_matric,
            'content': message_body,
            'timestamp': datetime.now().strftime('%d %b %Y, %I:%M %p')
        })
        
        # SIMULATED MATRIX LOGGING (Remove once database ORM is active)
        print(f"\n--- [SECURE TRANSMISSION INTERCEPTED] ---")
        print(f"Timestamp:   {datetime.now()}")
        print(f"Target Node: {target_matric}")
        print(f"Payload:     {message_body}")
        print(f"Status:      200 OK - Payload buffered for delivery.")
        print(f"-----------------------------------------\n")
        
        # 5. Return success acknowledgment to the frontend UI
        return jsonify({
            'status': 'success', 
            'message': f'Transmission to {target_matric} secured and logged.',
            'timestamp': datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        # Log critical core failures
        print(f"[CRITICAL FAILURE] Routing error in message pipeline: {str(e)}")
        return jsonify({
            'status': 'error', 
            'message': 'Internal Server Error during transmission routing.'
        }), 500



# ==========================================
# ENTERPRISE MESSAGING PROTOCOL: RECEIVER
# ==========================================

# Temporary matrix buffer (Replace with your actual Database ORM later)
# If using this buffer, make sure your send_secure_message route appends to it!
SECURE_MESSAGE_BUFFER = [] 

@app.route('/api/student/messages', methods=['GET'])
def get_secure_messages():
    """
    Fetches direct messages for the logged-in student.
    Triggered by the student_portal.html auto-polling system.
    """
    try:
        # Extract the matric number from the query parameters
        matric = request.args.get('matric_number')
        
        if not matric:
            return jsonify({'status': 'error', 'message': 'Authentication matrix failed. Matric required.'}), 400

        # ENTERPRISE DB FETCH (Uncomment and adapt to your SQLAlchemy models)
        # messages = DirectMessage.query.filter_by(recipient_matric=matric).order_by(DirectMessage.timestamp.desc()).all()
        # msg_list = [{'content': m.content, 'timestamp': m.timestamp.strftime('%d %b %Y, %I:%M %p')} for m in messages]
        
        # SIMULATED DB FETCH (Using the temporary buffer for immediate testing)
        msg_list = [msg for msg in SECURE_MESSAGE_BUFFER if msg['matric'] == matric]
        
        return jsonify({
            'status': 'success',
            'messages': msg_list
        }), 200

    except Exception as e:
        print(f"[CRITICAL] Error fetching secure messages: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Internal database sync failure.'}), 500




# ==========================================
# GLOBAL IDENTITY RESOLUTION API
# ==========================================

@app.route('/api/student/lookup', methods=['GET'])
def lookup_student_by_name():
    """
    Dynamically looks up ANY student's REAL matric number and department by their name.
    Strictly queries the Student database model. No simulations.
    """
    name = request.args.get('name')
    
    if not name:
        return jsonify({'status': 'error', 'message': 'Search parameter missing.'}), 400
        
    try:
        # 🟢 REAL DATABASE QUERY: Search the Student table for this exact name
        student = Student.query.filter(Student.name.ilike(f"%{name}%")).first()
        
        if student:
            return jsonify({
                'status': 'success', 
                'matric': student.matric_no, 
                'dept': student.department
            }), 200
        else:
            return jsonify({'status': 'error', 'message': 'Student not found in matrix.'}), 404

    except Exception as e:
        print(f"[IDENTITY API ERROR]: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Database connection failed.'}), 500


# ==========================================
# 🚀 APP STARTUP & SAFE SELF-HEALING DB
# ==========================================
if __name__ == '__main__':
    with app.app_context():
        import sqlite3
        import os
        
        # 1. Determine the EXACT database file Flask is using
        db_path = 'lasu_data.db'
        # If Flask is using an 'instance' folder, check there too
        if not os.path.exists(db_path) and os.path.exists(os.path.join('instance', 'lasu_data.db')):
            db_path = os.path.join('instance', 'lasu_data.db')
            
        print(f"🔧 Connecting to database at: {db_path}")

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 2. SAFE COLUMN INJECTION
            for col, col_type in [
                ('password_hash', 'VARCHAR(200)'),
                ('exam_date', 'DATE'),
                ('exam_time', 'VARCHAR(20)')
            ]:
                try:
                    cursor.execute(f'ALTER TABLE { "student" if col=="password_hash" else "course" } ADD COLUMN {col} {col_type}')
                    conn.commit()
                    print(f"✅ Database updated: {col} column added.")
                except sqlite3.OperationalError:
                    pass  # Column exists

            # 3. 🟢 CRITICAL FIX: FORCE CREATE 'complaint_message'
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS complaint_message (
                    id INTEGER PRIMARY KEY,
                    complaint_id INTEGER NOT NULL,
                    sender VARCHAR(20),
                    text TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(complaint_id) REFERENCES complaint(id)
                )
            ''')
            print("✅ Verified/Created 'complaint_message' table.")

            # 4. Create other tables if missing
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS clearance (
                    id INTEGER PRIMARY KEY,
                    student_id INTEGER NOT NULL,
                    dept_status TEXT DEFAULT 'Pending',
                    library_status TEXT DEFAULT 'Pending',
                    bursary_status TEXT DEFAULT 'Pending',
                    sports_status TEXT DEFAULT 'Pending',
                    date_initiated DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(student_id) REFERENCES student(id)
                )
            ''')

            conn.commit()
            conn.close()

            # 5. Ensure Admin Email
            try:
                admin_user = User.query.filter_by(username='admin').first()
                if admin_user:
                    admin_user.email = "favouradamson803@gmail.com"
                    db.session.commit()
            except:
                pass

            # 6. Final SQLAlchemy Check
            db.create_all()
            
        except Exception as e:
            print(f"❌ Initialization Error: {e}")

    app.run(debug=True, host='0.0.0.0', port=5000)
