import logging

from celery import shared_task

from .models import Booking
from .utils import send_booking_confirmation_email_message
from .reservations import release_all_expired_locks


logger = logging.getLogger("movies.email")
reservation_logger = logging.getLogger("movies.reservations")


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_booking_confirmation_email(self, booking_ids):
    """Send booking confirmation email in the background with retries."""
    bookings = list(
        Booking.objects.select_related("user", "movie", "theater", "seat")
        .filter(id__in=booking_ids)
        .order_by("seat__seat_number")
    )

    if not bookings:
        logger.warning("No bookings found for confirmation email", extra={"booking_ids": booking_ids})
        return

    first_booking = bookings[0]
    user = first_booking.user

    if not user.email:
        logger.warning("User email missing, skipping confirmation email", extra={"user_id": user.id})
        return

    try:
        send_booking_confirmation_email_message(bookings)
        logger.info("Booking confirmation email sent", extra={"user_id": user.id, "booking_ids": booking_ids})
    except Exception as exc:
        logger.exception(
            "Booking confirmation email delivery failed",
            extra={"user_id": user.id, "booking_ids": booking_ids, "retry": self.request.retries},
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)
        logger.error(
            "Booking confirmation email permanently failed after retries",
            extra={"user_id": user.id, "booking_ids": booking_ids},
        )


@shared_task(bind=True, default_retry_delay=60)
def release_expired_seat_locks_task(self):
    """
    Periodic background task to automatically release expired seat locks.
    
    Schedule: Run every 1 minute via Celery Beat
    
    Purpose: Ensure seats temporarily locked during payment are made available
    if the user closes the app, network fails, or payment stalls.
    
    Edge Cases Handled:
    ===================
    1. User closes booking app during payment
       -> Seat stays locked for 2 minutes
       -> This task releases it automatically
       
    2. Network interruption during payment
       -> Transaction rolls back, lock persists (not yet committed)
       -> Actually: lock _is_ committed if we made it to hold_seats_for_payment()
       -> But payment verification fails
       -> This task releases it after 2 min
       
    3. Multiple tabs/devices with same user
       -> Each gets a different PaymentAttempt
       -> Only that attempt's held seats are released
       -> Other tabs can continue normally
    
    Returns:
        Count of seats auto-released
    """
    try:
        released_count = release_all_expired_locks()
        if released_count > 0:
            reservation_logger.info(f"Auto-released {released_count} expired seat locks")
        return released_count
    except Exception as exc:
        reservation_logger.exception("Error releasing expired seat locks")
        # Retry after delay
        raise self.retry(exc=exc, countdown=60)

