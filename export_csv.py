#!/usr/bin/env python3
"""
CSV Export Script for Domain Cache Database
Exports domain check results from SQLite database to CSV format.
"""

import sqlite3
import csv
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

def setup_logging():
    """Setup logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )

def parse_redirect_history(redirect_history_json: Optional[str]) -> str:
    """Parse redirect history JSON into a readable string format.
    
    Args:
        redirect_history_json: JSON string containing redirect history
        
    Returns:
        Formatted string representing the redirect chain
    """
    if not redirect_history_json:
        return ""
    
    try:
        redirect_history = json.loads(redirect_history_json)
        if not redirect_history or len(redirect_history) <= 1:
            return ""
        
        # Create a readable redirect chain
        chain_parts = []
        for step in redirect_history:
            status_code = step.get('status_code', 'Unknown')
            url = step.get('url', 'Unknown URL')
            chain_parts.append(f"{status_code}:{url}")
        
        return " -> ".join(chain_parts)
    except (json.JSONDecodeError, TypeError) as e:
        logging.warning(f"Failed to parse redirect history: {e}")
        return ""

def export_database_to_csv(db_path: str, output_path: str, include_details: bool = True) -> int:
    """Export domain cache database to CSV format.
    
    Args:
        db_path: Path to the SQLite database file
        output_path: Path for the output CSV file
        include_details: Whether to include detailed redirect information
        
    Returns:
        Number of records exported
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Enable dict-like access
    cursor = conn.cursor()
    
    try:
        # Query all records from domain_cache table
        cursor.execute("""
            SELECT domain, is_ok, detail, redirect_history, redirect_count, 
                   final_status_code, created_at, updated_at
            FROM domain_cache 
            ORDER BY created_at DESC
        """)
        
        records = cursor.fetchall()
        
        if not records:
            logging.warning("No records found in database")
            return 0
        
        # Prepare CSV headers
        if include_details:
            headers = [
                'Domain',
                'Status',
                'Detail',
                'Redirect_Count',
                'Final_Status_Code',
                'Redirect_Chain',
                'Created_At',
                'Updated_At'
            ]
        else:
            headers = [
                'Domain',
                'Status',
                'Detail',
                'Redirect_Count',
                'Final_Status_Code',
                'Created_At'
            ]
        
        # Write CSV file
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow(headers)
            
            # Write data rows
            for record in records:
                status = 'Online' if record['is_ok'] else 'Offline'
                redirect_chain = parse_redirect_history(record['redirect_history']) if include_details else ''
                
                if include_details:
                    row = [
                        record['domain'],
                        status,
                        record['detail'] or '',
                        record['redirect_count'] or 0,
                        record['final_status_code'] or '',
                        redirect_chain,
                        record['created_at'] or '',
                        record['updated_at'] or ''
                    ]
                else:
                    row = [
                        record['domain'],
                        status,
                        record['detail'] or '',
                        record['redirect_count'] or 0,
                        record['final_status_code'] or '',
                        record['created_at'] or ''
                    ]
                
                writer.writerow(row)
        
        logging.info(f"Successfully exported {len(records)} records to {output_path}")
        return len(records)
        
    finally:
        conn.close()

def get_database_stats(db_path: str) -> Dict[str, Any]:
    """Get basic statistics about the database.
    
    Args:
        db_path: Path to the SQLite database file
        
    Returns:
        Dictionary containing database statistics
    """
    if not Path(db_path).exists():
        return {"error": "Database file not found"}
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Total records
        cursor.execute("SELECT COUNT(*) as total FROM domain_cache")
        total = cursor.fetchone()[0]
        
        # Online vs Offline
        cursor.execute("SELECT is_ok, COUNT(*) as count FROM domain_cache GROUP BY is_ok")
        status_counts = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Latest record date
        cursor.execute("SELECT MAX(created_at) as latest FROM domain_cache")
        latest = cursor.fetchone()[0]
        
        # Earliest record date
        cursor.execute("SELECT MIN(created_at) as earliest FROM domain_cache")
        earliest = cursor.fetchone()[0]
        
        return {
            "total_records": total,
            "online_domains": status_counts.get(1, 0),
            "offline_domains": status_counts.get(0, 0),
            "earliest_record": earliest,
            "latest_record": latest
        }
        
    finally:
        conn.close()

def main():
    """Main function for the CSV export script."""
    parser = argparse.ArgumentParser(
        description="Export domain cache database to CSV format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python export_csv.py                                    # Export with default settings
  python export_csv.py --output my_domains.csv           # Custom output file
  python export_csv.py --simple                          # Export without redirect details
  python export_csv.py --stats-only                      # Show statistics only
  python export_csv.py --db custom_cache.db              # Use different database file
        """
    )
    
    parser.add_argument(
        '--db', 
        default='domain_cache.db',
        help='Path to the SQLite database file (default: domain_cache.db)'
    )
    
    parser.add_argument(
        '--output', '-o',
        help='Output CSV file path (default: domain_export_YYYYMMDD_HHMMSS.csv)'
    )
    
    parser.add_argument(
        '--simple',
        action='store_true',
        help='Export without detailed redirect information'
    )
    
    parser.add_argument(
        '--stats-only',
        action='store_true',
        help='Show database statistics only, do not export'
    )
    
    args = parser.parse_args()
    
    setup_logging()
    
    # Check if database exists
    if not Path(args.db).exists():
        logging.error(f"Database file not found: {args.db}")
        return 1
    
    # Show statistics
    stats = get_database_stats(args.db)
    if "error" in stats:
        logging.error(stats["error"])
        return 1
    
    logging.info("Database Statistics:")
    logging.info(f"  Total records: {stats['total_records']}")
    logging.info(f"  Online domains: {stats['online_domains']}")
    logging.info(f"  Offline domains: {stats['offline_domains']}")
    logging.info(f"  Date range: {stats['earliest_record']} to {stats['latest_record']}")
    
    if args.stats_only:
        return 0
    
    # Generate output filename if not provided
    if not args.output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"domain_export_{timestamp}.csv"
    
    try:
        # Export to CSV
        record_count = export_database_to_csv(
            db_path=args.db,
            output_path=args.output,
            include_details=not args.simple
        )
        
        if record_count > 0:
            logging.info(f"Export completed successfully!")
            logging.info(f"Output file: {Path(args.output).absolute()}")
            logging.info(f"File size: {Path(args.output).stat().st_size / 1024:.1f} KB")
        else:
            logging.warning("No records were exported")
            
        return 0
        
    except Exception as e:
        logging.error(f"Export failed: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
