import os
import hashlib
import hmac
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

MASTER_SALT: str = os.getenv("SUBSCRIPTION_SALT", "alpha_signals_default_salt")


class SubscriptionTier:
    FREE    = "free"
    BASIC   = "basic"
    PREMIUM = "premium"


SUBSCRIBER_REGISTRY: dict[str, dict] = {
    "e662910f6c635d748087a9e9fcc28fe505b8e9a17f1afe9a91e87268ca836dbd": {
        "name":    "Johnny",
        "tier":    SubscriptionTier.PREMIUM,
        "active":  True,
        "expires": "2027-01-01T00:00:00",
    },
}


def generate_token_hash(raw_token: str) -> str:
    return hmac.new(
        MASTER_SALT.encode(),
        raw_token.encode(),
        hashlib.sha256
    ).hexdigest()


def verify_subscriber(raw_token: str) -> tuple[bool, str]:
    if not raw_token:
        return False, "No subscription token provided."

    token_hash = generate_token_hash(raw_token)

    subscriber = SUBSCRIBER_REGISTRY.get(token_hash)
    if not subscriber:
        return False, f"Token not recognised. Access denied."

    if not subscriber.get("active", False):
        return False, f"Subscription for '{subscriber['name']}' is inactive."

    expires_str = subscriber.get("expires", "")
    if expires_str:
        try:
            expiry = datetime.fromisoformat(expires_str).replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expiry:
                return False, f"Subscription for '{subscriber['name']}' expired on {expires_str}."
        except ValueError:
            pass

    tier = subscriber.get("tier", SubscriptionTier.FREE)
    name = subscriber.get("name", "Unknown")
    return True, f"Access granted for '{name}' (tier: {tier})."


def requires_subscription(func):
    def wrapper(*args, **kwargs):
        token = os.getenv("SUBSCRIBER_TOKEN", "")
        valid, message = verify_subscriber(token)
        print(f"[Subscription] {message}")
        if not valid:
            print("[Subscription] Broadcast blocked — subscription verification failed.")
            return {"broadcast_result": f"blocked: {message}"}
        return func(*args, **kwargs)
    return wrapper