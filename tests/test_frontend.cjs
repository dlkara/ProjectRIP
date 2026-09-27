const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const elements = new Map();
const listeners = {};
let project = null;
function element(selector) {
  if (!elements.has(selector)) {
    elements.set(selector, {
      textContent: "",
      innerHTML: "",
      value: "",
      hidden: selector === "#error" || selector === "#status",
      addEventListener() {},
      scrollIntoView() {},
    });
  }
  return elements.get(selector);
}

let healthCalls = 0;
let revisionCalls = 0;
let fallbackDiagnostics = 0;
const formSubmissions = [];
const session = new Map();
const context = {
  console,
  setTimeout,
  localStorage: { getItem: () => null, setItem() {} },
  sessionStorage: { getItem: (key) => session.get(key) || null, setItem: (key, value) => session.set(key, value), removeItem: (key) => session.delete(key) },
  document: {
    querySelector: element,
    querySelectorAll: () => [],
    createElement(tag) {
      return { tag, children: [], appendChild(child) { this.children.push(child); }, submit() { formSubmissions.push(this); } };
    },
    body: { appendChild() {} },
    addEventListener(name, callback) { listeners[name] = callback; },
  },
  fetch: async (url, options = {}) => {
    if (url === "/api/health?client=revision-form-fallback") {
      fallbackDiagnostics += 1;
      return { ok: true, status: 200, text: async () => '{"ok":true}' };
    }
    if (url === "/api/health") {
      healthCalls += 1;
      return { ok: true, status: 200, text: async () => healthCalls === 1 ? "" : JSON.stringify({ ok: true, mode: "demo", model: null, cases: 12 }) };
    }
    if (url === "/api/projects" && options.method === "POST") {
      const payload = JSON.parse(options.body);
      project = {
        id: "test-project", title: payload.title, feedback: [], current_version_id: "v1",
        versions: [{ id: "v1", number: 1, plan: payload.plan, interpretation: null, report: null }],
      };
      return { ok: true, status: 201, text: async () => JSON.stringify(project) };
    }
    if (url === "/api/projects") return { ok: true, status: 200, text: async () => JSON.stringify({ projects: project ? [{ id: project.id, title: project.title, current_version: 1 }] : [] }) };
    if (url === "/api/cases") return { ok: true, status: 200, text: async () => '{"cases":[]}' };
    if (url === "/api/projects/test-project/question") return { ok: true, status: 200, text: async () => '{"question":null}' };
    if (url === "/api/projects/test-project/interpret") {
      project.versions[0].interpretation = { facts: [{ text: project.versions[0].plan, quote: project.versions[0].plan }], assumptions: [], gaps: [] };
      return { ok: true, status: 200, text: async () => JSON.stringify({ interpretation: project.versions[0].interpretation, project }) };
    }
    if (url === "/api/projects/test-project/versions") {
      revisionCalls += 1;
      if (revisionCalls === 1 || revisionCalls >= 4) return { ok: true, status: 201, text: async () => "" };
      const payload = JSON.parse(options.body);
      assert.equal(payload.base_version_id, project.current_version_id);
      const number = project.versions[0].number + 1;
      project.versions.unshift({ id: `v${number}`, number, plan: payload.plan, interpretation: null, report: null });
      project.current_version_id = `v${number}`;
      if (revisionCalls === 3) return { ok: true, status: 201, text: async () => "" };
      return { ok: true, status: 201, text: async () => JSON.stringify(project) };
    }
    if (url === "/api/projects/test-project") return { ok: true, status: 200, text: async () => JSON.stringify(project) };
    if (url === "/api/projects/test-project/analyze") {
      const report = { risks: [], comparison: null, mode: "demo", headline: "테스트", summary: "테스트" };
      project.versions[0].report = report;
      return { ok: true, status: 200, text: async () => JSON.stringify({ report, project }) };
    }
    throw new Error(`Unexpected URL: ${url}`);
  },
};

const source = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
vm.runInNewContext(source, context);

setTimeout(() => {
  assert.equal(healthCalls, 2, "empty GET response should be retried once");
  assert.match(element("#app").innerHTML, /프로젝트가/);
  assert.equal(element("#error").hidden, true);
  const exampleButton = { id: "", dataset: { action: "example" }, closest() { return this; } };
  listeners.click({ target: exampleButton });
  assert.match(element("#project-plan").value, /전 직원/);
  listeners.submit({ target: { id: "create-form" }, preventDefault() {} });
  setTimeout(() => {
    assert.match(element("#app").innerHTML, /AI 사내 문서 검색/);
    assert.match(element("#app").innerHTML, /확인된 사실/);
    assert.equal(element("#error").hidden, true);
    element("#revision-plan").value = "한 부서에서 먼저 시험한다.";
    const reviseButton = { id: "", dataset: { action: "revise" }, closest() { return this; } };
    listeners.click({ target: reviseButton });
    setTimeout(() => {
      assert.equal(revisionCalls, 2, "empty revision response should retry after checking current state");
      assert.equal(project.versions.length, 2);
      assert.equal(project.versions[0].plan, "한 부서에서 먼저 시험한다.");
      assert.equal(element("#error").hidden, true);
      element("#revision-plan").value = "평가 지표를 추가한다.";
      listeners.click({ target: reviseButton });
      setTimeout(() => {
        assert.equal(revisionCalls, 3, "saved version must be recovered without another POST");
        assert.equal(project.versions.length, 3);
        assert.equal(project.versions[0].plan, "평가 지표를 추가한다.");
        assert.equal(element("#error").hidden, true);
        element("#revision-plan").value = "부서별 접근 권한을 검증한다.";
        listeners.click({ target: reviseButton });
        setTimeout(() => {
          assert.equal(revisionCalls, 5);
          assert.equal(fallbackDiagnostics, 1);
          assert.equal(formSubmissions.length, 1, "two empty fetch responses should use form submission");
          assert.equal(formSubmissions[0].method, "POST");
          assert.equal(formSubmissions[0].children.find((field) => field.name === "plan").value, "부서별 접근 권한을 검증한다.");
          assert.equal(JSON.parse(session.get("autopsy.pendingRevision")).plan, "부서별 접근 권한을 검증한다.");
          console.log("frontend example, revision recovery, and form fallback: ok");
        }, 25);
      }, 25);
    }, 25);
  }, 25);
}, 25);
