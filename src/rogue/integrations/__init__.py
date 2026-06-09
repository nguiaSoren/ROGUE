"""Net-new top-level integration surfaces (Surface-1 delivery layers).

Distinct from `rogue.platform.integrations` (the alert dispatcher). This package holds
the customer-facing self-registration surfaces — currently `rogue.integrations.slack`,
where a consented Slack agent registers itself as a ROGUE `DeploymentConfig`.

No imports with side effects: importing this package opens no DB connection and builds
no engine.
"""
