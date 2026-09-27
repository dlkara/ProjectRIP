from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from project_autopsy.cases import CaseCatalog
from project_autopsy.engine import AutopsyEngine, exact_substring
from project_autopsy.storage import Store


ROOT = Path(__file__).resolve().parents[1]


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "app.sqlite3")
        self.catalog = CaseCatalog(ROOT / "cases" / "cases.json")
        self.engine = AutopsyEngine(self.store, self.catalog, "demo")

    def tearDown(self):
        self.temp.cleanup()

    def test_corpus_excerpts_are_exact(self):
        self.assertEqual(len(self.catalog.cases), 12)
        for case in self.catalog.cases:
            self.assertIn(case["excerpt"], case["story"])
            self.assertEqual(case["source_type"], "fictional_sample")

    def test_full_revision_preserves_evidence_and_history(self):
        initial = "사내 문서 10만 건을 검색하는 AI 서비스를 6주 안에 전 직원에게 배포한다. 문서에는 개인정보가 포함될 수 있다. 정확도 목표는 90%다."
        project = self.store.create_project("AI 사내 검색", initial)
        self.engine.interpret(project)
        project = self.store.get_project(project["id"])
        first = self.engine.analyze(project)
        keys = {risk["mechanism_key"] for risk in first["risks"]}
        self.assertIn("scope_overreach", keys)
        self.assertIn("permission_gap", keys)
        for risk in first["risks"]:
            self.assertIn(risk["condition_quote"], initial)
            self.assertIn(risk["evidence"]["excerpt"], risk["evidence"]["story"])
            self.assertEqual(risk["evidence"]["source_type"], "fictional_sample")

        revised = "사내 문서 검색 서비스를 한 부서의 공개 문서 500개로 시작한다. 실제 질문 100개와 정답 근거로 평가한다. 개인정보가 있는 문서는 권한을 검증한 뒤 포함한다."
        project = self.store.add_version(project["id"], revised)
        self.engine.interpret(project)
        project = self.store.get_project(project["id"])
        second = self.engine.analyze(project)
        changes = {change["mechanism_key"]: change["status"] for change in second["comparison"]["changes"]}
        self.assertEqual(changes["scope_overreach"], "완화")
        self.assertEqual(changes["permission_gap"], "유지")
        saved = self.store.get_project(project["id"])
        self.assertEqual(saved["versions"][1]["plan"], initial)
        self.assertEqual(saved["versions"][1]["report"]["headline"], first["headline"])

    def test_excluded_risk_is_not_reintroduced_in_next_analysis(self):
        plan = "전 직원에게 6주 안에 AI 서비스를 출시한다."
        project = self.store.create_project("범위", plan)
        self.engine.interpret(project)
        project = self.store.get_project(project["id"])
        first = self.engine.analyze(project)
        self.assertIn("scope_overreach", {item["mechanism_key"] for item in first["risks"]})
        self.store.set_feedback(project["id"], "scope_overreach", True, "이미 파일럿을 진행했다")
        second = self.engine.analyze(self.store.get_project(project["id"]))
        self.assertNotIn("scope_overreach", {item["mechanism_key"] for item in second["risks"]})

    def test_search_finds_mechanism_not_just_domain(self):
        results = self.catalog.search("민감한 사내 문서를 직원마다 다른 권한으로 검색")
        self.assertEqual(results[0]["id"], "permission_gap")

    def test_comparison_rejects_unsupported_resolution(self):
        class FakeModel:
            def structured(self, *_args):
                return {"changes": [
                    {"mechanism_key": "permission_gap", "status": "해소", "reason": "해결됐다", "plan_quote": "계획에 없는 문장"},
                ]}

        self.engine.mode = "live"
        self.engine.model = FakeModel()
        previous = {"number": 1, "plan": "개인정보 문서를 검색한다", "report": {"risks": [{"mechanism_key": "permission_gap"}]}}
        current = {"number": 2, "plan": "개인정보 문서를 계속 검색한다"}
        report = {"risks": [{"mechanism_key": "permission_gap"}]}
        result = self.engine.compare(previous, current, report)
        self.assertEqual(result["changes"][0]["status"], "판단 보류")
        self.assertEqual(result["changes"][0]["plan_quote"], "")
        self.assertFalse(exact_substring(None, current["plan"]))

        class StillPresentModel:
            def structured(self, *_args):
                return {"changes": [
                    {"mechanism_key": "permission_gap", "status": "해소", "reason": "해결됐다", "plan_quote": "개인정보 문서를 계속 검색한다"},
                ]}

        self.engine.model = StillPresentModel()
        result = self.engine.compare(previous, current, report)
        self.assertEqual(result["changes"][0]["status"], "유지")

    def test_unknown_answer_does_not_mitigate_its_risk(self):
        previous = {"number": 1, "plan": "정확도 목표는 90%다.", "report": {"risks": [{"mechanism_key": "undefined_metric"}]}}
        current = {
            "number": 2, "plan": "실제 질문 100개로 평가한다.",
            "clarification": {"status": "unknown", "mechanism_key": "undefined_metric"},
        }
        comparison = self.engine.compare(previous, current, {"risks": []})
        change = comparison["changes"][0]
        self.assertEqual(change["status"], "판단 보류")
        self.assertEqual(change["plan_quote"], "")

    def test_user_answer_cannot_claim_executed_resolution(self):
        class ResolvedModel:
            def structured(self, *_args):
                return {"changes": [{"mechanism_key": "undefined_metric", "status": "해소", "reason": "완료", "plan_quote": "실제 질문 100개로 평가한다."}]}

        self.engine.mode = "live"
        self.engine.model = ResolvedModel()
        previous = {"number": 1, "plan": "정확도 목표는 90%다.", "report": {"risks": [{"mechanism_key": "undefined_metric"}]}}
        current = {
            "number": 2, "plan": "실제 질문 100개로 평가한다.",
            "clarification": {"status": "answered", "mechanism_key": "undefined_metric", "answer": "실제 질문 100개로 평가한다"},
        }
        change = self.engine.compare(previous, current, {"risks": []})["changes"][0]
        self.assertEqual(change["status"], "완화")
        self.assertIn("실제 검증 완료", change["reason"])


if __name__ == "__main__":
    unittest.main()
