from django.contrib import admin
from .models import SubscriptionPlan, PaymentHistory, TransactionToken


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'currency', 'period', 'is_active', 'created_at')
    list_filter = ('is_active', 'period', 'currency')
    search_fields = ('name',)
    ordering = ('-created_at',)


@admin.register(TransactionToken)
class TransactionTokenAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'token_type', 'payment_type', 'card_brand', 
                    'card_last_four', 'is_active', 'mode', 'created_at')
    list_filter = ('token_type', 'payment_type', 'is_active', 'mode', 'card_brand')
    search_fields = ('user__email', 'univapay_token_id', 'email')
    readonly_fields = ('created_at', 'updated_at', 'last_used_at', 'raw_token_data')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'univapay_token_id', 'token_type', 'payment_type', 'email')
        }),
        ('Card Details', {
            'fields': ('card_brand', 'card_last_four', 'card_exp_month', 'card_exp_year',
                      'card_bin', 'card_type', 'card_category', 'card_issuer')
        }),
        ('Security', {
            'fields': ('cvv_authorize_enabled', 'cvv_authorize_status', 
                      'three_ds_enabled', 'three_ds_status')
        }),
        ('Settings', {
            'fields': ('is_active', 'usage_limit', 'mode')
        }),
        ('Data', {
            'fields': ('billing_data', 'raw_token_data')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_used_at')
        })
    )


@admin.register(PaymentHistory)
class PaymentHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'payment_type', 'amount', 'currency', 
                    'status', 'mode', 'created_at')
    list_filter = ('payment_type', 'status', 'mode', 'currency')
    search_fields = ('user__email', 'univapay_id', 'transaction_token__univapay_token_id')
    readonly_fields = ('created_at', 'updated_at', 'raw_json')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'payment_type', 'status', 'mode', 'transaction_token')
        }),
        ('Payment Details', {
            'fields': ('univapay_id', 'store_id', 'univapay_transaction_token_id',
                      'amount', 'currency', 'amount_formatted')
        }),
        ('One-time Payment Fields', {
            'fields': ('charged_amount', 'charged_currency', 'fee_amount', 
                      'error_code', 'error_message'),
            'classes': ('collapse',)
        }),
        ('Subscription Fields', {
            'fields': ('subscription_plan', 'period', 'initial_amount', 
                      'next_payment_due_date', 'next_payment_amount', 'cancelled_on'),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('metadata', 'raw_json'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_on', 'created_at', 'updated_at')
        })
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user', 'transaction_token', 'subscription_plan')