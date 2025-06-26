from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

# Note model remains the same
class Note(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    data     = db.Column(db.String(10000))
    date     = db.Column(db.DateTime(timezone=True), default=func.now())
    user_id  = db.Column(db.Integer, db.ForeignKey('user.id'))

# New Plan model to store plan-specific data
class Plan(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(100), nullable=False)
    monthly_income = db.Column(db.Float)
    budget_pref    = db.Column(JSON)  # e.g., {"needs": 50, "wants": 30, "savings": 20}
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# User model updated for multi-plan support
class User(db.Model, UserMixin):
    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(150), unique=True, nullable=False)
    password   = db.Column(db.String(150))
    first_name = db.Column(db.String(150))
    last_name  = db.Column(db.String(150))

    # Foreign key to the currently active plan
    active_plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=True)

    # Mark if user has completed the first onboarding
    profile_complete = db.Column(db.Boolean, default=False)
    theme = db.Column(db.String(50), nullable=False, default='system')

    # Relationships
    notes = db.relationship('Note', backref='user', lazy=True)
    plans = db.relationship('Plan', foreign_keys=[Plan.user_id], backref='user', lazy=True, cascade="all, delete-orphan")
    active_plan = db.relationship('Plan', foreign_keys=[active_plan_id], post_update=True)