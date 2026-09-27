from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from project_autopsy.cases import CaseCatalog
from project_autopsy.engine import AutopsyEngine
from project_autopsy.questions import choose_question
from project_autopsy.storage import Store


ROOT = Path(__file__).resolve().parents[1]


class QuestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "app.sqlite3")
        self.engine = AutopsyEngine(self.store, CaseCatalog(ROOT / "cases" / "cases.json"), "demo")

    def tearDown(self):
        self.temp.cleanup()

    def test_question_is_stable_and_excluded_risk_is_not_selected(self):
        project = self.store.create_project("사내 검색", "AI 문서 검색을 6주 안에 전 직원에게 출시한다. 개인정보 문서가 있다. 정확도 목표는 90%다.")
        self.assertIsNone(choose_question(project))
        self.engine.interpret(project)
        self.engine.analyze(self.store.get_project(project["id"]))
        project = self.store.get_project(project["id"])
        question = choose_question(project)
        self.assertEqual(question, choose_question(project))
        self.assertIn(question["condition_quote"], project["versions"][0]["plan"])
        self.assertEqual(question["base_version_id"], project["current_version_id"])
        self.store.set_feedback(project["id"], question["mechanism_key"], True, "이미 검증함")
        next_question = choose_question(self.store.get_project(project["id"]))
        self.assertTrue(next_question is None or next_question["mechanism_key"] != question["mechanism_key"])

    def test_clarification_and_request_id_survive_retry(self):
        project = self.store.create_project("질문", "정확도 목표는 90%다.")
        clarification = {"question_id": "q1", "status": "answered", "answer": "실제 질문 100개로 평가한다", "source": "user_provided_unverified"}
        plan = "정확도 목표는 90%다. 실제 질문 100개로 평가한다."
        first = self.store.add_version(project["id"], plan, project["current_version_id"], clarification, "same-request")
        second = self.store.add_version(project["id"], plan, project["current_version_id"], clarification, "same-request")
        self.assertEqual(len(first["versions"]), 2)
        self.assertEqual(len(second["versions"]), 2)
        self.assertEqual(second["versions"][0]["clarification"], clarification)
        with self.assertRaises(ValueError):
            self.store.add_version(project["id"], "다른 계획", project["current_version_id"], None, "same-request")

    def test_existing_database_adds_new_columns(self):
        path = Path(self.temp.name) / "legacy.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE plan_versions (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, number INTEGER NOT NULL,
                plan TEXT NOT NULL, interpretation TEXT, created_at TEXT NOT NULL,
                UNIQUE(project_id, number))""")
        Store(path)
        with sqlite3.connect(path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(plan_versions)")}
        self.assertIn("clarification", columns)
        self.assertIn("request_id", columns)


if __name__ == "__main__":
    unittest.main()
