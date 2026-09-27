from __future__ import annotations

import json
import mimetypes
import os
import re
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .cases import CaseCatalog
from .engine import AutopsyEngine, exact_substring
from .model import ModelError
from .questions import choose_question
from .storage import Store


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


class Application:
    def __init__(self, root: Path = ROOT, mode: str | None = None, database: Path | None = None):
        self.mode = mode or os.environ.get("AUTOPSY_MODE") or "demo"
        if self.mode not in {"live", "demo"}:
            raise ValueError("AUTOPSY_MODE must be live or demo")
        self.store = Store(database or root / "data" / "autopsy.sqlite3")
        self.catalog = CaseCatalog(root / "cases" / "cases.json")
        self.engine = AutopsyEngine(self.store, self.catalog, self.mode)


class Handler(BaseHTTPRequestHandler):
    server: "AppServer"

    def respond(self, status: int, data: dict | list) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 200_000:
            raise ValueError("요청 크기가 허용 범위를 벗어났습니다.")
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("JSON 형식이 올바르지 않습니다.") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON 객체가 필요합니다.")
        return data

    def read_form(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 200_000:
            raise ValueError("요청 크기가 허용 범위를 벗어났습니다.")
        try:
            fields = parse_qs(self.rfile.read(length).decode("utf-8"), strict_parsing=True)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("폼 입력을 읽지 못했습니다.") from exc
        return {key: values[0] for key, values in fields.items()}

    def serve_static(self, path: str) -> None:
        name = "index.html" if path == "/" else path.removeprefix("/")
        requested = (STATIC / name).resolve()
        if not requested.is_relative_to(STATIC.resolve()) or not requested.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = requested.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", (mimetypes.guess_type(requested.name)[0] or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def dispatch(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        app = self.server.app
        if self.command == "GET" and not path.startswith("/api/"):
            self.serve_static(path)
            return
        if self.command == "GET" and path == "/api/health":
            self.respond(200, {"ok": True, "mode": app.mode, "model": app.engine.model.model if app.engine.model else None, "cases": len(app.catalog.cases)})
            return
        if self.command == "GET" and path == "/api/cases":
            self.respond(200, {"cases": app.catalog.public_metadata()})
            return
        if path == "/api/projects":
            if self.command == "GET":
                self.respond(200, {"projects": app.store.list_projects()})
                return
            if self.command == "POST":
                data = self.read_json()
                if not isinstance(data.get("title"), str) or not isinstance(data.get("plan"), str):
                    raise ValueError("프로젝트 제목과 계획은 문자열이어야 합니다.")
                title = data["title"].strip()
                plan = data["plan"].strip()
                if not title or not plan:
                    raise ValueError("프로젝트 제목과 계획을 입력해 주세요.")
                if len(plan) > 20_000:
                    raise ValueError("계획은 2만 자 이하로 입력해 주세요.")
                self.respond(201, app.store.create_project(title[:120], plan))
                return
        match = re.fullmatch(r"/api/projects/([0-9a-f-]+)(?:/(interpret|interpretation|analyze|versions|feedback|question))?", path)
        if not match:
            self.respond(404, {"error": "요청한 경로를 찾지 못했습니다."})
            return
        project_id, action = match.groups()
        project = app.store.get_project(project_id)
        if not project:
            self.respond(404, {"error": "프로젝트를 찾지 못했습니다."})
            return
        if self.command == "GET" and action is None:
            self.respond(200, project)
            return
        if self.command == "GET" and action == "question":
            self.respond(200, {"question": choose_question(project)})
            return
        if self.command == "POST" and action == "interpret":
            result = app.engine.interpret(project)
            self.respond(200, {"interpretation": result, "project": app.store.get_project(project_id)})
            return
        if self.command == "PUT" and action == "interpretation":
            data = self.read_json()
            version = project["versions"][0]
            if data.get("version_id") != version["id"]:
                raise ValueError("현재 계획 버전이 아닙니다. 화면을 새로고침해 주세요.")
            raw = data.get("interpretation")
            if not isinstance(raw, dict):
                raise ValueError("계획 해석이 올바르지 않습니다.")
            facts = raw.get("facts", [])
            assumptions = raw.get("assumptions", [])
            gaps = raw.get("gaps", [])
            if not all(isinstance(value, list) for value in (facts, assumptions, gaps)):
                raise ValueError("계획 해석의 목록 형식이 올바르지 않습니다.")
            if any(not isinstance(item, dict) or not exact_substring(item.get("quote", ""), version["plan"]) or not isinstance(item.get("text"), str) for item in facts):
                raise ValueError("사실은 계획 원문의 정확한 인용을 포함해야 합니다.")
            if any(not isinstance(item, dict) or not isinstance(item.get("text"), str) or not isinstance(item.get("based_on"), str) for item in assumptions):
                raise ValueError("가정 형식이 올바르지 않습니다.")
            if any(not isinstance(item, str) for item in gaps):
                raise ValueError("정보 공백 형식이 올바르지 않습니다.")
            clean = {"facts": facts[:20], "assumptions": assumptions[:20], "gaps": gaps[:20]}
            app.store.set_interpretation(version["id"], clean)
            self.respond(200, {"interpretation": clean, "project": app.store.get_project(project_id)})
            return
        if self.command == "POST" and action == "analyze":
            report = app.engine.analyze(project)
            self.respond(200, {"report": report, "project": app.store.get_project(project_id)})
            return
        if self.command == "POST" and action == "versions":
            form_submission = self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded")
            data = self.read_form() if form_submission else self.read_json()
            if not isinstance(data.get("plan"), str):
                raise ValueError("수정된 계획은 문자열이어야 합니다.")
            if data.get("base_version_id") is not None and not isinstance(data["base_version_id"], str):
                raise ValueError("기준 계획 버전이 올바르지 않습니다.")
            request_id = data.get("request_id")
            if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 120):
                raise ValueError("저장 요청 식별자가 올바르지 않습니다.")
            clarification = data.get("clarification")
            if form_submission and isinstance(clarification, str):
                try:
                    clarification = json.loads(clarification)
                except json.JSONDecodeError as exc:
                    raise ValueError("질문 답변 형식이 올바르지 않습니다.") from exc
            if clarification is not None:
                if not isinstance(clarification, dict):
                    raise ValueError("질문 답변 형식이 올바르지 않습니다.")
                if clarification.get("status") not in {"answered", "unknown"}:
                    raise ValueError("질문 답변 상태가 올바르지 않습니다.")
                answer = clarification.get("answer", "")
                if not isinstance(answer, str) or len(answer) > 2000 or (clarification["status"] == "answered" and not answer.strip()):
                    raise ValueError("질문 답변을 확인해 주세요.")
                if data.get("base_version_id") == project["current_version_id"]:
                    question = choose_question(project)
                    if not question or clarification.get("question_id") != question["id"]:
                        raise ValueError("현재 계획의 질문이 아닙니다. 페이지를 새로고침해 주세요.")
                    clarification = {
                        "question_id": question["id"], "mechanism_key": question["mechanism_key"],
                        "question": question["prompt"], "status": clarification["status"],
                        "answer": answer.strip(),
                        "source": "user_provided_unverified" if clarification["status"] == "answered" else "user_declared_unknown",
                    }
            plan = data["plan"].strip()
            if not plan:
                raise ValueError("수정된 계획을 입력해 주세요.")
            if len(plan) > 20_000:
                raise ValueError("수정된 계획은 2만 자 이하로 입력해 주세요.")
            if plan == project["versions"][0]["plan"] and data.get("base_version_id") in (None, project["current_version_id"]):
                raise ValueError("이전 계획과 같은 내용입니다.")
            revised = app.store.add_version(project_id, plan, data.get("base_version_id"), clarification, request_id)
            if form_submission:
                if app.mode == "demo" and revised["versions"][0]["report"] is None:
                    app.engine.interpret(revised)
                    app.engine.analyze(app.store.get_project(project_id))
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.respond(201, revised)
            return
        if self.command == "POST" and action == "feedback":
            data = self.read_json()
            key = str(data.get("mechanism_key", ""))
            if key not in app.catalog.by_id:
                raise ValueError("알 수 없는 위험 유형입니다.")
            excluded = data.get("excluded")
            if not isinstance(excluded, bool):
                raise ValueError("제외 상태를 선택해 주세요.")
            if not isinstance(data.get("reason", ""), str):
                raise ValueError("제외 이유는 문자열이어야 합니다.")
            reason = data.get("reason", "").strip()[:500]
            if excluded and not reason:
                raise ValueError("위험을 제외하는 이유를 입력해 주세요.")
            app.store.set_feedback(project_id, key, excluded, reason)
            self.respond(200, app.store.get_project(project_id))
            return
        self.respond(405, {"error": "지원하지 않는 요청입니다."})

    def do_GET(self) -> None:
        self.handle_request()

    def do_POST(self) -> None:
        self.handle_request()

    def do_PUT(self) -> None:
        self.handle_request()

    def handle_request(self) -> None:
        try:
            self.dispatch()
        except ValueError as exc:
            self.respond(400, {"error": str(exc)})
        except ModelError as exc:
            self.respond(502, {"error": str(exc)})
        except Exception:
            traceback.print_exc()
            self.respond(500, {"error": "서버에서 오류가 발생했습니다. 터미널 로그를 확인해 주세요."})


class AppServer(ThreadingHTTPServer):
    app: Application


def serve(host: str = "127.0.0.1", port: int = 8765, mode: str | None = None, database: Path | None = None) -> None:
    server = AppServer((host, port), Handler)
    server.app = Application(mode=mode, database=database)
    print(f"Project Autopsy: http://{host}:{port} ({server.app.mode} mode)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
