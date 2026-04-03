from django.db import models
from django.contrib.auth.models import User 
from django.core.exceptions import ValidationError
from urllib.parse import parse_qs, urlparse
from django.utils import timezone
import re


YOUTUBE_VIDEO_ID_REGEX = re.compile(r'^[A-Za-z0-9_-]{11}$')
YOUTUBE_ALLOWED_HOSTS = {
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'youtu.be',
    'www.youtu.be',
}


def extract_youtube_video_id(url):
    if not url:
        return None

    try:
        parsed = urlparse(str(url).strip())
    except (ValueError, AttributeError):
        return None

    if parsed.scheme not in {'http', 'https'}:
        return None

    host = parsed.netloc.lower().split(':')[0]
    if host not in YOUTUBE_ALLOWED_HOSTS:
        return None

    video_id = None
    if host in {'youtu.be', 'www.youtu.be'}:
        video_id = parsed.path.lstrip('/').split('/')[0]
    elif parsed.path == '/watch':
        video_id = parse_qs(parsed.query).get('v', [None])[0]
    elif parsed.path.startswith('/embed/'):
        video_id = parsed.path.split('/embed/', 1)[1].split('/')[0]
    elif parsed.path.startswith('/shorts/'):
        video_id = parsed.path.split('/shorts/', 1)[1].split('/')[0]

    if not video_id or not YOUTUBE_VIDEO_ID_REGEX.fullmatch(video_id):
        return None

    return video_id


def validate_youtube_trailer_url(url):
    if not url:
        return
    if not extract_youtube_video_id(url):
        raise ValidationError('Enter a valid YouTube URL from youtube.com or youtu.be.')

class Genre(models.Model):
    name = models.CharField(max_length=100, db_index=True, unique=True)

    class Meta:
        indexes = [
            models.Index(fields=['name']),
        ]
        ordering = ['name']

    def __str__(self):
        return self.name

class Language(models.Model):
    name = models.CharField(max_length=100, db_index=True, unique=True)

    class Meta:
        indexes = [
            models.Index(fields=['name']),
        ]
        ordering = ['name']

    def __str__(self):
        return self.name
class Movie(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    genre = models.ManyToManyField(Genre, related_name='movies')
    language = models.ManyToManyField(Language, related_name='movies')
    image = models.ImageField(upload_to="movies/")
    rating = models.DecimalField(max_digits=3, decimal_places=1, db_index=True)
    cast = models.TextField()
    description = models.TextField(blank=True, null=True)  # optional
    trailer_url = models.URLField(blank=True, null=True, validators=[validate_youtube_trailer_url])

    class Meta:
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['rating']),
            models.Index(fields=['-rating']),  # For descending rating queries
        ]
        ordering = ['-id']

    def __str__(self):
        return self.name

class Theater(models.Model):
    name = models.CharField(max_length=255)
    movie = models.ForeignKey(Movie,on_delete=models.CASCADE,related_name='theaters')
    time= models.DateTimeField()

    def __str__(self):
        return f'{self.name} - {self.movie.name} at {self.time}'

class Seat(models.Model):
    theater = models.ForeignKey(Theater,on_delete=models.CASCADE,related_name='seats')
    seat_number = models.CharField(max_length=10)
    is_booked=models.BooleanField(default=False)
    
    # Seat reservation locking fields for concurrency-safe temporary holds
    # =====================================================================
    # Seats are locked for 2 minutes during payment to prevent double-booking.
    # Multiple users selecting the same seat simultaneously cannot bypass this lock
    # because database-level row locking (select_for_update) is used in transactions.
    is_locked = models.BooleanField(default=False, db_index=True, help_text="Seat temporarily reserved during payment")
    locked_at = models.DateTimeField(null=True, blank=True, db_index=True, help_text="When the reservation lock was created")
    locked_by_attempt = models.ForeignKey(
        'PaymentAttempt',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reserved_seats',
        help_text="Which payment attempt holds this seat lock"
    )

    def __str__(self):
        return f'{self.seat_number} in {self.theater.name}'

class Booking(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE)
    seat=models.OneToOneField(Seat,on_delete=models.CASCADE)
    movie=models.ForeignKey(Movie,on_delete=models.CASCADE)
    theater=models.ForeignKey(Theater,on_delete=models.CASCADE)
    payment_id = models.CharField(max_length=64, db_index=True)
    booked_at=models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['booked_at'], name='movies_book_booked__61a946_idx'),
            models.Index(fields=['movie', 'booked_at'], name='movies_book_movie_i_006235_idx'),
            models.Index(fields=['theater', 'booked_at'], name='movies_book_theater_45a594_idx'),
        ]

    def __str__(self):
        return f'Booking by{self.user.username} for {self.seat.seat_number} at {self.theater.name}'


class PaymentAttempt(models.Model):
    STATUS_INITIATED = 'initiated'
    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_TIMEOUT = 'timeout'
    STATUS_PARTIAL_FAILURE = 'partial_failure'

    STATUS_CHOICES = [
        (STATUS_INITIATED, 'Initiated'),
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_TIMEOUT, 'Timeout'),
        (STATUS_PARTIAL_FAILURE, 'Partial Failure'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_attempts')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='payment_attempts')
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE, related_name='payment_attempts')
    idempotency_key = models.CharField(max_length=64, unique=True, db_index=True)
    provider_order_id = models.CharField(max_length=80, blank=True, null=True, unique=True)
    provider_payment_id = models.CharField(max_length=80, blank=True, null=True, unique=True)
    provider_signature = models.CharField(max_length=255, blank=True, null=True)
    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=8, default='INR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_INITIATED, db_index=True)
    seat_ids = models.JSONField(default=list)
    seat_numbers = models.JSONField(default=list)
    failure_reason = models.TextField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True, db_index=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f'{self.idempotency_key} - {self.status}'

    def is_expired(self):
        return bool(self.expires_at and timezone.now() > self.expires_at)


class PaymentWebhookEvent(models.Model):
    provider = models.CharField(max_length=30, default='razorpay')
    event_id = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=80)
    signature_valid = models.BooleanField(default=False)
    processed = models.BooleanField(default=False)
    payload_hash = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f'{self.event_type} ({self.event_id})'