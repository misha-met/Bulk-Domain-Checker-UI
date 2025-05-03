#!/usr/bin/env python3
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

async def check(domain: str, client: AsyncClient) -> tuple[bool, str]:
    # Extract clean host (strip any path, query, or port)
    parsed = urllib.parse.urlparse(domain)
    raw = parsed.netloc or parsed.path
    host = raw.split('/')[0].split(':')[0]
    # Try both schemes WITHOUT trailing slash initially, NO redirects
    urls = [f"https://{host}", f"http://{host}"]
    last_err = None
    for url in urls:
        try:
            # Perform GET WITHOUT redirects first
            resp = await client.get(url, follow_redirects=False)
            # Return True for any status code < 400 (success or redirect)
            # and report the actual status code
            if resp.status_code < 400:
                return True, str(resp.status_code)
            else:
                # Treat >= 400 as an error for this specific URL attempt
                last_err = HTTPError(f"HTTP status {resp.status_code}")
                continue # Try the other scheme
        except Exception as e:
            # record error and try next URL
            last_err = e
            continue

    # If initial checks failed (no 2xx/3xx), try fallbacks
    # TCP connect fallback on ports 443/80
    for port in (443, 80):
        try:
            # Set a reasonable timeout for the connection attempt
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=client.timeout.connect
            )
            writer.close()
            await writer.wait_closed()
            return True, f'TCP connect on port {port}'
        except asyncio.TimeoutError:
            last_err = asyncio.TimeoutError(f"TCP connect timeout on port {port}")
        except Exception as e:
            last_err = e # Keep the last error
            pass # Try next port or DNS

    # DNS resolution fallback
    try:
        await asyncio.get_event_loop().getaddrinfo(host, None)
        return True, 'DNS resolution only'
    except Exception as e:
        # If DNS also fails, return False with the last recorded error
        return False, str(last_err or e) # Ensure we return an error string

async def run(domains, timeout, workers):
    # configure HTTPX async client with HTTP/2 and limits
    timeout_cfg = Timeout(timeout=timeout)
    limits = Limits(max_connections=workers, max_keepalive_connections=workers)
    async with AsyncClient(http2=True, verify=False, trust_env=False, timeout=timeout_cfg, limits=limits) as client:
        sem = asyncio.Semaphore(workers)
        async def bound_check(d):
            async with sem:
                ok, detail = await check(d, client)
                return d, ok, detail

        tasks = [bound_check(d) for d in domains]
        results = []
        for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
            results.append(await coro)
        return results

async def run_stream(domains, timeout, workers):
    """Async generator: yields (domain, ok, detail) as each check completes."""
    timeout_cfg = Timeout(timeout=timeout)
    limits = Limits(max_connections=workers, max_keepalive_connections=workers)
    async with AsyncClient(http2=True, verify=False, trust_env=False, timeout=timeout_cfg, limits=limits) as client:
        sem = asyncio.Semaphore(workers)
        async def bound_check(d):
            async with sem:
                ok, detail = await check(d, client)
                return d, ok, detail

        tasks = [bound_check(d) for d in domains]
        for coro in asyncio.as_completed(tasks):
            d, ok, detail = await coro
            yield d, ok, detail

def main():
    p = argparse.ArgumentParser(description="Check responsiveness of domains")
    p.add_argument("file", help="One domain per line")
    p.add_argument("--timeout", type=int, default=5, help="Seconds per request")
    p.add_argument("--workers", type=int, default=100, help="Max concurrent requests")
    p.add_argument("--log-file", default="domain_check.log", help="Path to log file")
    args = p.parse_args()

    with open(args.file) as f:
        domains = [line.strip() for line in f if line.strip()]

    results = asyncio.run(run(domains, args.timeout, args.workers))
    up = [(d, detail) for d, ok, detail in results if ok]
    down = [(d, detail) for d, ok, detail in results if not ok]

    # Detailed breakdown of results by reason
    reasons = Counter(detail for _, _, detail in results)
    
    # display results in a rich table
    console = Console()
    table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
    table.add_column("Domain", style="dim", width=30)
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for d, ok, detail in results:
        status = "[green]Online[/]" if ok else "[red]Taken[/]"
        table.add_row(d, status, detail)
    console.print(table)
    console.print(f"Responsive: [green]{len(up)}[/]    Unresponsive: [red]{len(down)}[/]")

    # print breakdown of detail reasons
    breakdown = Table(show_header=True, header_style="bold cyan")
    breakdown.add_column("Reason", style="dim")
    breakdown.add_column("Count", justify="right")
    for reason, count in reasons.most_common():
        breakdown.add_row(reason, str(count))
    console.print(breakdown)

    # write log file
    with open(args.log_file, 'w') as logf:
        for d, ok, detail in results:
            symbol = '✔' if ok else '✖'
            logf.write(f"{symbol} {d} ({detail})\n")

if __name__ == "__main__":
    main()