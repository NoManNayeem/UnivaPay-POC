from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator


class SubscriptionPlan(models.Model):
    PERIOD_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('biweekly', 'Biweekly'),
        ('monthly', 'Monthly'),
        ('bimonthly', 'Bimonthly'),
        ('quarterly', 'Quarterly'),
        ('semiannually', 'Semiannually'),
        ('annually', 'Annually'),
    ]

    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default='JPY')
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.amount} {self.currency}"


class TransactionToken(models.Model):
    """Store transaction tokens created by frontend widget"""
    TOKEN_TYPE_CHOICES = [
        ('one_time', 'One Time'),
        ('subscription', 'Subscription'),
        ('recurring', 'Recurring'),
    ]
    
    PAYMENT_TYPE_CHOICES = [
        ('card', 'Credit Card'),
        ('paidy', 'Paidy'),
        ('online', 'Online Payment'),
        ('konbini', 'Convenience Store'),
        ('bank_transfer', 'Bank Transfer'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transaction_tokens')
    univapay_token_id = models.UUIDField(unique=True, db_index=True)
    token_type = models.CharField(max_length=20, choices=TOKEN_TYPE_CHOICES)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='card')
    
    # Email from token creation
    email = models.EmailField()
    
    # Card details (if payment_type is 'card')
    card_last_four = models.CharField(max_length=4, null=True, blank=True)
    card_brand = models.CharField(max_length=50, null=True, blank=True)
    card_exp_month = models.IntegerField(null=True, blank=True)
    card_exp_year = models.IntegerField(null=True, blank=True)
    card_bin = models.CharField(max_length=8, null=True, blank=True)
    card_type = models.CharField(max_length=20, null=True, blank=True)
    card_category = models.CharField(max_length=20, null=True, blank=True)
    card_issuer = models.CharField(max_length=100, null=True, blank=True)
    
    # Billing information
    billing_data = models.JSONField(default=dict, blank=True)  # Full billing address data
    
    # CVV authorization status (for recurring tokens)
    cvv_authorize_enabled = models.BooleanField(default=False)
    cvv_authorize_status = models.CharField(max_length=20, null=True, blank=True)  # pending, current, failed, inactive
    
    # 3D Secure settings
    three_ds_enabled = models.BooleanField(default=False)
    three_ds_status = models.CharField(max_length=20, null=True, blank=True)
    
    # Token status
    is_active = models.BooleanField(default=True)
    usage_limit = models.CharField(max_length=20, null=True, blank=True)  # daily, weekly, monthly, annually, null
    mode = models.CharField(max_length=10, default='test')  # test or live
    
    # Raw response from UnivaPay when token was created
    raw_token_data = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['univapay_token_id']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['user', 'token_type']),
        ]
        
    def __str__(self):
        if self.card_brand and self.card_last_four:
            return f"{self.user} - {self.card_brand} ****{self.card_last_four}"
        return f"{self.user} - {self.univapay_token_id}"


class PaymentHistory(models.Model):
    # Payment type choices
    PAYMENT_TYPE_CHOICES = [
        ('one_time', 'One Time Payment'),
        ('recurring', 'Recurring Payment'),
    ]

    # Status choices for one-time payments
    ONETIME_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('awaiting', 'Awaiting'),
        ('authorized', 'Authorized'),
        ('successful', 'Successful'),
        ('failed', 'Failed'),
        ('error', 'Error'),
        ('canceled', 'Canceled'),
    ]

    # Status choices for recurring payments
    RECURRING_STATUS_CHOICES = [
        ('unverified', 'Unverified'),
        ('unconfirmed', 'Unconfirmed'),
        ('canceled', 'Canceled'),
        ('unpaid', 'Unpaid'),
        ('current', 'Current'),
        ('suspended', 'Suspended'),
        ('completed', 'Completed'),
    ]

    # Period choices for recurring payments
    PERIOD_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('biweekly', 'Biweekly'),
        ('monthly', 'Monthly'),
        ('bimonthly', 'Bimonthly'),
        ('quarterly', 'Quarterly'),
        ('semiannually', 'Semiannually'),
        ('annually', 'Annually'),
    ]

    # Termination mode choices
    TERMINATION_MODE_CHOICES = [
        ('immediate', 'Immediate'),
        ('on_next_payment', 'On Next Payment'),
    ]

    # 3DS mode choices
    THREE_DS_MODE_CHOICES = [
        ('normal', 'Normal'),
        ('require', 'Require'),
        ('force', 'Force'),
        ('skip', 'Skip'),
    ]

    # Common fields for both payment types
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payment_history')
    payment_type = models.CharField(max_length=10, choices=PAYMENT_TYPE_CHOICES)
    
    # Link to transaction token - ADDED
    transaction_token = models.ForeignKey(
        TransactionToken,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments'
    )
    
    # UnivaPay IDs - CORRECTED to be nullable
    univapay_id = models.UUIDField(null=True, blank=True, db_index=True)
    store_id = models.UUIDField(null=True, blank=True)
    univapay_transaction_token_id = models.UUIDField(null=True, blank=True)
    
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3)
    amount_formatted = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    only_direct_currency = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict)
    mode = models.CharField(max_length=10)  # test or live
    created_on = models.DateTimeField(null=True, blank=True)  # CORRECTED to be nullable
    
    # Raw JSON response - ADDED (was missing)
    raw_json = models.JSONField(default=dict, blank=True)

    # Status field - will be interpreted based on payment_type
    status = models.CharField(max_length=20)

    # One-time payment-specific fields
    transaction_token_type = models.CharField(max_length=20, null=True, blank=True)
    subscription_id = models.UUIDField(null=True, blank=True)  # For charges that are part of a subscription
    merchant_transaction_id = models.CharField(max_length=255, null=True, blank=True)
    requested_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    requested_currency = models.CharField(max_length=3, null=True, blank=True)
    requested_amount_formatted = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    charged_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    charged_currency = models.CharField(max_length=3, null=True, blank=True)
    charged_amount_formatted = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    fee_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    fee_currency = models.CharField(max_length=3, null=True, blank=True)
    fee_amount_formatted = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    capture_at = models.DateTimeField(null=True, blank=True)
    descriptor = models.CharField(max_length=255, null=True, blank=True)
    descriptor_phone_number = models.CharField(max_length=20, null=True, blank=True)
    error_code = models.CharField(max_length=50, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    error_detail = models.TextField(null=True, blank=True)
    redirect_endpoint = models.URLField(null=True, blank=True)
    redirect_id = models.UUIDField(null=True, blank=True)
    three_ds_redirect_endpoint = models.URLField(null=True, blank=True)
    three_ds_redirect_id = models.UUIDField(null=True, blank=True)
    three_ds_mode = models.CharField(max_length=10, choices=THREE_DS_MODE_CHOICES, null=True, blank=True)

    # Bank transfer fields (for Japanese bank transfers)
    bank_ledger_type = models.CharField(max_length=20, null=True, blank=True)
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    virtual_bank_account_holder_name = models.CharField(max_length=255, null=True, blank=True)
    virtual_bank_account_number = models.CharField(max_length=20, null=True, blank=True)
    virtual_account_id = models.CharField(max_length=50, null=True, blank=True)
    transaction_date = models.DateField(null=True, blank=True)
    transaction_timestamp = models.DateTimeField(null=True, blank=True)
    transaction_id = models.CharField(max_length=50, null=True, blank=True)

    # Recurring payment specific fields
    subscription_plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True
    )
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES, null=True, blank=True)
    initial_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    initial_amount_formatted = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    subsequent_cycles_start = models.DateField(null=True, blank=True)
    schedule_settings = models.JSONField(default=dict, null=True, blank=True)  # Store all schedule settings as JSON
    first_charge_capture_after = models.DurationField(null=True, blank=True)
    first_charge_authorization_only = models.BooleanField(default=False)
    cyclical_period = models.CharField(max_length=20, null=True, blank=True)

    # Next payment details for subscriptions
    next_payment_id = models.UUIDField(null=True, blank=True)
    next_payment_due_date = models.DateField(null=True, blank=True)
    next_payment_zone_id = models.CharField(max_length=50, null=True, blank=True)
    next_payment_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    next_payment_currency = models.CharField(max_length=3, null=True, blank=True)
    next_payment_amount_formatted = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    next_payment_is_paid = models.BooleanField(default=False)
    next_payment_is_last_payment = models.BooleanField(default=False)
    next_payment_created_on = models.DateTimeField(null=True, blank=True)
    next_payment_updated_on = models.DateTimeField(null=True, blank=True)
    next_payment_retry_date = models.DateField(null=True, blank=True)

    # Subscription management fields
    cancelled_on = models.DateTimeField(null=True, blank=True)
    termination_mode = models.CharField(
        max_length=20, choices=TERMINATION_MODE_CHOICES, null=True, blank=True
    )
    retry_interval = models.CharField(max_length=20, null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Payment Histories"
        indexes = [
            models.Index(fields=['univapay_id']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['payment_type', 'status']),
            models.Index(fields=['transaction_token', 'created_at']),  # ADDED index
        ]

    def __str__(self):
        return f"{self.user} - {self.payment_type} - {self.amount} {self.currency} - {self.status}"

    def is_one_time_payment(self):
        return self.payment_type == 'one_time'

    def is_recurring_payment(self):
        return self.payment_type == 'recurring'

    def is_successful(self):
        if self.is_one_time_payment():
            return self.status == 'successful'
        else:
            return self.status == 'current'

    def is_canceled(self):
        return self.status == 'canceled'

    def get_status_display(self):
        if self.is_one_time_payment():
            for code, name in self.ONETIME_STATUS_CHOICES:
                if code == self.status:
                    return name
        else:
            for code, name in self.RECURRING_STATUS_CHOICES:
                if code == self.status:
                    return name
        return self.status