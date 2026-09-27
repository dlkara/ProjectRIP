from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plan_versions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    number INTEGER NOT NULL,
                    plan TEXT NOT NULL,
                    interpretation TEXT,
                    created_at TEXT NOT NULL,
                    clarification TEXT,
                    request_id TEXT,
                    UNIQUE(project_id, number)
                );
                CREATE TABLE IF NOT EXISTS analyses (
                    id TEXT PRIMARY KEY,
                    version_id TEXT NOT NULL REFERENCES plan_versions(id),
                    report TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    mechanism_key TEXT NOT NULL,
                    excluded INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, mechanism_key)
                );
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(plan_versions)")}
            if "clarification" not in columns:
                db.execute("ALTER TABLE plan_versions ADD COLUMN clarification TEXT")
            if "request_id" not in columns:
                db.execute("ALTER TABLE plan_versions ADD COLUMN request_id TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_versions_request_id ON plan_versions(request_id) WHERE request_id IS NOT NULL")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def list_projects(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT p.id, p.title, p.created_at, MAX(v.number) AS current_version
                   FROM projects p JOIN plan_versions v ON v.project_id = p.id
                   GROUP BY p.id ORDER BY p.created_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def create_project(self, title: str, plan: str) -> dict:
        project_id, version_id = str(uuid4()), str(uuid4())
        created = now()
        with self._connect() as db:
            db.execute("INSERT INTO projects VALUES (?, ?, ?)", (project_id, title, created))
            db.execute(
                "INSERT INTO plan_versions (id, project_id, number, plan, interpretation, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (version_id, project_id, 1, plan, None, created),
            )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict | None:
        with self._connect() as db:
            project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not project:
                return None
            versions = db.execute(
                "SELECT * FROM plan_versions WHERE project_id = ? ORDER BY number DESC", (project_id,)
            ).fetchall()
            feedback = db.execute(
                "SELECT mechanism_key, excluded, reason FROM feedback WHERE project_id = ?", (project_id,)
            ).fetchall()
            output = dict(project)
            output["versions"] = []
            for version in versions:
                record = dict(version)
                record["interpretation"] = json.loads(record["interpretation"]) if record["interpretation"] else None
                record["clarification"] = json.loads(record["clarification"]) if record["clarification"] else None
                analysis = db.execute(
                    "SELECT * FROM analyses WHERE version_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (record["id"],),
                ).fetchone()
                record["report"] = json.loads(analysis["report"]) if analysis else None
                output["versions"].append(record)
            output["feedback"] = [dict(row) for row in feedback]
            output["current_version_id"] = output["versions"][0]["id"]
            return output

    def add_version(self, project_id: str, plan: str, base_version_id: str | None = None,
                    clarification: dict | None = None, request_id: str | None = None) -> dict | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if request_id:
                existing = db.execute(
                    "SELECT project_id, plan FROM plan_versions WHERE request_id = ?", (request_id,)
                ).fetchone()
                if existing:
                    if existing["project_id"] != project_id or existing["plan"] != plan:
                        raise ValueError("저장 요청 식별자가 다른 계획에 이미 사용됐습니다.")
                    return self.get_project(project_id)
            latest = db.execute(
                "SELECT id, number, plan FROM plan_versions WHERE project_id = ? ORDER BY number DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if not latest:
                return None
            if base_version_id and latest["id"] != base_version_id:
                if latest["plan"] != plan:
                    raise ValueError("계획이 다른 곳에서 변경되었습니다. 페이지를 새로고침해 주세요.")
            else:
                db.execute(
                    """INSERT INTO plan_versions
                       (id, project_id, number, plan, interpretation, created_at, clarification, request_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid4()), project_id, latest["number"] + 1, plan, None, now(),
                     encode(clarification) if clarification else None, request_id),
                )
        return self.get_project(project_id)

    def set_interpretation(self, version_id: str, interpretation: dict) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE plan_versions SET interpretation = ? WHERE id = ?",
                (encode(interpretation), version_id),
            )

    def add_analysis(self, version_id: str, report: dict) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO analyses VALUES (?, ?, ?, ?)",
                (str(uuid4()), version_id, encode(report), now()),
            )

    def set_feedback(self, project_id: str, mechanism_key: str, excluded: bool, reason: str) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO feedback VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, mechanism_key) DO UPDATE SET
                   excluded = excluded.excluded, reason = excluded.reason,
                   updated_at = excluded.updated_at""",
                (project_id, mechanism_key, int(excluded), reason, now()),
            )
