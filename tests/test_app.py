import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import mysql.connector

import app as module
import setup_database
from database import transaction


class AppTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(module.app.config)
        module.app.config.update(TESTING=True, APP_PASSWORD="", SECRET_KEY="test-secret")
        self.client = module.app.test_client()

    def tearDown(self):
        module.app.config.clear()
        module.app.config.update(self.config)

    def token(self, client=None):
        client = client or self.client
        client.get("/")
        with client.session_transaction() as session:
            return session["csrf_token"]

    def test_home_and_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="csrf_token"', response.data)
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", response.headers["Set-Cookie"])

    def test_untrusted_host_and_remote_access_rejected(self):
        self.assertEqual(self.client.get("/", headers={"Host": "evil.example"}).status_code, 400)
        self.assertEqual(self.client.get("/", environ_overrides={"REMOTE_ADDR": "192.0.2.1"}).status_code, 403)

    def test_authentication_required_for_reads_and_writes(self):
        module.app.config["APP_PASSWORD"] = "secret"
        for path in ("/", "/result", "/visual", "/static/js/app.js"):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post("/reset").status_code, 401)
        wrong = base64.b64encode(b"admin:wrong").decode()
        self.assertEqual(self.client.get("/", headers={"Authorization": "Basic " + wrong}).status_code, 401)
        correct = base64.b64encode(b"admin:secret").decode()
        self.assertEqual(self.client.get("/", headers={"Authorization": "Basic " + correct}).status_code, 200)

    def test_csrf_missing_invalid_and_cross_session(self):
        token = self.token()
        with patch.object(module, "get_db") as database:
            for path in ("/result", "/reset"):
                for form in ({}, {"csrf_token": "wrong"}, {"csrf_token": "é"}):
                    self.assertEqual(self.client.post(path, data=form).status_code, 400)
            other_client = module.app.test_client()
            other_client.get("/")
            self.assertEqual(other_client.post("/result", data={"csrf_token": token, "text": "Planet."}).status_code, 400)
            database.assert_not_called()

    def test_input_limits_and_empty_text(self):
        token = self.token()
        with patch.object(module, "get_db") as database:
            for text in (None, "", "   ", "x" * 10001, "Planet. " * 101):
                form = {"csrf_token": token}
                if text is not None:
                    form["text"] = text
                self.assertEqual(self.client.post("/result", data=form).status_code, 400)
            self.assertEqual(self.client.post("/result", data={"csrf_token": token, "text": "x" * 140000}).status_code, 413)
            database.assert_not_called()

    def test_extraction_phrase_stemming_best_match_and_bounded_score(self):
        result = module.extract_knowledge("Tata surya.")[0]
        self.assertEqual(result["category"], "astronomi")
        self.assertGreater(result["accuracy"], 0)
        self.assertEqual(module.extract_knowledge("Tumbuhan berkembang.")[0]["category"], "biologi")
        self.assertEqual(module.extract_knowledge("Planet energi listrik gelombang.")[0]["category"], "fisika")
        self.assertEqual(module.extract_knowledge("xyzq.")[0]["category"], "unknown")
        self.assertEqual(module.extract_knowledge("xyzq.")[0]["accuracy"], 0)
        once = module.calculate_accuracy(module.normalize("planet"), "astronomi")
        repeated = module.calculate_accuracy(module.normalize("planet " * 100), "astronomi")
        self.assertEqual(once, repeated)
        self.assertLessEqual(repeated, 1)
        self.assertEqual(len(module.extract_knowledge("Planet. Bulan! Matahari?")), 3)
        self.assertEqual(module.normalize("a" * 10000), ("a" * 10000,))

    def test_successful_post_and_reset_disabled_by_default(self):
        token = self.token()
        with patch.object(module, "insert_extracted_knowledge") as insert:
            response = self.client.post("/result", data={"csrf_token": token, "text": "Planet."})
            self.assertEqual(response.status_code, 303)
            self.assertEqual(insert.call_args.args[0][0]["category"], "astronomi")
        with patch.object(module, "get_db") as database:
            self.assertEqual(self.client.post("/reset", data={"csrf_token": token}).status_code, 403)
            self.assertEqual(self.client.get("/reset").status_code, 405)
            database.assert_not_called()

    def test_database_failure_is_generic(self):
        with patch.object(module, "connect_database", side_effect=mysql.connector.Error("private password")):
            response = self.client.get("/result")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"private password", response.data)

    def test_connection_closed_at_teardown(self):
        connection = Mock()
        with patch.object(module, "connect_database", return_value=connection):
            with module.app.app_context():
                self.assertIs(module.get_db(), module.get_db())
            connection.close.assert_called_once()

    def test_transaction_rollback_and_cursor_cleanup(self):
        connection = Mock()
        with self.assertRaises(RuntimeError):
            with transaction(connection):
                raise RuntimeError("failed write")
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
        connection.cursor.return_value.close.assert_called_once()

    def test_transaction_commit_and_cursor_cleanup(self):
        connection = Mock()
        with transaction(connection) as cursor:
            cursor.execute("SELECT 1")
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()
        connection.cursor.return_value.close.assert_called_once()

    def test_keyword_map_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keywords.txt"
            path.write_text("bad line", encoding="utf-8")
            with self.assertRaises(ValueError):
                module.read_keyword_map(path)


@unittest.skipUnless(os.environ.get("TEST_MYSQL") == "1", "requires isolated MySQL database")
class MySQLIntegrationTests(unittest.TestCase):
    """Runs the application against a disposable database, never the user's DB."""
    def setUp(self):
        if not os.environ.get("DB_NAME", "").endswith("_test"):
            self.fail("Integration tests require a DB_NAME ending in _test")
        AppTests.setUp(self)
        self.connection = module.connect_database()
        self.reset_schema(with_id=True)

    def tearDown(self):
        self.connection.close()
        AppTests.tearDown(self)

    token = AppTests.token

    def reset_schema(self, with_id):
        with transaction(self.connection) as cursor:
            cursor.execute("DROP TABLE IF EXISTS extracted_knowledge")
            prefix = "id INT AUTO_INCREMENT PRIMARY KEY, " if with_id else ""
            cursor.execute("CREATE TABLE extracted_knowledge (" + prefix +
                           "category VARCHAR(255), sentence TEXT, accuracy FLOAT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")

    def insert_rows(self, rows):
        with transaction(self.connection) as cursor:
            cursor.executemany("INSERT INTO extracted_knowledge (category,sentence,accuracy) VALUES (%s,%s,%s)", rows)

    def test_roundtrip_both_legacy_schemas_and_escaping(self):
        for with_id in (False, True):
            self.reset_schema(with_id)
            token = self.token()
            text = "Planet <script>alert('xss')</script>."
            self.assertEqual(self.client.post("/result", data={"csrf_token": token, "text": text}).status_code, 303)
            response = self.client.get("/result")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"astronomi", response.data)
            self.assertIn(b"&lt;script&gt;", response.data)
            self.assertNotIn(b"<script>alert", response.data)
            self.assertIn(b"astronomi", self.client.get("/visual").data)

    def test_pagination_filter_injection_and_visual_counts(self):
        self.insert_rows([("astronomi", f"Planet {i:02}", 0.1) for i in range(21)] + [("kimia", "Molekul", 0.2)])
        first = self.client.get("/result?category=astronomi")
        self.assertIn(b"Planet 09", first.data)
        self.assertNotIn(b"Planet 10", first.data)
        self.assertIn(b"Halaman 1 dari 3", first.data)
        last = self.client.get("/result?category=astronomi&page=999")
        self.assertIn(b"Planet 20", last.data)
        self.assertNotIn(b"Planet 19", last.data)
        self.assertIn(b"Halaman 3 dari 3", last.data)
        for page in ("bad", "-4", "0"):
            self.assertEqual(self.client.get("/result?page=" + page).status_code, 200)
        attack = self.client.get("/result", query_string={"category": "' OR 1=1 --"})
        self.assertNotIn(b"Planet 00", attack.data)
        visual = self.client.get("/visual?category=astronomi")
        self.assertIn(b'value="21"', visual.data)
        self.assertNotIn(b'for="bar-2"', visual.data)

    def test_authorized_reset_deletes_without_dropping_table(self):
        self.insert_rows([("astronomi", "Planet", 0.1)])
        module.app.config["APP_PASSWORD"] = "secret"
        auth = {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode()}
        self.client.get("/", headers=auth)
        with self.client.session_transaction() as session:
            token = session["csrf_token"]
        self.assertEqual(self.client.post("/reset", data={"csrf_token": token}, headers=auth).status_code, 303)
        with transaction(self.connection) as cursor:
            cursor.execute("SELECT COUNT(*) FROM extracted_knowledge")
            self.assertEqual(cursor.fetchone()[0], 0)
        self.assertIn("berhasil dihapus", self.client.get("/result", headers=auth).text)

    def test_setup_and_real_transaction_rollback(self):
        with transaction(self.connection) as cursor:
            cursor.execute("DROP TABLE extracted_knowledge")
        setup_database.main()
        with self.assertRaises(RuntimeError):
            with transaction(self.connection) as cursor:
                cursor.execute("INSERT INTO extracted_knowledge (category,sentence,accuracy) VALUES (%s,%s,%s)",
                               ("astronomi", "Planet", 0.1))
                raise RuntimeError("simulate failed write")
        with transaction(self.connection) as cursor:
            cursor.execute("SELECT COUNT(*) FROM extracted_knowledge")
            self.assertEqual(cursor.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
