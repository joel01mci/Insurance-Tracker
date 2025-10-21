# Insurance Production Tracker (Flask + SQLite)

A lightweight web app to track insurance production by agent/category with dashboards and charts.

## Local Run
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DB_PATH=insurance_production.db   # optional: path to your existing DB
export SECRET_KEY=change-me
python app.py
# visit http://localhost:5000
```

## Deploy to Render (Free)
1. Create a **new GitHub repo** and push these files.
2. On **Render.com** → "New +" → **Web Service** → connect your repo.
3. Settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Runtime: Python 3.x
   - Environment Variables:
     - `DB_PATH` = `insurance_production.db` (uses the SQLite file in the repo)
     - `SECRET_KEY` = any random string
4. Deploy. Open the URL Render gives you.

> **Using your existing DB**  
> Add your `insurance_production.db` file to the repo root before deploying (or upload via Render's persistent disk). The app will also create a new DB if none exists.

## Features
- Data entry form → writes to `entry_import` which normalizes into `entries` via trigger.
- Dashboard with totals, % to goal, projected pace, tables and charts.
- Simple settings form to update the agency goal.

## Notes
- Free tiers may sleep when idle. Wake by visiting the URL.
- For multi-user/production usage, consider PostgreSQL and a proper auth layer.
