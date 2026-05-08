#!/usr/bin/env python3
"""Bulk domain responsiveness checker.

Strategy per domain:
  1. Normalize the input while preserving the literal hostname.
  2. Resolve DNS using either the OS path or pinned public resolvers.
  3. Try HTTPS first with HEAD; on 405, retry with GET.
  4. Surface SSL/cert failures as `ssl` without masking them via HTTP.
  5. Only fall back to HTTP for connection-class HTTPS failures.

The CLI mode uses Rich for table output; the web mode imports `run_stream`.
"""
from __future__ import annotations

import argparse
import asyncio
import socket
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import AsyncIterator, Literal

import httpx
from httpx import AsyncClient, Limits, Timeout
from rich import box
from rich.console import Console
from rich.table import Table
from tqdm import tqdm

USER_AGENT = "BulkDomainChecker/2.0 (+https://github.com)"

DnsMode = Literal["system", "direct"]


# ──────────────────────────────────────────────────────────────────────────────
# DNS resolver supports two modes depending on what point of view you want to test.
#
# 'system' mode uses socket.getaddrinfo on a dedicated thread pool. It honours
#             /etc/hosts, the OS resolver, corporate VPN routes, MDM-pushed
#             DNS profiles, Pi-hole on the local interface, etc. Tells you
#             what *your machine* would actually see when visiting the URL.
# 'direct' mode uses aiodns and libcares to query public DNS directly over UDP,
#             Bypasses every local layer above. Tells you whether the domain
#             exists on the public internet, regardless of your network.
#
# Diagnostic pattern: run once in 'system', run again in 'direct'. Domains
# that fail in system but succeed in direct are the ones your firewall /
# DNS policy is silently blocking the domain rather than it actually being down.
# ──────────────────────────────────────────────────────────────────────────────
class Resolver:
    def __init__(
        self,
        mode: DnsMode = "system",
        concurrency: int = 64,
        timeout: float = 3.0,
    ) -> None:
        self.mode = mode
        self.timeout = timeout
        self._executor: ThreadPoolExecutor | None = None
        self._aiodns = None
        if mode == "system":
            # Dedicated pool so DNS doesn't compete with whatever else is on
            # the asyncio default executor. Sized to absorb a burst.
            self._executor = ThreadPoolExecutor(
                max_workers=concurrency, thread_name_prefix="dns-"
            )
        elif mode == "direct":
            try:
                import aiodns  # type: ignore
            except ImportError as e:
                raise RuntimeError(
                    "Direct DNS mode requires the 'aiodns' package. "
                    "Install with: pip install aiodns"
                ) from e
            # Pin to public resolvers so the diagnostic story is honest:
            # "Direct" must mean "ask the public internet, not the network
            # I'm sitting on". Without explicit nameservers, aiodns falls
            # back to /etc/resolv.conf on Linux and platform-specific paths
            # on macOS, which defeats the whole point.
            self._aiodns = aiodns.DNSResolver(
                timeout=timeout,
                tries=2,
                nameservers=["1.1.1.1", "8.8.8.8", "9.9.9.9"],
            )
        else:
            raise ValueError(f"Unknown DNS mode: {mode!r}")

    async def resolve(self, host: str) -> tuple[bool, str | None]:
        """Resolve `host`. Returns (ok, error_detail_if_failed)."""
        if self.mode == "system":
            return await self._resolve_system(host)
        return await self._resolve_direct(host)

    async def _resolve_system(self, host: str) -> tuple[bool, str | None]:
        loop = asyncio.get_running_loop()
        last_msg = "DNS failed"
        # One retry on transient errors (EAI_AGAIN). NXDOMAIN-class errors
        # are returned immediately because there is no point retrying a confirmed "no such host".
        for attempt in range(2):
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(
                        self._executor, socket.getaddrinfo, host, None
                    ),
                    timeout=self.timeout,
                )
                return True, None
            except asyncio.TimeoutError:
                last_msg = "DNS timeout"
                # A timeout is transient enough to retry once.
                if attempt == 0:
                    continue
                return False, last_msg
            except socket.gaierror as e:
                # macOS / Linux gaierror codes worth distinguishing:
                #   EAI_AGAIN (3 / -3): transient error, try again.
                #   EAI_NONAME (8 / -2): NXDOMAIN represents a definitive failure, do not retry.
                if e.errno in (socket.EAI_AGAIN, -3) and attempt == 0:
                    await asyncio.sleep(0.1)
                    last_msg = f"DNS transient: {e.strerror or str(e)}"
                    continue
                return False, _gai_message(e)
            except OSError as e:
                return False, f"DNS error: {_truncate(str(e), 60)}"
        return False, last_msg

    async def _resolve_direct(self, host: str) -> tuple[bool, str | None]:
        """Resolve via aiodns. Race A and AAAA records and succeed if either resolves
        so IPv6-only hosts aren't false negatives."""
        import aiodns  # type: ignore

        # aiodns.query returns a pycares Future (not a coroutine) so wrap
        # with ensure_future, which accepts both.
        a_task = asyncio.ensure_future(self._aiodns.query(host, "A"))
        aaaa_task = asyncio.ensure_future(self._aiodns.query(host, "AAAA"))
        pending: set[asyncio.Future] = {a_task, aaaa_task}
        last_err: BaseException | None = None
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for t in done:
                    try:
                        t.result()
                        return True, None
                    except asyncio.CancelledError:
                        raise
                    except BaseException as e:  # noqa: BLE001
                        last_err = e
        finally:
            for p in pending:
                p.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        # Both A and AAAA failed. Report the most specific reason.
        if isinstance(last_err, aiodns.error.DNSError):  # type: ignore[attr-defined]
            code = last_err.args[0] if last_err.args else 0
            msg = last_err.args[1] if len(last_err.args) > 1 else str(last_err)
            # c-ares error codes (subset we care about):
            #   1=ENODATA 4=ENOTFOUND (NXDOMAIN) 11=ETIMEOUT 6=EREFUSED
            if code == 4:
                return False, "DNS: no record (NXDOMAIN)"
            if code == 1:
                return False, "DNS: no A or AAAA record"
            if code == 11:
                return False, "DNS: timeout (direct)"
            if code == 6:
                return False, "DNS: refused by public resolver"
            return False, f"DNS: {_truncate(str(msg), 60)}"
        return False, f"DNS error: {_truncate(str(last_err) if last_err else 'unknown', 60)}"

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False)


def _gai_message(e: socket.gaierror) -> str:
    # Strip the "[Errno 8]" prefix we used to surface because the human label is
    # clearer for end users and stable across platforms.
    if e.errno in (socket.EAI_NONAME, -2):
        return "DNS: no record (NXDOMAIN)"
    if e.errno in (socket.EAI_AGAIN, -3):
        return "DNS: transient resolver failure"
    msg = e.strerror or str(e)
    return f"DNS: {_truncate(msg, 60)}"


@dataclass
class CheckResult:
    domain: str
    ok: bool
    detail: str
    category: str  # online | http_error | timeout | dns | connection | ssl | other
    status_code: int | None = None
    elapsed_ms: float | None = None
    protocol: str | None = None  # "https" or "http"

    def to_dict(self) -> dict:
        return asdict(self)


def _extract_host(domain: str) -> str:
    """Pull a clean hostname out of arbitrary input (URL, bare host, host:port)."""
    raw = domain.strip()
    if not raw:
        return ""
    # If there's no scheme, urlparse puts everything in path; prefix one.
    if "://" not in raw:
        raw = "//" + raw
    parsed = urllib.parse.urlparse(raw)
    host = parsed.hostname or ""
    return host.lower()


def _categorize_exception(exc: BaseException) -> tuple[str, str]:
    """Map an httpx/network exception to (category, short detail)."""
    if isinstance(exc, httpx.ConnectTimeout):
        return "timeout", "Connect timeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "timeout", "Read timeout"
    if isinstance(exc, httpx.PoolTimeout):
        return "timeout", "Pool timeout"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", "Timeout"
    # For SSL detection, httpx wraps ssl errors in ConnectError, so we need to sniff the message.
    msg = str(exc) or exc.__class__.__name__
    low = msg.lower()
    if "ssl" in low or "certificate" in low or "tls" in low:
        return "ssl", _truncate(f"SSL: {msg}")
    if isinstance(exc, httpx.ConnectError):
        return "connection", _truncate(f"Connect: {msg}")
    if isinstance(exc, httpx.NetworkError):
        return "connection", _truncate(f"Network: {msg}")
    return "other", _truncate(msg)


def _truncate(s: str, n: int = 80) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


async def _try_one(
    client: AsyncClient, url: str, *, allow_get_fallback: bool = True
) -> tuple[httpx.Response | None, BaseException | None]:
    """Issue HEAD; on 405, retry the same URL with GET. Returns (response, error)."""
    try:
        resp = await client.request("HEAD", url, follow_redirects=False)
        if resp.status_code == 405 and allow_get_fallback:
            resp = await client.get(url, follow_redirects=False)
        return resp, None
    except asyncio.CancelledError:
        raise
    except BaseException as e:  # noqa: BLE001 to surface every kind of failure
        return None, e


async def check(domain: str, client: AsyncClient, resolver: Resolver) -> CheckResult:
    """Check one domain with DNS preflight, HTTPS-first logic, and HTTP fallback."""
    host = _extract_host(domain)
    if not host:
        return CheckResult(domain=domain, ok=False, detail="Invalid domain", category="other")

    # ── DNS prefetch via the chosen resolver. ─────────────────────────────────
    # Bad domains fail fast (~ms instead of HTTP-timeout seconds), and the
    # resolver mode determines whether we honour local network rules
    # (system) or query public DNS (direct).
    ok, dns_err = await resolver.resolve(host)
    if not ok:
        return CheckResult(domain=domain, ok=False, detail=dns_err or "DNS failed", category="dns")

    # ── HTTPS first; HTTP only as a connection-class fallback. ──────────────
    # The previous design raced HTTPS + HTTP and took whichever responded
    # first. That hid SSL failures whenever the site also redirects HTTP→HTTPS:
    # the HTTP HEAD returned a 301 before HTTPS finished its handshake, the
    # HTTPS task was cancelled, and the cert error never surfaced.
    #
    # New rule:
    #   1. Try HTTPS. If it succeeds, return.
    #   2. If HTTPS responds with 4xx/5xx, that's the answer (http_error).
    #   3. If HTTPS fails with SSL/cert error → ssl, *don't* try HTTP.
    #      The site is broken from a browser's perspective; HTTP would
    #      mask the real failure.
    #   4. If HTTPS fails with a connection-class error (refused, no route,
    #      timeout) → fall back to HTTP, since the site might be HTTP-only.
    https_resp, https_err = await _try_one(client, f"https://{host}")
    if https_resp is not None and https_resp.status_code < 400:
        return _online(domain, https_resp, "https")
    if https_resp is not None:
        return _http_error(domain, https_resp, "https")
    if https_err is not None:
        category, detail = _categorize_exception(https_err)
        if category == "ssl":
            return CheckResult(domain=domain, ok=False, detail=detail, category="ssl")
        # Since there was a connection-class failure on HTTPS, try HTTP as a graceful fallback.

    http_resp, http_err = await _try_one(client, f"http://{host}")
    if http_resp is not None and http_resp.status_code < 400:
        return _online(domain, http_resp, "http")
    if http_resp is not None:
        return _http_error(domain, http_resp, "http")

    # Both failed. Prefer HTTPS error info since that's the canonical endpoint.
    last_exc = https_err or http_err
    category, detail = (
        _categorize_exception(last_exc) if last_exc else ("other", "Unknown error")
    )
    return CheckResult(domain=domain, ok=False, detail=detail, category=category)


def _online(domain: str, resp: httpx.Response, proto: str) -> CheckResult:
    elapsed = resp.elapsed.total_seconds() * 1000 if resp.elapsed else None
    return CheckResult(
        domain=domain, ok=True, detail=str(resp.status_code), category="online",
        status_code=resp.status_code,
        elapsed_ms=round(elapsed, 1) if elapsed is not None else None,
        protocol=proto,
    )


def _http_error(domain: str, resp: httpx.Response, proto: str) -> CheckResult:
    elapsed = resp.elapsed.total_seconds() * 1000 if resp.elapsed else None
    return CheckResult(
        domain=domain, ok=False, detail=f"HTTP {resp.status_code}",
        category="http_error", status_code=resp.status_code,
        elapsed_ms=round(elapsed, 1) if elapsed is not None else None,
        protocol=proto,
    )


def _make_client(timeout: float, workers: int) -> AsyncClient:
    """Configure the async HTTP client.

    SSL verification is **on** by default (verify=True). Expired, self-signed,
    or hostname-mismatched certs surface as `ssl` failures which is what
    you want, because a browser would refuse to load the site too. Internal
    sites with corp-signed certs work because we honour SSL_CERT_FILE /
    SSL_CERT_DIR env vars (trust_env=True).

    Environment trust is **on** so the checker mirrors what the user's
    browser would see: HTTP_PROXY / HTTPS_PROXY / NO_PROXY are honoured,
    along with custom CA bundle paths. This is essential for corporate
    networks behind a TLS-terminating proxy.
    """
    timeout_cfg = Timeout(connect=min(timeout, 5.0), read=timeout, write=timeout, pool=None)
    limits = Limits(
        max_connections=workers,
        max_keepalive_connections=min(workers, 50),
        keepalive_expiry=15.0,
    )
    return AsyncClient(
        http2=True,
        verify=True,
        trust_env=True,
        timeout=timeout_cfg,
        limits=limits,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        follow_redirects=False,
    )


async def run_stream(
    domains: list[str],
    timeout: float,
    workers: int,
    dns_mode: DnsMode = "system",
) -> AsyncIterator[CheckResult]:
    """Yield results as each check completes (used by the web API)."""
    resolver = Resolver(mode=dns_mode, concurrency=max(64, workers), timeout=3.0)
    try:
        async with _make_client(timeout, workers) as client:
            sem = asyncio.Semaphore(workers)

            async def bound(d: str) -> CheckResult:
                async with sem:
                    return await check(d, client, resolver)

            tasks = [asyncio.create_task(bound(d)) for d in domains]
            try:
                for coro in asyncio.as_completed(tasks):
                    yield await coro
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        resolver.close()


async def run(
    domains: list[str],
    timeout: float,
    workers: int,
    dns_mode: DnsMode = "system",
) -> list[CheckResult]:
    """Run all checks concurrently and collect results (used by the CLI)."""
    results: list[CheckResult] = []
    resolver = Resolver(mode=dns_mode, concurrency=max(64, workers), timeout=3.0)
    try:
        async with _make_client(timeout, workers) as client:
            sem = asyncio.Semaphore(workers)

            async def bound(d: str) -> CheckResult:
                async with sem:
                    return await check(d, client, resolver)

            tasks = [bound(d) for d in domains]
            for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Checking domains"):
                results.append(await coro)
    finally:
        resolver.close()
    return results


def _install_uvloop() -> None:
    """Use uvloop on platforms where it's available since it provides 2x to 4x event-loop performance."""
    try:
        import uvloop  # type: ignore
        uvloop.install()
    except ImportError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check responsiveness of domains using DNS preflight and HTTPS-first HTTP checks."
    )
    parser.add_argument("file", help="Path to a file containing domains, one per line.")
    parser.add_argument("--timeout", type=float, default=5.0, help="Per-check timeout (default: 5).")
    parser.add_argument("--workers", type=int, default=100, help="Max concurrent checks (default: 100).")
    parser.add_argument("--log-file", default="domain_check.log", help="Output log path.")
    parser.add_argument("--json", action="store_true", help="Emit NDJSON to stdout instead of tables.")
    parser.add_argument(
        "--dns-mode",
        choices=["system", "direct"],
        default="system",
        help="DNS resolution mode. 'system' (default) honours OS resolver, "
             "/etc/hosts, VPN, firewall. 'direct' queries pinned public "
             "resolvers (1.1.1.1 / 8.8.8.8 / 9.9.9.9) directly and bypasses "
             "local DNS overrides (requires aiodns).",
    )
    args = parser.parse_args()

    try:
        with open(args.file) as f:
            domains = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"Error: File not found '{args.file}'")
        return
    if not domains:
        print(f"Error: No domains found in '{args.file}'")
        return

    _install_uvloop()
    results = asyncio.run(run(domains, args.timeout, args.workers, dns_mode=args.dns_mode))

    if args.json:
        import json
        for r in results:
            print(json.dumps(r.to_dict()))
        return

    up = [r for r in results if r.ok]
    down = [r for r in results if not r.ok]
    reasons = Counter(r.detail for r in results)

    console = Console()
    table = Table(title="Domain Check Results", show_header=True, header_style="bold magenta", box=box.SIMPLE)
    table.add_column("Domain", style="dim", width=40, overflow="fold")
    table.add_column("Status", justify="center")
    table.add_column("Detail", overflow="fold")
    table.add_column("Time", justify="right")

    for r in sorted(results, key=lambda x: x.domain):
        status = "[green]Online[/]" if r.ok else "[red]Offline[/]"
        ms = f"{r.elapsed_ms:.0f} ms" if r.elapsed_ms is not None else "-"
        table.add_row(r.domain, status, r.detail, ms)

    console.print(table)
    console.print(f"Total: {len(results)} | Responsive: [green]{len(up)}[/] | Unresponsive: [red]{len(down)}[/]")

    breakdown = Table(title="Result Breakdown", show_header=True, header_style="bold cyan", box=box.SIMPLE)
    breakdown.add_column("Reason / Detail", style="dim")
    breakdown.add_column("Count", justify="right")
    for reason, count in reasons.most_common():
        breakdown.add_row(reason, str(count))
    console.print(breakdown)

    try:
        with open(args.log_file, "w") as logf:
            logf.write("# Domain Check Log\n")
            logf.write(f"# Total: {len(results)}, Responsive: {len(up)}, Unresponsive: {len(down)}\n")
            logf.write("#------------------------------------\n")
            for r in sorted(results, key=lambda x: x.domain):
                symbol = "✔" if r.ok else "✖"
                ms = f" [{r.elapsed_ms:.0f}ms]" if r.elapsed_ms is not None else ""
                logf.write(f"{symbol} {r.domain} ({r.detail}){ms}\n")
        console.print(f"[dim]Detailed log written to {args.log_file}[/]")
    except IOError as e:
        console.print(f"[red]Error writing log file '{args.log_file}': {e}[/]")


if __name__ == "__main__":
    main()
