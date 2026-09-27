const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const listeners = {};
const elements = new Map();
const session = new Map();
let savedPayload = null;
let project = {
  id: "test-project", title: "사내 검색", feedback: [], current_version_id: "v1",
  versions: [{
    id: "v1", number: 1, plan: "정확도 목표는 90%다.", clarification: null,
    interpretation: { facts: [], assumptions: [], gaps: ["평가 방법이 언급되지 않았습니다."] },
    report: {
      mode: "demo", headline: "가상 보고서", summary: "검증 필요", comparison: null,
      risks: [{ mechanism_key: "undefined_metric", title: "평가 기준 부재", impact: "medium",
        condition_quote: "정확도 목표는 90%다.", assumption: "측정할 수 있다", mechanism: "평가 기준 부재",
        outcome: "판단 불가", early_signal: "평가셋 없음", action: "실제 질문으로 평가한다",
        action_when: "개발 전", done_when: "질문 100개를 고정한다", evidence: {} }],
    },
  }],
};
const question = {
  id: "v1:undefined_metric", base_version_id: "v1", mechanism_key: "undefined_metric", risk_title: "평가 기준 부재",
  condition_quote: "정확도 목표는 90%다.", prompt: "목표 품질을 어떤 실제 질문과 채점 기준으로 확인할 건가요?",
  answer_hint: "평가 질문, 정답 근거, 통과 기준", why: "평가 방법이 필요합니다.",
  action: "실제 질문으로 평가한다", action_when: "개발 전", done_when: "질문 100개를 고정한다",
};

function element(selector) {
  if (!elements.has(selector)) elements.set(selector, {
    innerHTML: "", textContent: "", value: "", hidden: false, scrollIntoView() {},
  });
  return elements.get(selector);
}

const context = {
  console, setTimeout,
  localStorage: { getItem: () => "test-project", setItem() {} },
  sessionStorage: { getItem: (key) => session.get(key) || null, setItem: (key, value) => session.set(key, value), removeItem: (key) => session.delete(key) },
  document: {
    querySelector: element, querySelectorAll: () => [],
    addEventListener(name, callback) { listeners[name] = callback; },
  },
  fetch: async (url, options = {}) => {
    const reply = (data, status = 200) => ({ ok: true, status, text: async () => JSON.stringify(data) });
    if (url === "/api/health") return reply({ ok: true, mode: "demo", model: null });
    if (url === "/api/projects") return reply({ projects: [{ id: project.id, title: project.title, current_version: project.versions[0].number }] });
    if (url === "/api/cases") return reply({ cases: [] });
    if (url === "/api/projects/test-project" && !options.method) return reply(project);
    if (url === "/api/projects/test-project/question") return reply({ question: project.current_version_id === "v1" ? question : null });
    if (url === "/api/projects/test-project/versions") {
      savedPayload = JSON.parse(options.body);
      project = {
        ...project, current_version_id: "v2",
        versions: [{ id: "v2", number: 2, plan: savedPayload.plan, clarification: { ...savedPayload.clarification, source: "user_provided_unverified" }, interpretation: null, report: null }, ...project.versions],
      };
      return reply(project, 201);
    }
    if (url === "/api/projects/test-project/interpret") {
      project.versions[0].interpretation = { facts: [], assumptions: [], gaps: [] };
      return reply({ project, interpretation: project.versions[0].interpretation });
    }
    if (url === "/api/projects/test-project/analyze") {
      project.versions[0].report = { mode: "demo", headline: "수정 보고서", summary: "비교", risks: [], comparison: { before_version: 1, after_version: 2, changes: [] } };
      return reply({ project, report: project.versions[0].report });
    }
    throw new Error(`Unexpected URL: ${url}`);
  },
};

vm.runInNewContext(fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8"), context);
const click = (action) => listeners.click({ target: { id: "", dataset: { action }, closest() { return this; } } });
const tick = () => new Promise((resolve) => setTimeout(resolve, 25));

(async () => {
  await tick();
  assert.match(element("#app").innerHTML, /보고서가 묻습니다/);
  assert.match(element("#app").innerHTML, /목표 품질을 어떤 실제 질문/);

  click("skip-question");
  assert.match(element("#app").innerHTML, /이번 질문을 건너뛰었습니다/);
  assert.equal(project.versions.length, 1);
  click("show-question");

  click("unknown-question");
  let draft = JSON.parse(session.get("autopsy.questionDraft.test-project"));
  assert.equal(draft.status, "unknown");
  assert.match(draft.plan, /검증 계획\(아직 실행 전\)/);
  assert.equal(project.versions.length, 1, "unknown answer alone must not save a version");

  element("#question-answer").value = "실제 질문 100개와 정답 근거를 모은다.";
  click("answer-question");
  draft = JSON.parse(session.get("autopsy.questionDraft.test-project"));
  assert.equal(draft.status, "answered");
  assert.match(draft.plan, /사용자 제공·미검증/);
  await context.start();
  assert.match(element("#app").innerHTML, /실제 질문 100개와 정답 근거를 모은다/);
  element("#revision-plan").value = draft.plan;
  click("revise");
  await tick();

  assert.equal(savedPayload.clarification.question_id, question.id);
  assert.equal(savedPayload.clarification.answer, "실제 질문 100개와 정답 근거를 모은다.");
  assert.ok(savedPayload.request_id);
  assert.equal(project.versions.length, 2);
  assert.match(element("#app").innerHTML, /계획상 무엇이 달라졌나/);
  assert.equal(session.has("autopsy.questionDraft.test-project"), false);
  console.log("question, unknown, skip, draft, and revision: ok");
})().catch((error) => { console.error(error); process.exitCode = 1; });
