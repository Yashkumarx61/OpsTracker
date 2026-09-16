"""
OpsTracker — Main Flask Application
====================================
A lightweight organizational project & task tracker.

Modules:
  - Database helpers (SQLite connection)
  - Flask-Login authentication
  - Role-based routing (Admin / Employee)
  - Health-check endpoint for CI/CD monitoring
"""

import functools
import os
import sqlite3
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, g
)
from flask_login import (
    LoginManager, UserMixin, login_user,
    logout_user, login_required, current_user
)
from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config

# ============================================================
# App Factory
# ============================================================
app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY
app.config["WTF_CSRF_ENABLED"] = True

# CSRF protection on all POST forms
csrf = CSRFProtect(app)

# Flask-Login setup
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "warning"


# ============================================================
# Database Helpers (SQLite)
# ============================================================
def dict_factory(cursor, row):
    """Convert sqlite3 Row to a dict so templates can use row['column']."""
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def get_db():
    """
    Return an SQLite connection stored on Flask's `g` object.
    Reuses the same connection within a single request.
    """
    if "db" not in g:
        try:
            g.db = sqlite3.connect(Config.DB_PATH)
            g.db.row_factory = dict_factory
            g.db.execute("PRAGMA journal_mode=WAL")
            g.db.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error as e:
            app.logger.error(f"Database connection failed: {e}")
            raise
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """Close DB connection at end of request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(sql, args=(), one=False):
    """Execute a SELECT query and return results as dicts."""
    conn = get_db()
    cur = conn.execute(sql, args)
    results = cur.fetchall()
    return (results[0] if results else None) if one else results


def execute_db(sql, args=()):
    """Execute an INSERT / UPDATE / DELETE and return lastrowid."""
    conn = get_db()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.lastrowid


def create_notification(user_id, title, message, link=None):
    """Insert a notification for a user."""
    try:
        execute_db(
            "INSERT INTO notifications (user_id, title, message, link) VALUES (?, ?, ?, ?)",
            (user_id, title, message, link)
        )
    except Exception as e:
        app.logger.error(f"Failed to create notification: {e}")


def init_db():
    """
    Create all tables if they don't exist, and seed the default admin user.
    Reads the SQLite-compatible schema.sql file.
    """
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if not os.path.exists(schema_path):
        app.logger.warning("schema.sql not found — skipping DB init.")
        return

    db = sqlite3.connect(Config.DB_PATH)
    db.execute("PRAGMA foreign_keys=ON")
    with open(schema_path, "r", encoding="utf-8") as f:
        db.executescript(f.read())

    # Migration: add current_status and employee_id columns if missing
    cur = db.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cur.fetchall()]
    if "current_status" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN current_status TEXT NOT NULL DEFAULT 'Available'")
        db.commit()

    if "employee_id" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN employee_id TEXT")
        db.commit()

    # Populate missing employee_ids
    users_without_empid = db.execute("SELECT id FROM users WHERE employee_id IS NULL OR employee_id = ''").fetchall()
    for row in users_without_empid:
        uid = row[0]
        emp_code = f"EMP-{1000 + uid}"
        db.execute("UPDATE users SET employee_id = ? WHERE id = ?", (emp_code, uid))
    db.commit()

    db.close()
    app.logger.info(f"Database initialized at {Config.DB_PATH}")


# Run DB init on startup
with app.app_context():
    init_db()


# ============================================================
# User Model (Flask-Login)
# ============================================================
class User(UserMixin):
    """Lightweight user wrapper for Flask-Login."""

    def __init__(self, id, full_name, email, password_hash, role, employee_id=None, current_status="Available", created_at=None):
        self.id = id
        self.employee_id = employee_id or f"EMP-{1000 + id}"
        self.full_name = full_name
        self.email = email
        self.password_hash = password_hash
        self.role = role  # 'Admin' or 'Employee'
        self.current_status = current_status or "Available"
        self.created_at = created_at

    @property
    def is_admin(self):
        return self.role == "Admin"


@login_manager.user_loader
def load_user(user_id):
    """Callback required by Flask-Login to reload a user from the session."""
    try:
        row = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    except Exception:
        return None
    if row:
        return User(**row)
    return None


# ============================================================
# Decorators
# ============================================================
def admin_required(f):
    """Restrict a view to Admin users only."""
    @functools.wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ============================================================
# Routes — Authentication
# ============================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    """Render login form and authenticate user."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        try:
            row = query_db("SELECT * FROM users WHERE email = ?", (email,), one=True)
        except Exception:
            flash("A database error occurred. Please try again.", "error")
            return render_template("login.html")

        if row and check_password_hash(row["password_hash"], password):
            user = User(**row)
            login_user(user)
            flash(f"Welcome back, {user.full_name}!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Render registration form and create a new Employee user."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        # Basic validation
        errors = []
        if not full_name:
            errors.append("Full name is required.")
        if not email:
            errors.append("Email is required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("register.html")

        # Check for duplicate email
        try:
            existing = query_db("SELECT id FROM users WHERE email = ?", (email,), one=True)
        except Exception:
            flash("A database error occurred. Please try again.", "error")
            return render_template("register.html")

        if existing:
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        employee_id_input = request.form.get("employee_id", "").strip().upper()

        # Create user (default role: Employee)
        hashed = generate_password_hash(password)
        try:
            new_id = execute_db(
                "INSERT INTO users (full_name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                (full_name, email, hashed, "Employee"),
            )
            final_emp_id = employee_id_input or f"EMP-{1000 + new_id}"
            execute_db("UPDATE users SET employee_id = ? WHERE id = ?", (final_emp_id, new_id))
        except Exception:
            flash("Could not create account. Please try again.", "error")
            return render_template("register.html")

        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    """Log out the current user and redirect to login."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ============================================================
# Routes — Dashboard Router
# ============================================================
@app.route("/")
@app.route("/dashboard")
@login_required
def dashboard():
    """Redirect to role-appropriate dashboard."""
    if current_user.is_admin:
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("employee_dashboard"))


# ============================================================
# Routes — Admin Dashboard
# ============================================================
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """Admin view: all teams, projects, tasks, users, and tickets."""
    teams = query_db("SELECT * FROM teams ORDER BY team_name")
    projects = query_db("""
        SELECT p.*, t.team_name
        FROM projects p
        JOIN teams t ON p.team_id = t.id
        ORDER BY p.created_at DESC
    """)
    tasks = query_db("""
        SELECT tk.*, p.title AS project_title, u.full_name AS assignee_name, u.employee_id AS assignee_emp_id, u.current_status AS assignee_status
        FROM tasks tk
        JOIN projects p ON tk.project_id = p.id
        LEFT JOIN users u ON tk.assigned_to = u.id
        ORDER BY tk.due_date ASC
    """)
    users = query_db("SELECT id, employee_id, full_name, email, role, current_status FROM users ORDER BY full_name")
    tickets = query_db("""
        SELECT tk.*, u.full_name AS author_name, u.email AS author_email, u.employee_id AS author_emp_id,
               adm.full_name AS replier_name
        FROM tickets tk
        JOIN users u ON tk.user_id = u.id
        LEFT JOIN users adm ON tk.replied_by = adm.id
        ORDER BY tk.created_at DESC
    """)
    return render_template(
        "admin_dashboard.html",
        teams=teams, projects=projects, tasks=tasks, users=users, tickets=tickets,
    )


# ============================================================
# Routes — Admin CRUD
# ============================================================
@app.route("/admin/teams", methods=["POST"])
@admin_required
def create_team():
    """Create a new team."""
    name = request.form.get("team_name", "").strip()
    desc = request.form.get("description", "").strip()

    if not name:
        flash("Team name is required.", "error")
        return redirect(url_for("admin_dashboard"))

    execute_db("INSERT INTO teams (team_name, description) VALUES (?, ?)", (name, desc))
    flash(f'Team "{name}" created.', "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/teams/<int:team_id>/members", methods=["POST"])
@admin_required
def add_team_member(team_id):
    """Add a user to a team."""
    user_id = request.form.get("user_id")
    if not user_id:
        flash("Please select a user.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        execute_db(
            "INSERT INTO team_members (user_id, team_id) VALUES (?, ?)",
            (user_id, team_id),
        )
        flash("Member added to team.", "success")
    except sqlite3.IntegrityError:
        flash("User is already a member of this team.", "warning")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/projects", methods=["POST"])
@admin_required
def create_project():
    """Create a new project under a team."""
    title = request.form.get("title", "").strip()
    desc = request.form.get("description", "").strip()
    team_id = request.form.get("team_id")

    if not title or not team_id:
        flash("Project title and team are required.", "error")
        return redirect(url_for("admin_dashboard"))

    execute_db(
        "INSERT INTO projects (title, description, team_id) VALUES (?, ?, ?)",
        (title, desc, team_id),
    )
    flash(f'Project "{title}" created.', "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/projects/<int:project_id>/status", methods=["POST"])
@admin_required
def update_project_status(project_id):
    """Toggle project status between Ongoing and Completed."""
    new_status = request.form.get("status")
    if new_status not in ("Ongoing", "Completed"):
        flash("Invalid status.", "error")
        return redirect(url_for("admin_dashboard"))

    execute_db("UPDATE projects SET status = ? WHERE id = ?", (new_status, project_id))
    flash("Project status updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/tasks", methods=["POST"])
@admin_required
def create_task():
    """Create and assign a task within a project."""
    title = request.form.get("title", "").strip()
    project_id = request.form.get("project_id")
    assigned_to = request.form.get("assigned_to") or None
    due_date = request.form.get("due_date") or None

    if not title or not project_id:
        flash("Task title and project are required.", "error")
        return redirect(url_for("admin_dashboard"))

    execute_db(
        "INSERT INTO tasks (title, project_id, assigned_to, due_date) VALUES (?, ?, ?, ?)",
        (title, project_id, assigned_to, due_date),
    )

    if assigned_to:
        create_notification(
            assigned_to,
            "New Task Assigned",
            f"You were assigned to task '{title}'.",
            link="/employee/dashboard"
        )

    flash(f'Task "{title}" created.', "success")
    return redirect(url_for("admin_dashboard"))


# ============================================================
# Routes — Employee Dashboard
# ============================================================
@app.route("/employee/dashboard")
@login_required
def employee_dashboard():
    """Employee view: tasks assigned to the current user, grouped by status."""
    tasks = query_db("""
        SELECT tk.*, p.title AS project_title
        FROM tasks tk
        JOIN projects p ON tk.project_id = p.id
        WHERE tk.assigned_to = ?
        ORDER BY tk.due_date ASC
    """, (current_user.id,))

    # Group tasks by status for kanban-style display
    grouped = {"To-Do": [], "In-Progress": [], "Done": []}
    for task in tasks:
        grouped.get(task["status"], grouped["To-Do"]).append(task)

    team_members = query_db("SELECT id, employee_id, full_name, email, role, current_status FROM users ORDER BY full_name")

    tickets = query_db("""
        SELECT tk.*, adm.full_name AS replier_name
        FROM tickets tk
        LEFT JOIN users adm ON tk.replied_by = adm.id
        WHERE tk.user_id = ?
        ORDER BY tk.created_at DESC
    """, (current_user.id,))

    return render_template(
        "employee_dashboard.html",
        grouped=grouped, team_members=team_members, tickets=tickets,
    )


@app.route("/employee/tasks/<int:task_id>/status", methods=["POST"])
@login_required
def update_task_status(task_id):
    """Allow an employee to update the status of their own task."""
    new_status = request.form.get("status")
    if new_status not in ("To-Do", "In-Progress", "Done"):
        flash("Invalid status.", "error")
        return redirect(url_for("employee_dashboard"))

    # Verify the task is assigned to the current user
    task = query_db(
        "SELECT * FROM tasks WHERE id = ? AND assigned_to = ?",
        (task_id, current_user.id), one=True,
    )
    if not task:
        flash("Task not found or not assigned to you.", "error")
        return redirect(url_for("employee_dashboard"))

    execute_db("UPDATE tasks SET status = ? WHERE id = ?", (new_status, task_id))
    flash(f'Task status updated to "{new_status}".', "success")
    return redirect(url_for("employee_dashboard"))


# ============================================================
# Routes — API (JSON endpoints for async frontend)
# ============================================================
@app.route("/api/tasks/<int:task_id>/status", methods=["POST"])
@login_required
@csrf.exempt  # AJAX JSON requests; auth via @login_required
def api_update_task_status(task_id):
    """API: Update task status via drag-and-drop (returns JSON)."""
    data = request.get_json(silent=True)
    if not data or "status" not in data:
        return jsonify({"error": "Missing status"}), 400

    new_status = data["status"]
    if new_status not in ("To-Do", "In-Progress", "Done"):
        return jsonify({"error": "Invalid status"}), 400

    # Employees can only move their own tasks; admins can move any
    if not current_user.is_admin:
        task = query_db(
            "SELECT * FROM tasks WHERE id = ? AND assigned_to = ?",
            (task_id, current_user.id), one=True,
        )
        if not task:
            return jsonify({"error": "Task not found or not assigned to you"}), 403
    else:
        task = query_db("SELECT * FROM tasks WHERE id = ?", (task_id,), one=True)
        if not task:
            return jsonify({"error": "Task not found"}), 404

    old_status = task["status"]
    execute_db("UPDATE tasks SET status = ? WHERE id = ?", (new_status, task_id))

    return jsonify({
        "ok": True,
        "task_id": task_id,
        "old_status": old_status,
        "status": new_status,
    })


@app.route("/api/user/status", methods=["POST"])
@login_required
@csrf.exempt
def api_update_user_status():
    """API: Update current logged-in employee's availability status."""
    data = request.get_json(silent=True) or request.form
    new_status = data.get("status")
    valid_statuses = ("Available", "On Call", "On Leave", "Offline")
    if not new_status or new_status not in valid_statuses:
        return jsonify({"error": "Invalid status", "valid_statuses": list(valid_statuses)}), 400

    execute_db("UPDATE users SET current_status = ? WHERE id = ?", (new_status, current_user.id))
    current_user.current_status = new_status
    return jsonify({"ok": True, "current_status": new_status})


# ============================================================
# Routes — Support Tickets & Admin Replies
# ============================================================
@app.route("/tickets/create", methods=["POST"])
@login_required
def create_ticket():
    """Employee: Raise a new support ticket to admins."""
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    priority = request.form.get("priority", "Medium")

    if not title or not description:
        flash("Title and description are required.", "error")
        return redirect(request.referrer or url_for("dashboard"))

    if priority not in ("Low", "Medium", "High", "Urgent"):
        priority = "Medium"

    ticket_id = execute_db(
        "INSERT INTO tickets (user_id, title, description, priority, status) VALUES (?, ?, ?, ?, 'Open')",
        (current_user.id, title, description, priority)
    )

    # Notify all admin users
    admins = query_db("SELECT id FROM users WHERE role = 'Admin'")
    for a in admins:
        create_notification(
            a["id"],
            f"New Support Ticket #{ticket_id}",
            f"{current_user.full_name} raised ticket: '{title}'",
            link="/admin/dashboard"
        )

    flash("Support ticket submitted successfully!", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/admin/tickets/<int:ticket_id>/reply", methods=["POST"])
@admin_required
def reply_ticket(ticket_id):
    """Admin: Reply to a support ticket and update status."""
    admin_reply = request.form.get("admin_reply", "").strip()
    status = request.form.get("status", "Resolved")

    ticket = query_db("SELECT * FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        flash("Ticket not found.", "error")
        return redirect(url_for("admin_dashboard"))

    if status not in ("Open", "In-Progress", "Resolved", "Closed"):
        status = "In-Progress"

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    execute_db(
        "UPDATE tickets SET admin_reply = ?, replied_by = ?, replied_at = ?, status = ? WHERE id = ?",
        (admin_reply or ticket.get("admin_reply"), current_user.id, now_str, status, ticket_id)
    )

    # Notify employee ticket creator
    create_notification(
        ticket["user_id"],
        f"Ticket #{ticket_id} Updated",
        f"Admin replied to your ticket '{ticket['title']}' (Status: {status})",
        link="/employee/dashboard"
    )

    flash("Ticket updated and response sent to employee.", "success")
    return redirect(url_for("admin_dashboard"))


# ============================================================
# Routes — Notifications API
# ============================================================
@app.route("/api/notifications", methods=["GET"])
@login_required
def api_get_notifications():
    """API: Fetch unread count and latest 10 notifications for current user."""
    unread = query_db(
        "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ? AND is_read = 0",
        (current_user.id,), one=True
    )
    unread_count = unread["count"] if unread else 0

    items = query_db("""
        SELECT id, title, message, link, is_read, created_at
        FROM notifications
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 10
    """, (current_user.id,))

    return jsonify({
        "unread_count": unread_count,
        "notifications": items or []
    })


@app.route("/api/notifications/read-all", methods=["POST"])
@login_required
@csrf.exempt
def api_mark_notifications_read():
    """API: Mark all unread notifications as read for current user."""
    execute_db("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (current_user.id,))
    return jsonify({"ok": True})


# ============================================================
# Routes — Live Chat Hub (Project & Direct Employee Messaging)
# ============================================================
@app.route("/chat")
@login_required
def chat_hub():
    """Live Chat Hub for project channels & direct employee messaging."""
    if current_user.is_admin:
        projects = query_db("SELECT p.*, t.team_name FROM projects p JOIN teams t ON p.team_id = t.id ORDER BY p.title")
    else:
        projects = query_db("""
            SELECT DISTINCT p.*, t.team_name
            FROM projects p
            JOIN teams t ON p.team_id = t.id
            JOIN team_members tm ON tm.team_id = t.id
            WHERE tm.user_id = ?
            ORDER BY p.title
        """, (current_user.id,))
        if not projects:
            projects = query_db("SELECT p.*, t.team_name FROM projects p JOIN teams t ON p.team_id = t.id ORDER BY p.title")

    colleagues = query_db(
        "SELECT id, employee_id, full_name, email, role, current_status FROM users WHERE id != ? ORDER BY full_name",
        (current_user.id,)
    )

    return render_template("chat.html", projects=projects or [], colleagues=colleagues or [])


@app.route("/api/chat/project/<int:project_id>", methods=["GET"])
@login_required
def api_get_project_chat(project_id):
    """API: Fetch message history for a project channel."""
    messages = query_db("""
        SELECT cm.*, u.full_name AS sender_name, u.role AS sender_role
        FROM chat_messages cm
        JOIN users u ON cm.sender_id = u.id
        WHERE cm.chat_type = 'project' AND cm.project_id = ?
        ORDER BY cm.created_at ASC
        LIMIT 100
    """, (project_id,))
    return jsonify(messages or [])


@app.route("/api/chat/direct/<int:user_id>", methods=["GET"])
@login_required
def api_get_direct_chat(user_id):
    """API: Fetch 1-on-1 message history between current user and target colleague."""
    messages = query_db("""
        SELECT cm.*, u.full_name AS sender_name, u.role AS sender_role
        FROM chat_messages cm
        JOIN users u ON cm.sender_id = u.id
        WHERE cm.chat_type = 'direct'
          AND ((cm.sender_id = ? AND cm.recipient_id = ?) OR (cm.sender_id = ? AND cm.recipient_id = ?))
        ORDER BY cm.created_at ASC
        LIMIT 100
    """, (current_user.id, user_id, user_id, current_user.id))
    return jsonify(messages or [])


@app.route("/api/chat/send", methods=["POST"])
@login_required
@csrf.exempt
def api_send_chat_message():
    """API: Send a message in a project channel or direct 1-on-1 chat."""
    data = request.get_json(silent=True) or request.form
    chat_type = data.get("chat_type")
    message = (data.get("message") or "").strip()

    if not chat_type or not message:
        return jsonify({"error": "Message content is required"}), 400

    if chat_type == "project":
        project_id = data.get("project_id")
        if not project_id:
            return jsonify({"error": "Missing project_id"}), 400

        project = query_db("SELECT * FROM projects WHERE id = ?", (project_id,), one=True)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        msg_id = execute_db(
            "INSERT INTO chat_messages (sender_id, chat_type, project_id, message) VALUES (?, 'project', ?, ?)",
            (current_user.id, project_id, message)
        )

        return jsonify({"ok": True, "id": msg_id, "sender_name": current_user.full_name})

    elif chat_type == "direct":
        recipient_id = data.get("recipient_id")
        if not recipient_id:
            return jsonify({"error": "Missing recipient_id"}), 400

        recipient = query_db("SELECT * FROM users WHERE id = ?", (recipient_id,), one=True)
        if not recipient:
            return jsonify({"error": "Recipient not found"}), 404

        msg_id = execute_db(
            "INSERT INTO chat_messages (sender_id, chat_type, recipient_id, message) VALUES (?, 'direct', ?, ?)",
            (current_user.id, recipient_id, message)
        )

        # Notify recipient of new direct message
        create_notification(
            recipient_id,
            f"New message from {current_user.full_name}",
            f"{current_user.full_name}: {message[:60]}{'...' if len(message) > 60 else ''}",
            link="/chat"
        )

        return jsonify({"ok": True, "id": msg_id, "sender_name": current_user.full_name})

    return jsonify({"error": "Invalid chat_type"}), 400


# ============================================================
# Routes — Health Check (CI/CD & IIS monitoring)
# ============================================================
@app.route("/health")
@csrf.exempt  # Health check should not require CSRF token
def health_check():
    """
    Returns JSON health status.
    Used by Docker HEALTHCHECK, IIS Application Request Routing,
    and CI/CD pipelines for readiness probes.
    """
    status = {"status": "healthy", "db": "disconnected", "timestamp": datetime.utcnow().isoformat()}
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        status["db"] = "connected"
    except Exception as e:
        status["status"] = "unhealthy"
        status["error"] = str(e)
        return jsonify(status), 503

    return jsonify(status), 200


# ============================================================
# Error Handlers
# ============================================================
@app.errorhandler(404)
def not_found(e):
    return render_template("base.html", error_code=404, error_msg="Page not found."), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("base.html", error_code=500, error_msg="Internal server error."), 500


# ============================================================
# Entry Point
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=Config.DEBUG)
