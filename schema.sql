-- ============================================================
-- OpsTracker — Database Initialization Script (SQLite)
-- This file is executed automatically by app.py on first run
-- to create all tables and seed the default admin user.
-- ============================================================

-- -----------------------------------------------------------
-- 1. Users
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'Employee' CHECK(role IN ('Admin', 'Employee')),
    current_status TEXT   NOT NULL DEFAULT 'Available' CHECK(current_status IN ('Available', 'On Call', 'On Leave', 'Offline')),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- -----------------------------------------------------------
-- 2. Teams
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_name   TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 3. Team_Members (many-to-many mapping)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_members (
    user_id   INTEGER NOT NULL,
    team_id   INTEGER NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, team_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------
-- 4. Projects
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'Ongoing' CHECK(status IN ('Ongoing', 'Completed')),
    team_id     INTEGER NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_projects_team ON projects(team_id);

-- -----------------------------------------------------------
-- 5. Tasks
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'To-Do' CHECK(status IN ('To-Do', 'In-Progress', 'Done')),
    due_date    TEXT,
    project_id  INTEGER NOT NULL,
    assigned_to INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);

-- -----------------------------------------------------------
-- 6. Tickets
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    priority    TEXT DEFAULT 'Medium' CHECK(priority IN ('Low', 'Medium', 'High', 'Urgent')),
    status      TEXT DEFAULT 'Open' CHECK(status IN ('Open', 'In-Progress', 'Resolved', 'Closed')),
    admin_reply TEXT,
    replied_by  INTEGER,
    replied_at  TIMESTAMP,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (replied_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

-- -----------------------------------------------------------
-- 7. Notifications
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    title      TEXT NOT NULL,
    message    TEXT NOT NULL,
    link       TEXT,
    is_read    INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------
-- 8. Chat Messages (Project & Direct Employee Chat)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id    INTEGER NOT NULL,
    chat_type    TEXT NOT NULL CHECK(chat_type IN ('project', 'direct')),
    project_id   INTEGER,
    recipient_id INTEGER,
    message      TEXT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_project ON chat_messages(chat_type, project_id);
CREATE INDEX IF NOT EXISTS idx_chat_direct ON chat_messages(sender_id, recipient_id);

-- -----------------------------------------------------------
-- Seed: Default Admin User
-- Email:    admin@opstracker.local
-- Password: admin123
-- Hash generated by: werkzeug.security.generate_password_hash("admin123")
-- -----------------------------------------------------------
INSERT OR IGNORE INTO users (full_name, email, password_hash, role)
VALUES (
    'System Admin',
    'admin@opstracker.local',
    'scrypt:32768:8:1$2Yp3UgsVEDTNulHi$90964c5ca198a7810a435c9b2be9884ce93401ca65adeca153543236bc186372b3c85d115e63a9d5d2d926612cee9c282be6b2eab2307484d252bfe42c55542e',
    'Admin'
);
