# OpsTracker — Unified Enterprise Operations & Task Management Workspace

OpsTracker is an enterprise-grade, unified operational workspace combining task tracking, RBAC team channels (**OpsChannels**), internal email delivery (**OpsMail**), instant video conferencing (**OpsMeet**), and a 3-step OTP security recovery workflow.

---

## Architecture Overview

```mermaid
graph TD
    User([Browser / Mobile Client]) --> |HTTPS / WSS| Nginx[IIS / Reverse Proxy Gateway]
    Nginx --> |Port 5000| FlaskApp[Flask WSGI Application]
    
    subgraph Core Application Engine
        FlaskApp --> Auth[Auth & OTP Session Manager]
        FlaskApp --> Channels[OpsChannels Engine]
        FlaskApp --> Mail[OpsMail Suite]
        FlaskApp --> Meet[OpsMeet Video Engine]
        FlaskApp --> Tasks[Task Velocity Manager]
    end

    FlaskApp --> |SQL Queries| DB[(MySQL 8.0 / SQLite Data Store)]

    subgraph CI/CD & DevOps Pipeline
        GitHub[GitHub Repo] --> |Push to main| GHA[GitHub Actions]
        GHA --> |Build & Test| DockerRegistry[GHCR Container Registry]
        GHA --> |Zero Downtime Deploy| AWS[AWS EC2 Instance]
    end
```

---

## Core Capabilities & Modules

| Module | Features & Capabilities |
| :--- | :--- |
| **Task Management** | Velocity metrics card, drag-and-drop Kanban board, task status transitions, role-based assignment. |
| **OpsChannels** | Real-time channel messaging, direct messaging, post-to-task conversion, inter-team RBAC isolation. |
| **OpsMail** | 3-pane Outlook-style reader, draft composer, folder hierarchy, 1-click email-to-task assignment. |
| **OpsMeet** | Instant Google Meet-style video workspace, active speaker detection, mic/cam toggle with avatar fallbacks, member side-panel. |
| **OTP Security Suite** | 3-step password recovery flow (`/forgot-password` -> `/verify-otp` -> `/reset-password`) with 5-digit auto-focus inputs. |

---

## Technology Stack

- **Backend:** Python 3.11, Flask, Flask-Login, Flask-WTF, CSRF Protection
- **Database:** MySQL 8.0 (Production) / SQLite3 (Development)
- **Frontend:** HTML5, Jinja2, Vanilla CSS (Design Tokens & Glassmorphism), Lucide Vector Icons
- **Containerization:** Docker Multi-stage Build, Docker Compose
- **DevOps & CI/CD:** GitHub Actions, AWS EC2, GHCR, Automated Rollback Triggers

---

## Role-Based Access Control (RBAC) Matrix

| Action / Feature | Admin | Team Lead | Employee / Member |
| :--- | :---: | :---: | :---: |
| Create Teams & Assign Projects | Yes | No | No |
| Cross-Team Channels Access | Yes | Yes | Assigned Team Only |
| Direct Message Colleagues | All Users | All Users | Team Members Only |
| Dispatch Tasks | Yes | Yes | Self/Assigned Only |
| Initiate OpsMeet Rooms | Yes | Yes | Yes |

---

## Quick Start (Docker Compose)

```bash
# 1. Clone the repository
git clone https://github.com/yashkumarx61/opstracker.git
cd OpsTracker

# 2. Configure Environment
cp .env.example .env

# 3. Launch Docker Compose Stack
docker-compose up -d --build

# 4. Access Application
# Web Interface: http://localhost:5000
# Database: mysql://root:rootpassword@localhost:3306/opstracker
```

### Initial Credentials
- **Admin Account:** `admin@opstracker.local` / `admin123`
- **Employee Account:** `lead@opstracker.local` / `devops123`

---

## CI/CD Pipeline & AWS Deployment

The `.github/workflows/deploy.yml` pipeline executes automatically on push to `main`:

1. **Lint & Test:** Validates Python syntax via `flake8`.
2. **Build & Push:** Builds container image and pushes tagged version to `ghcr.io`.
3. **Deploy to AWS EC2:** Pulls image, performs rolling container update, checks `/health` probe endpoint.
4. **Auto-Rollback:** On health check failure, restores previous stable container backup automatically.

---

## License

Distributed under the MIT License. See `LICENSE` for details.
