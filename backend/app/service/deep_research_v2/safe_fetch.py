"""Bounded public HTTP fetch for research sources; never follow private addresses."""
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

import urllib3


MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
FETCH_SECONDS = 10


def public_target(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP(S) sources are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Source credentials are not allowed")
    host = parsed.hostname.encode("idna").decode("ascii")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("Only standard web ports are allowed")
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips:
        raise ValueError("Source DNS returned no address")
    for value in ips:
        address = ipaddress.ip_address(value)
        if not address.is_global or address.is_multicast:
            raise ValueError("Private or non-public source address is blocked")
        if address.version == 6 and address.ipv4_mapped and not address.ipv4_mapped.is_global:
            raise ValueError("Mapped private source address is blocked")
    return parsed, host, port, ips[0]


def fetch_public_text(url):
    """Pin the validated IP for each hop (including TLS SNI), bound time and bytes.

    No environment proxies/cookies, no redirects handled by the HTTP library,
    and no second DNS resolution between validation and connection.
    """
    deadline = time.monotonic() + FETCH_SECONDS
    for hop in range(MAX_REDIRECTS + 1):
        parsed, host, port, address = public_target(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Source fetch time budget exceeded")
        timeout = urllib3.Timeout(connect=min(3, remaining), read=min(4, remaining), total=remaining)
        if parsed.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(address, port=port, assert_hostname=host,
                                              server_hostname=host, cert_reqs="CERT_REQUIRED")
        else:
            pool = urllib3.HTTPConnectionPool(address, port=port)
        response = None
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            host_header = f"[{host}]" if ":" in host else host
            if port != (443 if parsed.scheme == "https" else 80):
                host_header += f":{port}"
            response = pool.request("GET", path, headers={"Host": host_header,
                                    "User-Agent": "YAYI-Research/1.0", "Accept": "text/html,text/plain"},
                                    redirect=False, retries=False, preload_content=False, timeout=timeout)
            if response.status in {301, 302, 303, 307, 308}:
                if hop == MAX_REDIRECTS or not response.headers.get("Location"):
                    raise ValueError("Source redirect limit exceeded")
                url = urljoin(url, response.headers["Location"])
                continue
            if response.status != 200:
                raise ValueError(f"Source returned HTTP {response.status}")
            content_type = response.headers.get("Content-Type", "").lower()
            if not any(kind in content_type for kind in ("text/html", "text/plain", "application/xhtml+xml")):
                raise ValueError("Source is not an HTML/text document")
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                raise ValueError("Source response exceeds byte budget")
            chunks, size = [], 0
            for chunk in response.stream(65536, decode_content=True):
                size += len(chunk)
                if size > MAX_BYTES or time.monotonic() > deadline:
                    raise ValueError("Source response exceeds time/byte budget")
                chunks.append(chunk)
            encoding = "utf-8"
            if "charset=" in content_type:
                encoding = content_type.split("charset=", 1)[1].split(";", 1)[0].strip(' "\'')
            try:
                return b"".join(chunks).decode(encoding, errors="replace"), url
            except LookupError:
                return b"".join(chunks).decode("utf-8", errors="replace"), url
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise ValueError("Source redirect limit exceeded")
