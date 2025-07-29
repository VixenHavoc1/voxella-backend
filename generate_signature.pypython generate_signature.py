import hmac
import hashlib
import json

# Replace with your actual NowPayments IPN secret (from your .env)
secret = "your_nowpayments_ipn_secret"

# Simulated webhook payload (change user123/tier2 if needed)
payload = {
    "payment_status": "confirmed",
    "order_id": "user123:tier2"
}

# Convert payload to JSON string and encode it
raw_body = json.dumps(payload).encode()

# Generate HMAC SHA512 signature
signature = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()

# Output everything you need for the test
print("Use this signature in the 'x-nowpayments-sig' header:\n")
print(signature)
print("\nUse this JSON payload as the body:\n")
print(json.dumps(payload, indent=2))


