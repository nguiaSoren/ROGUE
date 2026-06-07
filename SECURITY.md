# Security Policy

ROGUE is a security product (a continuous open-web LLM red-team). We take the
security of the project and of our users seriously, and we welcome responsible
disclosure of vulnerabilities.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

Security fixes are applied to the latest released minor version. Older versions
are not patched; please upgrade.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report privately by email to **security@<your-domain>**.

<!-- TODO: replace security@<your-domain> with the real security contact address
     before publishing this policy. -->

Where possible, please include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce (proof-of-concept, affected endpoint/component, request
  samples).
- The version or commit you tested against.
- Any suggested remediation.

If you would like to encrypt your report or need an alternative channel, mention
that in an initial (non-sensitive) email and we will coordinate.

## Response Expectations

- **Acknowledgement:** within 3 business days of your report.
- **Triage and initial assessment:** within 7 business days.
- **Status updates:** at least every 14 days until resolution.
- **Resolution / disclosure:** we aim to ship a fix and coordinate public
  disclosure within 90 days, sooner for high-severity issues.

We will credit reporters who wish to be acknowledged once a fix is released,
unless you prefer to remain anonymous.

## Scope

In scope:

- The ROGUE backend (FastAPI app, `/v1` API, MCP server) and its data handling.
- The Next.js dashboard frontend.
- The hosted platform layer (scan orchestration, tenancy, reports).

Out of scope:

- Findings that require physical access to a user's device or account.
- Social engineering, phishing, or attacks against our staff.
- Denial-of-service via volumetric traffic.
- Vulnerabilities in third-party dependencies that are already publicly known
  and have an upstream fix pending (report those upstream; tell us if we are
  shipping an affected version).
- Reports from automated scanners without a demonstrated, exploitable impact.

Thank you for helping keep ROGUE and its users safe.
