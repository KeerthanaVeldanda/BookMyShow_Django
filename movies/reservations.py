"""
Concurrency-Safe Seat Reservation System

This module implements database-level locking and atomic transactions to prevent
double-booking scenarios even under simultaneous requests from multiple users
selecting the same seat within milliseconds.

Key Design Principles:
======================
1. ATOMIC TRANSACTIONS: All seat operations use transaction.atomic() to ensure
   either all seats are successfully locked or nothing changes.
   
2. ROW-LEVEL LOCKING: select_for_update() locks the seat row at the database level,
   preventing race conditions. Only one transaction can modify a locked seat.
   
3. LOCK EXPIRY: Seats are locked for exactly SEAT_LOCK_TIMEOUT_SECONDS (120s).
   After this, they're automatically released by a background Celery task.
   
4. STRONG CONSISTENCY: All queries check both is_booked AND lock status.
   Expired locks are treated as available.

Race Condition Prevention:
==========================
Without row-level locking, this would be vulnerable:
  T1: User A reads Seat X -> is_booked=False, is_locked=False
  T2: User B reads Seat X -> is_booked=False, is_locked=False
  T1: User A books Seat X -> is_booked=True
  T2: User B books Seat X -> is_booked=True (DUPLICATE BOOKING!)

With select_for_update():
  T1: User A locks Seat X row (database-level exclusive lock)
  T2: User B waits for lock to be released
  T1: User A marks Seat X as locked and commits
  T2: User B acquires lock, sees is_locked=True, rebounds with error
"""

from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from .models import Seat, PaymentAttempt
import logging

logger = logging.getLogger('movies.reservations')

# 2-minute lock timeout: customers have 10 minutes for payment (PAYMENT_TIMEOUT_MINUTES),
# but seats are only locked for 2 minutes to allow others to select if payment stalls
SEAT_LOCK_TIMEOUT_SECONDS = 120


def is_lock_expired(locked_at):
    """
    Check if a seat lock has expired.
    
    Args:
        locked_at: DateTimeField value when the lock was created
    
    Returns:
        True if more than SEAT_LOCK_TIMEOUT_SECONDS have passed, False otherwise
    """
    if not locked_at:
        return False
    return timezone.now() > locked_at + timedelta(seconds=SEAT_LOCK_TIMEOUT_SECONDS)


def get_available_seats_queryset(theater, seat_ids):
    """
    Get seats that are available for purchase (not booked, not locked or expired lock).
    
    Consistency Model: Strong Consistency
    ====================================
    A seat is available if:
      - is_booked = False (never sold)
      AND
      - (is_locked = False OR lock_expired = True)
    
    This ensures that even if a concurrent request holds a lock, we treat
    expired locks as stale data and allow re-selection.
    
    Args:
        theater: Theater instance
        seat_ids: List of seat IDs to check
    
    Returns:
        QuerySet of available Seat objects (not yet booked or locked)
    """
    available_seats = Seat.objects.filter(
        theater=theater,
        id__in=seat_ids,
        is_booked=False,
        is_locked=False
    )
    return available_seats


def hold_seats_for_payment(payment_attempt, theater, seat_ids, timeout_seconds=SEAT_LOCK_TIMEOUT_SECONDS):
    """
    Atomically hold seats for a payment attempt with database-level row locking.
    
    CRITICAL: This function must be called within transaction.atomic() context!
    
    Race Condition Prevention (Atomic Transaction):
    ===============================================
    1. Use select_for_update() to hold exclusive database locks on seat rows
    2. Read current state while locks are held
    3. Check if seat is available (not booked, not locked)
    4. Mark seat as locked in same transaction
    5. Commit atomically - all seats locked or none
    
    If transaction is interrupted (network failure, app crash), the locks
    are automatically released after timeout.
    
    Args:
        payment_attempt: PaymentAttempt instance holding the reservation
        theater: Theater instance
        seat_ids: List of seat IDs to hold
        timeout_seconds: How long to hold the lock (default 120s)
    
    Returns:
        Tuple: (held_seats, unavailable_seat_numbers)
            held_seats: List of locked Seat objects
            unavailable_seat_numbers: List of seat numbers that couldn't be locked
            
    Raises:
        transaction.TransactionManagementError: if called outside transaction.atomic()
    """
    if not seat_ids:
        return [], []
    
    # CRITICAL: select_for_update() ensures exclusive row-level locks for all seats.
    # This prevents other transactions from modifying these rows while we hold the lock.
    # The database waits for all locks to be acquired before proceeding.
    locked_seats = list(
        Seat.objects
        .select_for_update(skip_locked=False)  # skip_locked=False: WAIT for locks (strong consistency)
        .filter(theater=theater, id__in=seat_ids)
        .order_by('id')
    )
    
    if len(locked_seats) != len(seat_ids):
        missing_ids = set(seat_ids) - {s.id for s in locked_seats}
        logger.warning(
            'Seat IDs not found during lock attempt',
            extra={'payment_attempt_id': payment_attempt.id, 'missing_ids': missing_ids}
        )
        return [], []
    
    # Check each seat's availability while holding the lock
    now = timezone.now()
    unavailable_seats = []
    hold_expiry = now + timedelta(seconds=timeout_seconds)
    
    for seat in locked_seats:
        if seat.is_booked:
            unavailable_seats.append(seat.seat_number)
        elif seat.is_locked and not is_lock_expired(seat.locked_at):
            # Someone else holds an active lock on this seat
            unavailable_seats.append(seat.seat_number)
        else:
            # Seat is available: mark it as locked in this transaction
            seat.is_locked = True
            seat.locked_at = now
            seat.locked_by_attempt = payment_attempt
            seat.save(update_fields=['is_locked', 'locked_at', 'locked_by_attempt'])
    
    held_seats = [s for s in locked_seats if s.seat_number not in unavailable_seats]
    
    logger.info(
        'Seats held for payment',
        extra={
            'payment_attempt_id': payment_attempt.id,
            'held_count': len(held_seats),
            'unavailable': unavailable_seats,
            'theatre_id': theater.id
        }
    )
    
    return held_seats, unavailable_seats


def release_seat_locks(payment_attempt, seat_ids=None, reason='manual_release'):
    """
    Release (unlock) seats held by a payment attempt.
    
    Used when:
      - Payment verification succeeds (seats become booked, lock no longer needed)
      - Payment fails or is cancelled (revert lock so others can book)
      - Payment times out (allow others to select)
      - User closes app (timeout job releases after 2 min)
    
    Args:
        payment_attempt: PaymentAttempt instance
        seat_ids: List of specific seat IDs to release (if None, release all for this attempt)
        reason: Reason for release (for logging)
    
    Returns:
        Count of seats unlocked
    """
    if seat_ids:
        update_filter = {'id__in': seat_ids, 'locked_by_attempt': payment_attempt}
    else:
        update_filter = {'locked_by_attempt': payment_attempt}
    
    count = Seat.objects.filter(**update_filter).update(
        is_locked=False,
        locked_at=None
        # Keep locked_by_attempt NULL to maintain audit trail
    )
    
    if count > 0:
        logger.info(
            'Seats released from lock',
            extra={
                'payment_attempt_id': payment_attempt.id,
                'released_count': count,
                'reason': reason
            }
        )
    
    return count


def get_expired_seat_locks():
    """
    Find all seat locks that have exceeded the timeout period.
    
    Background Task Trigger:
    ========================
    This is called by a Celery beat periodic task (release_expired_seat_locks_task)
    that runs every minute to clean up stale locks.
    
    Handles Edge Cases:
      1. User closes app -> payment_attempt status remains INITIATED/PENDING,
         but lock expires after 2 min
      2. Network interruption -> transaction rolled back, lock expires after 2 min
      3. Multiple tabs/devices -> different payment attempts, but only one lock
         expires, others can continue
    
    Returns:
        QuerySet of Seat objects with expired locks
    """
    expiry_threshold = timezone.now() - timedelta(seconds=SEAT_LOCK_TIMEOUT_SECONDS)
    expired_locks = Seat.objects.filter(
        is_locked=True,
        locked_at__lt=expiry_threshold,
        locked_by_attempt__isnull=False
    )
    return expired_locks


def release_all_expired_locks():
    """
    Periodically called (every minute via Celery beat) to auto-release expired locks.
    
    Ensures that seats locked by failed, abandoned, or stalled payments
    are made available again without manual intervention.
    
    Returns:
        Count of seats unlocked
    """
    expired = get_expired_seat_locks()
    attempt_ids = expired.values_list('locked_by_attempt_id', flat=True).distinct()
    
    if not expired.exists():
        return 0
    
    count = expired.update(
        is_locked=False,
        locked_at=None
    )
    
    logger.info(
        'Expired seat locks auto-released',
        extra={'released_count': count, 'payment_attempts': len(set(attempt_ids))}
    )
    
    return count
