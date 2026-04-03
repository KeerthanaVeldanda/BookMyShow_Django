# Payment Lifecycle (Razorpay)

## 1) Order Creation
- Client sends selected seats + `idempotency_key` to `POST /movies/theater/<theater_id>/payments/order/`.
- Server validates seat availability and creates/reuses `PaymentAttempt`.
- Server creates Razorpay order and returns only safe public fields (`order_id`, amount, currency, key_id).

## 2) Payment Completion and Verification
- Client receives Razorpay callback data (`razorpay_order_id`, `razorpay_payment_id`, `razorpay_signature`).
- Client calls `POST /movies/payments/verify/`.
- Server verifies HMAC signature and fetches payment from Razorpay API.
- Booking is created only after server-side verification succeeds.

## 3) Idempotency and Duplicate Protection
- `PaymentAttempt.idempotency_key` is unique.
- Duplicate order requests with same key do not create new payment attempts.
- Verification uses row locking (`select_for_update`) to avoid race-based double booking.
- If a payment attempt is already `success`, duplicate callbacks return safely without creating duplicate bookings.

## 4) Webhook Security and Replay Defense
- Endpoint: `POST /movies/payments/webhook/razorpay/`.
- Server validates `X-Razorpay-Signature` using `RAZORPAY_WEBHOOK_SECRET`.
- Duplicate/retried events are ignored via unique `PaymentWebhookEvent.event_id`.
- Payload hash is stored for audit and replay diagnostics.

## 5) Failure Handling
- Failure/cancel endpoint: `POST /movies/payments/failure/`.
- Status transitions: `failed`, `cancelled`, `timeout`, `partial_failure`.
- Timeout window is enforced using `expires_at`; retries use a new idempotency key.
- Partial failures are recorded for manual refund/reconciliation.

## 6) Fraud Prevention Summary
- No trust in frontend success alone.
- Signature checks for both checkout callback and webhook payload.
- Gateway fetch cross-checks amount and order_id.
- Secrets remain in environment variables only, never returned to frontend.
