from django.contrib import admin
from .models import Genre, Language, Movie, Theater, Seat, Booking, PaymentAttempt, PaymentWebhookEvent


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    search_fields = ['name']
    list_display = ['name']


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    search_fields = ['name']
    list_display = ['name']


class TheaterInline(admin.TabularInline):
    model = Theater
    extra = 0


class SeatInline(admin.TabularInline):
    model = Seat
    extra = 0

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'cast','description']
    search_fields = ['name', 'cast', 'description']
    list_filter = ['rating', 'genre', 'language']
    filter_horizontal = ['genre', 'language']
    inlines = [TheaterInline]


@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'movie', 'time']
    search_fields = ['name', 'movie__name']
    list_filter = ['movie']
    inlines = [SeatInline]


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['theater', 'seat_number', 'is_booked']
    search_fields = ['seat_number', 'theater__name', 'theater__movie__name']
    list_filter = ['is_booked', 'theater']

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
