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

async def check(domain: str, client: AsyncClient) -> tuple[bool, str]:
    """Checks a single domain for responsiveness.

    Tries HTTPS, then HTTP. If those fail, attempts TCP connection on 443/80.
    As a last resort, checks DNS resolution.

    Args:
        domain: The domain name (can include http/https prefix, path, etc.).
        client: An httpx.AsyncClient instance.

    Returns:
        A tuple containing:
            - bool: True if the domain is considered responsive, False otherwise.
            - str: A detail string explaining the result (e.g., status code, error message).
    """
    # Extract the clean hostname (netloc) from the input domain string.
    # Handles cases like 'example.com', 'http://example.com/path', 'https://www.example.com:8080'
    parsed = urllib.parse.urlparse(domain)
    raw = parsed.netloc or parsed.path # Use netloc if present, otherwise assume path is the host
    host = raw.split('/')[0].split(':')[0] # Remove any path or port

    # Define the primary URLs to check (HTTPS first, then HTTP)
    urls = [f"https://{host}", f"http://{host}"]
    last_err = None # Keep track of the last error encountered

    # --- Primary Check: HTTP GET requests --- 
    for url in urls:
        try:
            # Perform a GET request, but *do not* follow redirects initially.
            # This helps determine the initial status of the direct URL.
            resp = await client.get(url, follow_redirects=False)

            # Consider any status code below 400 (1xx, 2xx, 3xx) as success/responsive.
            # We report the specific status code (e.g., 200, 301, 302) as the detail.
            if resp.status_code < 400:
                return True, str(resp.status_code)
            else:
                # If status code is 400 or higher, treat it as an error for this specific URL.
                last_err = HTTPError(f"HTTP status {resp.status_code}")
                continue # Try the next URL (e.g., try HTTP if HTTPS failed)
        except Exception as e:
            # Catch any exception during the request (e.g., connection error, timeout, SSL error)
            last_err = e
            continue # Try the next URL

    # --- Fallback Check 1: TCP Connection --- 
    # If both HTTPS and HTTP GET requests failed, try a direct TCP connection.
    for port in (443, 80): # Check standard HTTPS and HTTP ports
        try:
            # Attempt to open a TCP connection to the host on the specified port.
            # Use a timeout matching the client's connect timeout.
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=client.timeout.connect
            )
            # If connection succeeds, immediately close it.
            writer.close()
            await writer.wait_closed()
            # Consider successful TCP connection as responsive.
            return True, f'TCP connect on port {port}'
        except asyncio.TimeoutError:
            # Record timeout error specifically.
            last_err = asyncio.TimeoutError(f"TCP connect timeout on port {port}")
        except Exception as e:
            # Record any other connection error.
            last_err = e
            pass # Continue to try the next port or the next fallback

    # --- Fallback Check 2: DNS Resolution --- 
    # If all previous checks failed, try resolving the domain name via DNS.
    try:
        # Use the event loop's getaddrinfo to perform an async DNS lookup.
        await asyncio.get_event_loop().getaddrinfo(host, None)
        # If DNS resolution succeeds, consider it responsive (but note it's DNS only).
        return True, 'DNS resolution only'
    except Exception as e:
        # If DNS resolution also fails, the domain is considered unresponsive.
        # Return False and the *last recorded error* from any previous step (or the DNS error).
        return False, str(last_err or e) # Ensure an error string is always returned

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
                ok, detail = await check(d, client)
                return d, ok, detail # Return result tuple
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
        Tuples of (domain, ok, detail) as each check finishes.
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
                ok, detail = await check(d, client)
                return d, ok, detail

        # Create tasks for all domains
        tasks = [bound_check(d) for d in domains]
        # Use asyncio.as_completed to iterate over tasks as they finish
        for coro in asyncio.as_completed(tasks):
            d, ok, detail = await coro # Get the result from the completed coroutine
            yield d, ok, detail # Yield the result immediately

def main():
    """Main function for the command-line interface."""
    # Set up argument parser
    p = argparse.ArgumentParser(description="Check responsiveness of domains using multiple methods (HTTP, TCP, DNS).")
    p.add_argument("file", help="Path to a file containing domains, one per line.")
    p.add_argument("--timeout", type=int, default=5, help="Timeout in seconds for each check attempt (default: 5).")
    p.add_argument("--workers", type=int, default=100, help="Maximum number of concurrent checks (default: 100).")
    p.add_argument("--log-file", default="domain_check.log", help="Path to write detailed log output (default: domain_check.log).")
    args = p.parse_args()

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
    up = [(d, detail) for d, ok, detail in results if ok]
    down = [(d, detail) for d, ok, detail in results if not ok]

    # Count the occurrences of each unique result detail string
    reasons = Counter(detail for _, _, detail in results)

    # --- Display Results using Rich --- 
    console = Console()

    # Create a table for the main results
    table = Table(title="Domain Check Results", show_header=True, header_style="bold magenta", box=box.SIMPLE)
    table.add_column("Domain", style="dim", width=40, overflow="fold") # Allow domain folding if long
    table.add_column("Status", justify="center")
    table.add_column("Detail", overflow="fold") # Allow detail folding

    # Populate the results table
    for d, ok, detail in sorted(results): # Sort results alphabetically by domain
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
            for d, ok, detail in sorted(results):
                symbol = '✔' if ok else '✖'
                logf.write(f"{symbol} {d} ({detail})\n")
        console.print(f"[dim]Detailed log written to {args.log_file}[/]")
    except IOError as e:
        console.print(f"[red]Error writing log file '{args.log_file}': {e}[/]")

# Standard Python entry point check
if __name__ == "__main__":
    main() # Run the main CLI function