import os
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
import jwt

# UnivaPay client wrapper
from univapay_client import UnivapayClient, UnivapayError

# -------------------------
# Env & App Initialization
# -------------------------
load_dotenv()

PORT = int(os.getenv("PORT", "5000"))
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///poc.db")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
WEBHOOK_AUTH = os.getenv("UNIVAPAY_WEBHOOK_AUTH", "").strip()  # shared secret to validate webhooks

# Polling (fallback to webhooks)
ENABLE_POLL_FALLBACK = os.getenv("UNIVAPAY_POLL_ENABLE", "true").lower() in ("1", "true", "yes")
POLL_AFTER_SECONDS = int(os.getenv("UNIVAPAY_POLL_AFTER_SECONDS", "30"))
POLL_RETRY_AFTER_SECONDS = int(os.getenv("UNIVAPAY_POLL_RETRY_SECONDS", "60"))

def now_utc():
    return datetime.now(timezone.utc)

def utc_iso(dt: datetime) -> str:
    # Return ISO8601 with 'Z'
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"

def _coerce_token_id(val) -> str:
    """Accept a string or a dict like {'id': '...'} and return a trimmed string id."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        cand = val.get("id") or val.get("token_id") or val.get("univapayTokenId")
        if isinstance(cand, str):
            return cand.strip()
        return (str(cand) if cand is not None else "").strip()
    # last resort: stringify
    return str(val).strip()


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

CORS(app, resources={
    r"/api/*": {
        "origins": ALLOWED_ORIGINS or "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": False,
    }
})

db = SQLAlchemy(app)

# Try init UnivaPay client (ok if keys missing; we simply show a warning)
try:
    univapay = UnivapayClient()
    print("[UnivaPay] Client initialized")
except Exception as e:
    univapay = None
    print(f"[UnivaPay] Init warning: {e}")

# -------------
# DB Models
# -------------
class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(64), nullable=False)         # e.g., "Nayeem"
    kind = db.Column(db.String(32), nullable=False)         # "product" | "subscription"
    item_name = db.Column(db.String(255), nullable=True)    # product purchases
    amount_jpy = db.Column(db.Integer, nullable=False)      # integer yen
    plan = db.Column(db.String(32), nullable=True)          # "monthly" | "6months"
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user,
            "kind": self.kind,
            "item_name": self.item_name,
            "amount_jpy": self.amount_jpy,
            "plan": self.plan,
            "created_at": utc_iso(self.created_at),
        }

class ProviderPayment(db.Model):
    __tablename__ = "provider_payments"
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(32), nullable=False, default="univapay")
    payment_id = db.Column(db.Integer, nullable=False)  # logical FK to payments.id
    provider_charge_id = db.Column(db.String(64), nullable=True)
    provider_subscription_id = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), nullable=True)    # e.g., pending/successful/failed/current/...
    currency = db.Column(db.String(8), nullable=True, default="JPY")
    raw_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class WebhookEvent(db.Model):
    __tablename__ = "webhook_events"
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(32), nullable=False, default="univapay")
    event_type = db.Column(db.String(64), nullable=True)    # e.g., CHARGE_FINISHED, SUBSCRIPTION_PAYMENT
    payload = db.Column(db.Text, nullable=False)            # raw JSON body
    headers = db.Column(db.Text, nullable=True)             # captured subset of headers
    received_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# -------------
# Auth Helpers
# -------------
def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "iat": now_utc(),
        "exp": now_utc() + timedelta(hours=12),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth.split(" ", 1)[1].strip()
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.user = data["sub"]
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except Exception:
            return jsonify({"error": "Invalid token"}), 401
        return fn(*args, **kwargs)
    return wrapper

# ----------------
# Health Endpoints
# ----------------
@app.get("/healthz")
def healthz():
    return jsonify({
        "ok": True,
        "env": {
            "PORT": PORT,
            "DB": DATABASE_URL.split(":///")[-1],
        }
    })

@app.get("/db/health")
def db_health():
    insp = inspect(db.engine)
    tables = insp.get_table_names()
    cols = {}
    for t in ("payments", "provider_payments", "webhook_events"):
        if t in tables:
            cols[t] = [c["name"] for c in insp.get_columns(t)]
    count = db.session.query(Payment).count() if "payments" in tables else None
    return jsonify({"ok": True, "tables": tables, "columns": cols, "payments_count": count})

# ----------------
# Auth Endpoints
# ----------------
@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if username == "Nayeem" and password == "password":
        token = create_token(username)
        return jsonify({"token": token, "user": {"username": username}})
    return jsonify({"error": "Invalid credentials"}), 401

@app.get("/api/me")
@auth_required
def me():
    return jsonify({"user": {"username": request.user}})

# --------------------------------
# Local (POC) Payments (unchanged)
# --------------------------------
@app.post("/api/purchase")
@auth_required
def purchase():
    data = request.get_json(silent=True) or {}
    item_name = (data.get("item_name") or "").strip()
    amount = data.get("amount")

    if not item_name:
        return jsonify({"error": "Item name is required"}), 400
    try:
        amount = int(amount)
        assert amount > 0
    except Exception:
        return jsonify({"error": "Amount must be a positive integer (JPY)"}), 400

    row = Payment(user=request.user, kind="product", item_name=item_name, amount_jpy=amount, plan=None)
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "payment": row.to_dict()}), 201

@app.post("/api/subscribe")
@auth_required
def subscribe():
    data = request.get_json(silent=True) or {}
    plan = (data.get("plan") or "").strip().lower()

    PRICES = {"monthly": 10000, "6months": 58000}
    if plan not in PRICES:
        return jsonify({"error": "Invalid plan. Use 'monthly' or '6months'."}), 400

    row = Payment(user=request.user, kind="subscription", item_jpy=None, item_name=None, amount_jpy=PRICES[plan], plan=plan)
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "payment": row.to_dict()}), 201

@app.get("/api/payments")
@auth_required
def list_payments():
    # 1. Load all local payments for this user
    payments = Payment.query.filter_by(user=request.user).order_by(Payment.created_at.desc()).all()

    # 2. Build response including provider data (if exists)
    result = []
    for p in payments:
        provider = ProviderPayment.query.filter_by(payment_id=p.id, provider="univapay").first()
        result.append({
            **p.to_dict(),
            "provider": {
                "id": provider.id if provider else None,
                "provider": provider.provider if provider else None,
                "charge_id": provider.provider_charge_id if provider else None,
                "subscription_id": provider.provider_subscription_id if provider else None,
                "status": provider.status if provider else None,
                "currency": provider.currency if provider else None,
                "created_at": provider.created_at.isoformat() + "Z" if provider and provider.created_at else None,
                "updated_at": provider.updated_at.isoformat() + "Z" if provider and provider.updated_at else None,
            } if provider else None
        })

    return jsonify({"payments": result})

# ------------------------------------
# Internal: polling fallback utilities
# ------------------------------------
def _poll_provider_status_later(kind: str, provider_row_id: int, delay_s: int, retry=False):
    """
    Schedule a one-off background poll to refresh provider status.
    kind: 'charge' | 'subscription'
    provider_row_id: ProviderPayment.id
    delay_s: seconds to wait
    retry: whether this is the second attempt
    """
    if not ENABLE_POLL_FALLBACK or univapay is None:
        return

    def _task():
        with app.app_context():
            prov = ProviderPayment.query.get(provider_row_id)
            if not prov:
                return
            try:
                if kind == "charge" and prov.provider_charge_id:
                    data = univapay.get_charge(prov.provider_charge_id)
                elif kind == "subscription" and prov.provider_subscription_id:
                    data = univapay.get_subscription(prov.provider_subscription_id)
                else:
                    return

                status = (data or {}).get("status")
                prov.status = status or prov.status
                prov.updated_at = datetime.utcnow()
                prov.raw_json = json.dumps(data or {}, ensure_ascii=False)
                db.session.add(prov)
                db.session.commit()

                # Optional: second attempt if still "pending/awaiting" for charges
                if not retry and kind == "charge" and (status in ("pending", "awaiting") or not status):
                    _poll_provider_status_later(kind, provider_row_id, POLL_RETRY_AFTER_SECONDS, retry=True)

            except Exception as e:
                db.session.rollback()
                print(f"[Poller] Error polling {kind} provider_id={provider_row_id}: {e}")

    threading.Timer(delay_s, _task).start()

# ------------------------------------
# UnivaPay: Checkout (server-to-server)
# ------------------------------------
@app.post("/api/checkout/charge")
@auth_required
def univapay_checkout_charge():
    if univapay is None:
        return jsonify({"error": "UnivaPay client not initialized (check env vars)."}), 500

    data = request.get_json(silent=True) or {}
    token_id = _coerce_token_id(data.get("transaction_token_id"))
    item_name = (data.get("item_name") or "")
    item_name = item_name.strip() if isinstance(item_name, str) else str(item_name).strip()
    redirect_endpoint = (data.get("redirect_endpoint") or "").strip() or None
    three_ds_mode = (data.get("three_ds_mode") or "").strip() or None
    amount = data.get("amount")

    if not token_id:
        return jsonify({"error": "transaction_token_id is required"}), 400
    if not item_name:
        return jsonify({"error": "item_name is required"}), 400
    try:
        amount = int(amount)
        assert amount > 0
    except Exception:
        return jsonify({"error": "amount must be a positive integer (JPY)"}), 400

    try:
        idem_key = UnivapayClient.new_idempotency_key()
        resp = univapay.create_charge(
            transaction_token_id=token_id,
            amount=amount,
            currency="JPY",
            capture=True,
            metadata={"user": request.user, "item_name": item_name},
            three_ds_mode=three_ds_mode,
            redirect_endpoint=redirect_endpoint,
            idempotency_key=idem_key,
        )

        # 2) Create local payment row
        pay = Payment(user=request.user, kind="product", item_name=item_name, amount_jpy=amount, plan=None)
        db.session.add(pay)
        db.session.flush()  # obtain pay.id

        # 3) Record provider mapping
        prov = ProviderPayment(
            provider="univapay",
            payment_id=pay.id,
            provider_charge_id=(resp.get("id") if isinstance(resp, dict) else None),
            provider_subscription_id=None,
            status=(resp.get("status") if isinstance(resp, dict) else None),
            currency=(resp.get("charged_currency") or "JPY") if isinstance(resp, dict) else "JPY",
            raw_json=json.dumps(resp, ensure_ascii=False),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(prov)
        db.session.commit()

        # 4) Schedule a one-off poll as fallback to webhook
        if ENABLE_POLL_FALLBACK and prov.provider_charge_id:
            _poll_provider_status_later("charge", prov.id, POLL_AFTER_SECONDS)

        return jsonify({
            "ok": True,
            "payment": pay.to_dict(),
            "provider": {
                "id": prov.id,
                "provider": prov.provider,
                "charge_id": prov.provider_charge_id,
                "status": prov.status,
            },
            "univapay": {
                "charge_id": resp.get("id") if isinstance(resp, dict) else None,
                "status": resp.get("status") if isinstance(resp, dict) else None,
                "mode": resp.get("mode") if isinstance(resp, dict) else None,
                # UnivaPay can return redirect/three_ds info (for 3DS flows)
                "redirect": (resp.get("redirect") or resp.get("three_ds") or {}) if isinstance(resp, dict) else {},
            }
        }), 201
    except UnivapayError as e:
        return jsonify({"error": "UnivaPay charge failed", "detail": e.body, "status": e.status}), 400
    except Exception as e:
        return jsonify({"error": "Unexpected error creating charge", "detail": str(e)}), 500

@app.post("/api/checkout/subscription")
@auth_required
def univapay_checkout_subscription():
    if univapay is None:
        return jsonify({"error": "UnivaPay client not initialized (check env vars)."}), 500

    data = request.get_json(silent=True) or {}
    token_id = _coerce_token_id(data.get("transaction_token_id"))
    plan = (data.get("plan") or "").strip().lower()
    redirect_endpoint = (data.get("redirect_endpoint") or "").strip() or None
    three_ds_mode = (data.get("three_ds_mode") or "").strip() or None

    PRICES = {"monthly": 10000, "6months": 58000}
    PERIODS = {"monthly": "monthly", "6months": "semiannually"}

    if not token_id:
        return jsonify({"error": "transaction_token_id is required"}), 400
    if plan not in PRICES:
        return jsonify({"error": "Invalid plan. Use 'monthly' or '6months'."}), 400

    amount = PRICES[plan]
    period = PERIODS[plan]

    try:
        idem_key = UnivapayClient.new_idempotency_key()
        resp = univapay.create_subscription(
            transaction_token_id=token_id,
            amount=amount,
            currency="JPY",
            period=period,
            metadata={"user": request.user, "plan": plan},
            three_ds_mode=three_ds_mode,
            redirect_endpoint=redirect_endpoint,
            idempotency_key=idem_key,
        )

        # 2) Create local payment row
        pay = Payment(user=request.user, kind="subscription", item_name=None, amount_jpy=amount, plan=plan)
        db.session.add(pay)
        db.session.flush()

        # 3) Record provider mapping
        prov = ProviderPayment(
            provider="univapay",
            payment_id=pay.id,
            provider_charge_id=None,
            provider_subscription_id=(resp.get("id") if isinstance(resp, dict) else None),
            status=(resp.get("status") if isinstance(resp, dict) else None),
            currency=(resp.get("currency") or "JPY") if isinstance(resp, dict) else "JPY",
            raw_json=json.dumps(resp, ensure_ascii=False),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(prov)
        db.session.commit()

        # 4) Schedule a one-off poll as fallback to webhook
        if ENABLE_POLL_FALLBACK and prov.provider_subscription_id:
            _poll_provider_status_later("subscription", prov.id, POLL_AFTER_SECONDS)

        return jsonify({
            "ok": True,
            "payment": pay.to_dict(),
            "provider": {
                "id": prov.id,
                "provider": prov.provider,
                "subscription_id": prov.provider_subscription_id,
                "status": prov.status,
            },
            "univapay": {
                "subscription_id": resp.get("id") if isinstance(resp, dict) else None,
                "status": resp.get("status") if isinstance(resp, dict) else None,
                "mode": resp.get("mode") if isinstance(resp, dict) else None,
                "next_payment": resp.get("next_payment") if isinstance(resp, dict) else None,
            }
        }), 201
    except UnivapayError as e:
        return jsonify({"error": "UnivaPay subscription failed", "detail": e.body, "status": e.status}), 400
    except Exception as e:
        return jsonify({"error": "Unexpected error creating subscription", "detail": str(e)}), 500

# ------------------------
# Webhook: receive & apply
# ------------------------
@app.post("/api/univapay/webhook")
def univapay_webhook():
    # 1) Verify a simple shared secret in Authorization header
    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {WEBHOOK_AUTH}" if WEBHOOK_AUTH else None
    if not expected or auth != expected:
        # Do not leak details; respond 401 for missing/invalid webhook auth
        return jsonify({"error": "Unauthorized webhook"}), 401

    # 2) Parse body
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Invalid JSON"}), 400

    # Capture basic event fields
    event_type = payload.get("event") or payload.get("type") or payload.get("status")
    headers_subset = {
        "content-type": request.headers.get("Content-Type"),
        "authorization": request.headers.get("Authorization"),
        "user-agent": request.headers.get("User-Agent"),
        "x-forwarded-for": request.headers.get("X-Forwarded-For"),
    }

    # 3) Store the raw webhook (for audit/debug)
    evt = WebhookEvent(
        provider="univapay",
        event_type=str(event_type) if event_type else None,
        payload=json.dumps(payload, ensure_ascii=False),
        headers=json.dumps(headers_subset, ensure_ascii=False),
    )
    db.session.add(evt)

    # 4) Attempt to update ProviderPayment status
    #    We defensively extract IDs from several possible shapes.
    obj = payload.get("object")
    data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else {}

    charge_id = None
    subscription_id = None

    if obj in ("charge", "charges"):
        charge_id = payload.get("id") or data_obj.get("id")
    elif obj in ("subscription", "subscriptions"):
        subscription_id = payload.get("id") or data_obj.get("id")
    else:
        # Try nested shapes
        charge_id = (payload.get("charge", {}) or {}).get("id") or data_obj.get("charge_id")
        subscription_id = (payload.get("subscription", {}) or {}).get("id") or data_obj.get("subscription_id")

    new_status = payload.get("status") or data_obj.get("status")

    try:
        updated = False
        now = datetime.utcnow()

        if charge_id:
            prov = ProviderPayment.query.filter_by(provider="univapay", provider_charge_id=str(charge_id)).first()
            if prov:
                if new_status:
                    prov.status = str(new_status)
                prov.updated_at = now
                db.session.add(prov)
                updated = True

        if subscription_id and not updated:
            prov = ProviderPayment.query.filter_by(provider="univapay", provider_subscription_id=str(subscription_id)).first()
            if prov:
                if new_status:
                    prov.status = str(new_status)
                prov.updated_at = now
                db.session.add(prov)
                updated = True

        db.session.commit()
    except Exception:
        # Don't block webhook ack on DB update errors
        db.session.rollback()

    # 5) Respond quickly
    return jsonify({"ok": True})

# -----------
# Entrypoint
# -----------
if __name__ == "__main__":
    app.run(debug=True, port=PORT)
