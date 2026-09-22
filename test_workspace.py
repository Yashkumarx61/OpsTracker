"""
OpsTracker — Personal Workspace Module Unit & Isolation Tests
===============================================================
Verifies multi-tenant data isolation: User A cannot read, update,
or delete personal tasks, notes, or bookmarks belonging to User B.
"""

import os
import unittest
from werkzeug.security import generate_password_hash

# Ensure test DB environment configuration
os.environ["FLASK_ENV"] = "testing"
os.environ["WTF_CSRF_ENABLED"] = "false"

from app import app, init_db, get_db, query_db, execute_db, User


class PersonalWorkspaceTestCase(unittest.TestCase):
    """Test suite for tenant isolation and CRUD logic in Personal Workspace."""

    def setUp(self):
        """Set up test environment and populate User A and User B."""
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

        with app.app_context():
            init_db()
            db = get_db()

            # Ensure clean state for test users
            db.execute("DELETE FROM users WHERE email IN ('usera@opstracker.local', 'userb@opstracker.local')")
            db.commit()

            pwd_hash = generate_password_hash("password123")
            self.user_a_id = execute_db(
                "INSERT INTO users (full_name, email, password_hash, role, status) VALUES (?, ?, ?, 'Employee', 'approved')",
                ("User A", "usera@opstracker.local", pwd_hash)
            )
            self.user_b_id = execute_db(
                "INSERT INTO users (full_name, email, password_hash, role, status) VALUES (?, ?, ?, 'Employee', 'approved')",
                ("User B", "userb@opstracker.local", pwd_hash)
            )

    def login_user(self, email, password="password123"):
        """Helper to log in via test client."""
        return self.client.post("/login", data={"email": email, "password": password}, follow_redirects=True)

    def test_personal_task_isolation(self):
        """Test User A's personal tasks cannot be accessed or deleted by User B."""
        # 1. Login as User A and create a personal task
        self.login_user("usera@opstracker.local")
        res = self.client.post("/api/workspace/tasks", json={
            "title": "User A Private Task",
            "description": "Sensitive personal info",
            "priority": "High"
        })
        self.assertEqual(res.status_code, 200)
        task_id = res.get_json()["task_id"]

        # 2. Login as User B and attempt to GET tasks
        self.client.get("/logout")
        self.login_user("userb@opstracker.local")
        res = self.client.get("/api/workspace/tasks")
        data = res.get_json()
        p_task_ids = [t["id"] for t in data.get("personal_tasks", [])]
        self.assertNotIn(task_id, p_task_ids)

        # 3. User B attempts PUT update on User A's task
        res_put = self.client.put(f"/api/workspace/tasks/{task_id}", json={"title": "Hacked Title"})
        self.assertEqual(res_put.status_code, 403)

        # 4. User B attempts DELETE on User A's task
        res_del = self.client.delete(f"/api/workspace/tasks/{task_id}")
        self.assertEqual(res_del.status_code, 403)

    def test_personal_note_isolation(self):
        """Test User A's scratchpad notes cannot be read or updated by User B."""
        # 1. Login as User A and create a note
        self.login_user("usera@opstracker.local")
        res = self.client.post("/api/workspace/notes", json={
            "title": "Confidential Note",
            "content": "Secret notes",
            "is_pinned": 1
        })
        note_id = res.get_json()["note_id"]

        # 2. Login as User B and verify note is absent
        self.client.get("/logout")
        self.login_user("userb@opstracker.local")
        res = self.client.get("/api/workspace/notes")
        note_ids = [n["id"] for n in res.get_json().get("notes", [])]
        self.assertNotIn(note_id, note_ids)

        # 3. User B attempts to delete User A's note
        res_del = self.client.delete(f"/api/workspace/notes/{note_id}")
        self.assertEqual(res_del.status_code, 403)

    def test_personal_bookmark_isolation(self):
        """Test User A's bookmarks cannot be deleted by User B."""
        self.login_user("usera@opstracker.local")
        res = self.client.post("/api/workspace/bookmarks", json={
            "label": "User A Private Bookmark",
            "url": "https://usera.private.local"
        })
        bm_id = res.get_json()["bookmark_id"]

        self.client.get("/logout")
        self.login_user("userb@opstracker.local")
        res_del = self.client.delete(f"/api/workspace/bookmarks/{bm_id}")
        self.assertEqual(res_del.status_code, 403)


if __name__ == "__main__":
    unittest.main()
