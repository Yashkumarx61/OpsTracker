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

import csv
import functools
import io
import os
import random
import sqlite3
import time
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, g, Response, session
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


@app.after_request
def set_security_headers(response):
    """Enforce defense-in-depth security headers on all HTTP responses."""
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


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
            db_dir = os.path.dirname(Config.DB_PATH)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
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

    db_dir = os.path.dirname(Config.DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    db = sqlite3.connect(Config.DB_PATH)
    db.execute("PRAGMA foreign_keys=ON")

    # Execute schema.sql first to ensure all tables exist
    with open(schema_path, "r", encoding="utf-8") as f:
        db.executescript(f.read())

    # Migration: add columns if missing and migrate legacy values
    try:
        cur = db.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cur.fetchall()]
        if columns:
            if "current_status" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN current_status TEXT NOT NULL DEFAULT 'Available'")
            if "employee_id" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN employee_id TEXT")
            if "status" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'")
            if "department" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN department TEXT DEFAULT 'General'")
            if "job_title" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN job_title TEXT DEFAULT 'Employee'")
            if "phone" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
            db.commit()

        cur_t = db.execute("PRAGMA table_info(tasks)")
        t_cols = [row[1] for row in cur_t.fetchall()]
        if t_cols:
            sql_row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()
            if sql_row and sql_row[0] and "('To-Do', 'In-Progress', 'Done')" in sql_row[0]:
                db.execute("ALTER TABLE tasks RENAME TO tasks_old")
                db.execute("""
                    CREATE TABLE tasks (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        title        TEXT NOT NULL,
                        description  TEXT,
                        status       TEXT NOT NULL DEFAULT 'Backlog' CHECK(status IN ('Backlog', 'In Progress', 'Under Review', 'Completed', 'Blocked')),
                        priority     TEXT NOT NULL DEFAULT 'Medium' CHECK(priority IN ('Low', 'Medium', 'High', 'Critical / Blocker', 'Urgent')),
                        category_tag TEXT NOT NULL DEFAULT 'Feature',
                        due_date     TEXT,
                        project_id   INTEGER NOT NULL,
                        assigned_to  INTEGER,
                        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                        FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL
                    )
                """)
                db.execute("""
                    INSERT INTO tasks (id, title, description, status, priority, category_tag, due_date, project_id, assigned_to, created_at)
                    SELECT id, title,
                        CASE WHEN instr(sql_old, 'description') > 0 THEN description ELSE NULL END,
                        CASE status
                            WHEN 'To-Do' THEN 'Backlog'
                            WHEN 'In-Progress' THEN 'In Progress'
                            WHEN 'Done' THEN 'Completed'
                            ELSE 'Backlog'
                        END,
                        'Medium', 'Feature', due_date, project_id, assigned_to, created_at
                    FROM (SELECT *, (SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks_old') as sql_old FROM tasks_old)
                """)
                db.execute("DROP TABLE tasks_old")
                db.commit()
            else:
                if "description" not in t_cols:
                    db.execute("ALTER TABLE tasks ADD COLUMN description TEXT")
                if "priority" not in t_cols:
                    db.execute("ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'Medium'")
                if "category_tag" not in t_cols:
                    db.execute("ALTER TABLE tasks ADD COLUMN category_tag TEXT NOT NULL DEFAULT 'Feature'")
                db.commit()
                db.execute("UPDATE tasks SET status = 'Backlog' WHERE status = 'To-Do'")
                db.execute("UPDATE tasks SET status = 'Completed' WHERE status = 'Done'")
                db.execute("UPDATE tasks SET status = 'In Progress' WHERE status = 'In-Progress'")
                db.commit()
    except Exception as e:
        app.logger.warning(f"Migration check warning: {e}")

    # Ensure all users have status populated
    db.execute("UPDATE users SET status = 'approved' WHERE status IS NULL OR status = ''")
    db.commit()

    # Populate missing or invalid employee_ids (e.g., if set to email)
    users_invalid_empid = db.execute("SELECT id FROM users WHERE employee_id IS NULL OR employee_id = '' OR employee_id LIKE '%@%'").fetchall()
    for row in users_invalid_empid:
        uid = row[0]
        emp_code = f"EMP-{1000 + uid}"
        db.execute("UPDATE users SET employee_id = ? WHERE id = ?", (emp_code, uid))
    db.commit()

    # Sanitize seed typos in task titles
    try:
        db.execute("UPDATE tasks SET title = REPLACE(title, 'Updrade', 'Upgrade') WHERE title LIKE '%Updrade%'")
        db.commit()
    except Exception as e:
        app.logger.warning(f"Seed typo fix warning: {e}")

    # Unique index on team_name
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_name ON teams(team_name)")
        db.commit()
    except Exception as e:
        app.logger.warning(f"Team name index warning: {e}")

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

    def __init__(self, id, full_name, email, password_hash, role, employee_id=None, current_status="Available", status="approved", department="General", job_title="Employee", phone="", created_at=None):
        self.id = id
        self.employee_id = employee_id or f"EMP-{1000 + id}"
        self.full_name = full_name
        self.email = email
        self.password_hash = password_hash
        self.role = role  # 'Admin', 'Project Lead', 'Employee'
        self.current_status = current_status or "Available"
        self.status = status or "approved"
        self.department = department or "General"
        self.job_title = job_title or "Employee"
        self.phone = phone or ""
        self.created_at = created_at

    @property
    def is_admin(self):
        return self.role == "Admin"

    @property
    def is_lead(self):
        return self.role in ("Admin", "Project Lead")

    @property
    def is_approved(self):
        return self.status == "approved"

    @property
    def is_pending(self):
        return self.status == "pending"

    @property
    def is_rejected(self):
        return self.status == "rejected"

    @property
    def is_terminated(self):
        return self.status == "terminated"


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
            user_status = row.get("status") or "approved"
            if user_status == "pending":
                flash("Your account is pending admin approval.", "warning")
                return render_template("login.html")
            elif user_status == "rejected":
                flash("Your registration request was declined.", "error")
                return render_template("login.html")
            elif user_status == "terminated":
                flash("Your account has been terminated. Please contact HR.", "error")
                return render_template("login.html")
            elif user_status == "approved":
                user = User(**row)
                login_user(user)
                flash(f"Welcome back, {user.full_name}!", "success")
                next_page = request.args.get("next")
                return redirect(next_page or url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Render registration form and submit new user for admin approval."""
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

        # Create user with 'pending' status
        hashed = generate_password_hash(password)
        try:
            new_id = execute_db(
                "INSERT INTO users (full_name, email, password_hash, role, status) VALUES (?, ?, ?, ?, ?)",
                (full_name, email, hashed, "Employee", "pending"),
            )
            final_emp_id = employee_id_input or f"EMP-{1000 + new_id}"
            execute_db("UPDATE users SET employee_id = ? WHERE id = ?", (final_emp_id, new_id))

            # Notify admin users
            admins = query_db("SELECT id FROM users WHERE role = 'Admin'")
            for a in admins:
                create_notification(
                    a["id"],
                    "Pending Registration Request",
                    f"New registration request from {full_name} ({email}).",
                    link="/admin/dashboard"
                )
        except Exception as e:
            app.logger.error(f"Failed to create pending account: {e}")
            flash("Could not create account. Please try again.", "error")
            return render_template("register.html")

        flash("Your registration request has been submitted and is pending administrator approval. You will receive access once approved.", "info")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Step 1: Accept email/username and generate 5-digit OTP."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email:
            flash("Please enter your email or username.", "error")
            return render_template("forgot_password.html")

        # Check if user exists
        user = query_db("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if not user:
            flash("No registered account found with that email.", "error")
            return render_template("forgot_password.html")

        # Generate 5-digit numeric OTP
        otp_code = str(random.randint(10000, 99999))
        session["reset_email"] = email
        session["reset_otp"] = otp_code
        session["reset_otp_expiry"] = time.time() + 600  # 10 minute expiry

        app.logger.info(f"Password reset request initiated for email: {email}")
        flash(f"Security OTP code generated: {otp_code} (Valid for 10 minutes)", "info")
        return redirect(url_for("verify_otp"))

    return render_template("forgot_password.html")


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    """Step 2: Verify 5-digit OTP code."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    email = session.get("reset_email")
    if not email:
        flash("Password reset session expired. Please start over.", "warning")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        # Handle individual digit inputs or combined OTP
        d1 = request.form.get("otp_1", "")
        d2 = request.form.get("otp_2", "")
        d3 = request.form.get("otp_3", "")
        d4 = request.form.get("otp_4", "")
        d5 = request.form.get("otp_5", "")
        entered_otp = (d1 + d2 + d3 + d4 + d5).strip() or request.form.get("otp", "").strip()

        stored_otp = session.get("reset_otp")
        expiry = session.get("reset_otp_expiry", 0)

        if time.time() > expiry:
            flash("OTP has expired. Please request a new code.", "error")
            return redirect(url_for("forgot_password"))

        if entered_otp and entered_otp == stored_otp:
            session["otp_verified"] = True
            flash("OTP verified successfully. Please enter your new password.", "success")
            return redirect(url_for("reset_password"))
        else:
            flash("Invalid OTP code. Please check and try again.", "error")

    return render_template("verify_otp.html", email=email)


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    """Step 3: Reset password for verified session."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    email = session.get("reset_email")
    if not email or not session.get("otp_verified"):
        flash("Unauthorized access or session expired. Please request OTP first.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("reset_password.html")

        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html")

        try:
            pwd_hash = generate_password_hash(password)
            db = get_db()
            db.execute("UPDATE users SET password_hash = ? WHERE email = ?", (pwd_hash, email))
            db.commit()

            # Clean up reset session variables
            session.pop("reset_email", None)
            session.pop("reset_otp", None)
            session.pop("reset_otp_expiry", None)
            session.pop("otp_verified", None)

            flash("Password reset successfully! Please log in with your new password.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            app.logger.error(f"Failed to reset password for {email}: {e}")
            flash("Failed to update password. Please try again.", "error")

    return render_template("reset_password.html")


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
# Routes — User Profile (Self-Service)
# ============================================================
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """View and update logged-in user profile details."""
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        department = request.form.get("department", "").strip()
        job_title = request.form.get("job_title", "").strip()
        phone = request.form.get("phone", "").strip()

        if not full_name:
            flash("Full name is required.", "error")
            return redirect(url_for("profile"))

        execute_db(
            "UPDATE users SET full_name = ?, department = ?, job_title = ?, phone = ? WHERE id = ?",
            (full_name, department or "General", job_title or "Employee", phone, current_user.id)
        )
        current_user.full_name = full_name
        current_user.department = department or "General"
        current_user.job_title = job_title or "Employee"
        current_user.phone = phone

        flash("Profile details updated successfully.", "success")
        return redirect(url_for("profile"))

    return render_template("profile.html")


# ============================================================
# Routes — Admin Dashboard & Approval / Employee Directory
# ============================================================
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """Admin executive dashboard with metrics, workload, tasks, teams, projects, tickets, and user offboarding."""
    teams = query_db("SELECT DISTINCT id, team_name, description FROM teams ORDER BY team_name ASC")
    projects = query_db("""
        SELECT p.*, t.team_name
        FROM projects p
        JOIN teams t ON p.team_id = t.id
        ORDER BY p.created_at DESC
    """)
    tasks = query_db("""
        SELECT tk.*, p.title AS project_title, u.full_name AS assignee_name, u.employee_id AS assignee_emp_id, u.current_status AS assignee_status, u.department AS assignee_dept
        FROM tasks tk
        JOIN projects p ON tk.project_id = p.id
        LEFT JOIN users u ON tk.assigned_to = u.id
        ORDER BY tk.created_at DESC
    """)

    # Active non-terminated approved users for task assignments
    users = query_db("SELECT id, employee_id, full_name, email, role, current_status, status, department, job_title, phone FROM users WHERE status = 'approved' OR status IS NULL ORDER BY full_name")

    # Pending registration users
    pending_users = query_db("SELECT id, employee_id, full_name, email, role, status, created_at, department, job_title FROM users WHERE status = 'pending' ORDER BY created_at DESC")

    # All employee directory (including active, pending, and terminated)
    all_employees = query_db("SELECT id, employee_id, full_name, email, role, current_status, status, department, job_title, phone, created_at FROM users ORDER BY status ASC, full_name ASC")

    tickets = query_db("""
        SELECT tk.*, u.full_name AS author_name, u.email AS author_email, u.employee_id AS author_emp_id,
               adm.full_name AS replier_name
        FROM tickets tk
        JOIN users u ON tk.user_id = u.id
        LEFT JOIN users adm ON tk.replied_by = adm.id
        ORDER BY tk.created_at DESC
    """)

    # Executive Metrics Computation (Safely computed Resolution Velocity %)
    total_tasks = len(tasks)
    completed_tasks = len([t for t in tasks if t["status"] == "Completed"])
    total_active_tasks = len([t for t in tasks if t["status"] != "Completed"])

    import datetime
    today_str = datetime.date.today().isoformat()
    overdue_count = len([t for t in tasks if t["due_date"] and t["due_date"] < today_str and t["status"] != "Completed"])

    velocity = round((completed_tasks / total_tasks) * 100, 1) if total_tasks > 0 else 0.0
    bottleneck_alerts = len([t for t in tasks if t["status"] == "Blocked" or (t["due_date"] and t["due_date"] < today_str and t["status"] != "Completed")])

    metrics = {
        "active_tasks": total_active_tasks,
        "overdue_count": overdue_count,
        "velocity": velocity,
        "resolution_velocity": velocity,
        "bottlenecks": bottleneck_alerts
    }

    # Group tasks for 5-state Kanban Board
    kanban_tasks = {
        "Backlog": [],
        "In Progress": [],
        "Under Review": [],
        "Completed": [],
        "Blocked": []
    }
    for t in tasks:
        st = t["status"]
        if st == "To-Do": st = "Backlog"
        elif st == "Done": st = "Completed"
        elif st == "In-Progress": st = "In Progress"
        kanban_tasks.get(st, kanban_tasks["Backlog"]).append(t)

    # Workload Distribution per Employee
    workload = []
    for u in users:
        emp_tasks = [t for t in tasks if t["assigned_to"] == u["id"] and t["status"] != "Completed"]
        workload.append({
            "user_id": u["id"],
            "full_name": u["full_name"],
            "employee_id": u["employee_id"],
            "department": u["department"] or "General",
            "active_count": len(emp_tasks),
            "task_count": len(emp_tasks)
        })
    workload.sort(key=lambda x: x["active_count"], reverse=True)

    return render_template(
        "admin_dashboard.html",
        teams=teams, projects=projects, tasks=tasks, users=users,
        pending_users=pending_users, all_employees=all_employees, tickets=tickets,
        metrics=metrics, kanban_tasks=kanban_tasks, workload=workload,
    )


@app.route("/admin/users/<int:user_id>/approve", methods=["POST"])
@admin_required
def approve_user(user_id):
    """Admin: Approve a pending user registration request."""
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin_dashboard"))

    execute_db("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
    create_notification(
        user_id,
        "Registration Approved",
        "Your account registration has been approved by an administrator! You may now log in to OpsTracker.",
        link="/login"
    )
    flash(f"User registration for '{user['full_name']}' has been approved.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/<int:user_id>/reject", methods=["POST"])
@admin_required
def reject_user(user_id):
    """Admin: Reject a pending user registration request."""
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin_dashboard"))

    execute_db("UPDATE users SET status = 'rejected' WHERE id = ?", (user_id,))
    flash(f"User registration request for '{user['full_name']}' was declined.", "info")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/<int:user_id>/terminate", methods=["POST"])
@admin_required
def terminate_user(user_id):
    """Admin: Terminate/offboard an employee account with Employee ID confirmation verification."""
    if user_id == current_user.id:
        flash("You cannot terminate your own admin account.", "error")
        return redirect(url_for("admin_dashboard"))

    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin_dashboard"))

    target_emp_id = request.form.get("target_emp_id", "").strip().upper()
    expected_emp_id = (user.get("employee_id") or f"EMP-{1000 + user['id']}").strip().upper()

    if target_emp_id != expected_emp_id:
        flash(f"Verification Failed: Confirmation Employee ID '{target_emp_id}' does not match '{expected_emp_id}'. Account offboarding cancelled.", "error")
        return redirect(url_for("admin_dashboard"))

    execute_db("UPDATE users SET status = 'terminated' WHERE id = ?", (user_id,))
    flash(f"Employee '{user['full_name']}' ({expected_emp_id}) has been terminated and offboarded.", "warning")
    return redirect(url_for("admin_dashboard"))



@app.route("/admin/users/<int:user_id>/reactivate", methods=["POST"])
@admin_required
def reactivate_user(user_id):
    """Admin: Reactivate a terminated employee account."""
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin_dashboard"))

    execute_db("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
    flash(f"Employee '{user['full_name']}' account has been reactivated.", "success")
    return redirect(url_for("admin_dashboard"))


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
    desc = request.form.get("description", "").strip()
    project_id = request.form.get("project_id")
    assigned_to = request.form.get("assigned_to") or None
    priority = request.form.get("priority", "Medium")
    category_tag = request.form.get("category_tag", "Feature")
    due_date = request.form.get("due_date") or None

    if not title or not project_id:
        flash("Task title and project are required.", "error")
        return redirect(url_for("admin_dashboard"))

    valid_priorities = ("Low", "Medium", "High", "Critical / Blocker")
    if priority not in valid_priorities: priority = "Medium"

    valid_tags = ("Frontend", "Backend", "Ops", "Bug", "Feature", "Security")
    if category_tag not in valid_tags: category_tag = "Feature"

    task_id = execute_db(
        "INSERT INTO tasks (title, description, status, priority, category_tag, project_id, assigned_to, due_date) VALUES (?, ?, 'Backlog', ?, ?, ?, ?, ?)",
        (title, desc, priority, category_tag, project_id, assigned_to, due_date),
    )

    execute_db(
        "INSERT INTO task_audit_logs (task_id, user_id, action, details) VALUES (?, ?, 'Task Created', ?)",
        (task_id, current_user.id, f"Created task '{title}' with priority '{priority}'")
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
    """Employee view: assigned tasks grouped by standardized workflow states, team availability, and tickets."""
    tasks = query_db("""
        SELECT tk.*, p.title AS project_title
        FROM tasks tk
        JOIN projects p ON tk.project_id = p.id
        WHERE tk.assigned_to = ?
        ORDER BY tk.due_date ASC
    """, (current_user.id,))

    # Group tasks by 5 workflow states
    grouped = {
        "Backlog": [],
        "In Progress": [],
        "Under Review": [],
        "Completed": [],
        "Blocked": []
    }
    for task in tasks:
        st = task["status"]
        if st == "To-Do": st = "Backlog"
        elif st == "Done": st = "Completed"
        elif st == "In-Progress": st = "In Progress"
        grouped.get(st, grouped["Backlog"]).append(task)

    team_members = query_db("SELECT id, employee_id, full_name, email, role, current_status, department, job_title FROM users WHERE status = 'approved' OR status IS NULL ORDER BY full_name")

    tickets = query_db("""
        SELECT tk.*, adm.full_name AS replier_name
        FROM tickets tk
        LEFT JOIN users adm ON tk.replied_by = adm.id
        WHERE tk.user_id = ?
        ORDER BY tk.created_at DESC
    """, (current_user.id,))

    return render_template(
        "employee_dashboard.html",
        grouped=grouped, tasks=tasks, team_members=team_members, tickets=tickets,
    )


@app.route("/employee/tasks/<int:task_id>/status", methods=["POST"])
@login_required
def update_task_status(task_id):
    """Allow an employee or admin to update the status of a task."""
    new_status = request.form.get("status")
    valid_statuses = ("Backlog", "In Progress", "Under Review", "Completed", "Blocked")
    if new_status not in valid_statuses:
        flash("Invalid status.", "error")
        return redirect(url_for("employee_dashboard"))

    if not current_user.is_admin:
        task = query_db(
            "SELECT * FROM tasks WHERE id = ? AND assigned_to = ?",
            (task_id, current_user.id), one=True,
        )
        if not task:
            flash("Task not found or not assigned to you.", "error")
            return redirect(url_for("employee_dashboard"))
    else:
        task = query_db("SELECT * FROM tasks WHERE id = ?", (task_id,), one=True)
        if not task:
            flash("Task not found.", "error")
            return redirect(url_for("admin_dashboard"))

    old_status = task["status"]
    execute_db("UPDATE tasks SET status = ? WHERE id = ?", (new_status, task_id))
    execute_db(
        "INSERT INTO task_audit_logs (task_id, user_id, action, details) VALUES (?, ?, 'Status Update', ?)",
        (task_id, current_user.id, f"Changed status from '{old_status}' to '{new_status}'")
    )
    flash(f'Task status updated to "{new_status}".', "success")
    return redirect(request.referrer or url_for("dashboard"))


# ============================================================
# Routes — API (Subtasks, Comments, Audit Logs, Export)
# ============================================================
@app.route("/api/tasks/<int:task_id>", methods=["GET"])
@login_required
def api_get_task_details(task_id):
    """API: Fetch complete task details, subtasks, comments, and audit log entries."""
    task = query_db("""
        SELECT tk.*, p.title AS project_title, u.full_name AS assignee_name, u.employee_id AS assignee_emp_id
        FROM tasks tk
        JOIN projects p ON tk.project_id = p.id
        LEFT JOIN users u ON tk.assigned_to = u.id
        WHERE tk.id = ?
    """, (task_id,), one=True)

    if not task:
        return jsonify({"error": "Task not found"}), 404

    subtasks = query_db("SELECT * FROM subtasks WHERE task_id = ? ORDER BY id ASC", (task_id,))
    comments = query_db("""
        SELECT tc.*, u.full_name AS author_name, u.role AS author_role
        FROM task_comments tc
        JOIN users u ON tc.user_id = u.id
        WHERE tc.task_id = ?
        ORDER BY tc.created_at ASC
    """, (task_id,))
    audit_logs = query_db("""
        SELECT al.*, u.full_name AS actor_name
        FROM task_audit_logs al
        JOIN users u ON al.user_id = u.id
        WHERE al.task_id = ?
        ORDER BY al.created_at DESC
    """, (task_id,))

    return jsonify({
        "task": task,
        "subtasks": subtasks,
        "comments": comments,
        "audit_logs": audit_logs
    })


@app.route("/api/tasks/<int:task_id>/subtasks", methods=["POST"])
@login_required
@csrf.exempt
def api_add_subtask(task_id):
    """API: Add a subtask checklist item."""
    data = request.get_json(silent=True) or request.form
    title = data.get("title", "").strip() if data else ""
    if not title:
        return jsonify({"error": "Subtask title is required"}), 400

    subtask_id = execute_db(
        "INSERT INTO subtasks (task_id, title) VALUES (?, ?)",
        (task_id, title)
    )
    execute_db(
        "INSERT INTO task_audit_logs (task_id, user_id, action, details) VALUES (?, ?, 'Added Subtask', ?)",
        (task_id, current_user.id, f"Added subtask item '{title}'")
    )
    return jsonify({"ok": True, "subtask_id": subtask_id, "title": title})


@app.route("/api/subtasks/<int:subtask_id>/toggle", methods=["POST"])
@login_required
@csrf.exempt
def api_toggle_subtask(subtask_id):
    """API: Toggle subtask completion status."""
    subtask = query_db("SELECT * FROM subtasks WHERE id = ?", (subtask_id,), one=True)
    if not subtask:
        return jsonify({"error": "Subtask not found"}), 404

    new_val = 0 if subtask["is_completed"] else 1
    execute_db("UPDATE subtasks SET is_completed = ? WHERE id = ?", (new_val, subtask_id))
    action_text = "Completed" if new_val else "Uncompleted"
    execute_db(
        "INSERT INTO task_audit_logs (task_id, user_id, action, details) VALUES (?, ?, ?, ?)",
        (subtask["task_id"], current_user.id, f"{action_text} Subtask", f"{action_text} checklist item '{subtask['title']}'")
    )
    return jsonify({"ok": True, "is_completed": new_val})


@app.route("/api/tasks/<int:task_id>/comments", methods=["POST"])
@login_required
@csrf.exempt
def api_add_task_comment(task_id):
    """API: Add a comment to a task."""
    data = request.get_json(silent=True) or request.form
    comment = data.get("comment", "").strip() if data else ""
    if not comment:
        return jsonify({"error": "Comment text cannot be empty"}), 400

    comment_id = execute_db(
        "INSERT INTO task_comments (task_id, user_id, comment) VALUES (?, ?, ?)",
        (task_id, current_user.id, comment)
    )
    execute_db(
        "INSERT INTO task_audit_logs (task_id, user_id, action, details) VALUES (?, ?, 'Posted Comment', ?)",
        (task_id, current_user.id, f"Added a comment")
    )
    return jsonify({
        "ok": True,
        "comment_id": comment_id,
        "author": current_user.full_name,
        "comment": comment,
        "created_at": "Just now"
    })


@app.route("/api/tasks/export", methods=["GET"])
@login_required
def export_tasks_csv():
    """Export tasks to downloadable CSV file."""

    tasks = query_db("""
        SELECT tk.id, tk.title, tk.description, tk.status, tk.priority, tk.category_tag, tk.due_date,
               p.title AS project_title, u.full_name AS assignee_name, u.employee_id AS assignee_emp_id, tk.created_at
        FROM tasks tk
        JOIN projects p ON tk.project_id = p.id
        LEFT JOIN users u ON tk.assigned_to = u.id
        ORDER BY tk.created_at DESC
    """)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Task ID", "Title", "Project", "Assignee Name", "Assignee Emp ID", "Status", "Priority", "Category Tag", "Due Date", "Created At", "Description"])

    for t in tasks:
        writer.writerow([
            t["id"], t["title"], t["project_title"], t["assignee_name"] or "Unassigned",
            t["assignee_emp_id"] or "N/A", t["status"], t["priority"], t["category_tag"],
            t["due_date"] or "No due date", t["created_at"], t["description"] or ""
        ])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=opstracker_tasks_export.csv"
    return response


@app.route("/api/tasks/<int:task_id>/status", methods=["POST"])
@login_required
@csrf.exempt
def api_update_task_status(task_id):
    """API: Update task status via drag-and-drop or select (returns JSON)."""
    data = request.get_json(silent=True) or request.form
    if not data or "status" not in data:
        return jsonify({"error": "Missing status"}), 400

    new_status = data["status"]
    if new_status == "To-Do": new_status = "Backlog"
    elif new_status == "Done": new_status = "Completed"
    elif new_status == "In-Progress": new_status = "In Progress"

    valid_statuses = ("Backlog", "In Progress", "Under Review", "Completed", "Blocked")
    if new_status not in valid_statuses:
        return jsonify({"error": f"Invalid status: {new_status}"}), 400

    if not current_user.is_admin:
        task = query_db("SELECT * FROM tasks WHERE id = ? AND assigned_to = ?", (task_id, current_user.id), one=True)
        if not task:
            return jsonify({"error": "Task not found or not assigned to you"}), 403
    else:
        task = query_db("SELECT * FROM tasks WHERE id = ?", (task_id,), one=True)
        if not task:
            return jsonify({"error": "Task not found"}), 404

    old_status = task["status"]
    execute_db("UPDATE tasks SET status = ? WHERE id = ?", (new_status, task_id))
    execute_db(
        "INSERT INTO task_audit_logs (task_id, user_id, action, details) VALUES (?, ?, 'Status Change', ?)",
        (task_id, current_user.id, f"Changed status from '{old_status}' to '{new_status}'")
    )

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
# Routes — User Preferences & Quick Action Modals
# ============================================================
@app.route("/api/user/preferences", methods=["POST"])
@login_required
def update_user_preferences():
    """API: Update user status, title, phone, department, or preferences."""
    data = request.get_json(silent=True) or request.form
    status = data.get("status", current_user.current_status)
    phone = data.get("phone", current_user.phone)
    job_title = data.get("job_title", current_user.job_title)
    department = data.get("department", current_user.department)

    if status in ("Available", "Busy", "Away", "Do Not Disturb", "On Call", "On Leave", "Offline"):
        execute_db(
            "UPDATE users SET current_status = ?, phone = ?, job_title = ?, department = ? WHERE id = ?",
            (status, phone, job_title, department, current_user.id)
        )
        current_user.current_status = status
        current_user.phone = phone
        current_user.job_title = job_title
        current_user.department = department

    return jsonify({"success": True, "status": status, "message": "Preferences updated successfully."})


@app.route("/api/quick/team", methods=["POST"])
@admin_required
def quick_create_team():
    """API: Modal quick-create team."""
    data = request.get_json(silent=True) or request.form
    name = data.get("team_name", "").strip()
    desc = data.get("description", "").strip()
    if not name:
        return jsonify({"error": "Team name is required"}), 400
    try:
        t_id = execute_db("INSERT INTO teams (team_name, description) VALUES (?, ?)", (name, desc))
        return jsonify({"success": True, "team_id": t_id, "team_name": name})
    except Exception as e:
        return jsonify({"error": "A team with this name already exists."}), 400


@app.route("/api/quick/project", methods=["POST"])
@admin_required
def quick_create_project():
    """API: Modal quick-create project."""
    data = request.get_json(silent=True) or request.form
    title = data.get("title", "").strip()
    desc = data.get("description", "").strip()
    team_id = data.get("team_id")
    if not title or not team_id:
        return jsonify({"error": "Project title and team selection are required"}), 400
    p_id = execute_db("INSERT INTO projects (title, description, team_id) VALUES (?, ?, ?)", (title, desc, team_id))
    return jsonify({"success": True, "project_id": p_id, "title": title})


@app.route("/api/quick/task", methods=["POST"])
@login_required
def quick_create_task():
    """API: Modal quick-dispatch task."""
    data = request.get_json(silent=True) or request.form
    title = data.get("title", "").strip()
    desc = data.get("description", "").strip()
    project_id = data.get("project_id")
    assigned_to = data.get("assigned_to")
    priority = data.get("priority", "Medium")
    category_tag = data.get("category_tag", "Feature")
    due_date = data.get("due_date")

    if not title or not project_id:
        return jsonify({"error": "Task title and project selection are required"}), 400
    t_id = execute_db(
        "INSERT INTO tasks (title, description, status, priority, category_tag, project_id, assigned_to, due_date) VALUES (?, ?, 'Backlog', ?, ?, ?, ?, ?)",
        (title, desc, priority, category_tag, project_id, assigned_to if assigned_to else None, due_date if due_date else None)
    )
    return jsonify({"success": True, "task_id": t_id, "title": title})


# ============================================================
# Routes — OpsChannels (Teams Module)
# ============================================================
@app.route("/channels")
@login_required
def ops_channels():
    """Teams-style OpsChannels team collaboration & chat workspace."""
    all_teams = query_db("SELECT DISTINCT id, team_name, description FROM teams ORDER BY team_name ASC")

    # Seed default channels for teams if empty
    for team in all_teams:
        chk = query_db("SELECT id FROM channels WHERE team_id = ?", (team["id"],))
        if not chk:
            execute_db("INSERT INTO channels (team_id, name, type) VALUES (?, ?, 'public')", (team["id"], "general"))
            execute_db("INSERT INTO channels (team_id, name, type) VALUES (?, ?, 'public')", (team["id"], "devops"))

    # Global public channels
    gen_chk = query_db("SELECT id FROM channels WHERE team_id IS NULL AND name = 'all-hands'", one=True)
    if not gen_chk:
        execute_db("INSERT INTO channels (team_id, name, type) VALUES (NULL, 'all-hands', 'public')")

    # Enforce RBAC Inter-Team Isolation
    is_admin_or_lead = current_user.role in ("Admin", "Project Lead")
    user_team_rows = query_db("SELECT team_id FROM team_members WHERE user_id = ?", (current_user.id,))
    user_team_ids = set(r["team_id"] for r in user_team_rows) if user_team_rows else set()

    if is_admin_or_lead:
        teams = all_teams
        channels = query_db("""
            SELECT c.*, t.team_name
            FROM channels c
            LEFT JOIN teams t ON c.team_id = t.id
            ORDER BY c.type DESC, c.name ASC
        """)
        users = query_db("SELECT id, full_name, email, employee_id, role, current_status, department FROM users WHERE status = 'approved' AND id != ? ORDER BY full_name", (current_user.id,))
    else:
        # Regular employee: Only show assigned teams, team channels + global public channels
        teams = [t for t in all_teams if t["id"] in user_team_ids]
        if user_team_ids:
            placeholders = ",".join("?" for _ in user_team_ids)
            sql = f"""
                SELECT c.*, t.team_name
                FROM channels c
                LEFT JOIN teams t ON c.team_id = t.id
                WHERE c.team_id IS NULL OR c.team_id IN ({placeholders})
                ORDER BY c.type DESC, c.name ASC
            """
            channels = query_db(sql, tuple(user_team_ids))
            
            # Colleagues only within user's assigned teams + Admins/Leads
            user_sql = f"""
                SELECT DISTINCT u.id, u.full_name, u.email, u.employee_id, u.role, u.current_status, u.department
                FROM users u
                LEFT JOIN team_members tm ON u.id = tm.user_id
                WHERE u.status = 'approved' AND u.id != ? AND (tm.team_id IN ({placeholders}) OR u.role IN ('Admin', 'Project Lead'))
                ORDER BY u.full_name
            """
            users = query_db(user_sql, (current_user.id, *user_team_ids))
        else:
            channels = query_db("SELECT c.*, t.team_name FROM channels c LEFT JOIN teams t ON c.team_id = t.id WHERE c.team_id IS NULL ORDER BY c.name ASC")
            users = query_db("SELECT id, full_name, email, employee_id, role, current_status, department FROM users WHERE status = 'approved' AND id != ? AND role IN ('Admin', 'Project Lead') ORDER BY full_name", (current_user.id,))

    projects = query_db("SELECT id, title FROM projects ORDER BY title ASC")

    return render_template(
        "ops_channels.html",
        teams=teams,
        channels=channels,
        users=users or [],
        projects=projects or [],
        is_admin_or_lead=is_admin_or_lead,
        user_team_ids=list(user_team_ids)
    )


@app.route("/api/channels/<int:channel_id>/messages", methods=["GET", "POST"])
@login_required
def channel_messages(channel_id):
    """API: Get or post messages in OpsChannels with RBAC authorization check."""
    channel = query_db("SELECT * FROM channels WHERE id = ?", (channel_id,), one=True)
    if not channel:
        return jsonify({"error": "Channel not found"}), 404

    # RBAC Inter-team authorization check
    is_admin_or_lead = current_user.role in ("Admin", "Project Lead")
    if not is_admin_or_lead and channel["team_id"] is not None:
        user_team = query_db("SELECT 1 FROM team_members WHERE user_id = ? AND team_id = ?", (current_user.id, channel["team_id"]), one=True)
        if not user_team:
            return jsonify({"error": "Access Denied: You are not a member of the team assigned to this channel."}), 403

    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        content = data.get("content", "").strip()
        parent_id = data.get("parent_id")
        if not content:
            return jsonify({"error": "Message content is required"}), 400

        msg_id = execute_db(
            "INSERT INTO messages (channel_id, sender_id, content, parent_id) VALUES (?, ?, ?, ?)",
            (channel_id, current_user.id, content, parent_id if parent_id else None)
        )
        msg = query_db("""
            SELECT m.*, u.full_name AS sender_name, u.employee_id AS sender_emp_id, u.role AS sender_role
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.id = ?
        """, (msg_id,), one=True)
        return jsonify({"success": True, "message": msg})
    else:
        messages = query_db("""
            SELECT m.*, u.full_name AS sender_name, u.employee_id AS sender_emp_id, u.role AS sender_role
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.channel_id = ?
            ORDER BY m.created_at ASC
        """, (channel_id,))
        for m in messages:
            m["reactions"] = query_db("SELECT emoji, COUNT(*) as count FROM message_reactions WHERE message_id = ? GROUP BY emoji", (m["id"],))
        return jsonify({"messages": messages})


@app.route("/api/messages/<int:message_id>/react", methods=["POST"])
@login_required
def react_message(message_id):
    """API: Add emoji reaction to channel message."""
    data = request.get_json(silent=True) or request.form
    emoji = data.get("emoji", "👍")
    try:
        execute_db("INSERT OR IGNORE INTO message_reactions (message_id, user_id, emoji) VALUES (?, ?, ?)", (message_id, current_user.id, emoji))
    except Exception:
        pass
    return jsonify({"success": True})


@app.route("/api/messages/<int:message_id>/convert-to-task", methods=["POST"])
@login_required
def convert_message_to_task(message_id):
    """API: Convert OpsChannels message directly into an Ops Task."""
    msg = query_db("SELECT * FROM messages WHERE id = ?", (message_id,), one=True)
    if not msg:
        return jsonify({"error": "Message not found"}), 404

    data = request.get_json(silent=True) or request.form
    project_id = data.get("project_id")
    if not project_id:
        p = query_db("SELECT id FROM projects ORDER BY id ASC", one=True)
        project_id = p["id"] if p else 1

    clean_content = msg['content'][:60]
    title = f"Task: {clean_content}..."
    task_id = execute_db(
        "INSERT INTO tasks (title, description, status, priority, category_tag, project_id, assigned_to) VALUES (?, ?, 'Backlog', 'Medium', 'Ops', ?, ?)",
        (title, f"Converted from OpsChannels message:\n\n{msg['content']}", project_id, current_user.id)
    )
    return jsonify({"success": True, "task_id": task_id, "message": "Message successfully converted to Ops Task!"})


# ============================================================
# Routes — OpsMail (Outlook Module)
# ============================================================
@app.route("/mail")
@login_required
def ops_mail():
    """Outlook-style OpsMail desktop workspace."""
    users = query_db("SELECT id, full_name, email, employee_id, role, department FROM users WHERE status = 'approved' AND id != ? ORDER BY full_name", (current_user.id,))
    projects = query_db("SELECT id, title FROM projects ORDER BY title ASC")
    return render_template("ops_mail.html", users=users, projects=projects)


@app.route("/api/mail", methods=["GET", "POST"])
@login_required
def api_mail():
    """API: List or send OpsMail messages."""
    import json
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        recipients = data.get("recipients", [])
        if isinstance(recipients, str):
            recipients = [r.strip() for r in recipients.split(",") if r.strip()]
        subject = data.get("subject", "No Subject").strip()
        body_html = data.get("body_html", "").strip()
        is_draft = int(data.get("is_draft", 0))

        mail_id = execute_db(
            "INSERT INTO mail_messages (sender_id, recipient_ids, subject, body_html, is_draft) VALUES (?, ?, ?, ?, ?)",
            (current_user.id, json.dumps(recipients), subject, body_html, is_draft)
        )
        return jsonify({"success": True, "mail_id": mail_id})
    else:
        folder = request.args.get("folder", "inbox")
        user_email_param = f'%"{current_user.email}"%'
        user_id_param = f'%"{current_user.id}"%'

        if folder == "sent":
            mails = query_db("""
                SELECT m.*, u.full_name AS sender_name, u.email AS sender_email
                FROM mail_messages m
                JOIN users u ON m.sender_id = u.id
                WHERE m.sender_id = ? AND m.is_draft = 0 AND m.is_deleted = 0
                ORDER BY m.created_at DESC
            """, (current_user.id,))
        elif folder == "drafts":
            mails = query_db("""
                SELECT m.*, u.full_name AS sender_name, u.email AS sender_email
                FROM mail_messages m
                JOIN users u ON m.sender_id = u.id
                WHERE m.sender_id = ? AND m.is_draft = 1 AND m.is_deleted = 0
                ORDER BY m.created_at DESC
            """, (current_user.id,))
        elif folder == "archive":
            mails = query_db("""
                SELECT m.*, u.full_name AS sender_name, u.email AS sender_email
                FROM mail_messages m
                JOIN users u ON m.sender_id = u.id
                WHERE (m.sender_id = ? OR m.recipient_ids LIKE ? OR m.recipient_ids LIKE ?) AND m.is_archived = 1 AND m.is_deleted = 0
                ORDER BY m.created_at DESC
            """, (current_user.id, user_email_param, user_id_param))
        elif folder == "trash":
            mails = query_db("""
                SELECT m.*, u.full_name AS sender_name, u.email AS sender_email
                FROM mail_messages m
                JOIN users u ON m.sender_id = u.id
                WHERE (m.sender_id = ? OR m.recipient_ids LIKE ? OR m.recipient_ids LIKE ?) AND m.is_deleted = 1
                ORDER BY m.created_at DESC
            """, (current_user.id, user_email_param, user_id_param))
        else:  # inbox
            mails = query_db("""
                SELECT m.*, u.full_name AS sender_name, u.email AS sender_email
                FROM mail_messages m
                JOIN users u ON m.sender_id = u.id
                WHERE (m.recipient_ids LIKE ? OR m.recipient_ids LIKE ? OR m.recipient_ids = '["all"]' OR m.sender_id = ?)
                  AND m.is_draft = 0 AND m.is_archived = 0 AND m.is_deleted = 0
                ORDER BY m.created_at DESC
            """, (user_email_param, user_id_param, current_user.id))

        return jsonify({"mails": mails})


@app.route("/api/mail/<int:mail_id>/assign-task", methods=["POST"])
@login_required
def assign_task_from_mail(mail_id):
    """API: Quick-action 'Assign Task from Email'."""
    mail = query_db("SELECT * FROM mail_messages WHERE id = ?", (mail_id,), one=True)
    if not mail:
        return jsonify({"error": "Email not found"}), 404

    # Authorization Check: User must be sender, recipient, or Admin
    is_sender = (mail["sender_id"] == current_user.id)
    rec_str = str(mail.get("recipient_ids", ""))
    is_recipient = (str(current_user.id) in rec_str or current_user.email in rec_str or rec_str == '["all"]')

    if not (is_sender or is_recipient or current_user.is_admin):
        return jsonify({"error": "Access denied to target message"}), 403

    data = request.get_json(silent=True) or request.form
    project_id = data.get("project_id")
    if not project_id:
        p = query_db("SELECT id FROM projects ORDER BY id ASC", one=True)
        project_id = p["id"] if p else 1

    task_id = execute_db(
        "INSERT INTO tasks (title, description, status, priority, category_tag, project_id, assigned_to) VALUES (?, ?, 'Backlog', 'Medium', 'Feature', ?, ?)",
        (f"Email Task: {mail['subject']}", f"Assigned from OpsMail:\n\n{mail['body_html']}", project_id, current_user.id)
    )
    return jsonify({"success": True, "task_id": task_id, "message": "Task created from OpsMail!"})


# ============================================================
# Routes — OpsMeet (Google Meet Module)
# ============================================================
@app.route("/meet")
@app.route("/meet/<room_code>")
@login_required
def ops_meet(room_code=None):
    """Google Meet-style OpsMeet instant & scheduled video rooms."""
    import uuid
    if not room_code:
        room_code = f"meet-{str(uuid.uuid4())[:8]}"
        return redirect(url_for("ops_meet", room_code=room_code))

    meeting = query_db("SELECT * FROM meetings WHERE room_code = ?", (room_code,), one=True)
    if not meeting:
        m_id = execute_db(
            "INSERT INTO meetings (room_code, host_id, title, status) VALUES (?, ?, ?, 'live')",
            (room_code, current_user.id, f"OpsMeet Room ({room_code})")
        )
        meeting = query_db("SELECT * FROM meetings WHERE id = ?", (m_id,), one=True)

    # Participant logging
    execute_db(
        "INSERT INTO meeting_participants (meeting_id, user_id) VALUES (?, ?)",
        (meeting["id"], current_user.id)
    )

    projects = query_db("SELECT id, title FROM projects ORDER BY title ASC")
    users = query_db("SELECT id, full_name, email, employee_id FROM users WHERE status = 'approved' ORDER BY full_name")

    return render_template("ops_meet.html", meeting=meeting, room_code=room_code, projects=projects, users=users)


@app.route("/api/meetings/instant", methods=["POST"])
@login_required
def create_instant_meeting():
    """API: Generate instant 'Meet Now' room link."""
    import uuid
    room_code = f"meet-{str(uuid.uuid4())[:8]}"
    execute_db(
        "INSERT INTO meetings (room_code, host_id, title, status) VALUES (?, ?, 'Instant OpsMeet Sync', 'live')",
        (room_code, current_user.id)
    )
    return jsonify({"success": True, "room_code": room_code, "url": f"/meet/{room_code}"})


@app.route("/api/meetings/<int:meeting_id>/log-task", methods=["POST"])
@login_required
def log_meeting_task(meeting_id):
    """API: Log operational action item directly during video call."""
    data = request.get_json(silent=True) or request.form
    title = data.get("title", "").strip()
    project_id = data.get("project_id")
    assigned_to = data.get("assigned_to")

    if not title:
        return jsonify({"error": "Task title required"}), 400
    if not project_id:
        p = query_db("SELECT id FROM projects ORDER BY id ASC", one=True)
        project_id = p["id"] if p else 1

    task_id = execute_db(
        "INSERT INTO tasks (title, description, status, priority, category_tag, project_id, assigned_to) VALUES (?, ?, 'Backlog', 'High', 'Ops', ?, ?)",
        (title, f"In-call action item logged during OpsMeet session #{meeting_id}.", project_id, assigned_to if assigned_to else current_user.id)
    )
    return jsonify({"success": True, "task_id": task_id, "message": "In-call action item logged successfully!"})



# ============================================================
# Routes — Personal Workspace Module
# ============================================================
@app.route("/workspace")
@login_required
def personal_workspace():
    """Render Personal Workspace dashboard with tasks, notes, and bookmarks."""
    return render_template("personal_workspace.html")


@app.route("/api/workspace/tasks", methods=["GET", "POST"])
@login_required
def api_workspace_tasks():
    """GET personal + assigned team tasks; POST create new personal task."""
    if request.method == "GET":
        p_tasks = query_db(
            "SELECT * FROM personal_tasks WHERE user_id = ? ORDER BY id DESC",
            (current_user.id,)
        )
        org_tasks = query_db("""
            SELECT t.*, p.title AS project_title
            FROM tasks t
            JOIN projects p ON t.project_id = p.id
            WHERE t.assigned_to = ?
            ORDER BY t.created_at DESC
        """, (current_user.id,))

        return jsonify({
            "personal_tasks": p_tasks or [],
            "org_tasks": org_tasks or []
        })

    data = request.get_json(silent=True) or request.form
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Task title is required"}), 400

    desc = data.get("description", "").strip()
    priority = data.get("priority", "Medium")
    if priority not in ("Low", "Medium", "High", "Urgent"):
        priority = "Medium"
    status = data.get("status", "TODO")
    if status not in ("TODO", "IN_PROGRESS", "COMPLETED"):
        status = "TODO"
    due_date = data.get("due_date", "")

    task_id = execute_db(
        "INSERT INTO personal_tasks (user_id, title, description, status, priority, due_date) VALUES (?, ?, ?, ?, ?, ?)",
        (current_user.id, title, desc, status, priority, due_date)
    )
    return jsonify({"success": True, "task_id": task_id, "message": "Personal task created successfully"})


@app.route("/api/workspace/tasks/<int:task_id>", methods=["PUT", "DELETE"])
@login_required
def api_workspace_task_detail(task_id):
    """PUT update / DELETE personal task (Strict user_id scoping)."""
    existing = query_db("SELECT id FROM personal_tasks WHERE id = ? AND user_id = ?", (task_id, current_user.id), one=True)
    if not existing:
        return jsonify({"error": "Access denied or record not found"}), 403

    if request.method == "DELETE":
        execute_db("DELETE FROM personal_tasks WHERE id = ? AND user_id = ?", (task_id, current_user.id))
        return jsonify({"success": True, "message": "Personal task deleted"})

    data = request.get_json(silent=True) or request.form
    title = data.get("title")
    desc = data.get("description")
    status = data.get("status")
    priority = data.get("priority")
    due_date = data.get("due_date")

    fields = []
    params = []
    if title is not None:
        fields.append("title = ?")
        params.append(title.strip())
    if desc is not None:
        fields.append("description = ?")
        params.append(desc.strip())
    if status is not None and status in ("TODO", "IN_PROGRESS", "COMPLETED"):
        fields.append("status = ?")
        params.append(status)
    if priority is not None and priority in ("Low", "Medium", "High", "Urgent"):
        fields.append("priority = ?")
        params.append(priority)
    if due_date is not None:
        fields.append("due_date = ?")
        params.append(due_date)

    if fields:
        params.extend([task_id, current_user.id])
        sql = f"UPDATE personal_tasks SET {', '.join(fields)} WHERE id = ? AND user_id = ?"
        execute_db(sql, tuple(params))

    return jsonify({"success": True, "message": "Personal task updated"})


@app.route("/api/workspace/notes", methods=["GET", "POST"])
@login_required
def api_workspace_notes():
    """GET notes for current user; POST create new personal note."""
    if request.method == "GET":
        notes = query_db(
            "SELECT * FROM personal_notes WHERE user_id = ? ORDER BY is_pinned DESC, updated_at DESC",
            (current_user.id,)
        )
        return jsonify({"notes": notes or []})

    data = request.get_json(silent=True) or request.form
    title = data.get("title", "").strip() or "Untitled Scratchpad Note"
    content = data.get("content", "").strip()
    is_pinned = 1 if data.get("is_pinned") in (True, 1, "1", "true") else 0

    note_id = execute_db(
        "INSERT INTO personal_notes (user_id, title, content, is_pinned) VALUES (?, ?, ?, ?)",
        (current_user.id, title, content, is_pinned)
    )
    return jsonify({"success": True, "note_id": note_id, "message": "Note created"})


@app.route("/api/workspace/notes/<int:note_id>", methods=["PUT", "DELETE"])
@login_required
def api_workspace_note_detail(note_id):
    """PUT update / DELETE personal note (Strict user_id scoping)."""
    existing = query_db("SELECT id FROM personal_notes WHERE id = ? AND user_id = ?", (note_id, current_user.id), one=True)
    if not existing:
        return jsonify({"error": "Access denied or record not found"}), 403

    if request.method == "DELETE":
        execute_db("DELETE FROM personal_notes WHERE id = ? AND user_id = ?", (note_id, current_user.id))
        return jsonify({"success": True, "message": "Note deleted"})

    data = request.get_json(silent=True) or request.form
    fields = []
    params = []
    if "title" in data:
        fields.append("title = ?")
        params.append(str(data["title"]).strip())
    if "content" in data:
        fields.append("content = ?")
        params.append(str(data["content"]).strip())
    if "is_pinned" in data:
        fields.append("is_pinned = ?")
        params.append(1 if data["is_pinned"] in (True, 1, "1", "true") else 0)

    fields.append("updated_at = CURRENT_TIMESTAMP")
    params.extend([note_id, current_user.id])

    sql = f"UPDATE personal_notes SET {', '.join(fields)} WHERE id = ? AND user_id = ?"
    execute_db(sql, tuple(params))
    return jsonify({"success": True, "message": "Note updated"})


@app.route("/api/workspace/bookmarks", methods=["GET", "POST"])
@login_required
def api_workspace_bookmarks():
    """GET bookmarks for current user; POST create new bookmark."""
    if request.method == "GET":
        bookmarks = query_db(
            "SELECT * FROM personal_bookmarks WHERE user_id = ? ORDER BY id DESC",
            (current_user.id,)
        )
        return jsonify({"bookmarks": bookmarks or []})

    data = request.get_json(silent=True) or request.form
    label = data.get("label", "").strip()
    url = data.get("url", "").strip()
    icon_tag = data.get("icon_tag", "bookmark").strip()

    if not label or not url:
        return jsonify({"error": "Label and URL are required"}), 400

    bm_id = execute_db(
        "INSERT INTO personal_bookmarks (user_id, label, url, icon_tag) VALUES (?, ?, ?, ?)",
        (current_user.id, label, url, icon_tag)
    )
    return jsonify({"success": True, "bookmark_id": bm_id, "message": "Bookmark saved"})


@app.route("/api/workspace/bookmarks/<int:bookmark_id>", methods=["DELETE"])
@login_required
def api_workspace_bookmark_delete(bookmark_id):
    """DELETE bookmark (Strict user_id scoping)."""
    existing = query_db("SELECT id FROM personal_bookmarks WHERE id = ? AND user_id = ?", (bookmark_id, current_user.id), one=True)
    if not existing:
        return jsonify({"error": "Access denied or record not found"}), 403

    execute_db("DELETE FROM personal_bookmarks WHERE id = ? AND user_id = ?", (bookmark_id, current_user.id))
    return jsonify({"success": True, "message": "Bookmark removed"})



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
