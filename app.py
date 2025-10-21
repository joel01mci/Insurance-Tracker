from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3, os, datetime as dt

DB_PATH = os.environ.get("DB_PATH", "insurance_production.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db_if_needed():
    # If DB doesn't exist, create the core schema (matches the one I generated)
    if not os.path.exists(DB_PATH):
        conn = get_db()
        cur = conn.cursor()
        cur.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE agents (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
        CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
        CREATE TABLE lead_sources (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_date TEXT NOT NULL,
            agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
            quotes INTEGER NOT NULL DEFAULT 0 CHECK (quotes >= 0),
            sales INTEGER NOT NULL DEFAULT 0 CHECK (sales >= 0),
            premium REAL NOT NULL DEFAULT 0 CHECK (premium >= 0),
            lead_source_id INTEGER REFERENCES lead_sources(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_entries_date ON entries(entry_date);
        CREATE INDEX idx_entries_agent ON entries(agent_id);
        CREATE INDEX idx_entries_category ON entries(category_id);
        CREATE INDEX idx_entries_lead_source ON entries(lead_source_id);

        CREATE TABLE entry_import (
            entry_date TEXT, agent_name TEXT, category_name TEXT, quotes INTEGER, sales INTEGER, premium REAL, lead_source_name TEXT
        );
        CREATE TRIGGER trg_entry_import_ai
        AFTER INSERT ON entry_import
        BEGIN
            INSERT OR IGNORE INTO agents(name) VALUES (NEW.agent_name);
            INSERT OR IGNORE INTO categories(name) VALUES (NEW.category_name);
            INSERT OR IGNORE INTO lead_sources(name) VALUES (NEW.lead_source_name);
            INSERT INTO entries(entry_date, agent_id, category_id, quotes, sales, premium, lead_source_id)
            VALUES (
                NEW.entry_date,
                (SELECT id FROM agents WHERE name = NEW.agent_name),
                (SELECT id FROM categories WHERE name = NEW.category_name),
                COALESCE(NEW.quotes,0),
                COALESCE(NEW.sales,0),
                COALESCE(NEW.premium,0.0),
                (SELECT id FROM lead_sources WHERE name = NEW.lead_source_name)
            );
        END;

        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO settings(key,value) VALUES ('agency_goal','39500');

        CREATE VIEW v_dashboard AS
        WITH totals AS ( SELECT COALESCE(SUM(e.premium),0.0) AS total_premium FROM entries e ),
        d AS (
            SELECT date('now','start of month') AS month_start,
                   CAST(strftime('%d', date('now','start of month','+1 month','-1 day')) AS INTEGER) AS days_in_month,
                   CAST(julianday(date('now')) - julianday(date('now','start of month')) + 1 AS INTEGER) AS days_elapsed
        )
        SELECT t.total_premium,
               CAST((SELECT value FROM settings WHERE key='agency_goal') AS REAL) AS agency_goal,
               CASE WHEN CAST((SELECT value FROM settings WHERE key='agency_goal') AS REAL) > 0
                    THEN t.total_premium / CAST((SELECT value FROM settings WHERE key='agency_goal') AS REAL) ELSE 0 END AS pct_to_goal,
               d.month_start, d.days_in_month, d.days_elapsed,
               CASE WHEN d.days_elapsed > 0 THEN (t.total_premium / d.days_elapsed) * d.days_in_month ELSE 0 END AS projected_month_end_premium
        FROM totals t, d;

        CREATE VIEW v_agent_summary AS
        SELECT a.name AS agent,
               COALESCE(SUM(e.quotes),0) AS quotes,
               COALESCE(SUM(e.sales),0) AS sales,
               COALESCE(SUM(e.premium),0.0) AS total_premium,
               CASE WHEN CAST((SELECT value FROM settings WHERE key='agency_goal') AS REAL) > 0
                    THEN COALESCE(SUM(e.premium),0.0)/CAST((SELECT value FROM settings WHERE key='agency_goal') AS REAL) ELSE 0 END AS pct_of_goal
        FROM agents a LEFT JOIN entries e ON e.agent_id = a.id
        GROUP BY a.id, a.name ORDER BY total_premium DESC;

        CREATE VIEW v_category_summary AS
        SELECT c.name AS category,
               COALESCE(SUM(e.quotes),0) AS quotes,
               COALESCE(SUM(e.sales),0) AS sales,
               COALESCE(SUM(e.premium),0.0) AS total_premium
        FROM categories c LEFT JOIN entries e ON e.category_id = c.id
        GROUP BY c.id, c.name ORDER BY total_premium DESC;

        CREATE VIEW v_lead_source_summary AS
        SELECT ls.name AS lead_source,
               COALESCE(SUM(e.quotes),0) AS quotes,
               COALESCE(SUM(e.sales),0) AS sales,
               COALESCE(SUM(e.premium),0.0) AS total_premium
        FROM lead_sources ls LEFT JOIN entries e ON e.lead_source_id = ls.id
        GROUP BY ls.id, ls.name ORDER BY total_premium DESC;

        CREATE VIEW v_entries AS
        SELECT e.id, e.entry_date, a.name AS agent, c.name AS category,
               e.quotes, e.sales, e.premium, ls.name AS lead_source, e.created_at
        FROM entries e
        JOIN agents a ON a.id = e.agent_id
        JOIN categories c ON c.id = e.category_id
        LEFT JOIN lead_sources ls ON ls.id = e.lead_source_id
        ORDER BY e.entry_date DESC, e.id DESC;
        """)
        # Seed defaults
        cur.executemany("INSERT INTO agents(name) VALUES (?) ON CONFLICT(name) DO NOTHING;", [(f'Agent {i}',) for i in range(1,6)])
        cur.executemany("INSERT INTO categories(name) VALUES (?) ON CONFLICT(name) DO NOTHING;", [('Auto',),('Home',),('Life',),('Other',)])
        cur.executemany("INSERT INTO lead_sources(name) VALUES (?) ON CONFLICT(name) DO NOTHING;", [('Inbound Call',),('Referral',),('Walk-in',),('Web Lead',),('Email',),('Social',),('Other',)])
        conn.commit()
        conn.close()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

init_db_if_needed()

@app.route('/')
def dashboard():
    conn = get_db()
    dash = conn.execute("SELECT * FROM v_dashboard").fetchone()
    agents = conn.execute("SELECT * FROM v_agent_summary").fetchall()
    cats = conn.execute("SELECT * FROM v_category_summary").fetchall()
    leads = conn.execute("SELECT * FROM v_lead_source_summary").fetchall()
    return render_template('dashboard.html', dash=dash, agents=agents, cats=cats, leads=leads)

@app.route('/entries', methods=['GET','POST'])
def entries():
    conn = get_db()
    if request.method == 'POST':
        data = {
            "entry_date": request.form.get('entry_date'),
            "agent_name": request.form.get('agent_name'),
            "category_name": request.form.get('category_name'),
            "quotes": int(request.form.get('quotes') or 0),
            "sales": int(request.form.get('sales') or 0),
            "premium": float(request.form.get('premium') or 0.0),
            "lead_source_name": request.form.get('lead_source_name')
        }
        # Basic validation
        if not data["entry_date"] or not data["agent_name"] or not data["category_name"]:
            flash("Please provide Date, Agent, and Category.", "error")
        else:
            conn.execute("""INSERT INTO entry_import(entry_date, agent_name, category_name, quotes, sales, premium, lead_source_name)
                            VALUES (?,?,?,?,?,?,?)""",
                         (data["entry_date"], data["agent_name"], data["category_name"], data["quotes"], data["sales"], data["premium"], data["lead_source_name"]))
            conn.commit()
            flash("Entry added.", "success")
        return redirect(url_for('entries'))
    # GET
    agents = [r['name'] for r in conn.execute("SELECT name FROM agents ORDER BY name").fetchall()]
    cats = [r['name'] for r in conn.execute("SELECT name FROM categories ORDER BY name").fetchall()]
    leads = [r['name'] for r in conn.execute("SELECT name FROM lead_sources ORDER BY name").fetchall()]
    latest = conn.execute("SELECT * FROM v_entries LIMIT 50").fetchall()
    return render_template('entries.html', agents=agents, cats=cats, leads=leads, latest=latest)

@app.route('/api/chart/agent-premium')
def chart_agent_premium():
    conn = get_db()
    rows = conn.execute("SELECT agent, total_premium FROM v_agent_summary ORDER BY total_premium DESC").fetchall()
    return jsonify({"labels":[r["agent"] for r in rows], "values":[round(r["total_premium"] or 0,2) for r in rows]})

@app.route('/api/chart/category-premium')
def chart_category_premium():
    conn = get_db()
    rows = conn.execute("SELECT category, total_premium FROM v_category_summary ORDER BY total_premium DESC").fetchall()
    return jsonify({"labels":[r["category"] for r in rows], "values":[round(r["total_premium"] or 0,2) for r in rows]})

@app.route('/settings', methods=['POST'])
def settings_update():
    # Update agency goal
    goal = request.form.get('agency_goal')
    try:
        float_goal = float(goal)
    except:
        flash("Invalid goal amount.", "error")
        return redirect(url_for('dashboard'))
    conn = get_db()
    conn.execute("UPDATE settings SET value=? WHERE key='agency_goal'", (str(float_goal),))
    conn.commit()
    flash("Goal updated.", "success")
    return redirect(url_for('dashboard'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
