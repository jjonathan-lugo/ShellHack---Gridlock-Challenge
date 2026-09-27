"""Tiny HTTPS helper shared by the weather fetcher and the geocoder.

Why it exists: Python installed from python.org on macOS ships without root
certificates until you run "Install Certificates.command", so every HTTPS call
fails with CERTIFICATE_VERIFY_FAILED. If the `certifi` bundle is installed
(it usually is — requests/httpx/huggingface_hub depend on it) we use it, which
makes that problem disappear; otherwise we fall back to the system store and
explain the one-line fix when verification fails.
"""

from __future__ import annotations

import json
import ssl
import urllib.request

USER_AGENT = "gridlock-shellhacks/1.0 (utility coordination hackathon project)"

CERT_HELP = (
    "HTTPS certificate check failed. On macOS with Python from python.org, run once:\n"
    '    open "/Applications/Python 3.X/Install Certificates.command"   (use your version, e.g. 3.14)\n'
    "or: pip3 install certifi — then try again."
)


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_CTX = ssl_context()


def is_cert_error(err: BaseException) -> bool:
    text = f"{err} {getattr(err, 'reason', '')}"
    return "CERTIFICATE_VERIFY_FAILED" in text or isinstance(getattr(err, "reason", None), ssl.SSLCertVerificationError)


def get_json(url: str, data: bytes | None = None, timeout: float = 60):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
        return json.load(resp)
