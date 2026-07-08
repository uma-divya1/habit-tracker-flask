import sqlite3
from datetime import date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, g

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-this-in-production"

DATABASE = "habits.db"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS habit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS habit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                UNIQUE(habit_id, date),
                FOREIGN KEY (habit_id) REFERENCES habit (id) ON DELETE CASCADE
            )
            """
        )
        db.commit()


def get_completed_dates(db, habit_id):
    rows = db.execute(
        "SELECT date FROM habit_log WHERE habit_id = ? ORDER BY date", (habit_id,)
    ).fetchall()
    return {r["date"] for r in rows}


def calculate_streaks(completed_dates):
    """Returns (current_streak, longest_streak) given a set of 'YYYY-MM-DD' strings."""
    if not completed_dates:
        return 0, 0

    dates_as_dates = sorted(date.fromisoformat(d) for d in completed_dates)

    # Longest streak: scan for consecutive runs
    longest = 1
    run = 1
    for i in range(1, len(dates_as_dates)):
        if (dates_as_dates[i] - dates_as_dates[i - 1]).days == 1:
            run += 1
        else:
            run = 1
        longest = max(longest, run)

    # Current streak: count backwards from today (or yesterday if today not done yet)
    today = date.today()
    current = 0
    cursor = today
    date_set = set(dates_as_dates)
    if today not in date_set:
        cursor = today - timedelta(days=1)
    while cursor in date_set:
        current += 1
        cursor -= timedelta(days=1)

    return current, longest


@app.route("/")
def index():
    db = get_db()
    habits = db.execute("SELECT * FROM habit ORDER BY created_at DESC").fetchall()
    today_str = date.today().isoformat()

    habit_data = []
    for h in habits:
        completed_dates = get_completed_dates(db, h["id"])
        current, longest = calculate_streaks(completed_dates)
        habit_data.append(
            {
                "id": h["id"],
                "name": h["name"],
                "done_today": today_str in completed_dates,
                "current_streak": current,
                "longest_streak": longest,
                "total_completions": len(completed_dates),
            }
        )

    return render_template("index.html", habits=habit_data, today=today_str)


@app.route("/add", methods=["POST"])
def add_habit():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Habit name can't be empty.", "error")
        return redirect(url_for("index"))

    db = get_db()
    db.execute(
        "INSERT INTO habit (name, created_at) VALUES (?, ?)",
        (name, date.today().isoformat()),
    )
    db.commit()
    flash(f'Added habit "{name}".', "success")
    return redirect(url_for("index"))


@app.route("/toggle/<int:habit_id>", methods=["POST"])
def toggle_today(habit_id):
    db = get_db()
    today_str = date.today().isoformat()
    existing = db.execute(
        "SELECT id FROM habit_log WHERE habit_id = ? AND date = ?", (habit_id, today_str)
    ).fetchone()

    if existing:
        db.execute("DELETE FROM habit_log WHERE id = ?", (existing["id"],))
    else:
        db.execute(
            "INSERT INTO habit_log (habit_id, date) VALUES (?, ?)", (habit_id, today_str)
        )
    db.commit()
    return redirect(request.referrer or url_for("index"))


@app.route("/delete/<int:habit_id>", methods=["POST"])
def delete_habit(habit_id):
    db = get_db()
    db.execute("DELETE FROM habit_log WHERE habit_id = ?", (habit_id,))
    db.execute("DELETE FROM habit WHERE id = ?", (habit_id,))
    db.commit()
    flash("Habit deleted.", "success")
    return redirect(url_for("index"))


@app.route("/habit/<int:habit_id>")
def habit_detail(habit_id):
    db = get_db()
    habit = db.execute("SELECT * FROM habit WHERE id = ?", (habit_id,)).fetchone()
    if habit is None:
        flash("Habit not found.", "error")
        return redirect(url_for("index"))

    completed_dates = get_completed_dates(db, habit_id)
    current, longest = calculate_streaks(completed_dates)

    # Build a 90-day heatmap grid ending today, grouped into weeks (columns)
    days = 90
    today = date.today()
    start = today - timedelta(days=days - 1)
    # Pad to start on a Sunday so weeks line up as full columns
    start -= timedelta(days=(start.weekday() + 1) % 7)

    weeks = []
    cursor = start
    current_week = []
    while cursor <= today:
        in_range = cursor >= (today - timedelta(days=days - 1))
        current_week.append(
            {
                "date": cursor.isoformat(),
                "completed": cursor.isoformat() in completed_dates,
                "in_range": in_range,
                "is_future": cursor > today,
            }
        )
        if len(current_week) == 7:
            weeks.append(current_week)
            current_week = []
        cursor += timedelta(days=1)
    if current_week:
        weeks.append(current_week)

    return render_template(
        "habit_detail.html",
        habit=habit,
        current_streak=current,
        longest_streak=longest,
        total_completions=len(completed_dates),
        weeks=weeks,
        today=today.isoformat(),
    )


@app.route("/api/habits")
def api_habits():
    """Simple JSON API endpoint -- demonstrates a REST API alongside server-rendered pages."""
    db = get_db()
    habits = db.execute("SELECT * FROM habit").fetchall()
    result = []
    for h in habits:
        completed_dates = get_completed_dates(db, h["id"])
        current, longest = calculate_streaks(completed_dates)
        result.append(
            {
                "id": h["id"],
                "name": h["name"],
                "current_streak": current,
                "longest_streak": longest,
                "total_completions": len(completed_dates),
            }
        )
    return jsonify(result)


init_db()

if __name__ == "__main__":
    app.run(debug=True)
