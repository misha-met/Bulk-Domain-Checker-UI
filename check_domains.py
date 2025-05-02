#!/usr/bin/env python3
import asyncio
import argparse
from aiohttp import ClientSession, ClientTimeout
from tqdm import tqdm
from rich.console import Console
from rich.table import Table
from rich import box

async def check(domain: str, session: ClientSession, timeout: ClientTimeout) -> tuple[bool, str]:
    url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
    try:
        async with session.head(url, timeout=timeout) as resp:
            return resp.status < 400, str(resp.status)
    except Exception as e:
        return False, str(e)

async def run(domains, timeout, workers):
    timeout = ClientTimeout(total=timeout)
    async with ClientSession(timeout=timeout) as session:
        sem = asyncio.Semaphore(workers)
        async def bound_check(d):
            async with sem:
                ok, detail = await check(d, session, timeout)
                return d, ok, detail

        tasks = [bound_check(d) for d in domains]
        results = []
        for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
            results.append(await coro)
        return results


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

    # write log file
    with open(args.log_file, 'w') as logf:
        for d, ok, detail in results:
            symbol = '✔' if ok else '✖'
            logf.write(f"{symbol} {d} ({detail})\n")

if __name__ == "__main__":
    main()