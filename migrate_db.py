#!/usr/bin/env python3
"""
Database Migration Script for Bank Account Integration
Adds missing columns to Transaction table and creates BankAccount table
"""

import sqlite3
import os
from datetime import datetime

def migrate_database():
    db_path = 'website/database.db'
    
    if not os.path.exists(db_path):
        print("Database file not found!")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("Starting database migration...")
        
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(transaction)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Add new columns to Transaction table if they don't exist
        new_columns = [
            ('source_type', 'VARCHAR(20) DEFAULT "manual"'),
            ('bank_reference', 'VARCHAR(100)'),
            ('user_notes', 'TEXT'),
            ('bank_account_id', 'INTEGER')
        ]
        
        for column_name, column_def in new_columns:
            if column_name not in columns:
                print(f"Adding column: {column_name}")
                cursor.execute(f'ALTER TABLE transaction ADD COLUMN {column_name} {column_def}')
            else:
                print(f"Column {column_name} already exists")
        
        # Create BankAccount table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bank_account (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bank_name VARCHAR(50) NOT NULL,
                account_number VARCHAR(50) NOT NULL,
                account_holder_name VARCHAR(100) NOT NULL,
                nickname VARCHAR(50),
                api_token_encrypted TEXT,
                is_active BOOLEAN DEFAULT 1,
                plan_id INTEGER NOT NULL,
                created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_sync_date DATETIME,
                FOREIGN KEY (plan_id) REFERENCES plan (id)
            )
        ''')
        print("BankAccount table created/verified")
        
        conn.commit()
        print("Database migration completed successfully!")
        
    except Exception as e:
        print(f"Migration error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()
