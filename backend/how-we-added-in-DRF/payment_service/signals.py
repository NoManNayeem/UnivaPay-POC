# import logging
# import stripe
# from django.db.models.signals import post_save
# from django.dispatch import receiver
# from .models import SubscriptionPlan
#
# logger = logging.getLogger(__name__)
#
#
# @receiver(post_save, sender=SubscriptionPlan)
# def create_stripe_plan_on_save(sender, instance, created, **kwargs):
#     """
#     Automatically creates a Stripe product and price when a new SubscriptionPlan is created,
#     unless it already has associated Stripe IDs.
#     """
#     if created and not instance.stripe_product_id and not instance.stripe_price_id:
#         try:
#             instance.create_in_stripe()
#             logger.info(
#                 f"✅ Stripe product and price created for plan '{instance.name}' (ID: {instance.pk})"
#             )
#         except stripe.error.StripeError as e:
#             logger.error(
#                 f"❌ Stripe error while creating plan '{instance.name}' (ID: {instance.pk}): {e}"
#             )
#         except Exception as e:
#             logger.exception(
#                 f"❌ Unexpected error while creating Stripe plan for '{instance.name}' (ID: {instance.pk})"
#             )
