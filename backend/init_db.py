import sqlite3
import os
# pyrefly: ignore [missing-import]
from tinyflux import TinyFlux

DB_PATH = 'app.db'
TINYFLUX_PATH = 'metrics.db'

def init_sqlite():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        quota_ram INTEGER DEFAULT 0,
        quota_cpu INTEGER DEFAULT 0,
        quota_disk INTEGER DEFAULT 0
    )
    ''')

    # Create Containers table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS containers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lxd_name TEXT UNIQUE NOT NULL,
        owner_id INTEGER,
        FOREIGN KEY(owner_id) REFERENCES users(id)
    )
    ''')

    # Create Audit Logs table (as required by "destructive actions leave a trail")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        target TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    ''')

    conn.commit()
    conn.close()
    print(f"SQLite database initialized at {DB_PATH}")

def init_tinyflux():
    # TinyFlux will automatically create the file if it doesn't exist
    db = TinyFlux(TINYFLUX_PATH)
    print(f"TinyFlux database initialized at {TINYFLUX_PATH}")

if __name__ == "__main__":
    print("Initializing databases...")
    init_sqlite()
    init_tinyflux()
    print("Done.")
