from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from project_autopsy.cases import CaseCatalog
from project_autopsy.engine import AutopsyEngine
from project_autopsy.model import ModelError
from project_autopsy.storage import Store


ROOT = Path(__file__).resolve().parents[1]


class FakeModel:
    def __init__(self, invalid_case: bool = False):
        self.invalid_case = invalid_case

    def structured(self, name: str, _schema: dict, _instructions: str, data: dict) -> dict:
        if name == "project_interpretation":
            return {
                "facts": [{"text": data["plan"], "quote": data["plan"]}],
                "assumptions": [{"text": "권한 필터가 동작할 것이다", "based_on": "개인정보"}],
                "gaps": ["권한 테스트가 언급되지 않았습니다."],
            }
        if name == "project_autopsy_report":
            case_id = "fabricated_case" if self.invalid_case else data["candidate_cases"][0]["id"]
            return {
                "headline": "가상 부검 결과",
                "summary": "실패 경로를 조사합니다.",
                "risks": [{
                    "mechanism_key": case_id,
                    "title": "권한 검증",
                    "condition_quote": data["plan"],
                    "assumption": "권한 필터가 동작한다",
                    "mechanism": "검색 전 권한 검증 누락",
                    "early_signal": "권한 테스트가 없다",
                    "outcome": "제한 문서가 노출될 수 있다",
                    "action": "권한별 검색을 시험한다",
                    "action_when": "공개 전",
                    "done_when": "권한 테스트 통과",
                    "evidence_id": case_id,
                    "similarity": "문서 권한 조건이 닮았다",
                    "difference": "사례는 가상 샘플이다",
                    "impact": "high",
                }],
            }
        raise AssertionError(f"unexpected model call: {name}")


class LiveEngineValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "app.sqlite3")
        self.catalog = CaseCatalog(ROOT / "cases" / "cases.json")
        self.engine = AutopsyEngine(self.store, self.catalog, "demo")
        self.engine.mode = "live"

    def tearDown(self):
        self.temp.cleanup()

    def test_model_output_is_grounded_to_catalog(self):
        self.engine.model = FakeModel()
        project = self.store.create_project("검색", "개인정보가 포함된 사내 문서를 권한별로 검색한다.")
        self.engine.interpret(project)
        report = self.engine.analyze(self.store.get_project(project["id"]))
        risk = report["risks"][0]
        self.assertIn(risk["condition_quote"], project["versions"][0]["plan"])
        self.assertIn(risk["evidence"]["excerpt"], risk["evidence"]["story"])
        self.assertEqual(report["mode"], "live")

    def test_fabricated_case_id_is_rejected(self):
        self.engine.model = FakeModel(invalid_case=True)
        project = self.store.create_project("검색", "개인정보가 포함된 사내 문서를 권한별로 검색한다.")
        self.engine.interpret(project)
        with self.assertRaises(ModelError):
            self.engine.analyze(self.store.get_project(project["id"]))
        self.assertIsNone(self.store.get_project(project["id"])["versions"][0]["report"])


if __name__ == "__main__":
    unittest.main()
