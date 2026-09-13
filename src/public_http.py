"""Validate public PACE destinations before each request, including redirects."""
from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import requests


def validate_public_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        valid = (parts.scheme in {"http", "https"}
                 and parts.hostname in {"pace.ac.in", "www.pace.ac.in"}
                 and not parts.username and not parts.password
                 and parts.port in {None, 443 if parts.scheme == "https" else 80})
    except ValueError:
        valid = False
    if not valid:
        raise requests.exceptions.InvalidURL("Only public PACE HTTP(S) URLs on standard ports are allowed.")


def public_get(session: requests.Session, url: str, *, timeout: float,
               stream: bool = False, max_redirects: int = 3) -> requests.Response:
    for hop in range(max_redirects + 1):
        validate_public_url(url)
        response = session.get(url, timeout=timeout, stream=stream, allow_redirects=False)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response  # Caller owns and closes the final response.
        location = response.headers.get("Location")
        response.close()
        if not location or hop == max_redirects:
            raise requests.exceptions.TooManyRedirects("PACE redirect limit reached or destination missing.")
        destination = urljoin(url, location)
        if urlsplit(url).scheme == "https" and urlsplit(destination).scheme != "https":
            raise requests.exceptions.InvalidURL("Refusing an insecure PACE redirect.")
        url = destination
    raise requests.exceptions.TooManyRedirects("PACE redirect limit reached.")
