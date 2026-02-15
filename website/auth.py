from flask import Blueprint, render_template, request, flash, redirect, url_for, session, current_app

from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, login_required, logout_user
from flask_mail import Message
from .utils.forgot import generate_reset_token, verify_reset_token
import os, random, time, re

from . import db, oauth, mail
from .models import User

auth = Blueprint("auth", __name__) 

# ── Password validation function ─────────────────────────────────
def validate_password(password):
    """
    Validate password against security criteria:
    - At least 8 characters
    - At least 1 capital letter
    - At least 1 special character
    - At least 1 number
    Returns tuple (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least 1 capital letter."
    
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least 1 number."
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least 1 special character (!@#$%^&*(),.?\":{}|<>)."
    
    return True, ""

# ── Google OAuth client ──────────────────────────────────────────
google = oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    api_base_url="https://www.googleapis.com/oauth2/v2/",   # gives /userinfo
    client_kwargs={"scope": "openid email profile"},
)

# ── Google sign-in entry point ──────────────────────────────────
@auth.route("/login/google")
def google_login():
    session.clear()                               # keep this
    
    # Detect environment: Render sets RENDER=true automatically
    if os.environ.get('RENDER'):
        redirect_uri = "https://budgeting-webapp.onrender.com/auth/callback"
    else:
        from flask import request
        redirect_uri = f"http://{request.host}/auth/callback"

    # tell Google: “make the user pick an account every time”
    return google.authorize_redirect(
        redirect_uri,
        prompt="select_account"                   # ← new line
    )

# ── OAuth callback ──────────────────────────────────────────────
@auth.route("/auth/callback")
def google_callback():
    try:
        token = google.authorize_access_token()
    except Exception:
        current_app.logger.exception("OAuth callback failed")
        flash("Google login failed. Try again.", "error")
        return redirect(url_for("auth.login"))

    resp = google.get("userinfo")  # base URL + 'userinfo'
    if not resp.ok:
        flash("Could not fetch profile from Google.", "error")
        return redirect(url_for("auth.login"))
    data = resp.json()

    # 6-digit OTP
    code = f"{random.randint(0, 999999):06d}"
    session["otp"] = {"code": code, "exp": time.time() + 600}
    session["pending_user"] = {
        "email": data["email"],
        "first": data.get("given_name", ""),
        "last":  data.get("family_name", ""),
    }

    # email the OTP
    try:
        msg = Message(
            subject="Your verification code",
            recipients=[data["email"]],
            sender=current_app.config["MAIL_USERNAME"], 
            body=(
                f"Hi {data.get('given_name','')},\n\n"
                f"Your verification code is {code}. "
                "It expires in 10 minutes."
            ),
        )
        mail.send(msg)
    except Exception:
        current_app.logger.exception("OTP email failed")
        flash("Couldn’t send verification email. Try again.", "error")
        return redirect(url_for("auth.login"))

    return redirect(url_for("auth.verify"))

# ── OTP screen ──────────────────────────────────────────────────
@auth.route("/verify", methods=["GET", "POST"])
def verify():
    otp = session.get("otp")
    if not otp:
        flash("Session expired. Start again.", "error")
        return redirect(url_for("auth.google_login"))

    if request.method == "POST":
        typed = request.form.get("code", "").strip()
        if typed != otp["code"] or time.time() > otp["exp"]:
            flash("Invalid or expired code.", "error")
            return render_template("verify.html")

        data = session.pop("pending_user")
        session.pop("otp")
        user = User.query.filter_by(email=data["email"]).first()
        if not user:
            user = User(
                email=data["email"],
                first_name=data["first"],
                last_name=data["last"],
                password="",
            )
            db.session.add(user)
            db.session.commit()

        login_user(user, remember=True)

        # >>> redirect based on profile flag
        if not user.profile_complete:
            return redirect(url_for("onboard.show_form"))
        return redirect(url_for("views.home"))

    # GET  → just show the six-digit form
    return render_template("verify.html")
# ── Email/password login (unchanged) ────────────────────────────
@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email").strip().lower() 
        pw    = request.form.get("password")
        user  = User.query.filter_by(email=email).first()
        print("LOOKED-UP USER =", user) 
        if user and check_password_hash(user.password, pw):
            print(">>> LOGGING IN", user.id, user.email)
            login_user(user, remember=True)
            flash("Logged in!", "success")
            if not user.profile_complete:
                return redirect(url_for("onboard.show_form"))
            return redirect(url_for("views.home"))
        flash("Wrong email or password.", "error")
    return render_template("login.html")

# ── Sign-up flow (unchanged) ────────────────────────────────────
@auth.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email, fn, ln = (request.form.get("email").strip().lower(),
                         request.form.get("first_name","").strip(),
                         request.form.get("last_name","").strip())
        pw1, pw2 = request.form.get("password1"), request.form.get("password2")
        user = User.query.filter_by(email=email).first()
        if user:
            flash("Email already exists!", "error")
        elif len(email) < 4 or "@" not in email:
            flash("Enter a valid email.", "error")
        elif len(fn) < 2 or len(ln) < 2:
            flash("Name too short.", "error")
        elif pw1 != pw2:
            flash("Passwords don't match.", "error")
        else:
            # Validate password strength
            is_valid, error_msg = validate_password(pw1)
            if not is_valid:
                flash(error_msg, "error")
                return render_template("signup.html")
            
            new_user = User(
                email=email, first_name=fn, last_name=ln,
                password=generate_password_hash(pw1, method="pbkdf2:sha256")
            )
            db.session.add(new_user); db.session.commit()
            login_user(new_user, remember=True)
            flash("Account created!", "success")
            if not new_user.profile_complete:
                return redirect(url_for("onboard.show_form"))
            return redirect(url_for("views.home"))
    return render_template("signup.html")

@auth.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

# ── AJAX route: resend code without leaving the page ────────────
@auth.route("/resend-otp")
def resend_otp():
    data = session.get("pending_user")
    if not data:
        return {"ok": False, "err": "no_session"}, 400

    # generate a new 6-digit code
    code = f"{random.randint(0, 999999):06d}"
    session["otp"] = {"code": code, "exp": time.time() + 600}  # 10-min validity

    try:
        msg = Message(
            subject="Your new verification code",
            recipients=[data["email"]],
            sender=current_app.config["MAIL_USERNAME"],
            body=(
                f"Hi {data.get('first') or ''},\n\n"
                f"Your new verification code is {code}. "
                "It expires in 10 minutes."
            ),
        )
        mail.send(msg)
    except Exception:
        current_app.logger.exception("Resend OTP e-mail failed")
        return {"ok": False, "err": "send_fail"}, 500

    return {"ok": True}

@auth.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    print("\n=== DEBUG: Entered forgot_password function ===")  # Debug print
    if request.method == "POST":
        print("DEBUG: Received POST request")  # Debug print
        email = request.form.get("email", "").strip().lower()
        print(f"DEBUG: Email from form: '{email}'")  # Debug print
        
        user = User.query.filter_by(email=email).first()
        print(f"DEBUG: User found: {user is not None}")  # Debug print

        # Debug: Print mail config
        print("\n=== DEBUG: Mail Configuration ===")
        print(f"MAIL_SERVER: {current_app.config.get('MAIL_SERVER')}")
        print(f"MAIL_PORT: {current_app.config.get('MAIL_PORT')}")
        print(f"MAIL_USE_TLS: {current_app.config.get('MAIL_USE_TLS')}")
        print(f"MAIL_USERNAME: {current_app.config.get('MAIL_USERNAME')}")
        print("MAIL_PASSWORD: [REDACTED]")
        print(f"MAIL_DEFAULT_SENDER: {current_app.config.get('MAIL_DEFAULT_SENDER')}")
        print("===============================\n")
        
        if user:  # if user is found
            print("DEBUG: User exists, attempting to send reset email")  # Debug print
            try:
                # Generate reset token and URL
                print("DEBUG: Generating reset token...")  # Debug print
                token = generate_reset_token(email)
                reset_url = url_for("auth.reset_password", token=token, _external=True)
                print(f"DEBUG: Generated reset URL: {reset_url}")  # Debug print
                
                # Create message
                print("DEBUG: Creating email message...")  # Debug print
                msg = Message(
                    subject="Reset your password",
                    recipients=[email],
                    sender=current_app.config["MAIL_DEFAULT_SENDER"],
                    body=f"Hi {user.first_name or ''},\n\n"
                         f"Click to set a new password (valid for 60 mins): \n{reset_url}"
                )
                
                # Send message
                print("DEBUG: Attempting to send email...")  # Debug print
                mail.send(msg)
                print("DEBUG: Email sent successfully!")  # Debug print
                
                flash("If that email exists, a reset link has been sent.", "info")
                return redirect(url_for("auth.login"))
                
            except Exception as e:
                print(f"ERROR: Failed to send email: {str(e)}")  # Debug print
                import traceback
                print("Full traceback:")
                print(traceback.format_exc())  # Print full traceback
                current_app.logger.exception("reset-email failed")
                flash("There was an error sending the reset email. Please try again later.", "error")
                return render_template("forgot.html")
        else:
            print("DEBUG: No user found with that email")  # Debug print
            # For security, don't reveal if email exists or not
            flash("If that email exists, a reset link has been sent.", "info")
            return redirect(url_for("auth.login"))
            
    return render_template("forgot.html")
    
@auth.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    email = verify_reset_token(token)
    if not email:
        flash("Link expired or invalid. Request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))

    user = User.query.filter_by(email=email).first_or_404()

    if request.method == "POST":
        pw1 = request.form.get("password1")
        pw2 = request.form.get("password2")
        if pw1 != pw2:
            flash("Passwords don't match.", "error")
        else:
            # Validate password strength
            is_valid, error_msg = validate_password(pw1)
            if not is_valid:
                flash(error_msg, "error")
                return render_template("reset.html")
            
            user.password = generate_password_hash(pw1, method="pbkdf2:sha256")
            db.session.commit()
            flash("Password updated — you can log in now.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reset.html")   # you’ll create this template next



