from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func
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

# Budget Category model
class BudgetCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(50), default='bx-category')
    main_category = db.Column(db.String(50), nullable=False)  # 'needs', 'wants', 'bills', 'investments'
    assigned_amount = db.Column(db.Float, default=0.0)
    spent_amount = db.Column(db.Float, default=0.0)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    created_date = db.Column(db.DateTime(timezone=True), default=func.now())
    
    # Relationship
    plan = db.relationship('Plan', backref=db.backref('categories', lazy=True, cascade="all, delete-orphan"))
    transactions = db.relationship('Transaction', backref='category', lazy=True, cascade="all, delete-orphan")
    
    @property
    def available_amount(self):
        return self.assigned_amount - self.spent_amount
    
    @property
    def progress_percentage(self):
        if self.assigned_amount == 0:
            return 0
        return min((self.spent_amount / self.assigned_amount) * 100, 100)

# Monthly budget information per category for each month
class MonthlyBudget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Integer, nullable=False)  # 1-12
    year = db.Column(db.Integer, nullable=False)

    assigned_amount = db.Column(db.Float, default=0.0)
    spent_amount = db.Column(db.Float, default=0.0)

    # Foreign keys
    category_id = db.Column(db.Integer, db.ForeignKey('budget_category.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)

    # Relationships
    category = db.relationship('BudgetCategory', backref=db.backref('monthly_budgets', lazy=True, cascade="all, delete-orphan"))
    plan = db.relationship('Plan', backref=db.backref('monthly_budgets', lazy=True, cascade="all, delete-orphan"))

    @property
    def available_amount(self):
        return self.assigned_amount - self.spent_amount

# Rollover model to store leftover money from a month
class MonthlyRollover(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, default=0.0)

    # Foreign keys
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)

    # Relationships
    plan = db.relationship('Plan', backref=db.backref('rollovers', lazy=True, cascade="all, delete-orphan"))

# Transaction model
class Payee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    created_date = db.Column(db.DateTime(timezone=True), default=func.now())

    plan = db.relationship('Plan', backref=db.backref('payees', lazy=True, cascade="all, delete-orphan"))


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_date = db.Column(db.DateTime(timezone=True), default=func.now())
    category_id = db.Column(db.Integer, db.ForeignKey('budget_category.id'), nullable=False)
    payee_id = db.Column(db.Integer, db.ForeignKey('payee.id'), nullable=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    created_date = db.Column(db.DateTime(timezone=True), default=func.now())
    
    # Bank integration fields
    source_type = db.Column(db.String(20), default='manual')  # 'manual', 'receipt', 'bank'
    bank_reference = db.Column(db.String(100), nullable=True)  # Bank transaction ID
    user_notes = db.Column(db.Text, nullable=True)  # User's payment notes for categorization
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_account.id'), nullable=True)
    
    # Relationships
    plan = db.relationship('Plan', backref=db.backref('transactions', lazy=True, cascade="all, delete-orphan"))
    payee = db.relationship('Payee', backref=db.backref('transactions', lazy=True))
    bank_account = db.relationship('BankAccount', backref=db.backref('transactions', lazy=True))


class BankAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bank_name = db.Column(db.String(50), nullable=False)  # 'Bangkok Bank', 'Kasikorn Bank', 'Krungsiri Bank'
    account_number = db.Column(db.String(20), nullable=False)  # Masked for security
    account_name = db.Column(db.String(100), nullable=False)  # Account holder name
    nickname = db.Column(db.String(50), nullable=True)  # User-friendly name like "Main Account"
    is_active = db.Column(db.Boolean, default=True)
    last_sync = db.Column(db.DateTime(timezone=True), nullable=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    created_date = db.Column(db.DateTime(timezone=True), default=func.now())
    
    # API credentials (encrypted)
    api_token = db.Column(db.Text, nullable=True)  # Encrypted bank API token
    refresh_token = db.Column(db.Text, nullable=True)  # Encrypted refresh token
    
    # Relationships
    plan = db.relationship('Plan', backref=db.backref('bank_accounts', lazy=True, cascade="all, delete-orphan"))
    
    def __repr__(self):
        return f'<BankAccount {self.bank_name} - {self.account_number[-4:]}>'  # Show last 4 digits only


# User model updated for multi-plan support
class User(db.Model, UserMixin):
    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(150), unique=True, nullable=False)
    password   = db.Column(db.String(150))
    first_name = db.Column(db.String(150))
    last_name  = db.Column(db.String(150))
    date_created = db.Column(db.DateTime(timezone=True), default=func.now())

    # Foreign key to the currently active plan
    active_plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=True)

    # Mark if user has completed the first onboarding
    profile_complete = db.Column(db.Boolean, default=False)
    theme = db.Column(db.String(50), nullable=False, default='system')

    # Relationships
    notes = db.relationship('Note', backref='user', lazy=True)
    plans = db.relationship('Plan', foreign_keys=[Plan.user_id], backref='user', lazy=True, cascade="all, delete-orphan")
    active_plan = db.relationship('Plan', foreign_keys=[active_plan_id], post_update=True)