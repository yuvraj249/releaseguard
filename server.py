#!/usr/bin/env python3
import sys
import os
import json
import re
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')

SCENARIOS = {
    'flake_dom_timeout': {
        'id': 'flake_dom_timeout',
        'name': 'Async DOM Timeout (Cypress Flake)',
        'framework': 'Cypress E2E',
        'test_name': 'cypress/e2e/checkout_modal.cy.js:42',
        'test_log': "CypressError: Timed out retrying after 5000ms: Expected to find element: '[data-cy=confirm-order-btn]', but never found it.\n    at Context.eval (webpack:///./cypress/e2e/checkout_modal.cy.js:42:10)\n    at Runnable.run (http://localhost:3000/__cypress/runner/cypress_runner.js:154:21)\nNote: Element was detached from DOM during CSS transition hydration.",
        'pr_files': [
            'src/components/Footer.tsx',
            'src/styles/theme-dark.css',
            'docs/README.md'
        ],
        'pr_title': 'feat(ui): update footer branding and dark theme contrast',
        'historical_flake_rate': 38.5,
        'previous_runs_count': 120
    },
    'real_regression_blocker': {
        'id': 'real_regression_blocker',
        'name': 'Sev-1 API Logic Crash (Playwright Blocker)',
        'framework': 'Playwright',
        'test_name': 'tests/e2e/orders/order_total_spec.ts:89',
        'test_log': "Error: expect(received).toBe(expected) // Object.is equality\nExpected: 200\nReceived: 500\nResponse body: {\"error\": \"Internal Server Error\", \"exception\": \"NullPointerException: cannot read field tax_rate on null tenant configuration in OrderPricingService.calculateTotal\"}\n    at OrderPage.submitOrder (/tests/pages/order.ts:54:12)\n    at /tests/e2e/orders/order_total_spec.ts:89:9",
        'pr_files': [
            'src/services/order_pricing_service.go',
            'src/controllers/order_controller.go',
            'migrations/20261022_add_tax_rules.sql'
        ],
        'pr_title': 'feat(pricing): add localized tax calculations for enterprise tenants',
        'historical_flake_rate': 2.1,
        'previous_runs_count': 340
    },
    'transient_network_timeout': {
        'id': 'transient_network_timeout',
        'name': 'Third-Party Mock Gateway Timeout (Transient Glitch)',
        'framework': 'Playwright',
        'test_name': 'tests/e2e/payments/stripe_webhook_spec.ts:114',
        'test_log': "RequestFailedException: HTTP 504 Gateway Timeout while calling mock-stripe.staging.internal/v1/payment_intents\nConnection closed unexpectedly after 15000ms by peer.\n    at StripeMockClient.charge (/tests/mocks/stripe.ts:33:7)\n    at /tests/e2e/payments/stripe_webhook_spec.ts:114:5",
        'pr_files': [
            'src/config/webhook_retry_policy.ts',
            'package.json'
        ],
        'pr_title': 'chore: bump stripe client timeout tolerance',
        'historical_flake_rate': 18.0,
        'previous_runs_count': 85
    }
}

def analyze_test_failure(test_log, pr_files, pr_title, flake_rate):
    log_lower = test_log.lower()
    pr_files_str = ' '.join(pr_files).lower()
    pr_title_lower = pr_title.lower() if pr_title else ''

    is_dom_timeout = bool(re.search(r'timed out retrying|never found it|detached from dom|element not visible|selector', log_lower))
    is_server_500 = bool(re.search(r'\b500\b|nullpointer|internal server error|\bpanic\b', log_lower))
    is_network_timeout = bool(re.search(r'\b504\b|gateway timeout|connection closed|econnrefused|socket hang up', log_lower))
    is_assertion_fail = bool(re.search(r'expect\(received\)\.tobe|assertionerror', log_lower))

    keywords = ['order', 'pricing', 'tax', 'payment', 'stripe', 'footer', 'theme', 'modal', 'auth', 'login']
    log_matched_keywords = [k for k in keywords if k in log_lower]
    diff_matched_keywords = [k for k in keywords if k in pr_files_str or k in pr_title_lower]

    common_keywords = set(log_matched_keywords).intersection(set(diff_matched_keywords))
    has_direct_code_correlation = len(common_keywords) > 0

    risk_score = 50
    confidence = 85
    verdict = 'RETRY_ONCE'
    verdict_badge = 'RETRY WITH ISOLATION'
    verdict_color = 'yellow'
    category = 'Transient / Environmental'
    root_cause = ''
    trade_off = ''
    action = ''

    # Case 1: Hard Blocker (500 or logic crash)
    if is_server_500 or (is_assertion_fail and has_direct_code_correlation):
        if has_direct_code_correlation:
            risk_score = 94
            confidence = 96
            verdict = 'HARD_BLOCK'
            verdict_badge = 'HARD BLOCK RELEASE'
            verdict_color = 'red'
            category = 'P0 Code Regression'
            root_cause = f"Definite code regression detected: The failure manifests as a server/assertion crash directly correlated with modified files ({', '.join(list(common_keywords))})."
            trade_off = "Blocking this release prevents a critical Sev-1 incident in production. The certainty of customer disruption outweighs the cost of a delayed deployment window."
            action = "Immediately halt deployment. Reassign PR to author with stack trace; require local repro before re-testing."
        else:
            risk_score = 72
            confidence = 80
            verdict = 'HARD_BLOCK'
            verdict_badge = 'HARD BLOCK RELEASE'
            verdict_color = 'red'
            category = 'Potential Unrelated Regression'
            root_cause = "Server-side 500 error observed, although PR files do not show immediate direct correlation. Possible shared dependency regression."
            trade_off = "Even without direct diff correlation, 500 errors in E2E flows carry unacceptable risk for production rollout."
            action = "Block release until on-call engineer verifies if staging environment or shared database was broken independently."
    # Case 2: Flaky Async DOM Timeout
    elif is_dom_timeout:
        if not has_direct_code_correlation and flake_rate > 15.0:
            risk_score = 14
            confidence = 92
            verdict = 'SHIP_WITH_QUARANTINE'
            verdict_badge = 'PROCEED WITH QUARANTINE'
            verdict_color = 'green'
            category = 'Asynchronous DOM Timing Flake'
            root_cause = f"False-alarm UI hydration/timeout flakiness. PR files ({', '.join(pr_files[:2])}) have 0% correlation with failing test domain, and this spec has a high historical flake rate ({flake_rate}%)."
            trade_off = "Release velocity takes priority. Delaying a validated PR for an established false-positive wastes developer time with zero reliability benefit."
            action = "Quarantine test tag (@quarantined), bypass CI gate, proceed with production rollout, and file automated QA tech-debt ticket."
        elif has_direct_code_correlation:
            risk_score = 62
            confidence = 78
            verdict = 'RETRY_ONCE'
            verdict_badge = 'RETRY WITH SELECTOR CHECK'
            verdict_color = 'yellow'
            category = 'Potential UI Selector Mismatch'
            root_cause = "DOM timeout occurred on a component touched by this PR. Likely a selector rename or animation delay introduced in this change."
            trade_off = "Could be a broken user experience or merely a brittle test selector. A single targeted re-run is necessary before blocking."
            action = "Re-run this single test in isolated worker with trace viewer enabled. Check if data-cy attribute was accidentally modified."
        else:
            risk_score = 28
            confidence = 85
            verdict = 'SHIP_WITH_QUARANTINE'
            verdict_badge = 'PROCEED WITH QUARANTINE'
            verdict_color = 'green'
            category = 'Isolated DOM Flake'
            root_cause = "DOM timeout on unrelated component with moderate flake history."
            trade_off = "Low probability of production defect. Unblocking release protects sprint velocity."
            action = "Quarantine test in CI runner and proceed with deployment."
    # Case 3: Network / Mock Timeout
    elif is_network_timeout:
        risk_score = 42
        confidence = 88
        verdict = 'RETRY_ONCE'
        verdict_badge = 'RETRY ONCE (TRANSIENT)'
        verdict_color = 'yellow'
        category = 'Staging Environment / Mock Glitch'
        root_cause = "Transient network gateway timeout (504) while reaching internal mock services. External dependency latency."
        trade_off = "Neither a code defect nor a brittle test selector. Rerunning immediately resolves 90% of these transient network drops."
        action = "Trigger single-test retry. If failure repeats 2x consecutively, escalate staging infrastructure connectivity to DevOps."

    jira_priority = 'P0 - Blocker' if verdict == 'HARD_BLOCK' else ('P2 - Medium' if verdict == 'RETRY_ONCE' else 'P3 - Tech Debt')
    jira_ticket = {
        'summary': f"[ReleaseGuard] {category} in CI test: {pr_title[:40]}...",
        'priority': jira_priority,
        'labels': ['ci-gate', 'flaky-test' if 'Flake' in category else 'regression', 'releaseguard'],
        'description': (
            f"*Verdict*: {verdict_badge}\n"
            f"*Risk Score*: {risk_score}/100 | *Confidence*: {confidence}%\n\n"
            f"*Root Cause*: {root_cause}\n\n"
            f"*Recommended Action*: {action}\n\n"
            f"*PR Files Touched*: {', '.join(pr_files)}\n"
            f"*Flake History*: {flake_rate}%"
        )
    }

    return {
        'verdict': verdict,
        'verdict_badge': verdict_badge,
        'verdict_color': verdict_color,
        'risk_score': risk_score,
        'confidence': confidence,
        'category': category,
        'has_correlation': has_direct_code_correlation,
        'correlated_domains': list(common_keywords),
        'root_cause': root_cause,
        'trade_off': trade_off,
        'action': action,
        'jira_ticket': jira_ticket
    }

class ReleaseGuardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/scenarios':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(SCENARIOS).encode('utf-8'))
        elif parsed.path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'UP', 'service': 'ReleaseGuard'}).encode('utf-8'))
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/evaluate':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
                test_log = data.get('test_log', '')
                pr_files = data.get('pr_files', [])
                pr_title = data.get('pr_title', '')
                flake_rate = float(data.get('historical_flake_rate', 10.0))

                result = analyze_test_failure(test_log, pr_files, pr_title, flake_rate)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def run_headless_tests():
    print('Running ReleaseGuard self-test on 3 baseline scenarios...')
    for key, sc in SCENARIOS.items():
        res = analyze_test_failure(
            sc['test_log'], sc['pr_files'], sc['pr_title'], sc['historical_flake_rate']
        )
        print(f"  [OK] Scenario '{sc['name']}': Verdict = {res['verdict_badge']}, Risk = {res['risk_score']}/100")
        if key == 'flake_dom_timeout':
            assert res['verdict'] == 'SHIP_WITH_QUARANTINE'
        elif key == 'real_regression_blocker':
            assert res['verdict'] == 'HARD_BLOCK'
        elif key == 'transient_network_timeout':
            assert res['verdict'] == 'RETRY_ONCE'
    print('All internal tests PASSED successfully!')

if __name__ == '__main__':
    if '--test' in sys.argv:
        run_headless_tests()
        sys.exit(0)

    print(f'Starting ReleaseGuard on http://localhost:{PORT}')
    server = HTTPServer(('0.0.0.0', PORT), ReleaseGuardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping ReleaseGuard server.')
        server.server_close()
