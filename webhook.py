"""
Payment webhook handler for Flutterwave M-Pesa callbacks.

DEPLOYMENT:
-----------
Local testing:
    python webhook.py
    ngrok http 8080

Set the ngrok HTTPS URL in Flutterwave dashboard:
    Settings -> API Keys & Webhooks -> URL
    https://xxxx-xxxx.ngrok-free.app/webhook/payment

The verif-hash header must match FLUTTERWAVE_SECRET_HASH in .env exactly.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv
from subscription import generate_token_hash

# Import the centralized connection manager and initializer from the DB layer
from database import _get_connection, initialize_database

load_dotenv()

logger = logging.getLogger(__name__)

FLUTTERWAVE_SECRET_HASH: str   = os.getenv("FLUTTERWAVE_SECRET_HASH", "")
SUBSCRIPTION_PRICE_KES:  float = float(os.getenv("SUBSCRIPTION_PRICE_KES", "3500.0"))
SUBSCRIPTION_DAYS:       int   = int(os.getenv("SUBSCRIPTION_DAYS", "30"))
WEBHOOK_PORT:            int   = int(os.getenv("WEBHOOK_PORT", "8080"))


def _activate_subscriber(
    phone:       str,
    gateway_ref: str,
    amount:      float,
    name:        str = "",
    email:       str = "",
) -> bool:
    """
    Inserts or updates a subscriber record and records the payment using the 
    centralized database manager tool to prevent relative path isolation errors.

    New subscriber:      INSERT into subscribers with premium tier + token hash
    Existing subscriber: UPDATE subscription window, keep same token hash

    Returns True on success, False on any database error.
    """
    if not phone:
        logger.warning("_activate_subscriber called with empty phone. Skipping.")
        return False

    try:
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=SUBSCRIPTION_DAYS)).isoformat()
        display_name = name.strip() if name.strip() else phone

        # Use your central database connection layer rules cleanly
        with _get_connection() as conn:
            existing = conn.execute(
                "SELECT id, token_hash FROM subscribers WHERE phone = ?",
                (phone,)
            ).fetchone()

            if not existing:
                raw_token  = f"{phone}_{gateway_ref}"
                token_hash = generate_token_hash(raw_token)

                cursor = conn.execute("""
                    INSERT INTO subscribers
                        (name, phone, email, tier, token_hash, active,
                         subscription_start, subscription_end, mpesa_ref)
                    VALUES (?, ?, ?, 'premium', ?, 1, ?, ?, ?)
                """, (
                    display_name, phone, email, token_hash,
                    now, end, gateway_ref,
                ))
                subscriber_id = cursor.lastrowid
                logger.info(
                    "New subscriber created. phone=%s db_id=%d token_hash=%s...",
                    phone, subscriber_id, token_hash[:12]
                )

            else:
                # Handle connection row parsing cleanly matching sqlite3.Row configuration
                subscriber_id = existing["id"]
                conn.execute("""
                    UPDATE subscribers
                    SET active              = 1,
                        tier                = 'premium',
                        subscription_start  = ?,
                        subscription_end    = ?,
                        mpesa_ref           = ?,
                        updated_at          = ?
                    WHERE id = ?
                """, (now, end, gateway_ref, now, subscriber_id))
                logger.info(
                    "Existing subscriber renewed. phone=%s db_id=%d until=%s",
                    phone, subscriber_id, end
                )

            conn.execute("""
                INSERT INTO payments
                    (subscriber_id, amount_kes, currency, gateway, gateway_ref, status)
                VALUES (?, ?, 'KES', 'flutterwave', ?, 'confirmed')
            """, (subscriber_id, amount, gateway_ref))

        logger.info(
            "Subscriber activated successfully. phone=%s ref=%s amount=%.2f until=%s",
            phone, gateway_ref, amount, end
        )
        return True

    except Exception as e:
        logger.error(
            "Failed to activate subscriber. phone=%s error=%s",
            phone, str(e),
            exc_info=True
        )
        return False


class WebhookHandler(BaseHTTPRequestHandler):

    def do_POST(self) -> None:
        if self.path != "/webhook/payment":
            logger.warning("Request to unknown path: %s", self.path)
            self._respond(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            logger.warning("Webhook received with empty body.")
            self._respond(400)
            return

        raw_body = self.rfile.read(content_length)
        verif_hash = self.headers.get("verif-hash", "")

        if not FLUTTERWAVE_SECRET_HASH:
            logger.error(
                "FLUTTERWAVE_SECRET_HASH not set in .env. "
                "All webhooks will be rejected."
            )
            self._respond(500)
            return

        if verif_hash != FLUTTERWAVE_SECRET_HASH:
            logger.warning(
                "Webhook signature mismatch. "
                "Expected hash from .env, got: '%s...'. Rejecting.",
                verif_hash[:8] if verif_hash else "empty"
            )
            self._respond(401)
            return

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("Failed to parse webhook JSON body. error=%s", str(e))
            self._respond(400)
            return

        event_type = payload.get("event", "")
        data       = payload.get("data", {})

        if not data:
            logger.warning("Webhook payload missing 'data' key. event=%s", event_type)
            self._respond(200)
            return

        status = str(data.get("status", "")).lower()
        ref    = str(data.get("id", "")).strip()
        name   = str(data.get("customer", {}).get("name", "")).strip()
        email  = str(data.get("customer", {}).get("email", "")).strip()
        phone  = str(data.get("customer", {}).get("phone_number", "")).strip()

        try:
            amount = float(data.get("amount", 0))
        except (TypeError, ValueError):
            logger.warning("Could not parse amount from payload. raw=%s", data.get("amount"))
            amount = 0.0

        logger.info(
            "Webhook received. event=%s status=%s ref=%s phone=%s amount=%.2f",
            event_type, status, ref, phone, amount
        )

        if status == "successful" and amount >= SUBSCRIPTION_PRICE_KES and ref and phone:
            success = _activate_subscriber(phone, ref, amount, name, email)
            if success:
                logger.info("Payment processed successfully. ref=%s", ref)
            else:
                logger.error("Payment activation failed. ref=%s phone=%s", ref, phone)
            self._respond(200)
        else:
            logger.info(
                "Payment did not qualify for activation. "
                "status=%s amount=%.2f required=%.2f ref=%s phone=%s",
                status, amount, SUBSCRIPTION_PRICE_KES, ref, phone
            )
            self._respond(200)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, b"Alpha Signals Webhook Server OK")
        else:
            self._respond(404)

    def _respond(self, code: int, body: bytes = b"") -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        logger.debug("HTTP: %s", format % args)


def start_webhook_server(port: int = WEBHOOK_PORT) -> None:
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    logger.info(
        "Webhook server started. Listening on http://0.0.0.0:%d/webhook/payment",
        port
    )
    logger.info("Health check available at http://0.0.0.0:%d/health", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Webhook server stopped by keyboard interrupt.")
        server.shutdown()


if __name__ == "__main__":
    from logging_config import configure_logging
    configure_logging()
    
    # Initialize schema layers safely down the standard pipeline flow
    logger.info("Verifying structural database integrity...")
    initialize_database()
    
    start_webhook_server()