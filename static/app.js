const state = { health: null, projects: [], cases: [], project: null, viewVersion: null, question: null, questionSkipped: false, draft: null, busy: false };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

class EmptyResponseError extends Error {}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const attempts = method === "GET" ? 2 : 1;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const response = await fetch(path, {
      ...options,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const body = await response.text();
    if (!body.trim()) {
      if (attempt + 1 < attempts) continue;
      throw new EmptyResponseError(`${path} 응답이 비어 있습니다.`);
    }
    let data;
    try {
      data = JSON.parse(body);
    } catch {
      throw new Error(`${path} 응답을 읽지 못했습니다 (HTTP ${response.status}). 페이지를 새로고침해 주세요.`);
    }
    if (!response.ok) throw new Error(data.error || `${path} 요청 실패 (HTTP ${response.status})`);
    return data;
  }
}

function banner(message, error = false) {
  const target = $(error ? "#error" : "#status");
  const other = $(error ? "#status" : "#error");
  other.hidden = true;
  target.textContent = message;
  target.hidden = !message;
}

async function run(message, task) {
  if (state.busy) return;
  state.busy = true;
  banner(message);
  document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    await task();
    banner("");
  } catch (error) {
    banner(error.message, true);
  } finally {
    state.busy = false;
    document.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

async function refreshProject(id, keepView = false) {
  state.project = await api(`/api/projects/${id}`);
  if (!keepView) state.viewVersion = state.project.versions[0].number;
  state.questionSkipped = false;
  await refreshQuestion();
  restoreQuestionDraft();
  localStorage.setItem("autopsy.lastProject", id);
  state.projects = (await api("/api/projects")).projects;
  render();
  restoreRevisionDraft();
}

async function refreshQuestion() {
  state.question = null;
  if (!state.project?.versions[0]?.report) return;
  try {
    state.question = (await api(`/api/projects/${state.project.id}/question`)).question;
    const skipped = sessionStorage.getItem(`autopsy.skippedQuestion.${state.project.id}`);
    state.questionSkipped = Boolean(state.question && skipped === state.question.id);
  } catch (error) {
    console.warn("질문을 불러오지 못했습니다:", error);
  }
}

function renderSidebar() {
  $("#mode-label").textContent = state.health?.mode === "live" ? `LIVE · ${state.health.model}` : "DEMO · 가상 사례";
  $("#project-list").innerHTML = state.projects.length
    ? state.projects.map((project) => `<button class="project-link ${state.project?.id === project.id ? "active" : ""}" data-action="open" data-id="${escapeHtml(project.id)}">${escapeHtml(project.title)}<small>VERSION ${project.current_version}</small></button>`).join("")
    : `<div class="side-empty">아직 프로젝트가 없습니다.</div>`;
}

function renderLanding() {
  return `<section class="hero"><div><p class="eyebrow">PROJECT AUTOPSY / START HERE</p><h1>프로젝트가<br>망하기 전에.</h1><p class="hero-sub">계획을 입력하면 가능한 실패 경로를 조사합니다. 사망 보고서를 읽고 계획을 고쳐, 무엇이 달라졌는지 확인해보세요.</p></div><div class="hero-stamp">FUTURE<br>CASE FILE</div></section>
    <form id="create-form" class="surface form-card">
      <div class="field"><label for="project-title">프로젝트 이름</label><input id="project-title" type="text" maxlength="120" placeholder="예: AI 사내 문서 검색" required></div>
      <div class="field"><label for="project-plan">현재 계획</label><textarea id="project-plan" placeholder="무엇을, 누구에게, 언제까지 만들 계획인가요? 성공 기준과 제약도 함께 적어주세요." required></textarea><p class="helper">계획이 구체적일수록 조사할 가정을 더 정확히 찾을 수 있습니다.</p></div>
      <div class="button-row"><button class="primary" type="submit">부검 시작하기 →</button><button class="ghost" type="button" data-action="example">예시 계획 불러오기</button></div>
      <p class="footer-note">${state.health?.mode === "live" ? "Live 모드: 입력 계획이 OpenAI API로 전송됩니다." : "Demo 모드: 네트워크 호출 없이 가상 사례와 규칙 기반 분석으로 작동합니다."}</p>
    </form>`;
}

function renderInterpretation(interpretation, current) {
  if (!interpretation) return `<div class="surface panel"><h3>계획 해석 대기</h3><p class="muted">분석 전에 계획에서 확인된 사실과 아직 검증하지 않은 가정을 분리합니다.</p>${current ? `<button class="primary" data-action="interpret">계획 해석하기</button>` : ""}</div>`;
  const facts = interpretation.facts.map((fact, index) => `<div class="edit-item"><span class="risk-label">FACT ${index + 1}</span><input type="text" data-fact="${index}" value="${escapeHtml(fact.text)}"><code>원문: ${escapeHtml(fact.quote)}</code></div>`).join("");
  const assumptions = interpretation.assumptions.map((item, index) => `<div class="edit-item"><span class="risk-label">ASSUMPTION ${index + 1}</span><input type="text" data-assumption="${index}" value="${escapeHtml(item.text)}"><code>근거 맥락: ${escapeHtml(item.based_on)}</code></div>`).join("");
  return `<div class="two-col"><div class="surface panel"><h3>확인된 사실</h3><p class="section-help">계획 원문에서 직접 확인한 내용입니다.</p><div class="edit-group">${facts || `<p class="muted">확인된 사실이 없습니다.</p>`}</div></div>
    <div class="surface panel"><h3>가정과 빈칸</h3><p class="section-help">틀렸다고 판정한 항목이 아니라, 확인이 필요한 조건입니다.</p><div class="edit-group">${assumptions || `<p class="muted">추출된 가정이 없습니다.</p>`}</div><label for="gaps" style="margin-top:18px">언급되지 않은 정보</label><textarea id="gaps" style="min-height:95px">${escapeHtml(interpretation.gaps.join("\n"))}</textarea></div></div>
    ${current ? `<div class="button-row" style="margin-top:15px"><button class="ghost" data-action="save-interpretation">해석 수정 저장</button><button class="primary" data-action="analyze">사망 보고서 작성 →</button></div>` : ""}`;
}

function riskLabel(key, project) {
  for (const version of project.versions) {
    const risk = version.report?.risks?.find((item) => item.mechanism_key === key);
    if (risk) return risk.title;
  }
  return key;
}

function renderComparison(report) {
  if (!report.comparison) return "";
  const items = report.comparison.changes.map((change) => `<div class="comparison-item"><strong>${escapeHtml(change.status)}</strong><div><b>${escapeHtml(riskLabel(change.mechanism_key, state.project))}</b><br>${escapeHtml(change.reason)}${change.plan_quote ? `<br><span class="tiny muted">계획 근거: “${escapeHtml(change.plan_quote)}”</span>` : ""}</div></div>`).join("");
  return `<section><div class="section-title"><div><p class="section-kicker">REVISION IMPACT</p><h2>계획상 무엇이 달라졌나</h2><p class="section-help">V${report.comparison.before_version} → V${report.comparison.after_version} · 실제 조치 완료 여부는 별도 확인이 필요합니다.</p></div></div><div class="comparison-list">${items || `<p class="muted">비교할 위험이 없습니다.</p>`}</div></section>`;
}

function renderQuestion(version, current) {
  if (!current || !version.report) return "";
  if (state.questionSkipped) return `<section class="question-section"><div class="surface panel"><p class="section-kicker">ONE QUESTION</p><p class="muted">이번 질문을 건너뛰었습니다. 보고서는 변경되지 않았습니다.</p><button class="ghost" data-action="show-question">질문 다시 보기</button></div></section>`;
  const question = state.question;
  if (!question) return "";
  const draft = state.draft?.questionId === question.id ? state.draft : null;
  return `<section class="question-section" aria-labelledby="question-heading"><div class="section-title"><div><p class="section-kicker">ONE QUESTION / BEFORE YOU GO</p><h2 id="question-heading">보고서가 묻습니다</h2></div></div>
    <div class="surface panel question-card"><span class="pill pill-orange">연결 위험 · ${escapeHtml(question.risk_title)}</span><h3>${escapeHtml(question.prompt)}</h3><p class="muted">${escapeHtml(question.why)}</p><p class="helper">답변에 도움이 되는 정보: ${escapeHtml(question.answer_hint)}</p>
      <label for="question-answer">당신의 답변 <span class="muted">· 사용자 제공, 아직 검증되지 않음</span></label><textarea id="question-answer" maxlength="2000" placeholder="확인한 내용이나 구체적인 계획을 적어 주세요.">${escapeHtml(draft?.answer || "")}</textarea>
      <div class="button-row"><button class="primary" data-action="answer-question">답변으로 수정안 만들기 →</button><button class="ghost" data-action="unknown-question">아직 모름</button><button class="ghost" data-action="skip-question">건너뛰기</button></div>
      ${draft ? `<p class="question-result">${draft.status === "unknown" ? "아직 모르는 조건으로 기록했습니다. 검증 행동 초안을 아래에서 확인하세요." : "답변을 수정안 초안에 반영했습니다. 저장 전 내용을 확인하세요."}</p>` : ""}
    </div></section>`;
}

function renderRevision(version) {
  const draft = state.draft?.baseVersionId === version.id ? state.draft : null;
  const proposed = draft?.plan || version.plan;
  const addition = proposed.startsWith(version.plan) ? proposed.slice(version.plan.length).trim() : "";
  return `<section><div class="section-title"><div><p class="section-kicker">03 / RESUSCITATION</p><h2>계획 살리기</h2><p class="section-help">수정안은 초안입니다. 직접 확인·편집한 뒤 새 버전으로 저장하세요. 계획에 썼다는 사실만으로 조치가 완료되지는 않습니다.</p></div></div>
    <div class="surface form-card">${draft ? `<div class="draft-note"><span class="risk-label">${draft.status === "unknown" ? "아직 모름 · 검증 행동 제안" : "사용자 답변 · 미검증"}</span><p>연결 위험: ${escapeHtml(state.question?.risk_title || draft.mechanismKey)}</p>${addition ? `<p><b>초안에 추가:</b> ${escapeHtml(addition)}</p>` : ""}<button class="small-button" data-action="discard-draft">초안 취소</button></div>` : ""}
      <label for="revision-plan">수정된 계획</label><textarea id="revision-plan">${escapeHtml(proposed)}</textarea><div class="button-row" style="margin-top:13px"><button class="secondary" data-action="revise">새 버전으로 저장하고 분석 →</button></div></div></section>`;
}

function renderRisk(risk, excluded, current) {
  const evidence = risk.evidence || {};
  return `<article class="surface risk-card">
    <div class="button-row"><span class="pill pill-orange">${escapeHtml(risk.impact?.toUpperCase() || "RISK")}</span><span class="pill">${escapeHtml(evidence.source_type === "fictional_sample" ? "가상 샘플 사례" : evidence.source_type || "출처 확인")}</span>${excluded ? `<span class="pill">사용자가 제외함</span>` : ""}</div>
    <h3>${escapeHtml(risk.title)}</h3>
    <div class="risk-line"><span class="risk-label">현재 계획의 문장</span><p>“${escapeHtml(risk.condition_quote)}”</p></div>
    <div class="risk-line"><span class="risk-label">실패 경로</span><p>${escapeHtml(risk.assumption)} → ${escapeHtml(risk.mechanism)} → ${escapeHtml(risk.outcome)}</p></div>
    <div class="risk-line"><span class="risk-label">미리 볼 신호</span><p>${escapeHtml(risk.early_signal)}</p></div>
    <div class="evidence"><span class="risk-label">사례 근거 · ${escapeHtml(evidence.title)}</span><blockquote>${escapeHtml(evidence.excerpt)}</blockquote><p class="tiny muted">닮은 점: ${escapeHtml(risk.similarity)}</p><p class="tiny muted">다른 점: ${escapeHtml(risk.difference)}</p></div>
    <div class="action-box"><span class="risk-label">프로젝트를 살릴 조치</span><p><b>${escapeHtml(risk.action)}</b></p><p class="muted">시점: ${escapeHtml(risk.action_when)} · 완료 기준: ${escapeHtml(risk.done_when)}</p></div>
    ${current ? `<div class="risk-footer"><span class="tiny muted mono">${escapeHtml(risk.mechanism_key)}</span><button class="small-button" data-action="feedback" data-key="${escapeHtml(risk.mechanism_key)}" data-excluded="${excluded ? "0" : "1"}">${excluded ? "제외 취소" : "관련 없음"}</button></div>` : ""}
  </article>`;
}

function renderReport(report, current) {
  if (!report) return "";
  const feedback = new Map(state.project.feedback.map((item) => [item.mechanism_key, item]));
  const visibleRisks = current ? report.risks.filter((risk) => !feedback.get(risk.mechanism_key)?.excluded) : report.risks;
  const excluded = current ? state.project.feedback.filter((item) => item.excluded) : [];
  const excludedPanel = excluded.length ? `<div class="surface panel" style="margin-top:16px"><h3>제외한 위험</h3><p class="section-help">현재 분석에서 제외됩니다. 다시 포함할 수 있습니다.</p>${excluded.map((item) => {
    const known = state.cases.find((caseItem) => caseItem.id === item.mechanism_key);
    return `<div class="risk-footer"><div><b>${escapeHtml(known?.mechanism || item.mechanism_key)}</b><div class="tiny muted">${escapeHtml(item.reason)}</div></div><button class="small-button" data-action="feedback" data-key="${escapeHtml(item.mechanism_key)}" data-excluded="0">다시 포함</button></div>`;
  }).join("")}</div>` : "";
  return `<section><div class="section-title"><div><p class="section-kicker">THE AUTOPSY</p><h2>미래의 사망 보고서</h2></div></div>
    <div class="report-head"><p class="eyebrow">가상 미래 시나리오 · ${report.mode === "demo" ? "DEMO ANALYSIS" : "LIVE ANALYSIS"}</p><h2>${escapeHtml(report.headline)}</h2><p>${escapeHtml(report.summary)}</p><div class="report-meta"><span class="pill pill-light">미래 예측 아님</span><span class="pill pill-light">위험 ${visibleRisks.length}개</span></div></div>
    <div class="section-title"><div><p class="section-kicker">CAUSES OF FAILURE</p><h2>조사할 실패 경로</h2></div></div>
    ${visibleRisks.length ? `<div class="risk-grid">${visibleRisks.map((risk) => renderRisk(risk, false, current)).join("")}</div>` : `<div class="surface empty-report">현재 계획과 사례 라이브러리에서 근거를 연결할 수 있는 위험을 찾지 못했습니다. 계획을 더 구체적으로 써보세요.</div>`}
    ${excludedPanel}
    ${renderComparison(report)}</section>`;
}

function renderProject() {
  const project = state.project;
  const version = project.versions.find((item) => item.number === state.viewVersion) || project.versions[0];
  const current = version.id === project.current_version_id;
  const options = project.versions.map((item) => `<option value="${item.number}" ${item.number === version.number ? "selected" : ""}>Version ${item.number}</option>`).join("");
  return `<section class="hero"><div><p class="eyebrow">CASE NO. ${escapeHtml(project.id.slice(0, 8))}</p><h1>${escapeHtml(project.title)}</h1><p class="hero-sub">현재 계획을 조사하고, 바꾼 계획이 어떤 위험을 줄였는지 살펴보세요.</p></div><div class="hero-stamp">UNDER<br>EXAMINATION</div></section>
    <div class="section-title"><div><p class="section-kicker">01 / THE PLAN</p><h2>검토할 계획</h2></div><select class="version-select" id="version-select" aria-label="계획 버전">${options}</select></div>
    <div class="surface panel"><div class="button-row"><span class="pill">VERSION ${version.number}</span><span class="pill">${current ? "현재 계획" : "과거 계획"}</span></div><div class="plan-text">${escapeHtml(version.plan)}</div>${version.clarification ? `<p class="helper">이 버전의 질문 답변: ${version.clarification.status === "unknown" ? "아직 모름" : `“${escapeHtml(version.clarification.answer)}”`} · 사용자 제공/미검증</p>` : ""}</div>
    <div class="section-title"><div><p class="section-kicker">02 / INTERPRETATION</p><h2>계획에서 읽은 것</h2><p class="section-help">분석 전에 모델이 사실과 추론을 섞지 않았는지 확인해 주세요.</p></div></div>
    ${renderInterpretation(version.interpretation, current)}
    ${renderReport(version.report, current)}
    ${renderQuestion(version, current)}
    ${current ? renderRevision(version) : ""}`;
}

function render() {
  renderSidebar();
  $("#app").innerHTML = state.project ? renderProject() : renderLanding();
}

async function performInterpret() {
  const id = state.project.id;
  const data = await api(`/api/projects/${id}/interpret`, { method: "POST", body: "{}" });
  state.project = data.project;
  state.viewVersion = state.project.versions[0].number;
  await refreshQuestion();
  render();
}

async function performAnalyze() {
  const id = state.project.id;
  const data = await api(`/api/projects/${id}/analyze`, { method: "POST", body: "{}" });
  state.project = data.project;
  state.viewVersion = state.project.versions[0].number;
  await refreshQuestion();
  render();
  document.querySelector(".report-head")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function collectInterpretation() {
  const version = state.project.versions[0];
  return {
    facts: version.interpretation.facts.map((item, index) => ({ ...item, text: document.querySelector(`[data-fact="${index}"]`).value.trim() })),
    assumptions: version.interpretation.assumptions.map((item, index) => ({ ...item, text: document.querySelector(`[data-assumption="${index}"]`).value.trim() })),
    gaps: $("#gaps").value.split("\n").map((item) => item.trim()).filter(Boolean),
  };
}

async function saveInterpretation(interpretation) {
  const version = state.project.versions[0];
  const data = await api(`/api/projects/${state.project.id}/interpretation`, { method: "PUT", body: JSON.stringify({ version_id: version.id, interpretation }) });
  state.project = data.project;
  render();
}

function newRequestId() {
  return typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function questionDraftKey(id) { return `autopsy.questionDraft.${id}`; }

function persistQuestionDraft() {
  if (!state.project || !state.draft) return;
  try { sessionStorage.setItem(questionDraftKey(state.project.id), JSON.stringify(state.draft)); } catch { /* Storage may be unavailable. */ }
}

function clearQuestionDraft() {
  if (state.project) {
    try { sessionStorage.removeItem(questionDraftKey(state.project.id)); } catch { /* Storage may be unavailable. */ }
  }
  state.draft = null;
}

function restoreQuestionDraft() {
  state.draft = null;
  if (!state.project || !state.question) return;
  try {
    const saved = sessionStorage.getItem(questionDraftKey(state.project.id));
    if (!saved) return;
    const draft = JSON.parse(saved);
    if (draft.baseVersionId === state.project.current_version_id && draft.questionId === state.question.id && typeof draft.plan === "string") {
      state.draft = draft;
    } else {
      sessionStorage.removeItem(questionDraftKey(state.project.id));
    }
  } catch { /* Ignore malformed or unavailable session storage. */ }
}

function makeQuestionDraft(status, answer) {
  const question = state.question;
  const version = state.project.versions[0];
  const action = `검증 계획(아직 실행 전): ${question.action} 완료 기준: ${question.done_when}.`;
  const addition = status === "answered"
    ? `추가 정보(사용자 제공·미검증): ${answer}\n${action}`
    : `미확인 조건: ${question.prompt}\n${action}`;
  state.draft = {
    baseVersionId: version.id, questionId: question.id, mechanismKey: question.mechanism_key,
    status, answer, plan: `${version.plan.trimEnd()}\n\n${addition}`, requestId: newRequestId(),
  };
  persistQuestionDraft();
  render();
  $("#revision-plan")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function submitRevisionForm(path, payload) {
  try {
    sessionStorage.setItem("autopsy.pendingRevision", JSON.stringify({ projectId: state.project.id, baseVersionId: payload.base_version_id, plan: payload.plan }));
  } catch { /* Private browsing may disable storage. */ }
  const form = document.createElement("form");
  form.method = "POST";
  form.action = path;
  form.hidden = true;
  for (const [name, value] of Object.entries(payload)) {
    if (value === null || value === undefined) continue;
    const input = document.createElement("input");
    input.name = name;
    input.value = typeof value === "object" ? JSON.stringify(value) : value;
    form.appendChild(input);
  }
  document.body.appendChild(form);
  form.submit();
}

function restoreRevisionDraft() {
  try {
    const saved = sessionStorage.getItem("autopsy.pendingRevision");
    if (!saved || !state.project) return;
    const draft = JSON.parse(saved);
    if (draft.projectId !== state.project.id) return;
    if (state.project.versions[0].plan === draft.plan) {
      sessionStorage.removeItem("autopsy.pendingRevision");
      return;
    }
    if (draft.baseVersionId && draft.baseVersionId !== state.project.current_version_id) return;
    const field = $("#revision-plan");
    if (field) {
      field.value = draft.plan;
      banner("이전 저장 시도의 수정안을 복원했습니다. 저장 상태를 확인한 뒤 다시 시도해 주세요.");
    }
  } catch { /* Ignore malformed or unavailable session storage. */ }
}

async function saveRevision(plan) {
  const id = state.project.id;
  const baseVersionId = state.project.current_version_id;
  const path = `/api/projects/${id}/versions`;
  const draft = state.draft?.baseVersionId === baseVersionId ? state.draft : null;
  const payload = {
    plan, base_version_id: baseVersionId, request_id: draft?.requestId || newRequestId(),
    clarification: draft ? { question_id: draft.questionId, status: draft.status, answer: draft.answer } : null,
  };
  const body = JSON.stringify(payload);
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const headers = attempt === 1 ? { "Content-Type": "text/plain;charset=UTF-8" } : {};
      return await api(path, { method: "POST", body, headers });
    } catch (error) {
      // A proxy can lose the response after the server has saved the version.
      // Read back first so a retry cannot create a duplicate version.
      let latest;
      try {
        latest = await api(`/api/projects/${id}`);
      } catch {
        throw new Error("저장 여부를 확인할 수 없습니다. 작성 중인 계획을 유지한 채 서버 연결을 확인하고 다시 시도해 주세요.");
      }
      if (latest.current_version_id !== baseVersionId) {
        if (latest.versions[0].plan === plan) return latest;
        throw new Error("계획이 다른 곳에서 변경되었습니다. 페이지를 새로고침해 주세요.");
      }
      if (!(error instanceof EmptyResponseError || error instanceof TypeError)) throw error;
      if (attempt === 1) {
        try { await fetch("/api/health?client=revision-form-fallback", { cache: "no-store" }); } catch { /* Best-effort local diagnostic. */ }
        submitRevisionForm(path, payload);
        return null;
      }
    }
  }
}

document.addEventListener("submit", (event) => {
  if (event.target.id !== "create-form") return;
  event.preventDefault();
  const title = $("#project-title").value.trim();
  const plan = $("#project-plan").value.trim();
  run("프로젝트를 저장하고 계획을 해석하고 있습니다…", async () => {
    const project = await api("/api/projects", { method: "POST", body: JSON.stringify({ title, plan }) });
    state.project = project;
    state.projects = (await api("/api/projects")).projects;
    state.viewVersion = 1;
    localStorage.setItem("autopsy.lastProject", project.id);
    await performInterpret();
  });
});

document.addEventListener("change", (event) => {
  if (event.target.id === "version-select") {
    state.viewVersion = Number(event.target.value);
    render();
  }
});

document.addEventListener("input", (event) => {
  if (event.target.id !== "revision-plan" || !state.project) return;
  if (state.draft) {
    state.draft.plan = event.target.value;
    state.draft.requestId = newRequestId();
    persistQuestionDraft();
  }
  try {
    sessionStorage.setItem("autopsy.pendingRevision", JSON.stringify({
      projectId: state.project.id, baseVersionId: state.project.current_version_id, plan: event.target.value,
    }));
  } catch { /* Storage may be unavailable. */ }
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-action], #new-project");
  if (!button) return;
  const action = button.id === "new-project" ? "new" : button.dataset.action;
  if (action === "new") { state.project = null; state.question = null; state.draft = null; render(); return; }
  if (action === "open") { run("프로젝트를 여는 중입니다…", () => refreshProject(button.dataset.id)); return; }
  if (action === "example") {
    $("#project-title").value = "AI 사내 문서 검색";
    $("#project-plan").value = "사내 문서 10만 건을 검색하는 AI 서비스를 6주 안에 전 직원에게 배포한다. 문서에는 개인정보가 포함될 수 있다. 정확도 목표는 90%다. 백엔드 개발자 1명과 AI 개발자 1명이 개발한다.";
    return;
  }
  if (action === "interpret") { run("계획에서 사실과 가정을 찾는 중입니다…", performInterpret); return; }
  if (action === "save-interpretation") {
    const interpretation = collectInterpretation();
    run("수정한 해석을 저장 중입니다…", () => saveInterpretation(interpretation));
    return;
  }
  if (action === "analyze") {
    const interpretation = collectInterpretation();
    run("실패 사례를 조사하고 보고서를 작성 중입니다…", async () => {
      await saveInterpretation(interpretation);
      await performAnalyze();
    });
    return;
  }
  if (action === "answer-question") {
    const answer = $("#question-answer").value.trim();
    if (!answer) { banner("답변을 적거나 ‘아직 모름’을 선택해 주세요.", true); return; }
    banner("");
    makeQuestionDraft("answered", answer);
    return;
  }
  if (action === "unknown-question") { banner(""); makeQuestionDraft("unknown", ""); return; }
  if (action === "skip-question") {
    clearQuestionDraft();
    state.questionSkipped = true;
    try { sessionStorage.setItem(`autopsy.skippedQuestion.${state.project.id}`, state.question.id); } catch { /* Storage may be unavailable. */ }
    render();
    return;
  }
  if (action === "show-question") {
    state.questionSkipped = false;
    try { sessionStorage.removeItem(`autopsy.skippedQuestion.${state.project.id}`); } catch { /* Storage may be unavailable. */ }
    render();
    return;
  }
  if (action === "discard-draft") { clearQuestionDraft(); render(); return; }
  if (action === "revise") {
    const plan = $("#revision-plan").value.trim();
    const answerField = $("#question-answer");
    if (state.draft && answerField && answerField.value.trim() !== state.draft.answer) {
      banner("답변을 수정했어요. ‘답변으로 수정안 만들기’를 다시 눌러 주세요.", true);
      return;
    }
    run("수정된 계획을 저장하고 분석 중입니다…", async () => {
      const project = await saveRevision(plan);
      if (!project) return;
      state.project = project;
      clearQuestionDraft();
      try { sessionStorage.removeItem("autopsy.pendingRevision"); } catch { /* Storage may be unavailable. */ }
      state.viewVersion = project.versions[0].number;
      render();
      await performInterpret();
      await performAnalyze();
    });
    return;
  }
  if (action === "feedback") {
    const excluded = button.dataset.excluded === "1";
    const reason = excluded ? window.prompt("이 위험이 현재 프로젝트와 관련 없는 이유를 적어주세요.") : "";
    if (excluded && !reason?.trim()) return;
    run("판단을 저장 중입니다…", async () => {
      state.project = await api(`/api/projects/${state.project.id}/feedback`, { method: "POST", body: JSON.stringify({ mechanism_key: button.dataset.key, excluded, reason }) });
      await performAnalyze();
    });
  }
});

async function start() {
  try {
    state.health = await api("/api/health");
    state.projects = (await api("/api/projects")).projects;
    try {
      state.cases = (await api("/api/cases")).cases;
    } catch (error) {
      console.warn("사례 목록을 미리 읽지 못했습니다:", error);
      state.cases = [];
    }
    const last = localStorage.getItem("autopsy.lastProject");
    const selected = state.projects.find((item) => item.id === last) || state.projects[0];
    if (selected) state.project = await api(`/api/projects/${selected.id}`);
    if (state.project) state.viewVersion = state.project.versions[0].number;
    await refreshQuestion();
    restoreQuestionDraft();
    render();
    restoreRevisionDraft();
  } catch (error) {
    banner(error.message, true);
    render();
  }
}

start();
