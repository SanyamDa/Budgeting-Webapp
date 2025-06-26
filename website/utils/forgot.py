from itsdangerous import URLSafeTimedSerializer
from flask import current_app

def _s():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"],
                                  salt="password-reset")

def generate_reset_token(email):
    """Return a signed token that encodes the e-mail (valid 1 h)."""
    return _s().dumps(email)

def verify_reset_token(token, max_age=3600):
    """Return the e-mail if token is valid, else None."""
    try:
        return _s().loads(token, max_age=max_age)
    except Exception:
        return None