from flask import Flask, request, jsonify, session, render_template, redirect
import requests
import sqlite3
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me")

DB_PATH = os.environ.get("DB_PATH", "messages.db")
GATEWAY_URL = os.environ.get("SMS_GATEWAY_URL")
GATEWAY_USER = os.environ.get("SMS_GATEWAY_USER", "JDZXOV")
GATEWAY_PASS = os.environ.get("SMS_GATEWAY_PASS")
DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.environ.get("DASHBOARD_PASS", "changeme")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                message TEXT NOT NULL,
                direction TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.commit()


init_db()


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def index():
    if not session.get("logged_in"):
        return render_template("index.html", logged_in=False)
    return render_template("index.html", logged_in=True)


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    if data.get("username") == DASHBOARD_USER and data.get("password") == DASHBOARD_PASS:
        session["logged_in"] = True
        return jsonify({"status": "ok"})
    return jsonify({"error": "invalid credentials"}), 401


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/api/conversations")
@login_required
def conversations():
    with get_db() as db:
        rows = db.execute("""
            SELECT phone, message, direction, created_at
            FROM messages
            WHERE id IN (
                SELECT MAX(id) FROM messages GROUP BY phone
            )
            ORDER BY created_at DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/messages/<phone>")
@login_required
def messages(phone):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM messages WHERE phone = ? ORDER BY created_at ASC",
            (phone,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/send", methods=["POST"])
@login_required
def send():
    data = request.get_json(force=True)
    phone = data.get("phoneNumber")
    message = data.get("message")
    if not phone or not message:
        return jsonify({"error": "missing phoneNumber or message"}), 400
    resp = requests.post(
        GATEWAY_URL,
        json={"message": message, "phoneNumbers": [phone]},
        auth=(GATEWAY_USER, GATEWAY_PASS)
    )
    if resp.status_code == 200:
        with get_db() as db:
            db.execute(
                "INSERT INTO messages (phone, message, direction) VALUES (?, ?, 'outbound')",
                (phone, message)
            )
            db.commit()
    return jsonify(resp.json()), resp.status_code


@app.route("/inbound", methods=["POST"])
def inbound():
    data = request.get_json(force=True) or {}
    payload = data.get("payload", {})
    phone = payload.get("phoneNumber", "")
    message = payload.get("message", "")
    if phone and message:
        with get_db() as db:
            db.execute(
                "INSERT INTO messages (phone, message, direction) VALUES (?, ?, 'inbound')",
                (phone, message)
            )
            db.commit()
    return jsonify({"status": "ok"}), 200


@app.route("/healthz")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
