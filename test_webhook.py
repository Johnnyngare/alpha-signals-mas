# test_webhook.py
"""
Simulates a Flutterwave successful payment webhook.
Run this after starting webhook.py and ngrok.
"""

import json
import sqlite3
import urllib.request

WEBHOOK_URL          = "http://localhost:8080/webhook/payment"
FLUTTERWAVE_SECRET   = "alphasignals_webhook_secret_2026"
TEST_PHONE           = "254712345678"
TEST_AMOUNT          = 3500.0
TEST_GATEWAY_REF     = "FLW-TEST-REF-001"

payload = {
    "event": "charge.completed",
    "data": {
        "id":     TEST_GATEWAY_REF,
        "status": "successful",
        "amount": TEST_AMOUNT,
        "currency": "KES",
        "customer": {
            "name":         "Test Subscriber",
            "email":        "test@alphasignals.com",
            "phone_number": TEST_PHONE,
        },
        "payment_type": "mobilemoneyghana",
    }
}

body    = json.dumps(payload).encode("utf-8")
request = urllib.request.Request(
    WEBHOOK_URL,
    data=body,
    headers={
        "Content-Type":   "application/json",
        "Content-Length": str(len(body)),
        "verif-hash":     FLUTTERWAVE_SECRET,
    },
    method="POST"
)

print(f"Sending test webhook to {WEBHOOK_URL}")
print(f"Phone:  {TEST_PHONE}")
print(f"Amount: KES {TEST_AMOUNT}")
print(f"Ref:    {TEST_GATEWAY_REF}")
print()

try:
    with urllib.request.urlopen(request, timeout=10) as response:
        print(f"Response status: {response.status}")
        print("Webhook accepted successfully.")
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code} {e.reason}")
except Exception as e:
    print(f"Error: {e}")

print()
print("Checking database...")

try:
    conn = sqlite3.connect("data/alpha_signals.db")
    conn.row_factory = sqlite3.Row

    subscriber = conn.execute(
        "SELECT * FROM subscribers WHERE phone = ?",
        (TEST_PHONE,)
    ).fetchone()

    payment = conn.execute(
        "SELECT * FROM payments WHERE gateway_ref = ?",
        (TEST_GATEWAY_REF,)
    ).fetchone()

    conn.close()

    if subscriber:
        print(f"SUBSCRIBER RECORD FOUND:")
        print(f"  Name              : {subscriber['name']}")
        print(f"  Phone             : {subscriber['phone']}")
        print(f"  Tier              : {subscriber['tier']}")
        print(f"  Active            : {bool(subscriber['active'])}")
        print(f"  Token hash        : {subscriber['token_hash'][:16]}...")
        print(f"  Subscription end  : {subscriber['subscription_end']}")
    else:
        print("SUBSCRIBER NOT FOUND — check webhook.py logs for errors")

    if payment:
        print(f"\nPAYMENT RECORD FOUND:")
        print(f"  Amount KES  : {payment['amount_kes']}")
        print(f"  Gateway ref : {payment['gateway_ref']}")
        print(f"  Status      : {payment['status']}")
    else:
        print("\nPAYMENT NOT FOUND — check webhook.py logs for errors")

except Exception as e:
    print(f"Database check failed: {e}")