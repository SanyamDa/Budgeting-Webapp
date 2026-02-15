# website/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask import Blueprint, render_template
from flask_login import login_required
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate  
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import os, pathlib

load_dotenv()

db    = SQLAlchemy()
oauth = OAuth()
migrate = Migrate()    
mail  = Mail()

DB_NAME = "database.db"                       # will sit inside /website

def create_app():
    app = Flask(__name__) 

    # ── App config ─────────────────────────────
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev")

    db_path = pathlib.Path(__file__).with_name(DB_NAME)
    print("USING DB FILE:", db_path.resolve())
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config.update(
        MAIL_SERVER   = "smtp.gmail.com",
        MAIL_PORT     = 587,
        MAIL_USE_TLS  = True,
        MAIL_USERNAME = os.getenv("MAIL_USERNAME"),
        MAIL_PASSWORD = os.getenv("MAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER = os.getenv("MAIL_USERNAME"),   # ★ add this
    )

    # ── Initialise extensions ─────────────────
    db.init_app(app)
    oauth.init_app(app)
    mail.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # ── Blueprints ────────────────────────────
    from .views import views
    from .auth  import auth
    from .onboard import onboard
    app.register_blueprint(onboard, url_prefix="/")
    app.register_blueprint(views, url_prefix="/")
    app.register_blueprint(auth,  url_prefix="/")



    @login_manager.user_loader
    def load_user(user_id):
        from .models import User
        return User.query.get(int(user_id))

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    with app.app_context():
        from .models import User, Note, Plan, BudgetCategory, MonthlyBudget, Transaction, Payee, MonthlyRollover, AdditionalIncome
        db.create_all()

    return app
