import uuid
import requests
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

UNIVAPAY_APP_TOKEN = os.getenv('UNIVAPAY_APP_TOKEN', '')
UNIVAPAY_APP_SECRET = os.getenv('UNIVAPAY_APP_SECRET', '')
UNIVAPAY_WEBHOOK_AUTH = os.getenv('UNIVAPAY_WEBHOOK_AUTH', '')
UNIVAPAY_STORE_ID = os.getenv('UNIVAPAY_STORE_ID', '')
UNIVAPAY_BASE_URL = os.getenv('UNIVAPAY_BASE_URL', 'https://api.univapay.com')


class UnivapayError(Exception):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__(f"Univapay API error: {status} - {body}")


class UnivapayClient:
    def __init__(self):
        self.base_url = UNIVAPAY_BASE_URL
        self.secret_key = UNIVAPAY_APP_SECRET
        self.jwt_token = UNIVAPAY_APP_TOKEN
        self.store_id = UNIVAPAY_STORE_ID

        if not all([self.secret_key, self.jwt_token, self.store_id]):
            raise ValueError("Univapay credentials not configured properly")

        self.auth_header = f"Bearer {self.secret_key}.{self.jwt_token}"
        self.headers = {
            'Authorization': self.auth_header,
            'Content-Type': 'application/json',
        }

    @staticmethod
    def new_idempotency_key():
        return str(uuid.uuid4())

    def _request(self, method, endpoint, data=None, idempotency_key=None):
        url = f"{self.base_url}{endpoint}"
        headers = self.headers.copy()

        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key

        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=data)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, json=data)
            elif method.upper() == 'PUT':
                response = requests.put(url, headers=headers, json=data)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code >= 400:
                raise UnivapayError(response.status_code, response.text)

            return response.json()
        except requests.exceptions.RequestException as e:
            raise UnivapayError(500, str(e))

    def create_charge(self, transaction_token_id, amount, currency, metadata=None, only_direct_currency=False,
                      capture_at=None, descriptor=None, descriptor_phone_number=None,
                      redirect_endpoint=None, three_ds_mode='normal', idempotency_key=None, capture=True):
        endpoint = "/charges"
        data = {
            "transaction_token_id": transaction_token_id,
            "amount": amount,
            "currency": currency,
        }

        if metadata:
            data["metadata"] = metadata

        if only_direct_currency:
            data["only_direct_currency"] = only_direct_currency

        if capture_at:
            data["capture_at"] = capture_at

        if descriptor:
            data["descriptor"] = descriptor

        if descriptor_phone_number:
            data["descriptor_phone_number"] = descriptor_phone_number

        if redirect_endpoint:
            data["redirect"] = {"endpoint": redirect_endpoint}

        if three_ds_mode:
            data["three_ds"] = {"mode": three_ds_mode}

        if not capture:
            data["capture"] = capture

        return self._request('POST', endpoint, data, idempotency_key)

    def get_charge(self, charge_id):
        endpoint = f"/stores/{self.store_id}/charges/{charge_id}"
        return self._request('GET', endpoint)

    def create_subscription(self, transaction_token_id, amount, currency, period,
                            metadata=None, only_direct_currency=False, initial_amount=None,
                            schedule_settings=None, first_charge_capture_after=None,
                            first_charge_authorization_only=False, redirect_endpoint=None,
                            three_ds_mode='normal', idempotency_key=None):
        endpoint = "/subscriptions"
        data = {
            "transaction_token_id": transaction_token_id,
            "amount": amount,
            "currency": currency,
            "period": period,
        }

        if metadata:
            data["metadata"] = metadata

        if only_direct_currency:
            data["only_direct_currency"] = only_direct_currency

        if initial_amount:
            data["initial_amount"] = initial_amount

        if schedule_settings:
            data["schedule_settings"] = schedule_settings

        if first_charge_capture_after:
            data["first_charge_capture_after"] = first_charge_capture_after

        if first_charge_authorization_only:
            data["first_charge_authorization_only"] = first_charge_authorization_only

        if redirect_endpoint:
            data["redirect"] = {"endpoint": redirect_endpoint}

        if three_ds_mode:
            data["three_ds"] = {"mode": three_ds_mode}

        return self._request('POST', endpoint, data, idempotency_key)

    def get_subscription(self, subscription_id):
        endpoint = f"/stores/{self.store_id}/subscriptions/{subscription_id}"
        return self._request('GET', endpoint)

    def cancel_subscription(self, subscription_id, termination_mode='immediate', reason=None):
        endpoint = f"/stores/{self.store_id}/subscriptions/{subscription_id}/cancel"
        data = {
            "termination_mode": termination_mode,
        }
        if reason:
            data["reason"] = reason
        return self._request('POST', endpoint, data)

    def refund_charge(self, charge_id, amount=None, reason=None, metadata=None, idempotency_key=None):
        endpoint = f"/stores/{self.store_id}/charges/{charge_id}/refunds"
        data = {}
        if amount:
            data["amount"] = amount
        if reason:
            data["reason"] = reason
        if metadata:
            data["metadata"] = metadata
        return self._request('POST', endpoint, data, idempotency_key)