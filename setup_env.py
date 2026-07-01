import sqlite3
import os

def setup():
    # 1. Clean up old database if exists
    if os.path.exists('bank_data.db'):
        os.remove('bank_data.db')
        print("Existing database removed.")

    # 2. Initialize new database
    conn = sqlite3.connect('bank_data.db')
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute('''CREATE TABLE accounts 
                      (account_id INTEGER PRIMARY KEY, customer_name TEXT, balance REAL)''')
    cursor.execute('''CREATE TABLE transactions 
                      (tx_id INTEGER PRIMARY KEY, account_id INTEGER, amount REAL, tx_date TEXT)''')

    # Seed with dummy banking data
    accounts_data = [(1, 'Dawar Malik', 50000.0), (2, 'Fatima Noor', 75000.0)]
    transactions_data = [(101, 1, 500.0, '2026-06-25'), (102, 2, 1200.0, '2026-06-26')]
    
    cursor.executemany("INSERT INTO accounts VALUES (?,?,?)", accounts_data)
    cursor.executemany("INSERT INTO transactions VALUES (?,?,?,?)", transactions_data)
    
    conn.commit()
    conn.close()
    print("Environment setup complete: 'bank_data.db' is ready.")

if __name__ == "__main__":
    setup()