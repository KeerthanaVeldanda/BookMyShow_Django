import logging
from typing import Iterable

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Booking


logger = logging.getLogger("movies.email")


def build_booking_email_context(bookings: Iterable[Booking]) -> dict:
    bookings = list(bookings)
    first_booking = bookings[0]
    return {
        "username": first_booking.user.username,
        "movie_name": first_booking.movie.name,
        "theater_name": first_booking.theater.name,
        "show_time": timezone.localtime(first_booking.theater.time),
        "seat_numbers": [booking.seat.seat_number for booking in bookings],
        "payment_id": first_booking.payment_id,
        "booked_at": timezone.localtime(first_booking.booked_at),
        "booking_ids": [booking.id for booking in bookings],
    }


def send_booking_confirmation_email_message(bookings: Iterable[Booking]) -> None:
    """Render and send booking confirmation email using Django templates."""
    bookings = list(bookings)
    if not bookings:
        raise ValueError("Cannot send booking email without bookings")

    context = build_booking_email_context(bookings)
    recipient_email = bookings[0].user.email

    if not recipient_email:
        raise ValueError("User email is missing")

    subject = f"Booking Confirmed: {context['movie_name']}"
    text_body = render_to_string("emails/booking_confirmation.txt", context)
    html_body = render_to_string("emails/booking_confirmation.html", context)

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient_email],
    )
    email.attach_alternative(html_body, "text/html")
    email.send(fail_silently=False)
