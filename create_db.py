import sqlite3

def init_db():
    conn = sqlite3.connect('bank_data.db')
    cursor = conn.cursor()
    
    # Create Tables
    cursor.execute('''CREATE TABLE IF NOT EXISTS accounts 
                      (account_id INTEGER PRIMARY KEY, customer_name TEXT, balance REAL)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
                      (tx_id INTEGER PRIMARY KEY, account_id INTEGER, amount REAL, tx_date DATE)''')

    # Seed Data
    cursor.execute("INSERT OR IGNORE INTO accounts VALUES (1, 'Dawar Malik', 50000.0)")
    cursor.execute("INSERT OR IGNORE INTO transactions VALUES (101, 1, 500.0, '2026-06-25')")
    
    conn.commit()
    conn.close()
    print("Database 'bank_data.db' created successfully.")

if __name__ == "__main__":
    init_db()