from app import app, db
from models import Student, Payment
import random, string

with app.app_context():
    # Get all students
    students = Student.query.all()
    print(f"🔍 Checking {len(students)} students for missing payment records...")
    
    count = 0
    for s in students:
        # Check: If student is marked "PAID" but has an EMPTY payment history
        if s.has_paid_fees and not s.payments:
            print(f"🛠️  Fixing record for: {s.name} ({s.matric_no})")
            
            # Generate a simulated transaction reference
            ref = "LASU-FIX-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            
            # Create the missing payment record
            new_payment = Payment(student_id=s.id, amount=50000.00, reference=ref)
            db.session.add(new_payment)
            count += 1
            
    if count > 0:
        db.session.commit()
        print(f"✅ SUCCESS: Generated payment history for {count} students!")
    else:
        print("ℹ️  All paid students already have payment records. No changes made.")