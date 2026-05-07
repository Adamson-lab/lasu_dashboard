import sqlite3
import os

# 1. Find the database
target_db = os.path.join('instance', 'lasu_data.db')
if not os.path.exists(target_db):
    target_db = 'lasu_data.db' # Fallback

print(f"🎯 Target Database: {target_db}")

if os.path.exists(target_db):
    conn = sqlite3.connect(target_db)
    cursor = conn.cursor()

    # 2. Define the Real Links for each University
    updates = [
        ("https://www.rhodeshouse.ox.ac.uk/scholarships/applications/", "University of Oxford"),
        ("https://iso.mit.edu/visiting-students/", "MIT"),
        ("https://future.utoronto.ca/pearson/about/", "University of Toronto"),
        ("https://www.tum.de/en/studies/international-exchange-students", "Technical University of Munich"),
        ("https://mcfsp.uct.ac.za/", "University of Cape Town"),
        ("https://www.hbs.edu/mba/financial-aid/financial-aid-programs/Pages/fellowships.aspx", "Harvard University")
    ]

    print("🔧 Updating links...")
    
    # 3. Apply updates
    for url, uni_name in updates:
        cursor.execute("UPDATE exchange_program SET application_url = ? WHERE university = ?", (url, uni_name))
        print(f"   -> Linked {uni_name} to {url}")

    conn.commit()
    conn.close()
    print("\n✅ SUCCESS! All links have been refreshed.")
    print("👉 Restart your app and try the buttons again!")

else:
    print("❌ Error: Could not find the database.")