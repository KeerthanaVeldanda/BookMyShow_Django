from django.contrib import admin
from .models import Movie, Theater, Seat,Booking, PaymentAttempt, PaymentWebhookEvent

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'cast','description']

@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'movie', 'time']

@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['theater', 'seat_number', 'is_booked']

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['user', 'seat', 'movie','theater','booked_at']


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = ['idempotency_key', 'user', 'movie', 'theater', 'status', 'provider_order_id', 'provider_payment_id', 'created_at']
    search_fields = ['idempotency_key', 'provider_order_id', 'provider_payment_id', 'user__username']
    list_filter = ['status', 'currency', 'created_at']


@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = ['event_id', 'event_type', 'signature_valid', 'processed', 'received_at', 'processed_at']
    search_fields = ['event_id', 'event_type', 'payload_hash']
    list_filter = ['signature_valid', 'processed', 'provider']
