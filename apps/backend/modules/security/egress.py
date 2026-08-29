"""
modules/security/egress.py — Safe Egress HTTP Client with SSRF and DNS Rebinding Defense.
"""
import ipaddress
import logging
import socket
from urllib.parse import urlparse
from typing import Optional, Dict, Any

import aiohttp

logger = logging.getLogger("JARVIS.Security.Egress")

# Private and cloud metadata IP networks to block
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),       # Link-local & Cloud Metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),          # Multicast
    ipaddress.ip_network("240.0.0.0/4"),          # Reserved
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::1/128"),              # IPv6 loopback
    ipaddress.ip_network("::/128"),               # IPv6 unspecified
    ipaddress.ip_network("::ffff:0:0/96"),        # IPv4-mapped IPv6
    ipaddress.ip_network("fc00::/7"),             # IPv6 Unique Local Address
    ipaddress.ip_network("fe80::/10"),            # IPv6 link-local
    ipaddress.ip_network("ff00::/8"),             # IPv6 multicast
]

MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5 MB
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 15.0
DEFAULT_TOTAL_TIMEOUT = 20.0


class SSRFValidationError(ValueError):
    """Raised when an outbound URL target violates SSRF policy."""
    pass


class SafeEgressClient:
    """
    Centralized HTTP client enforcing outbound network security:
      1. Scheme allowlist (http, https).
      2. DNS resolution and IP address blocklist (blocking private/loopback/metadata).
      3. Connect/read/total timeouts.
      4. Maximum response size limits to prevent memory exhaustion.
    """

    ALLOWED_SCHEMES = {"http", "https"}

    @classmethod
    def validate_url(cls, url: str) -> str:
        """
        Validate URL scheme and resolve DNS to ensure target does not point to private/loopback IPs.
        Raises SSRFValidationError on violation.
        """
        if not url or not isinstance(url, str):
            raise SSRFValidationError("Missing or invalid URL parameter.")

        parsed = urlparse(url.strip())
        if not parsed.scheme or parsed.scheme.lower() not in cls.ALLOWED_SCHEMES:
            raise SSRFValidationError(f"URL scheme '{parsed.scheme}' is not permitted. Only HTTP/HTTPS are allowed.")

        hostname = parsed.hostname
        if not hostname:
            raise SSRFValidationError(f"Invalid URL '{url}': hostname is missing.")

        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)

        # Resolve hostname to all associated IP addresses
        try:
            addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise SSRFValidationError(f"DNS resolution failed for hostname '{hostname}': {e}")

        if not addr_info:
            raise SSRFValidationError(f"No IP addresses resolved for hostname '{hostname}'.")

        for entry in addr_info:
            sockaddr = entry[4]
            raw_ip = sockaddr[0]
            try:
                ip = ipaddress.ip_address(raw_ip)
            except ValueError:
                raise SSRFValidationError(f"Invalid IP address format '{raw_ip}' resolved for '{hostname}'.")

            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                raise SSRFValidationError(
                    f"SSRF violation: Hostname '{hostname}' resolved to blocked/private IP '{ip}'."
                )

            for blocked_net in BLOCKED_NETWORKS:
                if ip in blocked_net:
                    raise SSRFValidationError(
                        f"SSRF violation: Target IP '{ip}' falls within restricted network '{blocked_net}'."
                    )

        return url.strip()

    @classmethod
    async def request(
        cls,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        max_bytes: int = MAX_RESPONSE_SIZE,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    ) -> Dict[str, Any]:
        """
        Execute an outbound HTTP request safely with pre-flight SSRF validation,
        timeouts, and response truncation.
        """
        validated_url = cls.validate_url(url)
        timeout = aiohttp.ClientTimeout(
            total=total_timeout,
            connect=connect_timeout,
            sock_read=read_timeout
        )

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method=method.upper(),
                url=validated_url,
                headers=headers,
                json=json,
                data=data,
                params=params,
                allow_redirects=False  # Block automated redirection to prevent DNS rebinding / redirect SSRF
            ) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise SSRFValidationError(
                        f"Response Content-Length ({content_length} bytes) exceeds maximum allowable limit of {max_bytes} bytes."
                    )

                body_bytes = await response.content.read(max_bytes + 1)
                truncated = False
                if len(body_bytes) > max_bytes:
                    body_bytes = body_bytes[:max_bytes]
                    truncated = True

                text = body_bytes.decode("utf-8", errors="replace")

                logger.info(f"SafeEgress: {method.upper()} {validated_url} -> Status {response.status}")
                return {
                    "status": response.status,
                    "headers": dict(response.headers),
                    "text": text,
                    "truncated": truncated,
                    "url": str(response.url)
                }
