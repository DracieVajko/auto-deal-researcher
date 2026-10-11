import sqlite3
import os
from datetime import datetime

class StorageManager:
    def __init__(self, db_path="deals.db"):
        self.db_path = db_path
        self._init_database()
        
    def _init_database(self):
        """Initialize the SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create table for storing search results
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                title TEXT,
                price TEXT,
                website TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        
    def save_deal(self, url, title, price, website):
        """Save a deal to the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO deals (url, title, price, website)
                VALUES (?, ?, ?, ?)
            ''', (url, title, price, website))
            
            conn.commit()
        except Exception as e:
            print(f"Error saving deal: {e}")
        finally:
            conn.close()
            
    def get_deal(self, url):
        """Get a deal from the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT * FROM deals WHERE url = ?', (url,))
            return cursor.fetchone()
        finally:
            conn.close()
            
    def get_all_deals(self):
        """Get all deals from the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT * FROM deals')
            return cursor.fetchall()
        finally:
            conn.close()
            
    def delete_old_deals(self, days_old=7):
        """Delete deals older than specified number of days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                DELETE FROM deals 
                WHERE timestamp < datetime('now', '-{} days')
            '''.format(days_old))
            
            conn.commit()
        finally:
            conn.close()