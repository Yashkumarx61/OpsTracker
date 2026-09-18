# OpsTracker

A lightweight, production-ready two-tier web application for organizational project and task tracking. Built with Flask and MySQL, containerized with Docker, and configured for deployment to AWS Windows Server running IIS.

---

## Table of Contents

- [Overview](#overview)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [Features](#features)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Option 1: Docker Compose (Recommended)](#option-1-docker-compose-recommended)
  - [Option 2: Local Development](#option-2-local-development)
- [Environment Variables](#environment-variables)
- [API Endpoints](#api-endpoints)
- [Deployment](#deployment)
  - [Docker](#docker)
  - [IIS on Windows Server](#iis-on-windows-server)
- [Default Credentials](#default-credentials)
- [License](#license)

---

## Overview

OpsTracker enables organizations to manage teams, projects, and tasks through a role-based web interface. Admins create and assign work; employees track and update their task progress through an intuitive kanban-style board.

The application is designed as a two-tier architecture: a Flask backend serving Jinja2-rendered HTML templates, backed by a MySQL 8.0 database. It includes a health check endpoint for CI/CD pipeline integration and container orchestration readiness probes.

---

## Technology Stack

| Layer         | Technology                                      |
|---------------|--------------------------------------------------|
| Backend       | Python 3.11, Flask, Flask-Login, Flask-WTF       |
| Database      | MySQL 8.0, PyMySQL (pure Python driver)          |
| Frontend      | HTML5, Tailwind CSS v3 (CDN), Jinja2 templating |
| Auth          | Werkzeug (scrypt password hashing), session-based|
| Deployment    | Docker, Docker Compose, IIS (wfastcgi), Gunicorn |
| Configuration | python-dotenv                                    |

---

## Project Structure

```
OpsTracker/
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI/CD pipeline definition
├── .env.example                # Environment variable template
├── .gitignore                  # Git ignore rules
├── Dockerfile                  # Container image definition
├── app.py                      # Main Flask application
├── config.py                   # Configuration loader
├── docker-compose.yml          # Multi-service orchestration
├── requirements.txt            # Python dependencies
├── schema.sql                  # Database initialization script
├── web.config                  # IIS handler configuration
├── static/
│   └── css/
│       └── custom.css          # Custom styles
└── templates/
    ├── base.html               # Master layout
    ├── login.html              # Login page
    ├── register.html           # Registration page
    ├── admin_dashboard.html    # Admin view
    └── employee_dashboard.html # Employee kanban board
```

---

## Database Schema

The application uses five tables with enforced foreign key relationships:

```
users
├── id (PK)
├── full_name
├── email (UNIQUE)
├── password_hash
├── role (Admin | Employee)
└── created_at

teams
├── id (PK)
├── team_name
├── description
└── created_at

team_members
├── user_id (FK -> users.id)
└── team_id (FK -> teams.id)
    └── Composite PK (user_id, team_id)

projects
├── id (PK)
├── title
├── description
├── status (Ongoing | Completed)
├── team_id (FK -> teams.id)
└── created_at

tasks
├── id (PK)
├── title
├── status (To-Do | In-Progress | Done)
├── due_date
├── project_id (FK -> projects.id)
├── assigned_to (FK -> users.id)
└── created_at
```

Foreign keys use `ON DELETE CASCADE` for team and project relationships, and `ON DELETE SET NULL` for task assignments.

---

## Features

**Authentication**
- Secure login and registration with scrypt password hashing.
- Session-based authentication via Flask-Login.
- CSRF protection on all forms via Flask-WTF.
- Unauthenticated users are redirected to the login page.

**Admin Dashboard**
- View summary statistics for teams, projects, tasks, and users.
- Create teams and add members.
- Create projects and assign them to teams.
- Create tasks, assign them to users, and set due dates.
- Toggle project status between Ongoing and Completed.

**Employee Dashboard**
- Kanban-style board with three columns: To-Do, In-Progress, and Done.
- View only tasks assigned to the logged-in user.
- Update task status with a single click.
- Task cards display project name, due date, and current status.

**Health Check**
- `GET /health` returns JSON with application and database connection status.
- Designed for use with Docker HEALTHCHECK, load balancer probes, and CI/CD pipelines.

---

## Getting Started

### Prerequisites

- Python 3.11 or later
- MySQL 8.0 (or Docker)
- Git

### Option 1: Docker Compose (Recommended)

```bash
git clone https://github.com/Yashkumarx61/OpsTracker.git
cd OpsTracker
docker-compose up --build -d
```

The application will be available at `http://localhost:5000`. MySQL initializes automatically from `schema.sql`.

To verify:

```bash
curl http://localhost:5000/health
```

To stop:

```bash
docker-compose down
```

### Option 2: Local Development

1. Clone the repository:

```bash
git clone https://github.com/Yashkumarx61/OpsTracker.git
cd OpsTracker
```

2. Create and activate a virtual environment:

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Configure environment variables:

```bash
copy .env.example .env
# Edit .env with your MySQL credentials
```

5. Initialize the database:

```bash
mysql -u root -p < schema.sql
```

6. Run the application:

```bash
python app.py
```

The application will be available at `http://127.0.0.1:5000`.

---

## Environment Variables

| Variable      | Description                          | Default           |
|---------------|--------------------------------------|--------------------|
| `SECRET_KEY`  | Flask session signing key            | (required)         |
| `FLASK_ENV`   | Environment mode                     | `production`       |
| `FLASK_DEBUG` | Enable debug mode (`0` or `1`)       | `0`                |
| `DB_HOST`     | MySQL host                           | `localhost`        |
| `DB_PORT`     | MySQL port                           | `3306`             |
| `DB_USER`     | MySQL user                           | `root`             |
| `DB_PASSWORD` | MySQL password                       | (required)         |
| `DB_NAME`     | MySQL database name                  | `opstracker`       |

Create a `.env` file in the project root. See `.env.example` for the template.

---

## API Endpoints

| Route                              | Method   | Auth     | Role     | Description                        |
|------------------------------------|----------|----------|----------|------------------------------------|
| `/login`                           | GET/POST | No       | --       | User login                         |
| `/register`                        | GET/POST | No       | --       | User registration                  |
| `/logout`                          | GET      | Yes      | Any      | End session                        |
| `/dashboard`                       | GET      | Yes      | Any      | Redirect to role-specific dashboard|
| `/admin/dashboard`                 | GET      | Yes      | Admin    | Admin overview                     |
| `/admin/teams`                     | POST     | Yes      | Admin    | Create team                        |
| `/admin/teams/<id>/members`        | POST     | Yes      | Admin    | Add member to team                 |
| `/admin/projects`                  | POST     | Yes      | Admin    | Create project                     |
| `/admin/projects/<id>/status`      | POST     | Yes      | Admin    | Update project status              |
| `/admin/tasks`                     | POST     | Yes      | Admin    | Create and assign task             |
| `/employee/dashboard`              | GET      | Yes      | Employee | View assigned tasks                |
| `/employee/tasks/<id>/status`      | POST     | Yes      | Employee | Update task status                 |
| `/health`                          | GET      | No       | --       | Health check (JSON)                |

---

## CI/CD Pipeline (GitHub Actions)

The repository includes an automated GitHub Actions workflow defined in `.github/workflows/ci.yml` that triggers on pushes and pull requests to `main`, `master`, and `develop` branches:

- **Lint & Syntax Validation (`lint-and-validate`)**: Runs Python 3.11 dependency installation, `flake8` linting checks, and verifies script compilation (`py_compile`).
- **Windows Server Environment & IIS Config Test (`windows-server-test`)**: Runs on a native `windows-latest` runner to verify Windows compatibility, install Python dependencies on Windows, validate IIS `web.config` XML schema via PowerShell, and test Flask app initialization.
- **Docker Image Verification (`docker-build`)**: Builds the multi-stage Docker image using `docker/build-push-action` to ensure image health and build integrity.
- **Windows Server Deployment (Optional)**: Contains a pre-configured template for automated remote deployment to Windows Server via SSH/WinRM once server credentials are configured in GitHub Repository Secrets.

---

## Deployment

### Docker

The included `Dockerfile` builds a production image using `python:3.11-slim` and serves the application with Gunicorn (4 workers). A `HEALTHCHECK` directive monitors the `/health` endpoint.

```bash
docker build -t opstracker .
docker run -d -p 5000:5000 --env-file .env opstracker
```

### IIS on Windows Server

1. Install Python 3.11 and `wfastcgi` on the server.
2. Copy the application files to `C:\inetpub\wwwroot\OpsTracker`.
3. Install dependencies: `pip install -r requirements.txt`.
4. Enable wfastcgi: `wfastcgi-enable`.
5. The included `web.config` maps all requests to the Flask application through the FastCGI module.
6. Update the `scriptProcessor` path in `web.config` to match your Python installation.
7. Configure the `.env` file with production database credentials.
8. Restart the IIS site.

---

## Default Credentials

The `schema.sql` script seeds a default administrator account for initial access:

| Field    | Value                    |
|----------|--------------------------|
| Email    | `admin@opstracker.local` |
| Password | `admin123`               |

**Change these credentials immediately in any non-development environment.**

---

## License

This project is provided as-is for educational and organizational use. See the repository for licensing details.
