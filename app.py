"""
OpsTracker — Main Flask Application
====================================
A lightweight organizational project & task tracker.

Modules:
  - Database helpers (PyMySQL connection pooling)
  - Flask-Login authentication
  - Role-based routing (Admin / Employee)
  - Health-check endpoint for CI/CD monitoring
"""

import functools
from datetime import datetime

import pymysql
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
# Database Helpers
# ============================================================
def get_db():
    """
    Return a PyMySQL connection stored on Flask's `g` object.
    Reuses the same connection within a single request.
    """
    if "db" not in g:
        try:
            g.db = pymysql.connect(
                host=Config.DB_HOST,
                port=Config.DB_PORT,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                database=Config.DB_NAME,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True,
            )
        except pymysql.MySQLError as e:
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
    with conn.cursor() as cur:
        cur.execute(sql, args)
        results = cur.fetchall()
    return (results[0] if results else None) if one else results


def execute_db(sql, args=()):
    """Execute an INSERT / UPDATE / DELETE and return lastrowid."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(sql, args)
    return cur.lastrowid


# ============================================================
# User Model (Flask-Login)
# ============================================================
class User(UserMixin):
    """Lightweight user wrapper for Flask-Login."""

    def __init__(self, id, full_name, email, password_hash, role, created_at=None):
        self.id = id
        self.full_name = full_name
        self.email = email
        self.password_hash = password_hash
        self.role = role  # 'Admin' or 'Employee'
        self.created_at = created_at

    @property
    def is_admin(self):
        return self.role == "Admin"


@login_manager.user_loader
def load_user(user_id):
    """Callback required by Flask-Login to reload a user from the session."""
    try:
        row = query_db("SELECT * FROM users WHERE id = %s", (user_id,), one=True)
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
            row = query_db("SELECT * FROM users WHERE email = %s", (email,), one=True)
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
            existing = query_db("SELECT id FROM users WHERE email = %s", (email,), one=True)
        except Exception:
            flash("A database error occurred. Please try again.", "error")
            return render_template("register.html")

        if existing:
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        # Create user (default role: Employee)
        hashed = generate_password_hash(password)
        try:
            execute_db(
                "INSERT INTO users (full_name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                (full_name, email, hashed, "Employee"),
            )
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
    """Admin view: all teams, projects, tasks, and users."""
    teams = query_db("SELECT * FROM teams ORDER BY team_name")
    projects = query_db("""
        SELECT p.*, t.team_name
        FROM projects p
        JOIN teams t ON p.team_id = t.id
        ORDER BY p.created_at DESC
    """)
    tasks = query_db("""
        SELECT tk.*, p.title AS project_title, u.full_name AS assignee_name
        FROM tasks tk
        JOIN projects p ON tk.project_id = p.id
        LEFT JOIN users u ON tk.assigned_to = u.id
        ORDER BY tk.due_date ASC
    """)
    users = query_db("SELECT id, full_name, email, role FROM users ORDER BY full_name")
    return render_template(
        "admin_dashboard.html",
        teams=teams, projects=projects, tasks=tasks, users=users,
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

    execute_db("INSERT INTO teams (team_name, description) VALUES (%s, %s)", (name, desc))
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
            "INSERT INTO team_members (user_id, team_id) VALUES (%s, %s)",
            (user_id, team_id),
        )
        flash("Member added to team.", "success")
    except pymysql.IntegrityError:
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
        "INSERT INTO projects (title, description, team_id) VALUES (%s, %s, %s)",
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

    execute_db("UPDATE projects SET status = %s WHERE id = %s", (new_status, project_id))
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
        "INSERT INTO tasks (title, project_id, assigned_to, due_date) VALUES (%s, %s, %s, %s)",
        (title, project_id, assigned_to, due_date),
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
        WHERE tk.assigned_to = %s
        ORDER BY tk.due_date ASC
    """, (current_user.id,))

    # Group tasks by status for kanban-style display
    grouped = {"To-Do": [], "In-Progress": [], "Done": []}
    for task in tasks:
        grouped.get(task["status"], grouped["To-Do"]).append(task)

    return render_template("employee_dashboard.html", grouped=grouped)


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
        "SELECT * FROM tasks WHERE id = %s AND assigned_to = %s",
        (task_id, current_user.id), one=True,
    )
    if not task:
        flash("Task not found or not assigned to you.", "error")
        return redirect(url_for("employee_dashboard"))

    execute_db("UPDATE tasks SET status = %s WHERE id = %s", (new_status, task_id))
    flash(f'Task status updated to "{new_status}".', "success")
    return redirect(url_for("employee_dashboard"))


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
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
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
