import sqlite3

def safe_init():
    print("📚 Checking database health...")
    conn = sqlite3.connect('lasu_data.db')
    cursor = conn.cursor()

    # 1. Create Library Book Table (Safe Mode)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS library_book (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            description TEXT,
            cover_image TEXT DEFAULT 'default_book.jpg',
            pdf_file TEXT,
            stock_quantity INTEGER DEFAULT 0,
            category TEXT DEFAULT 'General',
            date_added DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 2. Create Borrowing Table (Safe Mode)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS borrowing (
            id INTEGER PRIMARY KEY,
            student_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            borrow_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            due_date DATETIME,
            return_date DATETIME,
            status TEXT DEFAULT 'Borrowed',
            FOREIGN KEY(student_id) REFERENCES student(id),
            FOREIGN KEY(book_id) REFERENCES library_book(id)
        )
    ''')

    conn.commit()
    conn.close()
    print("✅ Database updated! Your existing data is safe.")

if __name__ == "__main__":
    safe_init()