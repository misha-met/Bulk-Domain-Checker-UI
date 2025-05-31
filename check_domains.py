#!/usr/bin/env python3
"""
Domain responsiveness checker with comprehensive redirect tracking.

Provides both async streaming functions for web integration and CLI functionality
for bulk domain checking with detailed progress reporting and results export.
"""

import asyncio
import argparse
import httpx
from httpx import AsyncClient, Limits, Timeout, HTTPError
import urllib.parse
from tqdm import tqdm
from rich.console import Console
from rich.table import Table
from rich import box
from collections import Counter
import socket
import logging


async def check(domain: str, client: AsyncClient) -> tuple[bool, str, list]:
    """
    Checks a single domain for responsiveness with redirect history tracking.

    Tries HTTPS first, then HTTP. Tracks and logs redirect chains. If both fail, 
    checks DNS resolution for better error reporting.

    Args:
        domain: The domain name (can include http/https prefix, path, etc.)
        client: An httpx.AsyncClient instance

    Returns:
        Tuple containing:
        - bool: True if domain is responsive, False otherwise
        - str: Detail string explaining the result
        - list: Redirect history with step-by-step information
    """
    parsed = urllib.parse.urlparse(domain)
    raw = parsed.netloc or parsed.path
    host = raw.split('/')[0].split(':')[0]

    urls = [f"https://{host}", f"http://{host}"]
    last_err = None

    connection_failed = True
    for url in urls:
        try:
            redirect_history = []
            current_url = url
            max_redirects = 10
            redirect_count = 0
            
            while redirect_count < max_redirects:
                resp = await client.get(current_url, follow_redirects=False)
                connection_failed = False
                
                logging.info(f"Domain {domain}: Got status {resp.status_code} for {current_url}")
                if 'location' in resp.headers:
                    logging.info(f"Domain {domain}: Location header: {resp.headers.get('location')}")
                
                step_info = {
                    "url": current_url,
                    "status_code": resp.status_code,
                    "step": redirect_count + 1
                }
                redirect_history.append(step_info)
                
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get('location')
                    if location:
                        if location.startswith('/'):
                            current_url = urllib.parse.urljoin(current_url, location)
                        else:
                            current_url = location
                        
                        redirect_count += 1
                        logging.info(f"Domain {domain}: Redirect {redirect_count} - {resp.status_code} -> {current_url}")
                    else:
                        break
                else:
                    break
            
            if len(redirect_history) > 1:
                logging.info(f"Domain {domain}: {len(redirect_history) - 1} redirects total")
                for step in redirect_history:
                    logging.info(f"  Step {step['step']}: {step['status_code']} - {step['url']}")

            initial_status = redirect_history[0]['status_code']
            final_status = redirect_history[-1]['status_code']
            display_status = initial_status
            
            if final_status < 400:
                detail = str(display_status)
                return True, detail, redirect_history
            else:
                detail = str(display_status)
                return False, detail, redirect_history
        except Exception as e:
            if "StreamReset" in str(e) and hasattr(client, '_transport') and client._transport is not None:
                logging.info(f"Domain {domain}: HTTP/2 StreamReset detected, attempting HTTP/1.1 fallback")
                try:
                    timeout_cfg = Timeout(timeout=client.timeout.read if client.timeout else 5.0)
                    limits = Limits(max_connections=1, max_keepalive_connections=1)
                    async with AsyncClient(http2=False, verify=False, trust_env=False, timeout=timeout_cfg, limits=limits) as fallback_client:
                        resp = await fallback_client.get(url, follow_redirects=False)
                        connection_failed = False
                        
                        step_info = {
                            "url": url,
                            "status_code": resp.status_code,
                            "step": 1
                        }
                        redirect_history = [step_info]
                        
                        if resp.status_code < 400:
                            detail = f"{resp.status_code} (HTTP/1.1 fallback)"
                            return True, detail, redirect_history
                        else:
                            detail = f"{resp.status_code} (HTTP/1.1 fallback)"
                            return False, detail, redirect_history
                except Exception as fallback_err:
                    logging.info(f"Domain {domain}: HTTP/1.1 fallback also failed: {fallback_err}")
                    last_err = e
                    continue
            else:
                last_err = e
                continue

    if not connection_failed:
        return False, str(last_err or "HTTP errors on all protocols"), []

    try:
        await asyncio.get_event_loop().getaddrinfo(host, None)
        return False, str(last_err) if last_err else 'HTTP connection failed', []
    except Exception as e:
        return False, f'DNS resolution failed: {str(e)}', []

async def run(domains, timeout, workers):
    """Runs checks for a list of domains concurrently (CLI version).

    Args:
        domains: A list of domain strings.
        timeout: Request timeout in seconds.
        workers: Maximum number of concurrent checks.

    Returns:
        A list of tuples: [(domain, ok, detail), ...]
    """
    timeout_cfg = Timeout(timeout=timeout)
    limits = Limits(max_connections=workers, max_keepalive_connections=workers)
    async with AsyncClient(http2=True, verify=False, trust_env=False, timeout=timeout_cfg, limits=limits) as client:
        sem = asyncio.Semaphore(workers)

        async def bound_check(d):
            async with sem:
                ok, detail, redirect_history = await check(d, client)
                return d, ok, detail, redirect_history

        tasks = [bound_check(d) for d in domains]
        results = []
        for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Checking domains"):
            results.append(await coro)
        return results

async def run_stream(domains, timeout, workers):
    """Runs checks concurrently and yields results as they complete (Web API version).

    Args:
        domains: A list of domain strings.
        timeout: Request timeout in seconds.
        workers: Maximum number of concurrent checks.

    Yields:
        Tuples of (domain, ok, detail, redirect_history) as each check finishes.
    """
    timeout_cfg = Timeout(timeout=timeout)
    limits = Limits(max_connections=workers, max_keepalive_connections=workers)
    async with AsyncClient(http2=True, verify=False, trust_env=False, timeout=timeout_cfg, limits=limits) as client:
        sem = asyncio.Semaphore(workers)

        async def bound_check(d):
            async with sem:
                ok, detail, redirect_history = await check(d, client)
                return d, ok, detail, redirect_history

        tasks = [bound_check(d) for d in domains]
        for coro in asyncio.as_completed(tasks):
            d, ok, detail, redirect_history = await coro
            yield d, ok, detail, redirect_history

def main():
    """Main function for the command-line interface."""
    p = argparse.ArgumentParser(description="Check responsiveness of domains using HTTP and DNS methods.")
    p.add_argument("file", help="Path to a file containing domains, one per line.")
    p.add_argument("--timeout", type=int, default=5, help="Timeout in seconds for each check attempt (default: 5).")
    p.add_argument("--workers", type=int, default=100, help="Maximum number of concurrent checks (default: 100).")
    p.add_argument("--log-file", default="domain_check.log", help="Path to write detailed log output (default: domain_check.log).")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(args.log_file),
            logging.StreamHandler()
        ]
    )

    try:
        with open(args.file) as f:
            domains = [line.strip() for line in f if line.strip()]
        if not domains:
            print(f"Error: No domains found in file '{args.file}'")
            return
    except FileNotFoundError:
        print(f"Error: File not found '{args.file}'")
        return

    results = asyncio.run(run(domains, args.timeout, args.workers))

    up = [(d, detail) for d, ok, detail, redirect_history in results if ok]
    down = [(d, detail) for d, ok, detail, redirect_history in results if not ok]
    reasons = Counter(detail for _, _, detail, _ in results)

    console = Console()

    table = Table(title="Domain Check Results", show_header=True, header_style="bold magenta", box=box.SIMPLE)
    table.add_column("Domain", style="dim", width=40, overflow="fold")
    table.add_column("Status", justify="center")
    table.add_column("Detail", overflow="fold")

    for d, ok, detail, redirect_history in sorted(results):
        status = "[green]Online[/]" if ok else "[red]Offline[/]"
        table.add_row(d, status, detail)

    console.print(table)
    console.print(f"Total: {len(results)} | Responsive: [green]{len(up)}[/] | Unresponsive: [red]{len(down)}[/]")

    breakdown = Table(title="Result Details Breakdown", show_header=True, header_style="bold cyan", box=box.SIMPLE)
    breakdown.add_column("Reason / Detail", style="dim")
    breakdown.add_column("Count", justify="right")

    for reason, count in reasons.most_common():
        breakdown.add_row(reason, str(count))

    console.print(breakdown)

    try:
        with open(args.log_file, 'w') as logf:
            logf.write("# Domain Check Log\n")
            logf.write(f"# Total: {len(results)}, Responsive: {len(up)}, Unresponsive: {len(down)}\n")
            logf.write("#------------------------------------\n")
            for d, ok, detail, redirect_history in sorted(results):
                symbol = '✔' if ok else '✖'
                logf.write(f"{symbol} {d} ({detail})\n")
        console.print(f"[dim]Detailed log written to {args.log_file}[/]")
    except IOError as e:
        console.print(f"[red]Error writing log file '{args.log_file}': {e}[/]")

if __name__ == "__main__":
    main()
