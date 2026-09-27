# 검증 기록

## v0.2 구현 검증 — 2026-09-27

- 질문 선정은 동일 보고서에서 결정적으로 동작하고, 제외한 위험을 다시 질문하지 않는다.
- `답변 / 아직 모름 / 건너뛰기 → 수정안 초안 → 명시적 버전 저장`을 프런트엔드 모의 실행으로 확인했다. 새로고침 후 초안 복구도 확인했다.
- 답변 출처와 질문 ID가 새 버전에 저장된다. 동일 `request_id`의 JSON·폼 재전송은 버전을 중복 생성하지 않는다.
- `아직 모름`은 연결 위험을 자동 완화하지 않고, 사용자 답변만으로 실행 완료·해소를 확정하지 않는다.
- 기존 SQLite DB를 백업한 뒤 새 열을 추가했다. `PRAGMA integrity_check`가 `ok`였고, 기존 프로젝트 1개와 버전 1개가 보존됐다.
- 임시 DB 서버와 사용자 DB 서버에서 `/api/health`가 정상 응답했다.

```text
python3 -m unittest discover -s tests -q   → 17 tests OK
node tests/test_frontend.cjs                 → 통과
node tests/test_question_frontend.cjs        → 통과
node --check static/app.js                   → 통과
python3 -m compileall -q project_autopsy     → 통과
```

**아직 남은 출시 게이트:** 사용자가 실제 접속하는 브라우저에서 질문 답변부터 Version 2 비교까지 직접 클릭하며 검증하지 못했다. Mac이 잠겨 브라우저 제어가 불가능했고 `agent-browser` 명령도 설치되어 있지 않았다. 특히 이전에 발생한 로컬 브라우저의 빈 POST 응답이 실제 사용 환경에서 해결됐는지는 미확인이다. Live 모드의 실제 모델 호출도 유효한 API 키가 없어 미검증이다. 따라서 v0.2는 구현·자동 테스트 완료 상태이지 출시 검증 완료 상태가 아니다.

## v0.1 검증 — 2026-09-23

## 확인한 흐름

- 데모 모드에서 프로젝트 생성 → 계획 해석 → 사망 보고서 → 새 버전 → 위험 변화 비교 → 위험 제외 API가 순서대로 동작한다.
- 예시 버튼 클릭과 빈 초기 조회 응답의 재시도를 화면 스크립트 모의 실행으로 확인했다.
- 사례 인용문이 저장된 사례 원문에 존재하고, 모델이 없는 사례 ID를 제시하면 보고서를 저장하지 않는다.
- 새 계획에 대응 문장 근거가 없는 `완화`·`해소` 판정과 새 보고서에 위험이 남아 있는 `해소` 판정을 막는다.
- 빈 계획, 잘못된 인용, 제외 이유 누락 등의 요청은 JSON 오류와 HTTP 400을 반환한다.
- 실행 중인 서버에서 `/api/health`, `/api/projects`, `/api/cases`의 응답 본문을 끝까지 받고 JSON으로 파싱했다.

## 실행 결과

```text
python3 -m unittest discover -s tests -q   → 10 tests OK
node tests/test_frontend.cjs                 → frontend example and bootstrap retry: ok
node --check static/app.js                   → 통과
```

## 아직 검증하지 못한 부분

- 실제 브라우저 화면의 시각 확인: 검증 시점에 Mac이 잠겨 있어 브라우저 제어가 불가능했다.
- Live 모델 호출: 현재 환경의 `OPENAI_API_KEY`가 API에서 401로 거절됐다. 모델 출력과 인용 검증 경로는 모의 응답으로 테스트했다.

데모 분석에 쓰이는 12개 사례는 모두 `fictional_sample`이다. 실제 프로젝트의 실패 확률이나 검증된 과거 사건으로 해석하면 안 된다.
