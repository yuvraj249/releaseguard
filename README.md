# 🚦 ReleaseGuard
> **CI/CD Test Triage & Release Decision Intelligence Engine**

ReleaseGuard resolves the classic pre-deployment dilemma for Product Managers and Release Engineers: **Is a CI/CD test failure an actual code regression (block release) or an asynchronous DOM timing flake (quarantine and ship)?**

---

## ⚡ Features
- **Semantic AST Log Classifier**: Distinguishes between DOM timeout hydration issues, 500 server crashes, and transient network timeouts.
- **Git Diff Correlation**: Computes semantic keyword intersection between the PR's modified files and the failing test suite domain.
- **Dual Form Factor**:
  - **Headless CLI Runner (`cli.py`)**: UNIX-native exit codes (`0` for quarantine/pass, `1` for hard block) for CI/CD pipelines.
  - **Executive Web Dashboard (`server.py`)**: Zero-dependency dark-mode UI for PMs to audit risk scores and trade-off rationales.
- **Reusable GitHub Action (`action.yml`)**: Ready for zero-copy adoption across microservices (`uses: yuvraj249/releaseguard@main`).

---

## 🚀 Quickstart

### 1. Run the Headless CLI
```bash
# Pipe test failure logs directly
cat cypress_failure.log | python3 cli.py --auto-git
```

### 2. Run the Executive Web Dashboard
```bash
python3 server.py
# Opens on http://localhost:8080
```

### 3. Use in Any GitHub Actions Workflow
```yaml
- name: Run E2E Tests
  id: tests
  run: npx cypress run > cypress.log 2>&1
  continue-on-error: true

- name: ReleaseGuard Intelligent Triage
  if: steps.tests.outcome == 'failure'
  uses: yuvraj249/releaseguard@main
  with:
    log-file: cypress.log
```
