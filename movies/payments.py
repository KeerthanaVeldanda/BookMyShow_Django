import hashlib
import hmac


def generate_razorpay_payment_signature(order_id, payment_id, secret):
    payload = f"{order_id}|{payment_id}".encode('utf-8')
    return hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()


def verify_razorpay_payment_signature(order_id, payment_id, signature, secret):
    if not (order_id and payment_id and signature and secret):
        return False
    expected = generate_razorpay_payment_signature(order_id, payment_id, secret)
    return hmac.compare_digest(expected, signature)


def verify_razorpay_webhook_signature(payload_bytes, signature, secret):
    if not (payload_bytes and signature and secret):
        return False
    expected = hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def sha256_hex(payload_bytes):
    return hashlib.sha256(payload_bytes).hexdigest()
