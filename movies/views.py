from django.shortcuts import render, redirect ,get_object_or_404
from .models import Movie,Theater,Seat,Booking,Genre,Language
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db import transaction
from django.db.models import Count, Sum, Q, F, FloatField, Value, Case, When
from django.db.models.functions import Coalesce, ExtractHour
from django.core.paginator import Paginator
from uuid import uuid4
import logging
import json
import importlib
from threading import Thread
from datetime import timedelta
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.core.cache import cache
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from .utils import send_booking_confirmation_email_message
from .models import PaymentAttempt, PaymentWebhookEvent
from .payments import (
    sha256_hex,
    verify_razorpay_payment_signature,
    verify_razorpay_webhook_signature,
)
from .reservations import (
    hold_seats_for_payment,
    release_seat_locks,
    SEAT_LOCK_TIMEOUT_SECONDS,
)

try:
    razorpay = importlib.import_module('razorpay')
except Exception:  # pragma: no cover
    razorpay = None


logger = logging.getLogger(__name__)
payment_logger = logging.getLogger('movies.payment')

SEAT_PRICE_INR = int(getattr(settings, 'PAYMENT_SEAT_PRICE_INR', 200))
PAYMENT_TIMEOUT_MINUTES = int(getattr(settings, 'PAYMENT_TIMEOUT_MINUTES', 10))


def _create_razorpay_client():
    if razorpay is None:
        raise RuntimeError('razorpay package is not installed')
    key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
    key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')
    if not key_id or not key_secret:
        raise RuntimeError('Razorpay credentials are not configured')
    return razorpay.Client(auth=(key_id, key_secret))


def _send_booking_confirmation_async(booking_ids, user_id):
    if not booking_ids:
        return
    try:
        bookings = Booking.objects.filter(id__in=booking_ids)
        thread = Thread(target=send_booking_confirmation_email_message, args=(bookings,), daemon=True)
        thread.start()
    except Exception:
        payment_logger.exception(
            'Failed to send booking confirmation email after verified payment',
            extra={'user_id': user_id, 'booking_ids': booking_ids},
        )


def _finalize_verified_payment(attempt, provider_payment_id, provider_signature, source):
    """
    Finalize verified payment and create bookings within atomic transaction.
    
    LOCK RELEASE FLOW:
    ==================
    1. Inside transaction.atomic(), we hold exclusive locks on PaymentAttempt and Seats
    2. Verify payment is valid (not expired, seats exist, not already booked)
    3. Create Booking records and mark seats as is_booked=True
    4. Release seat reservation locks (via release_seat_locks)
    5. Commit transaction atomically
    
    If anything fails, transaction rolls back and seats remain locked
    (to be auto-released by cleanup job if needed).
    """
    with transaction.atomic():
        locked_attempt = PaymentAttempt.objects.select_for_update().get(id=attempt.id)

        if locked_attempt.status == PaymentAttempt.STATUS_SUCCESS:
            booking_ids = list(
                Booking.objects.filter(user=locked_attempt.user, payment_id=locked_attempt.provider_payment_id)
                .values_list('id', flat=True)
            )
            return {'ok': True, 'already_processed': True, 'booking_ids': booking_ids, 'message': 'Already processed'}

        if locked_attempt.is_expired():
            locked_attempt.status = PaymentAttempt.STATUS_TIMEOUT
            locked_attempt.failure_reason = 'Payment arrived after timeout window.'
            locked_attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
            # Also release the locks since payment is expired
            release_seat_locks(locked_attempt, seat_ids=locked_attempt.seat_ids, reason='payment_expired')
            return {'ok': False, 'message': 'Payment session timed out. Retry booking.'}

        seats = list(
            Seat.objects.select_for_update().filter(
                theater=locked_attempt.theater,
                id__in=locked_attempt.seat_ids,
            )
        )
        if len(seats) != len(locked_attempt.seat_ids):
            locked_attempt.status = PaymentAttempt.STATUS_PARTIAL_FAILURE
            locked_attempt.failure_reason = 'Seat mismatch during verification.'
            locked_attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
            # Release locks on mismatched seats
            release_seat_locks(locked_attempt, seat_ids=locked_attempt.seat_ids, reason='seat_mismatch')
            return {'ok': False, 'message': 'Seat state changed, mark for manual review/refund.'}

        already_booked = [seat.seat_number for seat in seats if seat.is_booked]
        if already_booked:
            locked_attempt.status = PaymentAttempt.STATUS_PARTIAL_FAILURE
            locked_attempt.failure_reason = f'Seats already booked: {", ".join(already_booked)}'
            locked_attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
            # Release locks since we can't book
            release_seat_locks(locked_attempt, seat_ids=locked_attempt.seat_ids, reason='seats_already_booked')
            return {'ok': False, 'message': 'Some seats already booked, mark for manual review/refund.'}

        created_booking_ids = []
        final_payment_id = provider_payment_id or f'WEBHOOK-{uuid4().hex[:12].upper()}'
        for seat in seats:
            booking = Booking.objects.create(
                user=locked_attempt.user,
                seat=seat,
                movie=locked_attempt.movie,
                theater=locked_attempt.theater,
                payment_id=final_payment_id,
            )
            created_booking_ids.append(booking.id)
            seat.is_booked = True
            # RELEASE LOCK: Clear the reservation lock now that seat is permanently booked
            seat.is_locked = False
            seat.locked_at = None
            seat.locked_by_attempt = None
            seat.save(update_fields=['is_booked', 'is_locked', 'locked_at', 'locked_by_attempt'])

        locked_attempt.provider_payment_id = final_payment_id
        locked_attempt.provider_signature = provider_signature
        locked_attempt.status = PaymentAttempt.STATUS_SUCCESS
        locked_attempt.verified_at = timezone.now()
        locked_attempt.completed_at = timezone.now()
        locked_attempt.failure_reason = ''
        locked_attempt.save(
            update_fields=[
                'provider_payment_id',
                'provider_signature',
                'status',
                'verified_at',
                'completed_at',
                'failure_reason',
                'updated_at',
            ]
        )

    _send_booking_confirmation_async(created_booking_ids, attempt.user_id)
    payment_logger.info(
        'Payment finalized successfully',
        extra={'attempt': attempt.idempotency_key, 'source': source, 'booking_ids': created_booking_ids},
    )
    return {
        'ok': True,
        'already_processed': False,
        'booking_ids': created_booking_ids,
        'message': 'Payment verified and booking confirmed',
    }

def movie_list(request):
    # Get and validate filter parameters (convert to integers for ID-based filtering)
    selected_genres_param = request.GET.getlist('genre')
    selected_languages_param = request.GET.getlist('language')
    sort = request.GET.get('sort', 'rating_desc')
    limit = 10
    search_term = request.GET.get('search', '').strip()

    # Convert genre/language params to integers and validate
    selected_genres = []
    selected_languages = []
    
    try:
        selected_genres = [int(g) for g in selected_genres_param if g.isdigit()]
    except (ValueError, TypeError):
        pass
    
    try:
        selected_languages = [int(language_id) for language_id in selected_languages_param if language_id.isdigit()]
    except (ValueError, TypeError):
        pass

    # Start with base queryset without prefetch (apply later only to paginated results)
    movie_query = Movie.objects.all()

    # Apply search filter (indexed on Movie.name)
    if search_term:
        movie_query = movie_query.filter(name__icontains=search_term)

    # Apply genre filter (ID-based, avoids string matching overhead)
    if selected_genres:
        movie_query = movie_query.filter(genre__id__in=selected_genres)

    # Apply language filter (ID-based, avoids string matching overhead)
    if selected_languages:
        movie_query = movie_query.filter(language__id__in=selected_languages)

    # Apply distinct to avoid duplicate rows from M2M joins
    movie_query = movie_query.distinct()

    # Apply stable sorting (secondary sort by ID prevents inconsistent pagination)
    if sort == 'rating_desc':
        movie_query = movie_query.order_by('-rating', '-id')
    elif sort == 'date_desc':
        movie_query = movie_query.order_by('-id')
    else:  # name_asc
        movie_query = movie_query.order_by('name', 'id')

    # Paginate after all filters/sorts applied
    paginator = Paginator(movie_query, limit)
    page_number = request.GET.get('page', 1)
    movies = paginator.get_page(page_number)

    # Optimize: prefetch_related only for paginated results to reduce memory/queries
    movies.object_list = movies.object_list.prefetch_related('genre', 'language')

    # Calculate dynamic facet counts for genres (exclude genre filter, include others)
    genre_count_query = Movie.objects.all()
    if search_term:
        genre_count_query = genre_count_query.filter(name__icontains=search_term)
    if selected_languages:
        genre_count_query = genre_count_query.filter(language__id__in=selected_languages)
    
    genre_counts = {}
    for genre in Genre.objects.all().order_by('name'):
        count = genre_count_query.filter(genre__id=genre.id).distinct().count()
        genre_counts[genre.id] = count

    # Calculate dynamic facet counts for languages (exclude language filter, include others)
    language_count_query = Movie.objects.all()
    if search_term:
        language_count_query = language_count_query.filter(name__icontains=search_term)
    if selected_genres:
        language_count_query = language_count_query.filter(genre__id__in=selected_genres)
    
    language_counts = {}
    for language in Language.objects.all().order_by('name'):
        count = language_count_query.filter(language__id=language.id).distinct().count()
        language_counts[language.id] = count

    return render(
        request,
        'movies/movie_list.html',
        {
            'movies': movies,
            'all_genres': Genre.objects.all().order_by('name'),
            'all_languages': Language.objects.all().order_by('name'),
            'selected_genres': selected_genres,
            'selected_languages': selected_languages,
            'sort': sort,
            'search_term': search_term,
            'genre_counts': genre_counts,
            'language_counts': language_counts,
        })

def theater_list(request,movie_id):
    movie = get_object_or_404(Movie,id=movie_id)
    theater=Theater.objects.filter(movie=movie)
    return render(request,'movies/theater_list.html',{'movie':movie,'theaters':theater})



@login_required(login_url='/login/')
def book_seats(request,theater_id):
    theaters=get_object_or_404(Theater,id=theater_id)
    seats=Seat.objects.filter(theater=theaters)
    if request.method=='POST':
        selected_Seats= request.POST.getlist('seats')
        error_seats=[]
        created_booking_ids = []
        payment_id = f"PAY-{uuid4().hex[:12].upper()}"
        if not selected_Seats:
            return render(request,"movies/seat_selection.html",{'theaters':theaters,"seats":seats,'error':"No seat selected"})
        for seat_id in selected_Seats:
            seat=get_object_or_404(Seat,id=seat_id,theater=theaters)
            if seat.is_booked:
                error_seats.append(seat.seat_number)
                continue
            try:
                booking = Booking.objects.create(
                    user=request.user,
                    seat=seat,
                    movie=theaters.movie,
                    theater=theaters,
                    payment_id=payment_id,
                )
                created_booking_ids.append(booking.id)
                seat.is_booked=True
                seat.save()
            except IntegrityError:
                error_seats.append(seat.seat_number)
        if error_seats:
            error_message=f"The following seats are already booked: {', '.join(error_seats)}"
            return render(request,'movies/seat_selection.html',{'theaters':theaters,"seats":seats,'error':error_message})

        if created_booking_ids:
            try:
                # Send email asynchronously in background thread (non-blocking)
                bookings = Booking.objects.filter(id__in=created_booking_ids)
                thread = Thread(
                    target=send_booking_confirmation_email_message,
                    args=(bookings,),
                    daemon=True
                )
                thread.start()
            except Exception:
                logger.exception(
                    "Failed to send booking confirmation email",
                    extra={"user_id": request.user.id, "booking_ids": created_booking_ids},
                )

        return redirect('profile')
    return render(request,'movies/seat_selection.html',{'theaters':theaters,"seats":seats})


@login_required(login_url='/login/')
@require_POST
def create_payment_order(request, theater_id):
    """
    Create a payment order and atomically lock seats for 2 minutes.
    
    CONCURRENCY SAFETY:
    ===================
    This view uses transaction.atomic() and database-level row locking (select_for_update)
    to prevent double-booking even under simultaneous requests selecting the same seat.
    
    Race Condition Prevention Example:
      User A & B both select Seat 5 simultaneously (milliseconds apart)
      
      Without atomic + select_for_update:
        T1: A reads Seat 5 -> is_locked=False ✓
        T2: B reads Seat 5 -> is_locked=False ✓
        T1: A locks Seat 5 -> is_locked=True
        T2: B locks Seat 5 -> is_locked=True (RACE CONDITION!)
      
      With atomic + select_for_update:
        T1: A's txn gets exclusive lock on Seat 5 row
        T2: B's txn waits for lock release
        T1: A marks Seat 5 is_locked=True, commits, releases lock
        T2: B acquires lock, sees is_locked=True, rebounds with "unavailable"
    
    Edge Cases Handled:
      1. Idempotent re-calls: Same key returns same order (no duplicate lock)
      2. Expired seats: If a previous lock expired, seats can be re-selected
      3. Network failure: Transaction rolled back, locks released by cleanup job
    """
    theater = get_object_or_404(Theater, id=theater_id)
    selected_seat_ids = sorted({int(seat_id) for seat_id in request.POST.getlist('seats') if seat_id.isdigit()})
    idempotency_key = request.POST.get('idempotency_key', '').strip() or uuid4().hex

    if not selected_seat_ids:
        return JsonResponse({'ok': False, 'message': 'No seats selected'}, status=400)

    selected_seats = list(Seat.objects.filter(theater=theater, id__in=selected_seat_ids).order_by('id'))
    if len(selected_seats) != len(selected_seat_ids):
        return JsonResponse({'ok': False, 'message': 'Invalid seat selection'}, status=400)

    # Check for already booked seats (not part of the atomic lock operation)
    already_booked = [seat.seat_number for seat in selected_seats if seat.is_booked]
    if already_booked:
        return JsonResponse(
            {'ok': False, 'message': f"Seats already booked: {', '.join(already_booked)}"},
            status=409,
        )

    amount_paise = len(selected_seats) * SEAT_PRICE_INR * 100
    expires_at = timezone.now() + timedelta(minutes=PAYMENT_TIMEOUT_MINUTES)

    defaults = {
        'user': request.user,
        'movie': theater.movie,
        'theater': theater,
        'amount_paise': amount_paise,
        'currency': 'INR',
        'status': PaymentAttempt.STATUS_INITIATED,
        'seat_ids': [seat.id for seat in selected_seats],
        'seat_numbers': [seat.seat_number for seat in selected_seats],
        'expires_at': expires_at,
    }

    try:
        attempt, created = PaymentAttempt.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults=defaults,
        )
    except IntegrityError:
        attempt = PaymentAttempt.objects.get(idempotency_key=idempotency_key)
        created = False

    if not created:
        if attempt.user_id != request.user.id:
            return JsonResponse({'ok': False, 'message': 'Invalid idempotency key for this user'}, status=403)
        if attempt.status == PaymentAttempt.STATUS_SUCCESS:
            return JsonResponse({'ok': True, 'already_processed': True, 'redirect_url': '/profile/'})
        if attempt.seat_ids != defaults['seat_ids']:
            return JsonResponse({'ok': False, 'message': 'Idempotency key reused for different seats'}, status=409)
        if attempt.is_expired():
            attempt.status = PaymentAttempt.STATUS_TIMEOUT
            attempt.failure_reason = 'Payment order request exceeded timeout window.'
            attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
            return JsonResponse({'ok': False, 'message': 'Payment session timed out, retry with new key'}, status=408)
        
        # IDEMPOTENT LOCK: If this is a retry with same key, seats may already be locked from first call
        # Check if seats are already locked by this attempt
        locked_by_this_attempt = Seat.objects.filter(
            locked_by_attempt=attempt,
            id__in=selected_seat_ids
        ).count()
        if locked_by_this_attempt == len(selected_seat_ids):
            # All seats already locked from previous call - return cached order
            return JsonResponse({
                'ok': True,
                'idempotency_key': attempt.idempotency_key,
                'order_id': attempt.provider_order_id,
                'amount': attempt.amount_paise,
                'currency': attempt.currency,
                'seat_numbers': attempt.seat_numbers,
                'razorpay_key_id': getattr(settings, 'RAZORPAY_KEY_ID', ''),
                'timeout_minutes': PAYMENT_TIMEOUT_MINUTES,
            })

    # ATOMIC SEAT LOCKING: Hold seats in database transaction with row-level locks
    # ======================
    # This ensures:
    # 1. All seats are locked together (all-or-nothing)
    # 2. No concurrent transaction can modify these seat rows
    # 3. On network failure/app crash, transaction rolls back and locks auto-release
    try:
        with transaction.atomic():
            held_seats, unavailable = hold_seats_for_payment(
                payment_attempt=attempt,
                theater=theater,
                seat_ids=selected_seat_ids,
                timeout_seconds=SEAT_LOCK_TIMEOUT_SECONDS
            )
            
            if unavailable:
                return JsonResponse(
                    {
                        'ok': False,
                        'message': f"Seats unavailable: {', '.join(unavailable)}. Some may be locked or booked.",
                        'unavailable_seats': unavailable
                    },
                    status=409,
                )
            
            if not held_seats or len(held_seats) != len(selected_seat_ids):
                return JsonResponse(
                    {
                        'ok': False,
                        'message': 'Could not acquire lock on all selected seats',
                    },
                    status=409,
                )
    except Exception as e:
        payment_logger.exception('Error holding seats for payment', extra={'attempt_id': attempt.id})
        return JsonResponse({'ok': False, 'message': 'Error reserving seats'}, status=500)

    # Create Razorpay order if not already created
    if not attempt.provider_order_id:
        try:
            client = _create_razorpay_client()
            order_data = {
                'amount': attempt.amount_paise,
                'currency': attempt.currency,
                'receipt': attempt.idempotency_key[:40],
                'notes': {
                    'idempotency_key': attempt.idempotency_key,
                    'user_id': str(request.user.id),
                    'theater_id': str(theater.id),
                },
            }
            order = client.order.create(order_data)
            attempt.provider_order_id = order.get('id')
            attempt.status = PaymentAttempt.STATUS_PENDING
            attempt.save(update_fields=['provider_order_id', 'status', 'updated_at'])
        except Exception:
            # If Razorpay order creation fails, release the seat locks
            with transaction.atomic():
                release_seat_locks(attempt, seat_ids=selected_seat_ids, reason='razorpay_order_creation_failed')
            payment_logger.exception('Failed to create Razorpay order', extra={'theater_id': theater.id})
            return JsonResponse({'ok': False, 'message': 'Failed to create payment order'}, status=502)

    return JsonResponse(
        {
            'ok': True,
            'idempotency_key': attempt.idempotency_key,
            'order_id': attempt.provider_order_id,
            'amount': attempt.amount_paise,
            'currency': attempt.currency,
            'seat_numbers': attempt.seat_numbers,
            'razorpay_key_id': getattr(settings, 'RAZORPAY_KEY_ID', ''),
            'timeout_minutes': PAYMENT_TIMEOUT_MINUTES,
            'seats_locked_until_seconds': SEAT_LOCK_TIMEOUT_SECONDS,
        }
    )


@login_required(login_url='/login/')
@require_POST
def verify_payment(request):
    idempotency_key = request.POST.get('idempotency_key', '').strip()
    order_id = request.POST.get('razorpay_order_id', '').strip()
    payment_id = request.POST.get('razorpay_payment_id', '').strip()
    signature = request.POST.get('razorpay_signature', '').strip()

    if not all([idempotency_key, order_id, payment_id, signature]):
        return JsonResponse({'ok': False, 'message': 'Missing verification fields'}, status=400)

    attempt = get_object_or_404(PaymentAttempt, idempotency_key=idempotency_key, user=request.user)
    if attempt.is_expired() and attempt.status != PaymentAttempt.STATUS_SUCCESS:
        attempt.status = PaymentAttempt.STATUS_TIMEOUT
        attempt.failure_reason = 'Verification attempted after timeout.'
        attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
        return JsonResponse({'ok': False, 'message': 'Payment session timed out'}, status=408)

    if attempt.provider_order_id != order_id:
        attempt.status = PaymentAttempt.STATUS_FAILED
        attempt.failure_reason = 'Order mismatch during verification.'
        attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
        payment_logger.error('Order mismatch in verify endpoint', extra={'attempt': idempotency_key})
        return JsonResponse({'ok': False, 'message': 'Order mismatch'}, status=400)

    if not verify_razorpay_payment_signature(order_id, payment_id, signature, getattr(settings, 'RAZORPAY_KEY_SECRET', '')):
        attempt.status = PaymentAttempt.STATUS_FAILED
        attempt.failure_reason = 'Signature verification failed.'
        attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
        payment_logger.error('Payment signature verification failed', extra={'attempt': idempotency_key})
        return JsonResponse({'ok': False, 'message': 'Invalid signature'}, status=400)

    try:
        client = _create_razorpay_client()
        payment_data = client.payment.fetch(payment_id)
    except Exception:
        payment_logger.exception('Failed to fetch payment details from Razorpay', extra={'payment_id': payment_id})
        return JsonResponse({'ok': False, 'message': 'Provider verification failed'}, status=502)

    if payment_data.get('order_id') != order_id or payment_data.get('amount') != attempt.amount_paise:
        attempt.status = PaymentAttempt.STATUS_FAILED
        attempt.failure_reason = 'Gateway payload mismatch.'
        attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
        return JsonResponse({'ok': False, 'message': 'Payment details mismatch'}, status=400)

    if payment_data.get('status') not in {'captured', 'authorized'}:
        attempt.status = PaymentAttempt.STATUS_FAILED
        attempt.failure_reason = f"Gateway payment status: {payment_data.get('status')}"
        attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
        return JsonResponse({'ok': False, 'message': 'Payment not successful'}, status=400)

    result = _finalize_verified_payment(attempt, payment_id, signature, source='verify-endpoint')
    if not result['ok']:
        return JsonResponse(result, status=409)

    return JsonResponse(
        {
            'ok': True,
            'already_processed': result['already_processed'],
            'booking_ids': result['booking_ids'],
            'redirect_url': '/profile/',
            'message': result['message'],
        }
    )


@login_required(login_url='/login/')
@require_POST
def payment_failure(request):
    """
    Record a payment failure and release all seat locks.
    
    LOCK RELEASE:
    =============
    When payment fails or is cancelled by user, release all seat locks
    so other users can select and book them immediately.
    """
    idempotency_key = request.POST.get('idempotency_key', '').strip()
    status_hint = request.POST.get('status', '').strip().lower()
    reason = request.POST.get('reason', '').strip() or 'Payment failed or cancelled by user'

    if not idempotency_key:
        return JsonResponse({'ok': False, 'message': 'idempotency_key is required'}, status=400)

    attempt = get_object_or_404(PaymentAttempt, idempotency_key=idempotency_key, user=request.user)
    if attempt.status == PaymentAttempt.STATUS_SUCCESS:
        return JsonResponse({'ok': True, 'message': 'Payment already succeeded'})

    new_status = PaymentAttempt.STATUS_CANCELLED if status_hint == 'cancelled' else PaymentAttempt.STATUS_FAILED
    if attempt.is_expired():
        new_status = PaymentAttempt.STATUS_TIMEOUT

    with transaction.atomic():
        attempt.status = new_status
        attempt.failure_reason = reason
        attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
        
        # RELEASE LOCKS: Allow other users to book these seats immediately
        released_count = release_seat_locks(
            attempt,
            seat_ids=attempt.seat_ids,
            reason=f'payment_{new_status}'
        )
    
    payment_logger.warning(
        'Payment marked unsuccessful and locks released',
        extra={'attempt': idempotency_key, 'status': new_status, 'seats_released': released_count}
    )

    return JsonResponse({'ok': True, 'message': 'Failure/cancellation recorded'})


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    payload_bytes = request.body
    signature = request.headers.get('X-Razorpay-Signature', '')

    try:
        payload = json.loads(payload_bytes.decode('utf-8'))
    except Exception:
        payment_logger.error('Invalid webhook payload JSON')
        return HttpResponse('Invalid payload', status=400)

    event_type = payload.get('event', 'unknown')
    event_id = request.headers.get('X-Razorpay-Event-Id') or f'body-{sha256_hex(payload_bytes)}'
    payload_hash = sha256_hex(payload_bytes)

    webhook_event, created = PaymentWebhookEvent.objects.get_or_create(
        event_id=event_id,
        defaults={
            'provider': 'razorpay',
            'event_type': event_type,
            'payload_hash': payload_hash,
            'signature_valid': False,
            'processed': False,
        },
    )

    if not created:
        payment_logger.info('Duplicate webhook ignored', extra={'event_id': event_id})
        return HttpResponse('Duplicate event ignored', status=200)

    secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')
    if not verify_razorpay_webhook_signature(payload_bytes, signature, secret):
        webhook_event.signature_valid = False
        webhook_event.processed = True
        webhook_event.processed_at = timezone.now()
        webhook_event.save(update_fields=['signature_valid', 'processed', 'processed_at'])
        payment_logger.error('Invalid webhook signature', extra={'event_id': event_id})
        return HttpResponse('Invalid signature', status=400)

    webhook_event.signature_valid = True

    payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
    provider_order_id = payment_entity.get('order_id', '')
    provider_payment_id = payment_entity.get('id', '')

    attempt = None
    if provider_order_id:
        attempt = PaymentAttempt.objects.filter(provider_order_id=provider_order_id).first()

    if attempt:
        if event_type in {'payment.captured', 'payment.authorized', 'order.paid'}:
            _finalize_verified_payment(
                attempt,
                provider_payment_id=provider_payment_id,
                provider_signature=f'webhook:{signature}',
                source='webhook',
            )
        elif event_type in {'payment.failed'} and attempt.status != PaymentAttempt.STATUS_SUCCESS:
            with transaction.atomic():
                attempt.status = PaymentAttempt.STATUS_FAILED
                attempt.failure_reason = 'Gateway reported payment failure via webhook.'
                attempt.save(update_fields=['status', 'failure_reason', 'updated_at'])
                # RELEASE LOCKS: Payment failed, unlock seats for other users
                release_seat_locks(attempt, seat_ids=attempt.seat_ids, reason='webhook_payment_failed')

    webhook_event.processed = True
    webhook_event.processed_at = timezone.now()
    webhook_event.save(update_fields=['signature_valid', 'processed', 'processed_at'])
    return HttpResponse('ok', status=200)


@login_required(login_url='/login/')
@require_GET
def admin_analytics_dashboard(request):
    """
    Secure analytics dashboard for admin/staff users only.

    Security:
    - Enforces authentication and explicit staff checks to prevent privilege escalation.
    - Returns HTTP 403 for unauthorized access, including API-style JSON requests.

    Performance:
    - Uses database-side aggregation/annotation for all heavy analytics.
    - Caches computed analytics for short TTL to avoid recalculating on every request.
    """
    if not request.user.is_active or not request.user.is_staff:
        wants_json = request.GET.get('format') == 'json' or 'application/json' in request.headers.get('Accept', '')
        if wants_json:
            return JsonResponse({'ok': False, 'detail': 'Forbidden'}, status=403)
        return HttpResponse('Forbidden', status=403)

    cache_timeout = int(getattr(settings, 'ADMIN_ANALYTICS_CACHE_TTL', 90))
    cache_timeout = max(60, min(120, cache_timeout))
    cache_key = 'movies:admin_dashboard:v1'
    cached = cache.get(cache_key)

    if cached:
        if request.GET.get('format') == 'json' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse(cached)
        return render(request, 'movies/admin_dashboard.html', {'analytics': cached})

    now = timezone.now()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_week = start_of_day - timedelta(days=start_of_day.weekday())
    start_of_month = start_of_day.replace(day=1)

    booking_field_names = {field.name for field in Booking._meta.fields}
    has_price_field = 'price' in booking_field_names
    has_status_field = 'status' in booking_field_names
    booking_time_field = 'created_at' if 'created_at' in booking_field_names else 'booked_at'

    # Revenue is aggregated in DB; fallback to successful PaymentAttempt totals when Booking.price is unavailable.
    if has_price_field:
        revenue_daily = Booking.objects.filter(**{f'{booking_time_field}__gte': start_of_day}).aggregate(
            total=Coalesce(Sum('price'), Value(0))
        )['total']
        revenue_weekly = Booking.objects.filter(**{f'{booking_time_field}__gte': start_of_week}).aggregate(
            total=Coalesce(Sum('price'), Value(0))
        )['total']
        revenue_monthly = Booking.objects.filter(**{f'{booking_time_field}__gte': start_of_month}).aggregate(
            total=Coalesce(Sum('price'), Value(0))
        )['total']
    else:
        successful_attempts = PaymentAttempt.objects.filter(status=PaymentAttempt.STATUS_SUCCESS)
        daily_paise = successful_attempts.filter(completed_at__gte=start_of_day).aggregate(
            total=Coalesce(Sum('amount_paise'), Value(0))
        )['total']
        weekly_paise = successful_attempts.filter(completed_at__gte=start_of_week).aggregate(
            total=Coalesce(Sum('amount_paise'), Value(0))
        )['total']
        monthly_paise = successful_attempts.filter(completed_at__gte=start_of_month).aggregate(
            total=Coalesce(Sum('amount_paise'), Value(0))
        )['total']
        revenue_daily = round((daily_paise or 0) / 100, 2)
        revenue_weekly = round((weekly_paise or 0) / 100, 2)
        revenue_monthly = round((monthly_paise or 0) / 100, 2)

    # Popular movies by booking volume (DB grouping, no Python-side iteration over records).
    popular_movies = list(
        Booking.objects.values('movie_id', 'movie__name')
        .annotate(total_bookings=Count('id'))
        .order_by('-total_bookings', 'movie__name')[:10]
    )

    # Busiest theaters by occupancy percentage: booked seats / total seats.
    busiest_theaters = list(
        Theater.objects.annotate(
            total_seats=Count('seats', distinct=True),
            booked_seats=Count('seats', filter=Q(seats__is_booked=True), distinct=True),
        )
        .annotate(
            occupancy_rate=Case(
                When(total_seats=0, then=Value(0.0)),
                default=(100.0 * F('booked_seats') / F('total_seats')),
                output_field=FloatField(),
            )
        )
        .values('id', 'name', 'total_seats', 'booked_seats', 'occupancy_rate')
        .order_by('-occupancy_rate', '-booked_seats', 'name')[:10]
    )

    # Peak booking hours (0-23) using DB-side hour extraction and count aggregation.
    peak_booking_hours = list(
        Booking.objects.annotate(hour=ExtractHour(booking_time_field))
        .values('hour')
        .annotate(total_bookings=Count('id'))
        .order_by('-total_bookings', 'hour')[:6]
    )

    cancellation_rate = None
    if has_status_field:
        status_agg = Booking.objects.aggregate(
            total=Count('id'),
            cancelled=Count('id', filter=Q(status__iexact='cancelled')),
        )
        total = status_agg['total'] or 0
        cancelled = status_agg['cancelled'] or 0
        cancellation_rate = round((cancelled / total) * 100, 2) if total else 0.0

    analytics = {
        'generated_at': now.isoformat(),
        'revenue': {
            'daily': revenue_daily,
            'weekly': revenue_weekly,
            'monthly': revenue_monthly,
        },
        'popular_movies': popular_movies,
        'busiest_theaters': busiest_theaters,
        'peak_booking_hours': peak_booking_hours,
        'cancellation_rate': cancellation_rate,
        'cache_ttl_seconds': cache_timeout,
    }

    cache.set(cache_key, analytics, timeout=cache_timeout)

    if request.GET.get('format') == 'json' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse(analytics)
    return render(request, 'movies/admin_dashboard.html', {'analytics': analytics})




