Budgeting Webapp

A Flask-based budgeting web application that allows users to track income, expenses, and budgets, with authentication support and basic analytics.

Features

User authentication (login/signup)

Create, view, and categorize expenses and incomes

Simple dashboard with budget vs. spend summary

Health-check endpoint for monitoring

Tech Stack

Backend: Python, Flask, Flask-Login, SQLAlchemy

Database: SQLite (via SQLAlchemy)

Auth: Authlib for OAuth integrations

Dependencies: requests, python-dateutil, Pillow, pillow-heif, openai, etc.

Server: Gunicorn WSGI server

Process Manager: systemd user service

Reverse Proxy & TLS: Caddy on Hack Club Nest

Prerequisites

Python 3.10+

Git

SQLite (bundled with Python)

An active Hack Club Nest account for deployment

Installation & Setup (Local)

Clone the repository

git clone https://github.com/SanyamDa/Budgeting-Webapp.git
cd Budgeting-Webapp

Create & activate a virtual environment

python3 -m venv .venv
source .venv/bin/activate

Install dependencies

pip install --upgrade pip
pip install -r requirements.txt

Configure environment variables

Create a .env file in the project root:

SECRET_KEY=your_flask_secret_key
DATABASE_URL=sqlite:///website/database.db
OPENAI_API_KEY=your_openai_key
OAUTH_CLIENT_ID=...
OAUTH_CLIENT_SECRET=...

Run the application

flask run

The app will be available at http://127.0.0.1:5000.

Health Check

A /health route is available for uptime monitoring:

curl http://127.0.0.1:5000/health

Deployment (Hack Club Nest)

Push code to GitHub

git add .
git commit -m "Deploy prep"
git push

SSH into Nest

ssh sanyamdababy@hackclub.app
cd ~/apps/Budgeting-Webapp

Setup Python venv & install

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt gunicorn

Systemd user service

Create ~/.config/systemd/user/budgeting.service:

[Unit]
Description=Budgeting Flask API
After=network.target

[Service]
WorkingDirectory=%h/apps/Budgeting-Webapp
EnvironmentFile=%h/apps/Budgeting-Webapp/.env
ExecStart=%h/apps/Budgeting-Webapp/.venv/bin/gunicorn \
          --bind 0.0.0.0:8010 'website:create_app()'
Restart=on-failure

[Install]
WantedBy=default.target

systemctl --user daemon-reload
systemctl --user enable --now budgeting.service

Caddy reverse-proxy & TLS

nest caddy add api.sanyamdababy.hackclub.app --proxy localhost:8010
systemctl --user restart caddy

Visit: https://api.sanyamdababy.hackclub.app

Updating / Redeploy

On your laptop:

# make changes...
git push

On Nest:

ssh sanyamdababy@hackclub.app
cd ~/apps/Budgeting-Webapp
git pull
source .venv/bin/activate && pip install -r requirements.txt
systemctl --user restart budgeting.service

Logs & Monitoring

API logs:  journalctl --user -fu budgeting.service

Caddy logs: journalctl --user -fu caddy

Contributing

Contributions welcome! Please open an issue or submit a PR.
