#!/usr/bin/env python3
"""
Accurate Domain Checker with Caching and Retry Logic

Features:
- 100% accuracy focused with controlled concurrency
- Comprehensive domain filtering
- Caching system for progress persistence
- Retry logic for offline domains (up to 5 attempts)
- HTTP status and redirect tracking
- Resume capability after failures
"""

import asyncio
import json
import time
import hashlib
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, asdict
from urllib.parse import urlparse, urljoin

import httpx
from httpx import AsyncClient, Timeout, Limits
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import box
import argparse


@dataclass
class RedirectStep:
    """Represents a single step in a redirect chain."""
    url: str
    status_code: int
    step: int
    timestamp: float
    headers: Dict[str, str] = None


@dataclass
class DomainResult:
    """Represents the complete result for a domain check."""
    domain: str
    final_status: Optional[int]
    is_online: bool
    redirect_chain: List[RedirectStep]
    total_redirects: int
    final_url: str
    error_message: Optional[str]
    check_count: int
    last_checked: float
    first_checked: float


class DomainFilter:
    """Handles filtering of domains based on predefined patterns."""
    
    # Domain prefixes to ignore
    IGNORE_PREFIXES = {
        # Email & Messaging
        'mail', 'smtp', 'pop', 'pop3', 'imap', 'webmail',
        'mx', 'mx1', 'mx2', 'mx3', 'mx4', 'mx5',
        'autodiscover', 'autoconfig', 'mailconfig',
        
        # DNS & Domain Control
        'ns1', 'ns2', 'ns3', 'ns4', 'ns5', 'ns6', 'ns7', 'ns8', 'ns9',
        'dns', 'domaincontrol', 'whois',
        'dyn', 'ddns', 'dynamic', 'dyndns',
        
        # File Transfer & Storage
        'ftp', 'ftps', 'sftp', 'scp',
        'nfs', 'smb', 'cifs', 'webdav',
        'files', 'share', 'storage',
        
        # Remote Access & Management
        'vpn', 'vpns', 'remote', 'rdp', 'vnc',
        'ssh', 'telnet', 'console', 'mgmt', 'management',
        'kvm', 'ilo', 'idrac', 'esxi',
        
        # Database & Back-end Services
        'db', 'database', 'sql', 'mysql', 'postgres', 'mongo',
        'redis', 'memcached', 'couch', 'cassandra',
        
        # Monitoring, Logging & Metrics
        'monitor', 'monitoring', 'metrics', 'grafana', 'prometheus',
        'logs', 'log', 'elk', 'kibana',
        # 'status' - commented out as some orgs host public status pages
        
        # CI/CD & Version Control
        'ci', 'jenkins', 'git', 'gitlab', 'github',
        'svn', 'bitbucket', 'artifact', 'nexus', 'artifactory',
        'build', 'pipelines', 'docker-registry', 'registry',
        
        # API & Service Endpoints (use with caution)
        'api', 'api1', 'api2', 'svc', 'services',
        'graphql', 'rest', 'soap',
        
        # Voice, Chat & Communication Protocols
        'sip', 'voip', 'xmpp', 'jitsi', 'meet', 'conference',
        'teams', 'zoom', 'webex', 'skype',
        
        # Specialized Protocols & Miscellaneous
        'ntp', 'time', 'snmp', 'syslog',
        'kerberos', 'ldap', 'radius', 'tftp',
        'proxy', 'wpad', 'wp-admin',
        'cdn', 'images', 'videos', 'media'
    }
    
    @classmethod
    def should_ignore_domain(cls, domain: str) -> bool:
        """Check if a domain should be ignored based on its prefix."""
        # Extract the subdomain part
        domain = domain.lower().strip()
        if '.' not in domain:
            return False
            
        # Get the first part (subdomain)
        subdomain = domain.split('.')[0]
        
        # Check exact matches
        if subdomain in cls.IGNORE_PREFIXES:
            return True
            
        # Check for numbered variations (e.g., ns1, mx2, api3)
        import re
        for prefix in cls.IGNORE_PREFIXES:
            if re.match(f'^{prefix}[0-9]+$', subdomain):
                return True
                
        return False
    
    @classmethod
    def filter_domains(cls, domains: List[str]) -> Tuple[List[str], List[str]]:
        """Filter domains into valid and ignored lists."""
        valid_domains = []
        ignored_domains = []
        
        for domain in domains:
            if cls.should_ignore_domain(domain):
                ignored_domains.append(domain)
            else:
                valid_domains.append(domain)
                
        return valid_domains, ignored_domains


class CacheManager:
    """Manages persistent caching of domain check results."""
    
    def __init__(self, cache_file: str = "domain_cache.json"):
        self.cache_file = Path(cache_file)
        self.cache: Dict[str, dict] = {}
        self.load_cache()
    
    def load_cache(self):
        """Load existing cache from file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load cache file: {e}")
                self.cache = {}
        else:
            self.cache = {}
    
    def save_cache(self):
        """Save cache to file."""
        try:
            # Create backup
            if self.cache_file.exists():
                backup_file = self.cache_file.with_suffix('.json.backup')
                self.cache_file.rename(backup_file)
            
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2, sort_keys=True)
        except IOError as e:
            print(f"Warning: Could not save cache file: {e}")
    
    def get_result(self, domain: str) -> Optional[DomainResult]:
        """Get cached result for a domain."""
        if domain in self.cache:
            data = self.cache[domain]
            # Reconstruct RedirectStep objects
            redirect_chain = [
                RedirectStep(**step) for step in data.get('redirect_chain', [])
            ]
            # Create DomainResult with redirect chain
            result_data = data.copy()
            result_data['redirect_chain'] = redirect_chain
            return DomainResult(**result_data)
        return None
    
    def store_result(self, result: DomainResult):
        """Store a domain result in cache."""
        # Convert RedirectStep objects to dictionaries
        result_dict = asdict(result)
        self.cache[result.domain] = result_dict
        self.save_cache()
    
    def should_recheck(self, domain: str, max_attempts: int = 5) -> bool:
        """Determine if a domain should be rechecked."""
        result = self.get_result(domain)
        if not result:
            return True
            
        # Always recheck if offline and under max attempts
        if not result.is_online and result.check_count < max_attempts:
            return True
            
        # If online, don't recheck (assuming it's stable)
        if result.is_online:
            return False
            
        return False


class AccurateDomainChecker:
    """Main domain checker class with accuracy focus."""
    
    def __init__(self, concurrency: int = 15, timeout: int = 10):
        self.concurrency = concurrency
        self.timeout = timeout
        self.cache_manager = CacheManager()
        self.console = Console()
        
        # HTTP client configuration for accuracy
        self.timeout_config = Timeout(
            timeout=timeout,
            connect=timeout // 2,
            read=timeout,
            write=timeout // 2,
            pool=timeout * 2
        )
        
        self.limits = Limits(
            max_connections=concurrency,
            max_keepalive_connections=concurrency // 2
        )
    
    async def check_domain(self, domain: str, semaphore: asyncio.Semaphore, 
                          client: AsyncClient) -> DomainResult:
        """Check a single domain with comprehensive redirect tracking."""
        async with semaphore:
            existing_result = self.cache_manager.get_result(domain)
            
            # Determine if we should check this domain
            if existing_result and not self.cache_manager.should_recheck(domain):
                return existing_result
            
            check_count = existing_result.check_count + 1 if existing_result else 1
            first_checked = existing_result.first_checked if existing_result else time.time()
            
            # Clean domain
            clean_domain = self._clean_domain(domain)
            
            # Try HTTPS first, then HTTP
            protocols = ['https', 'http']
            
            for protocol in protocols:
                result = await self._check_protocol(clean_domain, protocol, client, 
                                                  check_count, first_checked)
                if result.is_online:
                    self.cache_manager.store_result(result)
                    return result
            
            # If both protocols failed, return the last result
            if 'result' in locals():
                self.cache_manager.store_result(result)
                return result
            
            # Fallback result if everything failed
            error_result = DomainResult(
                domain=domain,
                final_status=None,
                is_online=False,
                redirect_chain=[],
                total_redirects=0,
                final_url=f"https://{clean_domain}",
                error_message="All protocols failed",
                check_count=check_count,
                last_checked=time.time(),
                first_checked=first_checked
            )
            self.cache_manager.store_result(error_result)
            return error_result
    
    async def _check_protocol(self, domain: str, protocol: str, client: AsyncClient,
                            check_count: int, first_checked: float) -> DomainResult:
        """Check a domain using a specific protocol."""
        redirect_chain = []
        current_url = f"{protocol}://{domain}"
        max_redirects = 10
        redirect_count = 0
        
        try:
            while redirect_count < max_redirects:
                start_time = time.time()
                
                # Make request without following redirects
                response = await client.get(current_url, follow_redirects=False)
                
                # Create redirect step
                step = RedirectStep(
                    url=current_url,
                    status_code=response.status_code,
                    step=redirect_count + 1,
                    timestamp=start_time,
                    headers=dict(response.headers)
                )
                redirect_chain.append(step)
                
                # Check if this is a redirect
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('location')
                    if location:
                        # Handle relative URLs
                        if location.startswith('/'):
                            current_url = urljoin(current_url, location)
                        else:
                            current_url = location
                        redirect_count += 1
                    else:
                        break
                else:
                    # Final response
                    break
            
            # Use the first redirect status if there are redirects, otherwise use final status
            if len(redirect_chain) > 1:
                # There are redirects - use the first redirect status code
                reported_status = redirect_chain[0].status_code
            else:
                # No redirects - use the final status
                reported_status = redirect_chain[-1].status_code
            
            # Domain is online if the final destination is accessible (< 400)
            final_status = redirect_chain[-1].status_code
            is_online = final_status < 400
            
            return DomainResult(
                domain=domain,
                final_status=reported_status,  # Report first redirect or final status
                is_online=is_online,
                redirect_chain=redirect_chain,
                total_redirects=len(redirect_chain) - 1,
                final_url=current_url,
                error_message=None if is_online else f"HTTP {reported_status}",
                check_count=check_count,
                last_checked=time.time(),
                first_checked=first_checked
            )
            
        except Exception as e:
            return DomainResult(
                domain=domain,
                final_status=None,
                is_online=False,
                redirect_chain=redirect_chain,
                total_redirects=len(redirect_chain),
                final_url=current_url,
                error_message=str(e)[:100],
                check_count=check_count,
                last_checked=time.time(),
                first_checked=first_checked
            )
    
    def _clean_domain(self, domain: str) -> str:
        """Clean and normalize domain name."""
        domain = domain.strip().lower()
        
        # Remove protocol if present
        if '://' in domain:
            domain = urlparse(domain).netloc or urlparse(domain).path
        
        # Remove path, port, etc.
        domain = domain.split('/')[0].split(':')[0]
        
        return domain
    
    async def check_domains(self, domains: List[str]) -> List[DomainResult]:
        """Check multiple domains with progress tracking."""
        # Filter domains
        valid_domains, ignored_domains = DomainFilter.filter_domains(domains)
        
        self.console.print(f"[yellow]Filtered out {len(ignored_domains)} domains[/yellow]")
        self.console.print(f"[green]Checking {len(valid_domains)} domains[/green]")
        
        if not valid_domains:
            return []
        
        # Setup async client
        async with AsyncClient(
            timeout=self.timeout_config,
            limits=self.limits,
            http2=True,
            verify=False,  # For broader compatibility
            trust_env=False
        ) as client:
            
            semaphore = asyncio.Semaphore(self.concurrency)
            
            # Create tasks
            tasks = [
                self.check_domain(domain, semaphore, client)
                for domain in valid_domains
            ]
            
            # Execute with progress tracking
            results = []
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=self.console
            ) as progress:
                
                task = progress.add_task("Checking domains...", total=len(tasks))
                
                for coro in asyncio.as_completed(tasks):
                    result = await coro
                    results.append(result)
                    progress.advance(task)
                    
                    # Save progress periodically
                    if len(results) % 50 == 0:
                        self.cache_manager.save_cache()
        
        # Final cache save
        self.cache_manager.save_cache()
        
        return results
    
    def display_results(self, results: List[DomainResult]):
        """Display results in a formatted table."""
        if not results:
            self.console.print("[red]No results to display[/red]")
            return
        
        # Sort results
        results.sort(key=lambda x: (not x.is_online, x.domain))
        
        # Create main table
        table = Table(
            title="Domain Check Results",
            show_header=True,
            header_style="bold magenta",
            box=box.SIMPLE
        )
        
        table.add_column("Domain", style="dim", width=40)
        table.add_column("Status", justify="center")
        table.add_column("HTTP Status", justify="center")
        table.add_column("Redirects", justify="center")
        table.add_column("Checks", justify="center")
        table.add_column("Details")
        
        online_count = 0
        offline_count = 0
        
        for result in results:
            status_color = "[green]Online[/]" if result.is_online else "[red]Offline[/]"
            http_status = str(result.final_status) if result.final_status else "N/A"
            redirect_count = str(result.total_redirects)
            check_count = str(result.check_count)
            
            details = result.error_message if result.error_message else "OK"
            if result.total_redirects > 0:
                details = f"{details} (→ {result.final_url})"
            
            table.add_row(
                result.domain,
                status_color,
                http_status,
                redirect_count,
                check_count,
                details[:60] + "..." if len(details) > 60 else details
            )
            
            if result.is_online:
                online_count += 1
            else:
                offline_count += 1
        
        self.console.print(table)
        self.console.print(f"\n[green]Online: {online_count}[/] | [red]Offline: {offline_count}[/] | [blue]Total: {len(results)}[/]")
    
    def export_results(self, results: List[DomainResult], filename: str = "domain_results.json"):
        """Export results to JSON file."""
        export_data = {
            'timestamp': datetime.now().isoformat(),
            'total_domains': len(results),
            'online_count': sum(1 for r in results if r.is_online),
            'offline_count': sum(1 for r in results if not r.is_online),
            'results': [asdict(result) for result in results]
        }
        
        with open(filename, 'w') as f:
            json.dump(export_data, f, indent=2, sort_keys=True)
        
        self.console.print(f"[green]Results exported to {filename}[/green]")
    
    def export_csv(self, results: List[DomainResult], filename: str = "domain_results.csv"):
        """Export results to CSV file."""
        if not results:
            self.console.print("[red]No results to export[/red]")
            return
        
        csv_filename = filename
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'domain',
                'is_online',
                'http_status',
                'total_redirects',
                'final_url',
                'redirect_chain',
                'error_message',
                'check_count',
                'first_checked',
                'last_checked'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in results:
                # Format redirect chain as a simple string for CSV
                redirect_chain_str = ""
                if result.redirect_chain:
                    chain_steps = []
                    for step in result.redirect_chain:
                        chain_steps.append(f"{step.status_code}:{step.url}")
                    redirect_chain_str = " -> ".join(chain_steps)
                
                # Format timestamps as readable dates
                first_checked_str = datetime.fromtimestamp(result.first_checked).isoformat() if result.first_checked else ""
                last_checked_str = datetime.fromtimestamp(result.last_checked).isoformat() if result.last_checked else ""
                
                writer.writerow({
                    'domain': result.domain,
                    'is_online': result.is_online,
                    'http_status': result.final_status if result.final_status else '',
                    'total_redirects': result.total_redirects,
                    'final_url': result.final_url,
                    'redirect_chain': redirect_chain_str,
                    'error_message': result.error_message if result.error_message else '',
                    'check_count': result.check_count,
                    'first_checked': first_checked_str,
                    'last_checked': last_checked_str
                })
        
        self.console.print(f"[green]CSV results exported to {csv_filename}[/green]")


def read_domains_from_file(file_path: str) -> List[str]:
    """Read domains from either TXT or CSV file format."""
    domains = []
    file_path = Path(file_path)
    
    # Check if it's a CSV file
    if file_path.suffix.lower() == '.csv':
        try:
            with open(file_path, 'r', encoding='utf-8') as csvfile:
                # Try to detect if it has headers
                sample = csvfile.read(1024)
                csvfile.seek(0)
                
                # Check if first line looks like headers
                first_line = csvfile.readline().strip().lower()
                csvfile.seek(0)
                
                has_headers = 'domain' in first_line and 'host' in first_line
                
                reader = csv.DictReader(csvfile) if has_headers else csv.reader(csvfile)
                
                if has_headers:
                    # CSV with headers: domain, host columns
                    for row in reader:
                        domain = row.get('domain', '').strip()
                        host = row.get('host', '').strip()
                        
                        if domain and host:
                            # Combine host.domain
                            full_domain = f"{host}.{domain}"
                            domains.append(full_domain)
                        elif domain:
                            # Just domain without host
                            domains.append(domain)
                else:
                    # CSV without headers - assume two columns: domain, host
                    for row in reader:
                        if len(row) >= 2:
                            domain = row[0].strip()
                            host = row[1].strip()
                            
                            if domain and host:
                                # Combine host.domain
                                full_domain = f"{host}.{domain}"
                                domains.append(full_domain)
                        elif len(row) == 1 and row[0].strip():
                            # Single column - just domain
                            domains.append(row[0].strip())
                            
        except Exception as e:
            print(f"Error reading CSV file: {e}")
            return []
    else:
        # TXT file - one domain per line
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                domains = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"Error reading TXT file: {e}")
            return []
    
    return domains


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Accurate Domain Checker with Caching")
    parser.add_argument("input_file", help="File containing domains to check (TXT: one per line, CSV: domain,host columns)")
    parser.add_argument("--concurrency", type=int, default=15, 
                       help="Number of concurrent checks (default: 15)")
    parser.add_argument("--timeout", type=int, default=10, 
                       help="Timeout per request in seconds (default: 10)")
    parser.add_argument("--export", default="domain_results.json",
                       help="Export results to file (default: domain_results.json)")
    parser.add_argument("--export-csv", default="domain_results.csv",
                       help="Export results to CSV file (default: domain_results.csv)")
    parser.add_argument("--cache", default="domain_cache.json",
                       help="Cache file location (default: domain_cache.json)")
    
    args = parser.parse_args()
    
    # Read domains from file (supports both TXT and CSV)
    domains = read_domains_from_file(args.input_file)
    
    if not domains:
        print("Error: No domains found in input file")
        return
    
    # Initialize checker
    checker = AccurateDomainChecker(
        concurrency=args.concurrency,
        timeout=args.timeout
    )
    checker.cache_manager.cache_file = Path(args.cache)
    checker.cache_manager.load_cache()
    
    # Run checks
    console = Console()
    console.print(f"[blue]Starting accurate domain checking...[/blue]")
    console.print(f"[dim]Input domains: {len(domains)}[/dim]")
    console.print(f"[dim]Concurrency: {args.concurrency}[/dim]")
    console.print(f"[dim]Timeout: {args.timeout}s[/dim]")
    console.print(f"[dim]Cache file: {args.cache}[/dim]")
    
    try:
        results = asyncio.run(checker.check_domains(domains))
        
        # Display and export results
        checker.display_results(results)
        checker.export_results(results, args.export)
        checker.export_csv(results, args.export_csv)
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user. Progress has been saved.[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")


if __name__ == "__main__":
    main()
