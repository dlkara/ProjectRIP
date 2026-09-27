from __future__ import annotations

import json
import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from project_autopsy.server import AppServer, Application, Handler, ROOT


class HttpFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = AppServer(("127.0.0.1", 0), Handler)
        self.server.app = Application(root=ROOT, mode="demo", database=Path(self.temp.name) / "test.sqlite3")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path: str, method: str = "GET", data: dict | None = None) -> dict:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        request = Request(
            self.base + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_browser_api_flow(self):
        self.assertEqual(self.request("/api/health")["mode"], "demo")
        project = self.request(
            "/api/projects",
            "POST",
            {"title": "사내 검색", "plan": "AI 문서 검색 서비스를 6주 안에 전 직원에게 배포한다. 개인정보가 포함된다. 정확도 목표는 90%다."},
        )
        project_id = project["id"]
        interpreted = self.request(f"/api/projects/{project_id}/interpret", "POST", {})
        self.assertGreater(len(interpreted["interpretation"]["facts"]), 0)
        report = self.request(f"/api/projects/{project_id}/analyze", "POST", {})["report"]
        self.assertGreater(len(report["risks"]), 0)
        self.assertTrue(all(item["evidence"]["source_type"] == "fictional_sample" for item in report["risks"]))

        revision_payload = {"plan": "AI 문서 검색 서비스를 한 부서의 공개 문서 500개로 시작한다. 실제 질문 100개와 정답 근거로 평가한다. 개인정보 문서는 권한을 검증한 뒤 포함한다.", "base_version_id": project["current_version_id"]}
        revised = self.request(
            f"/api/projects/{project_id}/versions",
            "POST",
            revision_payload,
        )
        self.assertEqual(revised["versions"][0]["number"], 2)
        repeated = self.request(f"/api/projects/{project_id}/versions", "POST", revision_payload)
        self.assertEqual(len(repeated["versions"]), 2, "lost-response retry must not create Version 3")
        with self.assertRaises(HTTPError) as context:
            self.request(f"/api/projects/{project_id}/versions", "POST", {"plan": "충돌하는 다른 계획", "base_version_id": project["current_version_id"]})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()
        self.request(f"/api/projects/{project_id}/interpret", "POST", {})
        compared = self.request(f"/api/projects/{project_id}/analyze", "POST", {})["report"]
        self.assertIsNotNone(compared["comparison"])
        self.assertEqual(compared["comparison"]["before_version"], 1)

        key = compared["risks"][0]["mechanism_key"]
        updated = self.request(
            f"/api/projects/{project_id}/feedback",
            "POST",
            {"mechanism_key": key, "excluded": True, "reason": "이미 검증한 조건"},
        )
        self.assertTrue(any(item["mechanism_key"] == key and item["excluded"] for item in updated["feedback"]))

    def test_invalid_input_returns_json_error(self):
        with self.assertRaises(HTTPError) as context:
            self.request("/api/projects", "POST", {"title": "", "plan": ""})
        error = context.exception
        self.assertEqual(error.code, 400)
        self.assertIn("application/json", error.headers["Content-Type"])
        self.assertIn("error", json.load(error))
        error.close()

        with self.assertRaises(HTTPError) as context:
            self.request("/api/projects", "POST", {"title": None, "plan": "계획"})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

        project = self.request("/api/projects", "POST", {"title": "검증", "plan": "전 직원에게 서비스를 공개한다."})
        version_id = project["versions"][0]["id"]
        with self.assertRaises(HTTPError) as context:
            self.request(
                f"/api/projects/{project['id']}/interpretation",
                "PUT",
                {"version_id": version_id, "interpretation": {"facts": [{"text": "없는 사실", "quote": "존재하지 않는 문장"}], "assumptions": [], "gaps": []}},
            )
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

        with self.assertRaises(HTTPError) as context:
            self.request(
                f"/api/projects/{project['id']}/feedback",
                "POST",
                {"mechanism_key": "scope_overreach", "excluded": True, "reason": ""},
            )
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

    def test_form_revision_redirects_with_completed_demo_report(self):
        project = self.request("/api/projects", "POST", {"title": "폼 저장", "plan": "전 직원에게 한 번에 배포한다."})
        path = f"/api/projects/{project['id']}/versions"
        payload = urlencode({"plan": "한 부서에서 먼저 시험한다.", "base_version_id": project["current_version_id"]})
        for _ in range(2):
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
            connection.request("POST", path, payload, {"Content-Type": "application/x-www-form-urlencoded"})
            response = connection.getresponse()
            self.assertEqual(response.status, 303)
            self.assertEqual(response.getheader("Location"), "/")
            response.read()
            connection.close()
        revised = self.request(f"/api/projects/{project['id']}")
        self.assertEqual(len(revised["versions"]), 2)
        self.assertIsNotNone(revised["versions"][0]["interpretation"])
        self.assertIsNotNone(revised["versions"][0]["report"])

    def test_question_answer_is_linked_to_saved_version(self):
        project = self.request("/api/projects", "POST", {"title": "질문 흐름", "plan": "AI 문서 검색을 6주 안에 전 직원에게 배포한다. 정확도 목표는 90%다."})
        project_id = project["id"]
        self.request(f"/api/projects/{project_id}/interpret", "POST", {})
        self.request(f"/api/projects/{project_id}/analyze", "POST", {})
        question = self.request(f"/api/projects/{project_id}/question")["question"]
        self.assertIsNotNone(question)
        self.assertEqual(question["base_version_id"], project["current_version_id"])

        plan = project["versions"][0]["plan"] + " 실제 질문 100개로 평가 기준을 정한다."
        payload = {
            "plan": plan, "base_version_id": project["current_version_id"], "request_id": "question-revision-1",
            "clarification": {"question_id": question["id"], "status": "answered", "answer": "실제 질문 100개로 확인한다"},
        }
        revised = self.request(f"/api/projects/{project_id}/versions", "POST", payload)
        repeated = self.request(f"/api/projects/{project_id}/versions", "POST", payload)
        self.assertEqual(len(revised["versions"]), 2)
        self.assertEqual(len(repeated["versions"]), 2)
        self.assertEqual(revised["versions"][0]["clarification"]["source"], "user_provided_unverified")
        self.assertEqual(revised["versions"][0]["clarification"]["answer"], "실제 질문 100개로 확인한다")

        form_payload = urlencode({**payload, "clarification": json.dumps(payload["clarification"], ensure_ascii=False)})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        connection.request("POST", f"/api/projects/{project_id}/versions", form_payload, {"Content-Type": "application/x-www-form-urlencoded"})
        response = connection.getresponse()
        self.assertEqual(response.status, 303)
        response.read()
        connection.close()
        self.assertEqual(len(self.request(f"/api/projects/{project_id}")["versions"]), 2)

        with self.assertRaises(HTTPError) as context:
            self.request(f"/api/projects/{project_id}/versions", "POST", {
                "plan": plan + " 다른 계획", "base_version_id": revised["current_version_id"],
                "clarification": {"question_id": "wrong", "status": "answered", "answer": "내용"},
            })
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

if __name__ == "__main__":
    unittest.main()
