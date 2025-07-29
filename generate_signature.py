import hmac
import hashlib
import json
import os

# Set your NOWPAYMENTS_IPN_SECRET here
IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET", "your_secret_here")

# Example payload
payload = {
    "payment_status": "confirmed",
    "order_id": "testuser:tier1"
}

raw_body = json.dumps(payload, separators=(',', ':')).encode()
signature = hmac.new(IPN_SECRET.encode(), raw_body, hashlib.sha512).hexdigest()

print("Payload:", json.dumps(payload))
print("Signature:", signature)

