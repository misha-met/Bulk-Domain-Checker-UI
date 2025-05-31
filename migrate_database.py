#!/usr/bin/env python3
"""
Database migration script to add new columns for separated code and redirect information.
Migrates existing database to new schema with separate columns.
"""

import sqlite3
import json
import logging
from pathlib import Path

def setup_logging():
    """Setup logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def migrate_database(db_path: str = "domain_cache.db"):
    """Migrate database to new schema with separate code and redirect columns.
    
    Args:
        db_path: Path to the SQLite database file
    """
    if not Path(db_path).exists():
        logging.info(f"Database {db_path} doesn't exist, no migration needed")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if new columns already exist
        cursor.execute("PRAGMA table_info(domain_cache)")
        columns = [row[1] for row in cursor.fetchall()]
        
        has_status_code = 'status_code' in columns
        has_redirect_info = 'redirect_info' in columns
        
        if has_status_code and has_redirect_info:
            logging.info("Database already has new columns, no migration needed")
            return
        
        logging.info("Starting database migration...")
        
        # Add new columns if they don't exist
        if not has_status_code:
            logging.info("Adding status_code column...")
            cursor.execute("ALTER TABLE domain_cache ADD COLUMN status_code TEXT")
        
        if not has_redirect_info:
            logging.info("Adding redirect_info column...")
            cursor.execute("ALTER TABLE domain_cache ADD COLUMN redirect_info TEXT")
        
        # Populate new columns based on existing data
        logging.info("Populating new columns from existing data...")
        cursor.execute("SELECT id, detail, redirect_count FROM domain_cache")
        rows = cursor.fetchall()
        
        for row_id, detail, redirect_count in rows:
            # status_code column gets the existing detail value
            status_code = detail
            
            # redirect_info column gets summary of redirects
            redirect_info = ""
            if redirect_count and redirect_count > 0:
                redirect_info = f"{redirect_count} redirect(s)"
            
            cursor.execute("""
                UPDATE domain_cache 
                SET status_code = ?, redirect_info = ? 
                WHERE id = ?
            """, (status_code, redirect_info, row_id))
        
        conn.commit()
        logging.info(f"Successfully migrated {len(rows)} records")
        logging.info("Database migration completed successfully")
        
    except Exception as e:
        logging.error(f"Error during migration: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def main():
    """Main function for the migration script."""
    setup_logging()
    
    logging.info("Database migration script starting...")
    migrate_database()
    logging.info("Migration script completed")

if __name__ == "__main__":
    main()
