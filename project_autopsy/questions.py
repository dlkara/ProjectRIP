from __future__ import annotations


TEMPLATES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "scope_overreach": ("첫 시험 운영의 대상은 누구이며, 전사 배포 전에 무엇을 확인할 건가요?", "대상 부서·인원과 배포 확대 기준", ("대상", "사용자")),
    "undefined_metric": ("목표 품질을 어떤 실제 질문과 채점 기준으로 확인할 건가요?", "평가 질문, 정답 근거, 통과 기준", ("평가", "정확도", "품질")),
    "permission_gap": ("권한이 다른 두 사용자가 같은 문서를 검색할 때 접근을 어떻게 검증할 건가요?", "권한 규칙과 접근 차단 테스트", ("권한", "개인정보")),
    "dirty_source_data": ("전체 색인 전에 어떤 문서 표본을 검사하고 제외 기준을 정할 건가요?", "표본 종류, 검수 방법, 제외 기준", ("문서", "데이터")),
    "no_user_research": ("실제 사용자의 어떤 문제를 누구에게 확인했나요?", "대상 사용자, 확인한 문제, 인터뷰 또는 관찰 결과", ("사용자", "문제")),
    "external_dependency": ("외부 서비스가 느려지거나 멈추면 어떤 대안을 쓸 건가요?", "호출 한도, 장애 신호, 대체 절차", ("외부", "API")),
    "single_owner": ("담당자가 자리를 비울 때 누가 어떤 문서로 배포와 복구를 진행할 수 있나요?", "대체 담당자와 복구 절차", ("운영", "복구")),
    "cost_blindness": ("예상 사용량이 늘어날 때 모델 호출 비용의 상한을 어떻게 정할 건가요?", "사용량 가정, 단위 비용, 제한 기준", ("비용", "사용량")),
    "migration_gap": ("실제 데이터 복사본으로 이전과 복구를 언제 시험할 건가요?", "시험 데이터, 성공 기준, 롤백 절차", ("이전", "복구")),
    "support_gap": ("출시 후 사용자의 문의와 예외 상황은 누가 어떤 기준으로 처리하나요?", "담당자, 응답 기준, 대표 예외", ("문의", "지원")),
    "stale_assumption": ("지금의 핵심 가정이 달라졌다는 신호를 무엇으로 확인할 건가요?", "관찰 지표와 재검토 시점", ("가정", "검증")),
    "schedule_shortcut": ("일정 안에서 생략하면 안 되는 검증은 무엇이고 언제 할 건가요?", "필수 검증, 예정 시점, 완료 기준", ("일정", "검증")),
}


def choose_question(project: dict) -> dict | None:
    if not project.get("versions"):
        return None
    version = project["versions"][0]
    report = version.get("report") or {}
    excluded = {item["mechanism_key"] for item in project.get("feedback", []) if item["excluded"]}
    gaps = " ".join((version.get("interpretation") or {}).get("gaps", []))
    candidates = []
    for index, risk in enumerate(report.get("risks", [])):
        key = risk.get("mechanism_key")
        if key in excluded or key not in TEMPLATES:
            continue
        _, _, gap_terms = TEMPLATES[key]
        gap_match = any(term in gaps for term in gap_terms)
        priority = (risk.get("impact") == "high", gap_match, -index)
        candidates.append((priority, risk))
    if not candidates:
        return None
    _, risk = max(candidates, key=lambda item: item[0])
    key = risk["mechanism_key"]
    prompt, hint, _ = TEMPLATES[key]
    return {
        "id": f"{version['id']}:{key}",
        "base_version_id": version["id"],
        "mechanism_key": key,
        "risk_title": risk["title"],
        "condition_quote": risk["condition_quote"],
        "prompt": prompt,
        "answer_hint": hint,
        "why": f"현재 계획의 ‘{risk['condition_quote']}’와 연결된 위험을 판단하려면 이 정보가 필요합니다.",
        "action": risk["action"],
        "action_when": risk["action_when"],
        "done_when": risk["done_when"],
    }
