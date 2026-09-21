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
    employee_id   TEXT    UNIQUE,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'Employee' CHECK(role IN ('Admin', 'Project Lead', 'Employee')),
    current_status TEXT   NOT NULL DEFAULT 'Available' CHECK(current_status IN ('Available', 'On Call', 'On Leave', 'Offline')),
    status        TEXT    NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected', 'terminated')),
    department    TEXT    DEFAULT 'General',
    job_title     TEXT    DEFAULT 'Employee',
    phone         TEXT    DEFAULT '',
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
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT,
    status       TEXT NOT NULL DEFAULT 'Backlog' CHECK(status IN ('Backlog', 'In Progress', 'Under Review', 'Completed', 'Blocked')),
    priority     TEXT NOT NULL DEFAULT 'Medium' CHECK(priority IN ('Low', 'Medium', 'High', 'Critical / Blocker')),
    category_tag TEXT NOT NULL DEFAULT 'Feature' CHECK(category_tag IN ('Frontend', 'Backend', 'Ops', 'Bug', 'Feature', 'Security')),
    due_date     TEXT,
    project_id   INTEGER NOT NULL,
    assigned_to  INTEGER,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);

-- -----------------------------------------------------------
-- 6. Subtasks (Checklist Items)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS subtasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL,
    title        TEXT NOT NULL,
    is_completed INTEGER DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_subtasks_task ON subtasks(task_id);

-- -----------------------------------------------------------
-- 7. Task Comments
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS task_comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    comment    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_comments_task ON task_comments(task_id);

-- -----------------------------------------------------------
-- 8. Task Audit Logs (Activity History)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS task_audit_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    action     TEXT NOT NULL,
    details    TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_task ON task_audit_logs(task_id);

-- -----------------------------------------------------------
-- 9. Tickets
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
-- 10. Notifications
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
-- 11. Chat Messages (Project & Direct Employee Chat)
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
-- 12. Channels (OpsChannels Module)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'public' CHECK(type IN ('public', 'private', 'direct_message')),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_channels_team ON channels(team_id);

-- -----------------------------------------------------------
-- 13. Channel Messages (OpsChannels Module)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      INTEGER NOT NULL,
    sender_id       INTEGER NOT NULL,
    content         TEXT NOT NULL,
    parent_id       INTEGER,
    attachments_url TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES messages(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id);
CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_id);

-- -----------------------------------------------------------
-- 14. Message Reactions (OpsChannels Module)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS message_reactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    emoji      TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(message_id, user_id, emoji),
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------
-- 15. Mail Messages (OpsMail Module)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS mail_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id     TEXT,
    sender_id     INTEGER NOT NULL,
    recipient_ids TEXT NOT NULL, -- JSON array of user IDs or emails
    cc_ids        TEXT DEFAULT '[]',
    bcc_ids       TEXT DEFAULT '[]',
    subject       TEXT NOT NULL,
    body_html     TEXT NOT NULL,
    is_read       INTEGER DEFAULT 0,
    is_draft      INTEGER DEFAULT 0,
    is_archived   INTEGER DEFAULT 0,
    is_deleted    INTEGER DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mail_sender ON mail_messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_mail_thread ON mail_messages(thread_id);

-- -----------------------------------------------------------
-- 16. Mail Attachments (OpsMail Module)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS mail_attachments (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    mail_id   INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    file_url  TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    FOREIGN KEY (mail_id) REFERENCES mail_messages(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------
-- 17. Meetings (OpsMeet Module)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS meetings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    room_code       TEXT UNIQUE NOT NULL,
    host_id         INTEGER NOT NULL,
    title           TEXT NOT NULL,
    scheduled_start TIMESTAMP,
    scheduled_end   TIMESTAMP,
    status          TEXT DEFAULT 'live' CHECK(status IN ('scheduled', 'live', 'ended')),
    recording_url   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (host_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_meetings_code ON meetings(room_code);

-- -----------------------------------------------------------
-- 18. Meeting Participants (OpsMeet Module)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS meeting_participants (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    left_at    TIMESTAMP,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------
-- 19. Voice Calls (OpsCall Module)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS voice_calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_id    INTEGER NOT NULL,
    receiver_id  INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'ringing' CHECK(status IN ('ringing', 'active', 'declined', 'ended')),
    offer_sdp    TEXT,
    answer_sdp   TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at     TIMESTAMP,
    FOREIGN KEY (caller_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_voice_calls_caller ON voice_calls(caller_id);
CREATE INDEX IF NOT EXISTS idx_voice_calls_receiver ON voice_calls(receiver_id);

-- -----------------------------------------------------------
-- Seed: Default Admin User
-- Email:    admin@opstracker.local
-- Password: admin123

-- -----------------------------------------------------------
INSERT OR IGNORE INTO users (full_name, email, password_hash, role, status, department, job_title, employee_id)
VALUES (
    'System Admin',
    'admin@opstracker.local',
    'scrypt:32768:8:1$2Yp3UgsVEDTNulHi$90964c5ca198a7810a435c9b2be9884ce93401ca65adeca153543236bc186372b3c85d115e63a9d5d2d926612cee9c282be6b2eab2307484d252bfe42c55542e',
    'Admin',
    'approved',
    'Executive Management',
    'Lead Administrator',
    'EMP-1001'
);

