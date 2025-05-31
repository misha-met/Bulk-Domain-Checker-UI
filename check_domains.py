#!/usr/bin/env python3
# Import necessary libraries
import asyncio # For asynchronous I/O operations
import argparse # For parsing command-line arguments
import httpx # Modern async HTTP client library
from httpx import AsyncClient, Limits, Timeout, HTTPError # Specific components from httpx
import urllib.parse # For parsing URLs
from tqdm import tqdm # For displaying progress bars (used in CLI mode)
from rich.console import Console # For rich text and beautiful formatting in the terminal
from rich.table import Table # For displaying results in a table format
from rich import box # Box styles for Rich tables
from collections import Counter # For counting occurrences of check results/details
import socket # Low-level networking interface (used for DNS lookup fallback)
import logging # For logging redirect history and domain checks

async def check(domain: str, client: AsyncClient) -> tuple[bool, str, list]:
    """Checks a single domain for responsiveness with redirect history tracking.

    Tries HTTPS, then HTTP. Tracks and logs redirect chains. If both fail, checks DNS resolution for better error reporting.

    Args:
        domain: The domain name (can include http/https prefix, path, etc.).
        client: An httpx.AsyncClient instance.

    Returns:
        A tuple containing:
            - bool: True if the domain serves HTTP content successfully, False otherwise.
            - str: A detail string explaining the result (e.g., status code, error message, redirect info).
            - list: Redirect history with step-by-step information.
    """
    # Extract the clean hostname (netloc) from the input domain string.
    # Handles cases like 'example.com', 'http://example.com/path', 'https://www.example.com:8080'
    parsed = urllib.parse.urlparse(domain)
    raw = parsed.netloc or parsed.path # Use netloc if present, otherwise assume path is the host
    host = raw.split('/')[0].split(':')[0] # Remove any path or port

    # Define the primary URLs to check (HTTPS first, then HTTP)
    urls = [f"https://{host}", f"http://{host}"]
    last_err = None # Keep track of the last error encountered

    # --- Primary Check: HTTP GET requests with redirect tracking --- 
    connection_failed = True  # Track if we had any successful HTTP connections
    for url in urls:
        try:
            # Track redirects manually to capture redirect history
            redirect_history = []
            current_url = url
            max_redirects = 10  # Prevent infinite redirect loops
            redirect_count = 0
            
            while redirect_count < max_redirects:
                # Perform a GET request without following redirects to track each step
                resp = await client.get(current_url, follow_redirects=False)
                connection_failed = False  # We got a response, even if it's an error
                
                # Debug logging for redirect detection
                logging.info(f"Domain {domain}: Got status {resp.status_code} for {current_url}")
                if 'location' in resp.headers:
                    logging.info(f"Domain {domain}: Location header: {resp.headers.get('location')}")
                
                # Record this step in redirect history
                step_info = {
                    "url": current_url,
                    "status_code": resp.status_code,
                    "step": redirect_count + 1
                }
                redirect_history.append(step_info)
                
                # Check if this is a redirect
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get('location')
                    if location:
                        # Handle relative URLs
                        if location.startswith('/'):
                            current_url = urllib.parse.urljoin(current_url, location)
                        else:
                            current_url = location
                        
                        redirect_count += 1
                        
                        # Log redirect step
                        logging.info(f"Domain {domain}: Redirect {redirect_count} - {resp.status_code} -> {current_url}")
                    else:
                        break
                else:
                    # Final response (not a redirect)
                    break
            
            # Log redirect chain if any redirects occurred
            if len(redirect_history) > 1:
                logging.info(f"Domain {domain}: {len(redirect_history) - 1} redirects total")
                for step in redirect_history:
                    logging.info(f"  Step {step['step']}: {step['status_code']} - {step['url']}")
            
            # Get status codes
            initial_status = redirect_history[0]['status_code']
            final_status = redirect_history[-1]['status_code']
            
            # For display purposes, show the initial status (especially important for redirects)
            display_status = initial_status
            
            # Consider any final status code below 400 (1xx, 2xx, 3xx) as success/responsive.
            if final_status < 400:
                detail = str(display_status)
                return True, detail, redirect_history
            else:
                # If final status code is 400 or higher, the server responded but with an error.
                # This means the domain is technically "reachable" but not serving content properly.
                detail = str(display_status)
                return False, detail, redirect_history
        except Exception as e:
            # Check if this is an HTTP/2 stream reset error
            if "StreamReset" in str(e) and hasattr(client, '_transport') and client._transport is not None:
                # HTTP/2 stream reset detected - try with HTTP/1.1 fallback
                logging.info(f"Domain {domain}: HTTP/2 StreamReset detected, attempting HTTP/1.1 fallback")
                try:
                    # Create a temporary HTTP/1.1-only client for this request
                    timeout_cfg = Timeout(timeout=client.timeout.read if client.timeout else 5.0)
                    limits = Limits(max_connections=1, max_keepalive_connections=1)
                    async with AsyncClient(http2=False, verify=False, trust_env=False, timeout=timeout_cfg, limits=limits) as fallback_client:
                        # Retry the request with HTTP/1.1
                        resp = await fallback_client.get(url, follow_redirects=False)
                        connection_failed = False
                        
                        # Record this successful fallback
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
                    last_err = e  # Keep original error
                    continue
            else:
                # Catch any other exception during the request (e.g., connection error, timeout, SSL error)
                last_err = e
                continue # Try the next URL

    # If we successfully connected via HTTP but got errors, we already returned above.
    # Only proceed to TCP fallback if we had connection failures (not HTTP errors).

    # If we successfully connected via HTTP but got errors, we already returned above.
    # Skip TCP fallback - for website checking, if HTTP doesn't work, it's not functional
    if not connection_failed:
        # We got HTTP responses but they were all errors - domain is reachable but not serving content
        return False, str(last_err or "HTTP errors on all protocols"), []

    # --- DNS Check for Better Error Reporting --- 
    # If HTTP failed, check DNS to provide more specific error information
    try:
        # Use the event loop's getaddrinfo to perform an async DNS lookup.
        await asyncio.get_event_loop().getaddrinfo(host, None)
        # DNS works but HTTP doesn't - provide the actual HTTP error
        return False, str(last_err) if last_err else 'HTTP connection failed', []
    except Exception as e:
        # If DNS resolution also fails, the domain name doesn't exist or DNS is broken
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
    # Configure the httpx AsyncClient
    timeout_cfg = Timeout(timeout=timeout) # Set overall request timeout
    # Set connection limits to control concurrency
    limits = Limits(max_connections=workers, max_keepalive_connections=workers)
    # Create the client, enabling HTTP/2, disabling SSL verification (common for broad checks),
    # ignoring environment proxies, and applying timeout/limits.
    # `verify=False` IS A SECURITY RISK for sensitive applications, but acceptable for general availability checks.
    async with AsyncClient(http2=True, verify=False, trust_env=False, timeout=timeout_cfg, limits=limits) as client:
        # Create a semaphore to limit concurrency to the specified number of workers
        sem = asyncio.Semaphore(workers)

        # Define a helper function to wrap the check call with the semaphore
        async def bound_check(d):
            async with sem: # Acquire the semaphore before running the check
                ok, detail, redirect_history = await check(d, client)
                return d, ok, detail, redirect_history # Return result tuple with redirect history
            # Semaphore is released automatically upon exiting the 'async with' block

        # Create a list of tasks (coroutines) for checking each domain
        tasks = [bound_check(d) for d in domains]
        results = []
        # Use asyncio.as_completed to process tasks as they finish, showing progress with tqdm
        for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Checking domains"):
            results.append(await coro) # Collect results as they become available
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
    # Configure the httpx AsyncClient (same configuration as the 'run' function)
    timeout_cfg = Timeout(timeout=timeout)
    limits = Limits(max_connections=workers, max_keepalive_connections=workers)
    async with AsyncClient(http2=True, verify=False, trust_env=False, timeout=timeout_cfg, limits=limits) as client:
        # Create a semaphore for concurrency control
        sem = asyncio.Semaphore(workers)

        # Define the semaphore-bound check helper function
        async def bound_check(d):
            async with sem:
                ok, detail, redirect_history = await check(d, client)
                return d, ok, detail, redirect_history

        # Create tasks for all domains
        tasks = [bound_check(d) for d in domains]
        # Use asyncio.as_completed to iterate over tasks as they finish
        for coro in asyncio.as_completed(tasks):
            d, ok, detail, redirect_history = await coro # Get the result from the completed coroutine
            yield d, ok, detail, redirect_history # Yield the result immediately

def main():
    """Main function for the command-line interface."""
    # Set up argument parser
    p = argparse.ArgumentParser(description="Check responsiveness of domains using multiple methods (HTTP, TCP, DNS).")
    p.add_argument("file", help="Path to a file containing domains, one per line.")
    p.add_argument("--timeout", type=int, default=5, help="Timeout in seconds for each check attempt (default: 5).")
    p.add_argument("--workers", type=int, default=100, help="Maximum number of concurrent checks (default: 100).")
    p.add_argument("--log-file", default="domain_check.log", help="Path to write detailed log output (default: domain_check.log).")
    args = p.parse_args()

    # Set up logging for redirect history
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(args.log_file),
            logging.StreamHandler()
        ]
    )

    # Read domains from the specified file
    try:
        with open(args.file) as f:
            # Read lines, strip whitespace, and ignore empty lines
            domains = [line.strip() for line in f if line.strip()]
        if not domains:
            print(f"Error: No domains found in file '{args.file}'")
            return
    except FileNotFoundError:
        print(f"Error: File not found '{args.file}'")
        return

    # Run the domain checks using the asyncio runner
    # asyncio.run() creates an event loop, runs the coroutine, and closes the loop.
    results = asyncio.run(run(domains, args.timeout, args.workers))

    # Separate results into responsive (up) and unresponsive (down)
    up = [(d, detail) for d, ok, detail, redirect_history in results if ok]
    down = [(d, detail) for d, ok, detail, redirect_history in results if not ok]

    # Count the occurrences of each unique result detail string
    reasons = Counter(detail for _, _, detail, _ in results)

    # --- Display Results using Rich --- 
    console = Console()

    # Create a table for the main results
    table = Table(title="Domain Check Results", show_header=True, header_style="bold magenta", box=box.SIMPLE)
    table.add_column("Domain", style="dim", width=40, overflow="fold") # Allow domain folding if long
    table.add_column("Status", justify="center")
    table.add_column("Detail", overflow="fold") # Allow detail folding

    # Populate the results table
    for d, ok, detail, redirect_history in sorted(results): # Sort results alphabetically by domain
        status = "[green]Online[/]" if ok else "[red]Offline[/]" # Use Rich markup for colors
        table.add_row(d, status, detail)

    # Print the main results table
    console.print(table)
    # Print a summary count
    console.print(f"Total: {len(results)} | Responsive: [green]{len(up)}[/] | Unresponsive: [red]{len(down)}[/]")

    # Create a table for the breakdown of reasons/details
    breakdown = Table(title="Result Details Breakdown", show_header=True, header_style="bold cyan", box=box.SIMPLE)
    breakdown.add_column("Reason / Detail", style="dim")
    breakdown.add_column("Count", justify="right")

    # Populate the breakdown table, sorted by count descending
    for reason, count in reasons.most_common():
        breakdown.add_row(reason, str(count))

    # Print the breakdown table
    console.print(breakdown)

    # --- Write Log File --- 
    try:
        with open(args.log_file, 'w') as logf:
            logf.write("# Domain Check Log\n")
            logf.write(f"# Total: {len(results)}, Responsive: {len(up)}, Unresponsive: {len(down)}\n")
            logf.write("#------------------------------------\n")
            # Write each result, sorted alphabetically, with a symbol indicator
            for d, ok, detail, redirect_history in sorted(results):
                symbol = '✔' if ok else '✖'
                logf.write(f"{symbol} {d} ({detail})\n")
        console.print(f"[dim]Detailed log written to {args.log_file}[/]")
    except IOError as e:
        console.print(f"[red]Error writing log file '{args.log_file}': {e}[/]")

# Standard Python entry point check
if __name__ == "__main__":
    main() # Run the main CLI function