import os
import json
import threading
import time
import hmac
import hashlib
from datetime import datetime
from django.utils.timezone import now, make_aware
from django.utils import timezone

from rest_framework import status, viewsets, mixins
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication, TokenAuthentication

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import SubscriptionPlan, PaymentHistory, TransactionToken
from .serializers import (
    SubscriptionPlanSerializer,
    PurchaseSerializer, 
    SubscribeSerializer, 
    UnivapayChargeSerializer,
    UnivapaySubscriptionSerializer, 
    PaymentHistorySerializer,
    PaymentHistoryListSerializer,
    WebhookEventSerializer,
    WebhookChargeSerializer,
    WebhookSubscriptionSerializer,
    CancelSubscriptionSerializer,
    RefundChargeSerializer,
    PaymentStatusSerializer,
    CreateTransactionTokenSerializer,
    TransactionTokenSerializer
)
from .univapay_client import UnivapayClient, UnivapayError, UNIVAPAY_WEBHOOK_AUTH

# Constants
POLL_AFTER_SECONDS = 30
POLL_RETRY_AFTER_SECONDS = 60
ENABLE_POLL_FALLBACK = True


# Helper functions
def _coerce_token_id(val):
    """Accept a string or a dict and return a trimmed string id."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        cand = val.get("id") or val.get("token_id") or val.get("univapayTokenId")
        if isinstance(cand, str):
            return cand.strip()
        return (str(cand) if cand is not None else "").strip()
    return str(val).strip()


def verify_webhook_signature(request):
    """Verify Univapay webhook signature using HMAC-SHA256."""
    if not UNIVAPAY_WEBHOOK_AUTH:
        return True  # Skip verification if not configured (dev only)
    
    signature = request.headers.get('X-Signature', '')
    if not signature:
        return False
    
    # Get raw body
    body = request.body
    
    # Calculate expected signature
    expected_signature = hmac.new(
        UNIVAPAY_WEBHOOK_AUTH.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    # Secure comparison
    return hmac.compare_digest(signature, expected_signature)


def parse_datetime(dt_string):
    """Parse datetime string from Univapay API responses."""
    if not dt_string:
        return None
    try:
        # Handle ISO format with Z timezone
        if dt_string.endswith('Z'):
            dt_string = dt_string.replace('Z', '+00:00')
        # Parse and make timezone aware
        dt = datetime.fromisoformat(dt_string)
        if timezone.is_naive(dt):
            dt = make_aware(dt)
        return dt
    except Exception as e:
        print(f"Error parsing datetime '{dt_string}': {e}")
        return None


def _poll_provider_status_later(kind, provider_id, delay_s, retry=False):
    """
    Schedule a one-off background poll to refresh provider status.
    kind: 'charge' | 'subscription'
    provider_id: PaymentHistory.id
    delay_s: seconds to wait
    retry: whether this is the second attempt
    """
    if not ENABLE_POLL_FALLBACK:
        return

    def _task():
        time.sleep(delay_s)
        try:
            payment = PaymentHistory.objects.get(id=provider_id)
            univapay = UnivapayClient()

            if kind == "charge" and payment.univapay_id:
                data = univapay.get_charge(payment.univapay_id)
            elif kind == "subscription" and payment.univapay_id:
                data = univapay.get_subscription(payment.univapay_id)
            else:
                return

            status_val = (data or {}).get("status")
            if status_val:
                payment.status = status_val
                payment.save(update_fields=['status', 'updated_at'])

                # Optional: second attempt if still "pending/awaiting" for charges
                if not retry and kind == "charge" and status_val in ("pending", "awaiting"):
                    _poll_provider_status_later(kind, provider_id, POLL_RETRY_AFTER_SECONDS, retry=True)

        except Exception as e:
            print(f"[Poller] Error polling {kind} provider_id={provider_id}: {e}")

    thread = threading.Thread(target=_task)
    thread.daemon = True
    thread.start()


# Widget Configuration Endpoint
class WidgetConfigView(APIView):
    """
    API endpoint to get widget configuration for frontend.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return widget configuration for frontend initialization."""
        return Response({
            'app_token': os.getenv('UNIVAPAY_APP_TOKEN', ''),
            'mode': 'test' if settings.DEBUG else 'live',
            'store_id': os.getenv('UNIVAPAY_STORE_ID', ''),
            'widget_url': 'https://widget.univapay.com/client/checkout.js',
            'api_endpoint': os.getenv('UNIVAPAY_BASE_URL', 'https://api.univapay.com')
        })


# Subscription Plan Views
class SubscriptionPlanViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing subscription plans.
    """
    queryset = SubscriptionPlan.objects.filter(is_active=True)
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [AllowAny]


# Payment History Views
class PaymentHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing payment history.
    """
    serializer_class = PaymentHistoryListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PaymentHistory.objects.filter(
            user=self.request.user
        ).select_related(
            'transaction_token',
            'subscription_plan'
        ).order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PaymentHistorySerializer
        return PaymentHistoryListSerializer


# Transaction Token Views
class TransactionTokenViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing transaction tokens.
    """
    serializer_class = TransactionTokenSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TransactionToken.objects.filter(
            user=self.request.user
        ).order_by('-created_at')

    @action(detail=False, methods=['post'])
    def store_token(self, request):
        """
        Store a transaction token from Univapay widget response.
        Expected format from widget:
        {
            "id": "uuid",
            "type": "one_time|subscription|recurring",
            "email": "user@example.com",
            "data": {
                "card": {...},
                "billing": {...}
            },
            "mode": "test|live"
        }
        """
        try:
            # Extract data from widget response
            token_id = request.data.get('id')
            token_type = request.data.get('type', 'one_time')
            email = request.data.get('email', request.user.email)
            data = request.data.get('data', {})
            mode = request.data.get('mode', 'test')
            
            if not token_id:
                return Response(
                    {'error': 'Token ID is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Extract card details if present
            card_data = data.get('card', {})
            billing_data = data.get('billing', {})
            
            with transaction.atomic():
                # Check if token already exists
                existing_token = TransactionToken.objects.filter(
                    univapay_token_id=token_id
                ).first()
                
                if existing_token:
                    # Update last_used_at
                    existing_token.last_used_at = now()
                    existing_token.save(update_fields=['last_used_at', 'updated_at'])
                    return Response(
                        TransactionTokenSerializer(existing_token).data,
                        status=status.HTTP_200_OK
                    )
                
                # Create new token
                token = TransactionToken.objects.create(
                    user=request.user,
                    univapay_token_id=token_id,
                    token_type=token_type,
                    payment_type=data.get('payment_type', 'card'),
                    email=email,
                    card_last_four=card_data.get('last4'),
                    card_brand=card_data.get('brand'),
                    card_exp_month=card_data.get('exp_month'),
                    card_exp_year=card_data.get('exp_year'),
                    card_bin=card_data.get('bin'),
                    card_type=card_data.get('type'),
                    card_category=card_data.get('category'),
                    card_issuer=card_data.get('issuer'),
                    billing_data=billing_data,
                    cvv_authorize_enabled=data.get('cvv_authorize', False),
                    cvv_authorize_status=data.get('cvv_authorize_status'),
                    three_ds_enabled=data.get('three_ds_enabled', False),
                    three_ds_status=data.get('three_ds_status'),
                    usage_limit=data.get('usage_limit'),
                    mode=mode,
                    raw_token_data=request.data,
                    last_used_at=now()
                )
                
                return Response(
                    TransactionTokenSerializer(token).data,
                    status=status.HTTP_201_CREATED
                )
                
        except Exception as e:
            return Response(
                {'error': f'Failed to store token: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate a transaction token."""
        token = self.get_object()
        token.is_active = False
        token.save(update_fields=['is_active', 'updated_at'])
        return Response({'status': 'Token deactivated'})


# Simple Payment Views (without Univapay integration)
class PurchaseView(APIView):
    """
    API endpoint for creating a simple purchase record (testing/demo).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PurchaseSerializer(data=request.data)
        if serializer.is_valid():
            item_name = serializer.validated_data['item_name']
            amount = serializer.validated_data['amount']

            # Create a local payment record
            payment = PaymentHistory.objects.create(
                user=request.user,
                payment_type='one_time',
                amount=amount,
                currency='JPY',
                status='pending',
                mode='test' if settings.DEBUG else 'live',
                created_on=now(),
                metadata={'item_name': item_name}
            )

            return Response({
                'ok': True,
                'payment': PaymentHistorySerializer(payment).data
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SubscribeView(APIView):
    """
    API endpoint for creating a simple subscription record (testing/demo).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SubscribeSerializer(data=request.data)
        if serializer.is_valid():
            plan_id = serializer.validated_data['plan'].id

            # Get the subscription plan
            subscription_plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)

            # Create a local subscription record
            payment = PaymentHistory.objects.create(
                user=request.user,
                payment_type='recurring',
                subscription_plan=subscription_plan,
                amount=subscription_plan.amount,
                currency=subscription_plan.currency,
                period=subscription_plan.period,
                status='unverified',
                mode='test' if settings.DEBUG else 'live',
                created_on=now(),
                metadata={'plan': subscription_plan.name}
            )

            return Response({
                'ok': True,
                'payment': PaymentHistorySerializer(payment).data
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Univapay Payment Views
class UnivapayChargeView(APIView):
    """
    API endpoint for creating a charge with Univapay.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UnivapayChargeSerializer(data=request.data)
        if serializer.is_valid():
            try:
                token_id = _coerce_token_id(serializer.validated_data['transaction_token_id'])
                amount = serializer.validated_data['amount']
                currency = serializer.validated_data.get('currency', 'JPY')
                metadata = serializer.validated_data.get('metadata', {})
                
                # Get or create TransactionToken record
                token_record = None
                try:
                    token_record = TransactionToken.objects.get(
                        univapay_token_id=token_id,
                        user=request.user
                    )
                    token_record.last_used_at = now()
                    token_record.save(update_fields=['last_used_at', 'updated_at'])
                except TransactionToken.DoesNotExist:
                    # Token doesn't exist in our DB, but we can still proceed with the charge
                    pass
                
                univapay = UnivapayClient()
                idem_key = univapay.new_idempotency_key()

                # Create charge with Univapay
                resp = univapay.create_charge(
                    transaction_token_id=token_id,
                    amount=amount,
                    currency=currency,
                    metadata=metadata,
                    only_direct_currency=serializer.validated_data.get('only_direct_currency', False),
                    capture_at=serializer.validated_data.get('capture_at'),
                    descriptor=serializer.validated_data.get('descriptor'),
                    descriptor_phone_number=serializer.validated_data.get('descriptor_phone_number'),
                    redirect_endpoint=serializer.validated_data.get('redirect', {}).get('endpoint') if serializer.validated_data.get('redirect') else None,
                    three_ds_mode=serializer.validated_data.get('three_ds', {}).get('mode', 'normal') if serializer.validated_data.get('three_ds') else 'normal',
                    idempotency_key=idem_key,
                )

                error_data = resp.get('error') or {}

                # Create local payment record with TransactionToken link
                payment = PaymentHistory.objects.create(
                    user=request.user,
                    payment_type='one_time',
                    transaction_token=token_record,  # Link the token if it exists
                    univapay_id=resp.get('id'),
                    store_id=resp.get('store_id'),
                    univapay_transaction_token_id=resp.get('transaction_token_id'),
                    transaction_token_type=resp.get('transaction_token_type'),
                    subscription_id=resp.get('subscription_id'),
                    merchant_transaction_id=resp.get('merchant_transaction_id'),
                    requested_amount=resp.get('requested_amount'),
                    requested_currency=resp.get('requested_currency'),
                    requested_amount_formatted=resp.get('requested_amount_formatted'),
                    charged_amount=resp.get('charged_amount'),
                    charged_currency=resp.get('charged_currency'),
                    charged_amount_formatted=resp.get('charged_amount_formatted'),
                    fee_amount=resp.get('fee_amount'),
                    fee_currency=resp.get('fee_currency'),
                    fee_amount_formatted=resp.get('fee_amount_formatted'),
                    amount=resp.get('charged_amount') or resp.get('requested_amount') or amount,
                    currency=resp.get('charged_currency') or resp.get('requested_currency') or currency,
                    amount_formatted=resp.get('charged_amount_formatted') or resp.get('requested_amount_formatted'),
                    only_direct_currency=resp.get('only_direct_currency'),
                    capture_at=parse_datetime(resp.get('capture_at')),
                    descriptor=resp.get('descriptor'),
                    descriptor_phone_number=resp.get('descriptor_phone_number'),
                    status=resp.get('status', 'pending'),
                    error_code=error_data.get('code'),
                    error_message=error_data.get('message'),
                    error_detail=error_data.get('detail'),
                    metadata=resp.get('metadata', {}),
                    mode=resp.get('mode', 'test'),
                    created_on=parse_datetime(resp.get('created_on')) or now(),
                    redirect_endpoint=resp.get('redirect', {}).get('endpoint') if resp.get('redirect') else None,
                    redirect_id=resp.get('redirect', {}).get('redirect_id') if resp.get('redirect') else None,
                    three_ds_redirect_endpoint=resp.get('three_ds', {}).get('redirect_endpoint') if resp.get('three_ds') else None,
                    three_ds_redirect_id=resp.get('three_ds', {}).get('redirect_id') if resp.get('three_ds') else None,
                    three_ds_mode=resp.get('three_ds', {}).get('mode') if resp.get('three_ds') else None,
                    raw_json=resp
                )

                # Schedule a one-off poll as fallback to webhook
                if ENABLE_POLL_FALLBACK and payment.univapay_id:
                    _poll_provider_status_later("charge", payment.id, POLL_AFTER_SECONDS)

                return Response({
                    'ok': True,
                    'payment': PaymentHistorySerializer(payment).data,
                    'univapay': {
                        'charge_id': resp.get('id'),
                        'status': resp.get('status'),
                        'mode': resp.get('mode'),
                        'redirect': resp.get('redirect') or resp.get('three_ds'),
                    }
                }, status=status.HTTP_201_CREATED)

            except UnivapayError as e:
                return Response({
                    'error': 'UnivaPay charge failed',
                    'detail': e.body,
                    'status': e.status
                }, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({
                    'error': 'Unexpected error creating charge',
                    'detail': str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UnivapaySubscriptionView(APIView):
    """
    API endpoint for creating a subscription with Univapay.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UnivapaySubscriptionSerializer(data=request.data)
        if serializer.is_valid():
            try:
                token_id = _coerce_token_id(serializer.validated_data['transaction_token_id'])
                amount = serializer.validated_data['amount']
                currency = serializer.validated_data.get('currency', 'JPY')
                period = serializer.validated_data['period']
                metadata = serializer.validated_data.get('metadata', {})
                
                # Get or create TransactionToken record
                token_record = None
                try:
                    token_record = TransactionToken.objects.get(
                        univapay_token_id=token_id,
                        user=request.user
                    )
                    token_record.last_used_at = now()
                    token_record.save(update_fields=['last_used_at', 'updated_at'])
                except TransactionToken.DoesNotExist:
                    # Token doesn't exist in our DB, but we can still proceed
                    pass
                
                univapay = UnivapayClient()
                idem_key = univapay.new_idempotency_key()

                # Create subscription with Univapay
                resp = univapay.create_subscription(
                    transaction_token_id=token_id,
                    amount=amount,
                    currency=currency,
                    period=period,
                    metadata=metadata,
                    only_direct_currency=serializer.validated_data.get('only_direct_currency', False),
                    initial_amount=serializer.validated_data.get('initial_amount'),
                    schedule_settings=serializer.validated_data.get('schedule_settings', {}),
                    first_charge_capture_after=serializer.validated_data.get('first_charge_capture_after'),
                    first_charge_authorization_only=serializer.validated_data.get('first_charge_authorization_only', False),
                    redirect_endpoint=serializer.validated_data.get('redirect', {}).get('endpoint') if serializer.validated_data.get('redirect') else None,
                    three_ds_mode=serializer.validated_data.get('three_ds', {}).get('mode', 'normal') if serializer.validated_data.get('three_ds') else 'normal',
                    idempotency_key=idem_key,
                )

                next_payment_data = resp.get('next_payment', {})

                # Create local payment record with TransactionToken link
                payment = PaymentHistory.objects.create(
                    user=request.user,
                    payment_type='recurring',
                    transaction_token=token_record,  # Link the token if it exists
                    univapay_id=resp.get('id'),
                    store_id=resp.get('store_id'),
                    univapay_transaction_token_id=resp.get('transaction_token_id'),
                    amount=resp.get('amount'),
                    currency=resp.get('currency'),
                    amount_formatted=resp.get('amount_formatted'),
                    initial_amount=resp.get('initial_amount'),
                    initial_amount_formatted=resp.get('initial_amount_formatted'),
                    subsequent_cycles_start=resp.get('subsequent_cycles_start'),
                    schedule_settings=resp.get('schedule_settings', {}),
                    only_direct_currency=resp.get('only_direct_currency'),
                    first_charge_capture_after=resp.get('first_charge_capture_after'),
                    first_charge_authorization_only=resp.get('first_charge_authorization_only'),
                    status=resp.get('status', 'unverified'),
                    metadata=resp.get('metadata', {}),
                    mode=resp.get('mode', 'test'),
                    created_on=parse_datetime(resp.get('created_on')) or now(),
                    period=resp.get('period'),
                    cyclical_period=resp.get('cyclical_period'),
                    next_payment_id=next_payment_data.get('id'),
                    next_payment_due_date=next_payment_data.get('due_date'),
                    next_payment_zone_id=next_payment_data.get('zone_id'),
                    next_payment_amount=next_payment_data.get('amount'),
                    next_payment_currency=next_payment_data.get('currency'),
                    next_payment_amount_formatted=next_payment_data.get('amount_formatted'),
                    next_payment_is_paid=next_payment_data.get('is_paid', False),
                    next_payment_is_last_payment=next_payment_data.get('is_last_payment', False),
                    next_payment_created_on=parse_datetime(next_payment_data.get('created_on')),
                    next_payment_updated_on=parse_datetime(next_payment_data.get('updated_on')),
                    next_payment_retry_date=next_payment_data.get('retry_date'),
                    redirect_endpoint=resp.get('redirect', {}).get('endpoint') if resp.get('redirect') else None,
                    redirect_id=resp.get('redirect', {}).get('redirect_id') if resp.get('redirect') else None,
                    three_ds_redirect_endpoint=resp.get('three_ds', {}).get('redirect_endpoint') if resp.get('three_ds') else None,
                    three_ds_redirect_id=resp.get('three_ds', {}).get('redirect_id') if resp.get('three_ds') else None,
                    three_ds_mode=resp.get('three_ds', {}).get('mode') if resp.get('three_ds') else None,
                    raw_json=resp
                )

                # Schedule a one-off poll as fallback to webhook
                if ENABLE_POLL_FALLBACK and payment.univapay_id:
                    _poll_provider_status_later("subscription", payment.id, POLL_AFTER_SECONDS)

                return Response({
                    'ok': True,
                    'payment': PaymentHistorySerializer(payment).data,
                    'univapay': {
                        'subscription_id': resp.get('id'),
                        'status': resp.get('status'),
                        'mode': resp.get('mode'),
                        'next_payment': resp.get('next_payment', {}),
                    }
                }, status=status.HTTP_201_CREATED)

            except UnivapayError as e:
                return Response({
                    'error': 'UnivaPay subscription failed',
                    'detail': e.body,
                    'status': e.status
                }, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({
                    'error': 'Unexpected error creating subscription',
                    'detail': str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CancelSubscriptionView(APIView):
    """
    API endpoint for canceling a subscription.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CancelSubscriptionSerializer(data=request.data)
        if serializer.is_valid():
            try:
                subscription_id = serializer.validated_data['subscription_id']
                termination_mode = serializer.validated_data.get('termination_mode', 'immediate')
                reason = serializer.validated_data.get('reason', '')

                univapay = UnivapayClient()

                # Cancel subscription with Univapay
                resp = univapay.cancel_subscription(
                    subscription_id=subscription_id,
                    termination_mode=termination_mode,
                    reason=reason
                )

                # Update local payment record
                payment = get_object_or_404(
                    PaymentHistory, 
                    univapay_id=subscription_id, 
                    user=request.user,
                    payment_type='recurring'
                )
                payment.status = 'canceled'
                payment.cancelled_on = now()
                payment.termination_mode = termination_mode
                payment.save(update_fields=['status', 'cancelled_on', 'termination_mode', 'updated_at'])

                return Response({
                    'ok': True,
                    'payment': PaymentHistorySerializer(payment).data,
                    'univapay': resp
                }, status=status.HTTP_200_OK)

            except UnivapayError as e:
                return Response({
                    'error': 'UnivaPay subscription cancellation failed',
                    'detail': e.body,
                    'status': e.status
                }, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({
                    'error': 'Unexpected error canceling subscription',
                    'detail': str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RefundChargeView(APIView):
    """
    API endpoint for refunding a charge.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RefundChargeSerializer(data=request.data)
        if serializer.is_valid():
            try:
                charge_id = serializer.validated_data['charge_id']
                amount = serializer.validated_data.get('amount')
                reason = serializer.validated_data.get('reason', '')
                metadata = serializer.validated_data.get('metadata', {})

                univapay = UnivapayClient()
                idem_key = univapay.new_idempotency_key()

                # Refund charge with Univapay
                resp = univapay.refund_charge(
                    charge_id=charge_id,
                    amount=amount,
                    reason=reason,
                    metadata=metadata,
                    idempotency_key=idem_key,
                )

                # Update local payment record
                payment = get_object_or_404(
                    PaymentHistory, 
                    univapay_id=charge_id, 
                    user=request.user,
                    payment_type='one_time'
                )
                
                # Set status based on refund amount
                if amount and amount < payment.amount:
                    payment.status = 'partially_refunded'
                else:
                    payment.status = 'refunded'
                
                payment.save(update_fields=['status', 'updated_at'])

                return Response({
                    'ok': True,
                    'payment': PaymentHistorySerializer(payment).data,
                    'univapay': resp
                }, status=status.HTTP_200_OK)

            except UnivapayError as e:
                return Response({
                    'error': 'UnivaPay refund failed',
                    'detail': e.body,
                    'status': e.status
                }, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({
                    'error': 'Unexpected error processing refund',
                    'detail': str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PaymentStatusView(APIView):
    """
    API endpoint for checking payment status.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PaymentStatusSerializer(data=request.data)
        if serializer.is_valid():
            try:
                payment_id = serializer.validated_data['payment_id']
                payment_type = serializer.validated_data['payment_type']

                univapay = UnivapayClient()

                if payment_type == 'charge':
                    resp = univapay.get_charge(payment_id)
                elif payment_type == 'subscription':
                    resp = univapay.get_subscription(payment_id)
                else:
                    return Response({
                        'error': 'Invalid payment type. Must be "charge" or "subscription"'
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Update local payment record if it exists
                payment = PaymentHistory.objects.filter(
                    univapay_id=payment_id, 
                    user=request.user
                ).first()
                
                if payment:
                    payment.status = resp.get('status', payment.status)
                    payment.save(update_fields=['status', 'updated_at'])
                    
                    return Response({
                        'ok': True,
                        'payment': PaymentHistorySerializer(payment).data,
                        'univapay': resp
                    }, status=status.HTTP_200_OK)
                else:
                    # Payment not found in local DB, return Univapay data only
                    return Response({
                        'ok': True,
                        'payment': None,
                        'univapay': resp
                    }, status=status.HTTP_200_OK)

            except UnivapayError as e:
                return Response({
                    'error': 'UnivaPay status check failed',
                    'detail': e.body,
                    'status': e.status
                }, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({
                    'error': 'Unexpected error checking status',
                    'detail': str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Webhook Handler
@method_decorator(csrf_exempt, name='dispatch')
class WebhookView(APIView):
    """
    Webhook endpoint for Univapay events with signature verification.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        # Verify webhook signature
        if not verify_webhook_signature(request):
            return Response({'error': 'Invalid signature'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            data = request.data
            event_type = data.get('event') or data.get('type') or data.get('object')
            
            # Log webhook for debugging
            print(f"Received webhook event: {event_type}")
            print(f"Webhook data: {json.dumps(data, indent=2)}")
            
            # Handle different event types
            if event_type in ['charge.finished', 'charge.updated', 'charge']:
                self._handle_charge_event(data)
            elif event_type in ['subscription.updated', 'subscription.payment', 'subscription.canceled', 'subscription']:
                self._handle_subscription_event(data)
            elif event_type in ['refund.finished', 'refund']:
                self._handle_refund_event(data)
            
            return Response({'ok': True}, status=status.HTTP_200_OK)
            
        except Exception as e:
            print(f"Webhook error: {e}")
            # Always return OK to prevent retries
            return Response({'ok': True}, status=status.HTTP_200_OK)
    
    def _handle_charge_event(self, data):
        """Handle charge-related webhook events."""
        charge_data = data.get('data') or data
        charge_id = charge_data.get('id')
        
        if not charge_id:
            return
        
        payment = PaymentHistory.objects.filter(
            univapay_id=charge_id,
            payment_type='one_time'
        ).first()
        
        if payment:
            # Update payment status
            payment.status = charge_data.get('status', payment.status)
            
            # Update amounts if provided
            if charge_data.get('charged_amount'):
                payment.charged_amount = charge_data['charged_amount']
            if charge_data.get('charged_currency'):
                payment.charged_currency = charge_data['charged_currency']
            
            # Update error information
            error_info = charge_data.get('error', {})
            if error_info:
                payment.error_code = error_info.get('code')
                payment.error_message = error_info.get('message')
                payment.error_detail = error_info.get('detail')
            
            payment.save()
            print(f"Updated charge {charge_id} status to {payment.status}")
    
    def _handle_subscription_event(self, data):
        """Handle subscription-related webhook events."""
        sub_data = data.get('data') or data
        sub_id = sub_data.get('id')
        
        if not sub_id:
            return
        
        payment = PaymentHistory.objects.filter(
            univapay_id=sub_id,
            payment_type='recurring'
        ).first()
        
        if payment:
            # Update subscription status
            payment.status = sub_data.get('status', payment.status)
            
            # Update cancellation info
            if sub_data.get('cancelled_on'):
                payment.cancelled_on = parse_datetime(sub_data['cancelled_on'])
            
            # Update next payment information
            next_payment = sub_data.get('next_payment', {})
            if next_payment:
                payment.next_payment_id = next_payment.get('id')
                payment.next_payment_due_date = next_payment.get('due_date')
                payment.next_payment_amount = next_payment.get('amount')
                payment.next_payment_currency = next_payment.get('currency')
                payment.next_payment_is_paid = next_payment.get('is_paid', False)
                payment.next_payment_is_last_payment = next_payment.get('is_last_payment', False)
                payment.next_payment_retry_date = next_payment.get('retry_date')
            
            payment.save()
            print(f"Updated subscription {sub_id} status to {payment.status}")
    
    def _handle_refund_event(self, data):
        """Handle refund-related webhook events."""
        refund_data = data.get('data') or data
        charge_id = refund_data.get('charge_id')
        
        if not charge_id:
            return
        
        payment = PaymentHistory.objects.filter(
            univapay_id=charge_id,
            payment_type='one_time'
        ).first()
        
        if payment:
            # Update payment status based on refund
            refund_amount = refund_data.get('amount')
            if refund_amount and refund_amount < payment.amount:
                payment.status = 'partially_refunded'
            else:
                payment.status = 'refunded'
            
            payment.save()
            print(f"Updated charge {charge_id} to refunded status")


# Alternative function-based webhook handler (if you prefer this style)
@api_view(['POST'])
@permission_classes([AllowAny])
def webhook_handler(request):
    """
    Alternative function-based webhook endpoint for Univapay events.
    """
    # Verify webhook signature
    if not verify_webhook_signature(request):
        return Response({'error': 'Invalid signature'}, status=status.HTTP_401_UNAUTHORIZED)
    
    # Process webhook using the same logic as WebhookView
    view = WebhookView()
    return view.post(request)