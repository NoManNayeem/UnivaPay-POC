# univapay_client.py
import os
import json
import time
import uuid
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

# -------------------------
# Env
# -------------------------
load_dotenv()

UNIVAPAY_BASE_URL = os.getenv("UNIVAPAY_BASE_URL", "https://api.univapay.com").rstrip("/")
UNIVAPAY_APP_TOKEN = os.getenv("UNIVAPAY_APP_TOKEN", "")   # public JWT (app token)
UNIVAPAY_APP_SECRET = os.getenv("UNIVAPAY_APP_SECRET", "") # secret string (pairs with token)
UNIVAPAY_STORE_ID = os.getenv("UNIVAPAY_STORE_ID", "").strip()  # optional, enables store-scoped GETs

DEFAULT_TIMEOUT = float(os.getenv("UNIVAPAY_HTTP_TIMEOUT", "15"))
DEFAULT_RETRIES = int(os.getenv("UNIVAPAY_HTTP_RETRIES", "2"))  # small safety net


# -------------------------
# Errors
# -------------------------
class UnivapayError(Exception):
    """Exception with HTTP status & parsed body attached."""

    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base} (status={self.status}, body={self.body})"


# -------------------------
# Helpers
# -------------------------
def _auth_header() -> Dict[str, str]:
    """
    Authorization: Bearer {secret}.{jwt}
    If secret omitted, fall back to just the token (some endpoints may fail).
    """
    if UNIVAPAY_APP_SECRET:
        return {"Authorization": f"Bearer {UNIVAPAY_APP_SECRET}.{UNIVAPAY_APP_TOKEN}"}
    return {"Authorization": f"Bearer {UNIVAPAY_APP_TOKEN}"}


def _make_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    base = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "POC-UnivaPay-Client/1.0 (+https://example.com)",
        **_auth_header(),
    }
    if extra:
        base.update({k: v for k, v in extra.items() if v is not None})
    return base


def _coerce_currency(cur: str) -> str:
    return (cur or "JPY").upper()


def _validate_amount(amount: Any) -> int:
    try:
        amt = int(amount)
        if amt <= 0:
            raise ValueError
        return amt
    except Exception:
        raise UnivapayError("amount must be a positive integer (in minor units, e.g., JPY)")  # noqa: B904


# -------------------------
# Client
# -------------------------
class UnivapayClient:
    """
    Thin REST wrapper for UnivaPay server-to-server calls.
    Most front-end sensitive steps (card entry, tokenization) should be done
    via the UnivaPay browser widget. Use the resulting transaction_token_id here.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES):
        self.base_url = (base_url or UNIVAPAY_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.retries = max(0, retries)

        if not UNIVAPAY_APP_TOKEN:
            raise RuntimeError("UNIVAPAY_APP_TOKEN is missing")
        if not UNIVAPAY_APP_SECRET:
            # Some endpoints (e.g., skip 3DS, certain admin ops) will require the secret.
            print("[UnivaPay] Warning: UNIVAPAY_APP_SECRET is empty; some endpoints may fail.")

        self._session = requests.Session()

    # ---- core request with lightweight retry ----
    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        extra_headers = headers or {}
        if idempotency_key:
            # Header name is commonly "Idempotency-Key" across APIs; supported by UnivaPay for safety.
            extra_headers["Idempotency-Key"] = idempotency_key

        hdrs = _make_headers(extra_headers)

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._session.request(
                    method=method.upper(),
                    url=url,
                    headers=hdrs,
                    json=json_body if json_body is not None else None,
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                if attempt <= self.retries:
                    time.sleep(0.4 * attempt)
                    continue
                raise UnivapayError(f"Network error calling {url}: {e}")

            # Success
            if 200 <= resp.status_code < 300:
                if resp.content and resp.headers.get("Content-Type", "").startswith("application/json"):
                    return resp.json()
                return None

            # Retry on 429/5xx
            if resp.status_code in (429, 500, 502, 503, 504) and attempt <= self.retries:
                # Respect Retry-After if present
                delay = 0.5 * attempt
                try:
                    ra = resp.headers.get("Retry-After")
                    if ra:
                        delay = max(delay, float(ra))
                except Exception:
                    pass
                time.sleep(delay)
                continue

            # Error: parse body if possible
            try:
                body = resp.json()
            except Exception:
                body = resp.text

            raise UnivapayError(f"UnivaPay API error {resp.status_code} for {path}", status=resp.status_code, body=body)

    # -------------------------
    # Charges (one-time)
    # -------------------------
    def create_charge(
        self,
        *,
        transaction_token_id: str,
        amount: int,
        currency: str = "JPY",
        capture: Optional[bool] = True,
        capture_at: Optional[str] = None,  # ISO-8601 datetime for delayed capture
        metadata: Optional[Dict[str, Any]] = None,
        three_ds_mode: Optional[str] = None,  # 'normal' | 'require' | 'force' | 'skip'
        redirect_endpoint: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """
        Create a one-time charge from a front-end transaction token.
        Docs: Charges Create

        - transaction_token_id: the short-lived token from the widget
        - amount: integer (minor units, e.g., JPY)
        - currency: 'JPY' by default
        - capture: True for immediate capture, False for authorize-only
        - capture_at: schedule ISO-8601 when to auto-capture (if capture=False)
        - metadata: arbitrary JSON
        - three_ds_mode: 'normal' | 'require' | 'force' | 'skip' (requires appropriate privileges)
        - redirect_endpoint: where UnivaPay should redirect the customer after 3DS
        - idempotency_key: optional string you provide to de-duplicate requests
        """
        amt = _validate_amount(amount)
        cur = _coerce_currency(currency)

        body: Dict[str, Any] = {
            "transaction_token_id": transaction_token_id,
            "amount": amt,
            "currency": cur,
        }
        if capture is not None:
            body["capture"] = bool(capture)
        if capture_at:
            body["capture_at"] = capture_at
        if metadata:
            body["metadata"] = metadata
        if redirect_endpoint:
            # Per docs, UnivaPay supports a redirect object.
            body["redirect"] = {"endpoint": redirect_endpoint}
        if three_ds_mode:
            # Follow doc field for three_ds mode on charge creation
            body["three_ds"] = {"mode": three_ds_mode}

        return self._request("POST", "/charges", json_body=body, idempotency_key=idempotency_key)

    def get_charge(self, charge_id: str) -> Any:
        """Retrieve a charge by ID (prefers store-scoped path when storeId present)."""
        if UNIVAPAY_STORE_ID:
            return self._request("GET", f"/stores/{UNIVAPAY_STORE_ID}/charges/{charge_id}")
        return self._request("GET", f"/charges/{charge_id}")

    def capture_charge(self, charge_id: str, *, amount: Optional[int] = None, idempotency_key: Optional[str] = None) -> Any:
        """
        Capture a previously authorized charge.
        If 'amount' provided, must be <= authorized amount.
        """
        body = {}
        if amount is not None:
            body["amount"] = _validate_amount(amount)
        return self._request("POST", f"/charges/{charge_id}/capture", json_body=body or None, idempotency_key=idempotency_key)

    def cancel_charge(self, charge_id: str, *, reason: Optional[str] = None, idempotency_key: Optional[str] = None) -> Any:
        """Cancel (void) an authorized charge (or refund rules depending on status)."""
        body = {"reason": reason} if reason else None
        return self._request("POST", f"/charges/{charge_id}/cancel", json_body=body, idempotency_key=idempotency_key)

    # -------------------------
    # Subscriptions (recurring)
    # -------------------------
    def create_subscription(
        self,
        *,
        transaction_token_id: str,
        amount: int,
        currency: str = "JPY",
        period: Optional[str] = "monthly",  # 'monthly', 'semiannually', etc.
        cyclical_period: Optional[str] = None,  # ISO-8601 duration alternative, e.g., 'P2M'
        start_on: Optional[str] = None,  # YYYY-MM-DD
        zone_id: str = "Asia/Tokyo",
        metadata: Optional[Dict[str, Any]] = None,
        three_ds_mode: Optional[str] = None,  # 'normal' | 'require' | 'force' | 'skip'
        redirect_endpoint: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """
        Create a subscription (recurring billing).
        Docs: Subscriptions Create

        Either 'period' or 'cyclical_period' must be provided.
        """
        amt = _validate_amount(amount)
        cur = _coerce_currency(currency)

        if not period and not cyclical_period:
            raise UnivapayError("Either 'period' or 'cyclical_period' must be specified for subscription.")

        body: Dict[str, Any] = {
            "transaction_token_id": transaction_token_id,
            "amount": amt,
            "currency": cur,
            "schedule_settings": {"zone_id": zone_id},
        }
        if period:
            body["period"] = period
        if cyclical_period:
            body["cyclical_period"] = cyclical_period
        if start_on:
            body["schedule_settings"]["start_on"] = start_on
        if metadata:
            body["metadata"] = metadata
        if redirect_endpoint:
            body["redirect"] = {"endpoint": redirect_endpoint}
        if three_ds_mode:
            body["three_ds"] = {"mode": three_ds_mode}

        return self._request("POST", "/subscriptions", json_body=body, idempotency_key=idempotency_key)

    def get_subscription(self, subscription_id: str) -> Any:
        """Retrieve a subscription by ID (prefers store-scoped path when storeId present)."""
        if UNIVAPAY_STORE_ID:
            return self._request("GET", f"/stores/{UNIVAPAY_STORE_ID}/subscriptions/{subscription_id}")
        return self._request("GET", f"/subscriptions/{subscription_id}")

    def cancel_subscription(self, subscription_id: str, *, termination_mode: Optional[str] = None) -> Any:
        """
        Cancel (permanently stop) a subscription.
        Optionally specify termination_mode: 'immediate' | 'on_next_payment'
        """
        body = {}
        if termination_mode:
            body["schedule_settings"] = {"termination_mode": termination_mode}
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", json_body=body or None)

    # -------------------------
    # Utility
    # -------------------------
    @staticmethod
    def new_idempotency_key() -> str:
        """Create a new idempotency key for safe retries."""
        return str(uuid.uuid4())
