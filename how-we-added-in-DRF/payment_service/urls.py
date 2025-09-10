from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SubscriptionPlanViewSet,
    PaymentHistoryViewSet,
    TransactionTokenViewSet,
    WidgetConfigView,
    UnivapayChargeView,
    UnivapaySubscriptionView,
    CancelSubscriptionView,
    RefundChargeView,
    PaymentStatusView,
    WebhookView,
)

router = DefaultRouter()
router.register(r'subscription-plans', SubscriptionPlanViewSet, basename='subscriptionplan')
router.register(r'payment-history', PaymentHistoryViewSet, basename='paymenthistory')
router.register(r'transaction-tokens', TransactionTokenViewSet, basename='transactiontoken')

urlpatterns = [
    path('', include(router.urls)),
    
    # Widget configuration
    path('widget-config/', WidgetConfigView.as_view(), name='widget-config'),
    
    # Univapay endpoints
    path('univapay/charge/', UnivapayChargeView.as_view(), name='univapay-charge'),
    path('univapay/subscription/', UnivapaySubscriptionView.as_view(), name='univapay-subscription'),
    path('univapay/cancel-subscription/', CancelSubscriptionView.as_view(), name='univapay-cancel-subscription'),
    path('univapay/refund-charge/', RefundChargeView.as_view(), name='univapay-refund-charge'),
    path('univapay/payment-status/', PaymentStatusView.as_view(), name='univapay-payment-status'),
    
    # Webhook
    path('webhook/univapay/', WebhookView.as_view(), name='univapay-webhook'),
]