#!/usr/bin/env python3
"""
Database module for domain check caching using SQLite.
Handles cache storage, retrieval, and management for domain check results.
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import threading
from typing import Optional, Tuple, List, Dict, Any

# Thread-local storage for database connections
_local = threading.local()

class DomainCache:
    """Manages SQLite cache for domain check results."""
    
    def __init__(self, db_path: str = "domain_cache.db"):
        """Initialize the domain cache with SQLite database.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(_local, 'connection'):
            _local.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            _local.connection.row_factory = sqlite3.Row  # Enable dict-like access
        return _local.connection
    
    def init_database(self) -> None:
        """Initialize the database schema if it doesn't exist."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Create the cache table with separate code and redirect columns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS domain_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                is_ok BOOLEAN NOT NULL,
                detail TEXT NOT NULL,
                status_code TEXT,        -- Status code or error message
                redirect_info TEXT,      -- Redirect summary text
                redirect_history TEXT,   -- JSON string of redirect history
                redirect_count INTEGER DEFAULT 0,
                final_status_code INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(domain) ON CONFLICT REPLACE
            )
        """)
        
        # Create index for faster domain lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_domain ON domain_cache(domain)
        """)
        
        # Create index for timestamp queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at ON domain_cache(created_at)
        """)
        
        conn.commit()
        logging.info(f"Database initialized at {self.db_path}")
    
    def should_cache_result(self, is_ok: bool, detail: str) -> bool:
        """Determine if a result should be cached based on business rules.
        
        Cache successful status codes (200, 3xx, 4xx) but not errors/failures.
        
        Args:
            is_ok: Whether the domain check was successful
            detail: Detail string from the check
            
        Returns:
            True if the result should be cached, False otherwise
        """
        # Cache successful responses (is_ok = True)
        if is_ok:
            return True
        
        # Cache HTTP error responses (4xx, 5xx) but not connection/DNS errors
        if detail.startswith('HTTP ') and any(code in detail for code in ['400', '401', '403', '404', '500', '502', '503']):
            return True
        
        # Don't cache DNS failures, connection errors, timeouts, etc.
        if any(error_type in detail.lower() for error_type in [
            'dns resolution failed', 'connection', 'timeout', 'ssl', 'certificate'
        ]):
            return False
        
        return False
    
    def get_cached_result(self, domain: str, max_age_hours: int = 24) -> Optional[Dict[str, Any]]:
        """Retrieve cached result for a domain if it exists and is not too old.
        
        Args:
            domain: Domain name to look up
            max_age_hours: Maximum age of cache entry in hours (default: 24)
            
        Returns:
            Dictionary with cached result or None if not found/expired
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Calculate cutoff time
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        cursor.execute("""
            SELECT domain, is_ok, detail, status_code, redirect_info, redirect_history, redirect_count, 
                   final_status_code, created_at, updated_at
            FROM domain_cache 
            WHERE domain = ? AND created_at > ?
        """, (domain, cutoff_time))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        # Parse redirect history from JSON
        redirect_history = []
        if row['redirect_history']:
            try:
                redirect_history = json.loads(row['redirect_history'])
            except json.JSONDecodeError:
                logging.warning(f"Failed to parse redirect history for {domain}")
        
        return {
            'domain': row['domain'],
            'ok': bool(row['is_ok']),
            'detail': row['detail'],
            'status_code': row['status_code'],
            'redirect_info': row['redirect_info'],
            'redirect_history': redirect_history,
            'redirect_count': row['redirect_count'] or 0,
            'final_status_code': row['final_status_code'],
            'cached_at': row['created_at'],
            'from_cache': True
        }
    
    def cache_result(self, domain: str, is_ok: bool, detail: str, 
                    redirect_history: List[Dict] = None) -> bool:
        """Cache a domain check result.
        
        Args:
            domain: Domain name
            is_ok: Whether the check was successful
            detail: Detail string from the check
            redirect_history: List of redirect steps
            
        Returns:
            True if cached successfully, False otherwise
        """
        # Check if we should cache this result
        if not self.should_cache_result(is_ok, detail):
            logging.debug(f"Skipping cache for {domain}: {detail}")
            return False

        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Prepare redirect data
            redirect_history_json = None
            redirect_count = 0
            final_status_code = None
            
            # Separate status code and redirect info
            status_code = detail  # Default to using detail as status code
            redirect_info = ""    # Default to empty redirect info
            
            if redirect_history:
                redirect_history_json = json.dumps(redirect_history)
                redirect_count = len(redirect_history) - 1  # Subtract 1 for the final response
                if redirect_history:
                    final_status_code = redirect_history[-1].get('status_code')
                
                # Create redirect summary text
                if redirect_count > 0:
                    redirect_info = f"{redirect_count} redirect(s)"
            
            # Extract status code from detail if available
            if final_status_code is None:
                try:
                    # Try to extract status code from detail string
                    if detail.isdigit():
                        final_status_code = int(detail)
                    elif detail.startswith('HTTP '):
                        final_status_code = int(detail.split()[1])
                    elif ' ' in detail:
                        final_status_code = int(detail.split()[0])
                except (ValueError, IndexError):
                    pass
            
            cursor.execute("""
                INSERT OR REPLACE INTO domain_cache 
                (domain, is_ok, detail, status_code, redirect_info, redirect_history, redirect_count, final_status_code, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (domain, is_ok, detail, status_code, redirect_info, redirect_history_json, redirect_count, final_status_code))
            
            conn.commit()
            logging.info(f"Cached result for {domain}: {detail}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to cache result for {domain}: {e}")
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the cache.
        
        Returns:
            Dictionary with cache statistics
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Total entries
        cursor.execute("SELECT COUNT(*) as total FROM domain_cache")
        total = cursor.fetchone()['total']
        
        # Entries by success/failure
        cursor.execute("SELECT is_ok, COUNT(*) as count FROM domain_cache GROUP BY is_ok")
        status_counts = {row['is_ok']: row['count'] for row in cursor.fetchall()}
        
        # Recent entries (last 24 hours)
        cutoff_time = datetime.now() - timedelta(hours=24)
        cursor.execute("SELECT COUNT(*) as recent FROM domain_cache WHERE created_at > ?", (cutoff_time,))
        recent = cursor.fetchone()['recent']
        
        # Database file size
        db_size = Path(self.db_path).stat().st_size if Path(self.db_path).exists() else 0
        
        return {
            'total_entries': total,
            'successful_entries': status_counts.get(1, 0),
            'failed_entries': status_counts.get(0, 0),
            'recent_entries_24h': recent,
            'database_size_bytes': db_size,
            'database_size_mb': round(db_size / (1024 * 1024), 2)
        }
    
    def get_all_cached_results(self) -> List[Dict[str, Any]]:
        """Get all cached results from the database.
        
        Returns:
            List of dictionaries containing all cached domain results
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT domain, is_ok, detail, status_code, redirect_info, redirect_history, 
                   redirect_count, final_status_code, created_at, updated_at
            FROM domain_cache 
            ORDER BY updated_at DESC
        """)
        
        results = []
        for row in cursor.fetchall():
            result = {
                'domain': row['domain'],
                'is_ok': bool(row['is_ok']),
                'detail': row['detail'],
                'status_code': row['status_code'],
                'redirect_info': row['redirect_info'],
                'redirect_history': row['redirect_history'],
                'redirect_count': row['redirect_count'] or 0,
                'final_status_code': row['final_status_code'],
                'created_at': row['created_at'],
                'updated_at': row['updated_at']
            }
            results.append(result)
        
        return results
    
    def cleanup_old_entries(self, max_age_days: int = 30) -> int:
        """Remove cache entries older than specified days.
        
        Args:
            max_age_days: Maximum age of entries to keep
            
        Returns:
            Number of entries removed
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cutoff_time = datetime.now() - timedelta(days=max_age_days)
        
        cursor.execute("DELETE FROM domain_cache WHERE created_at < ?", (cutoff_time,))
        deleted_count = cursor.rowcount
        conn.commit()
        
        logging.info(f"Cleaned up {deleted_count} old cache entries")
        return deleted_count
    
    def clear_cache(self) -> int:
        """Clear all cache entries.
        
        Returns:
            Number of entries removed
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as count FROM domain_cache")
        count = cursor.fetchone()['count']
        
        cursor.execute("DELETE FROM domain_cache")
        conn.commit()
        
        logging.info(f"Cleared all {count} cache entries")
        return count

# Global cache instance
cache = DomainCache()
