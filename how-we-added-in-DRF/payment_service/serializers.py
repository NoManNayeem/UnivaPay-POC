from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from .models import SubscriptionPlan, TransactionToken, PaymentHistory

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='profile.full_name', read_only=True)

    class Meta:
        model = User
        fields = ('id', 'email', 'full_name')


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class TransactionTokenSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = TransactionToken
        fields = '__all__'
        read_only_fields = (
            'user', 'created_at', 'updated_at', 'last_used_at'
        )


class CreateTransactionTokenSerializer(serializers.Serializer):
    """Serializer for creating/storing transaction tokens from frontend"""
    token_id = serializers.UUIDField()
    token_type = serializers.ChoiceField(choices=['one_time', 'subscription', 'recurring'])
    payment_type = serializers.ChoiceField(
        choices=['card', 'paidy', 'online', 'konbini', 'bank_transfer'],
        default='card'
    )
    email = serializers.EmailField()
    
    # Card details (only required if payment_type is 'card')
    card_details = serializers.DictField(
        required=False, 
        child=serializers.CharField(),
        allow_null=True
    )
    
    # Billing data
    billing_data = serializers.JSONField(required=False, default=dict)
    
    # CVV and 3DS status
    cvv_authorize_enabled = serializers.BooleanField(default=False)
    cvv_authorize_status = serializers.CharField(max_length=20, required=False, allow_blank=True)
    three_ds_enabled = serializers.BooleanField(default=False)
    three_ds_status = serializers.CharField(max_length=20, required=False, allow_blank=True)
    
    # Token settings
    usage_limit = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    mode = serializers.ChoiceField(choices=['test', 'live'], default='test')
    
    # Raw token data from UnivaPay
    raw_token_data = serializers.JSONField(required=False, default=dict)


class RedirectSerializer(serializers.Serializer):
    endpoint = serializers.URLField(required=False, allow_null=True)
    

class ThreeDSSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=[('normal', 'Normal'), ('require', 'Require'), ('force', 'Force'), ('skip', 'Skip')],
        default='normal',
        required=False
    )


class ScheduleSettingsSerializer(serializers.Serializer):
    start_on = serializers.DateTimeField(required=False, allow_null=True)
    zone_id = serializers.CharField(required=False, default='Asia/Tokyo')
    preserve_end_of_month = serializers.BooleanField(required=False, allow_null=True)
    retry_interval = serializers.CharField(required=False, allow_null=True)
    termination_mode = serializers.ChoiceField(
        choices=[('immediate', 'Immediate'), ('on_next_payment', 'On Next Payment')],
        default='immediate',
        required=False
    )


class UnivapayChargeSerializer(serializers.Serializer):
    """Serializer for creating a charge with UnivaPay"""
    transaction_token_id = serializers.UUIDField()
    amount = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=3, default='JPY')
    metadata = serializers.JSONField(required=False, default=dict)
    only_direct_currency = serializers.BooleanField(default=False, required=False)
    capture_at = serializers.DateTimeField(required=False, allow_null=True)
    descriptor = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    descriptor_phone_number = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    redirect = RedirectSerializer(required=False)
    three_ds = ThreeDSSerializer(required=False)


class UnivapaySubscriptionSerializer(serializers.Serializer):
    """Serializer for creating a subscription with UnivaPay"""
    transaction_token_id = serializers.UUIDField()
    amount = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=3, default='USD')
    period = serializers.ChoiceField(choices=SubscriptionPlan.PERIOD_CHOICES)
    metadata = serializers.JSONField(required=False, default=dict)
    only_direct_currency = serializers.BooleanField(default=False, required=False)
    initial_amount = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    schedule_settings = ScheduleSettingsSerializer(required=False)
    first_charge_capture_after = serializers.DurationField(required=False, allow_null=True)
    first_charge_authorization_only = serializers.BooleanField(default=False, required=False)
    redirect = RedirectSerializer(required=False)
    three_ds = ThreeDSSerializer(required=False)


class PaymentHistorySerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    subscription_plan = SubscriptionPlanSerializer(read_only=True)
    transaction_token = TransactionTokenSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_successful = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = PaymentHistory
        fields = '__all__'
        read_only_fields = (
            'created_at', 'updated_at', 'univapay_id', 'store_id',
            'transaction_token_id', 'created_on'
        )


class PaymentHistoryListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views"""
    user_email = serializers.EmailField(source='user.email', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_successful = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = PaymentHistory
        fields = [
            'id', 'user_email', 'payment_type', 'amount', 'currency',
            'status', 'status_display', 'is_successful', 'mode',
            'univapay_id', 'created_at'
        ]
        read_only_fields = fields


class WebhookEventSerializer(serializers.Serializer):
    """Serializer for UnivaPay webhook events"""
    event = serializers.CharField(required=False, allow_blank=True)
    type = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False, allow_blank=True)
    object = serializers.CharField(required=False, allow_blank=True)
    data = serializers.JSONField(required=False, default=dict)
    id = serializers.UUIDField(required=False, allow_null=True)
    charge = serializers.JSONField(required=False, default=dict)
    subscription = serializers.JSONField(required=False, default=dict)
    
    def validate(self, data):
        if not any(key in data for key in ['event', 'type', 'status', 'id']):
            raise serializers.ValidationError(
                "At least one of 'event', 'type', 'status', or 'id' is required."
            )
        return data


class WebhookChargeSerializer(serializers.Serializer):
    """Serializer for charge webhook events"""
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=PaymentHistory.ONETIME_STATUS_CHOICES)
    metadata = serializers.JSONField(required=False, default=dict)
    charged_amount = serializers.IntegerField(required=False, allow_null=True)
    charged_currency = serializers.CharField(required=False, allow_null=True, max_length=3)
    error_code = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    error_message = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    error_detail = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class WebhookSubscriptionSerializer(serializers.Serializer):
    """Serializer for subscription webhook events"""
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=PaymentHistory.RECURRING_STATUS_CHOICES)
    metadata = serializers.JSONField(required=False, default=dict)
    cancelled_on = serializers.DateTimeField(required=False, allow_null=True)
    next_payment = serializers.JSONField(required=False, default=dict)


class CancelSubscriptionSerializer(serializers.Serializer):
    """Serializer for cancelling a subscription"""
    subscription_id = serializers.UUIDField()
    termination_mode = serializers.ChoiceField(
        choices=[('immediate', 'Immediate'), ('on_next_payment', 'On Next Payment')],
        default='immediate'
    )
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class RefundChargeSerializer(serializers.Serializer):
    """Serializer for refunding a charge"""
    charge_id = serializers.UUIDField()
    amount = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False, default=dict)


class PaymentStatusSerializer(serializers.Serializer):
    """Serializer for checking payment status"""
    payment_id = serializers.UUIDField()
    payment_type = serializers.ChoiceField(choices=['charge', 'subscription'])


class PurchaseSerializer(serializers.Serializer):
    """Serializer for simple purchase without UnivaPay integration"""
    item_name = serializers.CharField(max_length=255)
    amount = serializers.IntegerField(min_value=1)


class SubscribeSerializer(serializers.Serializer):
    """Serializer for simple subscription without UnivaPay integration"""
    plan = serializers.PrimaryKeyRelatedField(queryset=SubscriptionPlan.objects.all())
