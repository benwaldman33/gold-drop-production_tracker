# Launch Readiness Audit TODO

These items are intentionally deferred until the feature set is closer to frozen. The current `Settings -> Launch Readiness` page is a manual blocker register with audit logging for updates. The later goal is to turn it into a hybrid readiness audit: manual checklist plus automated evidence checks.

## Deferred Automated Checks

- Open genealogy issues by severity and age.
- Missing Journey revenue assumptions for active derivative lot types.
- Released material lots with missing actual revenue.
- Material lots or runs with missing cost basis.
- Unresolved supervisor alerts, stale warnings, and reminder escalation status.
- Slack outbound configuration health for completions, warnings, and reminders.
- Standalone workflow enablement for purchasing, receiving, and extraction.
- Backup age and last successful backup marker.
- Restore rehearsal completion marker.
- Deployment rehearsal completion marker.
- Users without an expected role or with unexpected active access.
- API clients and remote-site registrations that are active but unused or stale.
- Import/export readiness checks once the final permission coverage audit is complete.

## Deferred AI / MCP Access Hardening

- Decide whether AI/MCP access remains local-only via stdio or becomes remotely reachable.
- If remote MCP is allowed, define authentication, least-privilege scopes, rate limits, logging, and network exposure rules before deployment.
- Align MCP access with the application permission model; the current MCP layer behaves like trusted internal read access and does not evaluate per-user access-control rules.
- Add read-only MCP tools for newer manager surfaces where useful:
  - finance/accounting summaries
  - material genealogy details
  - financial completeness flags
  - audit-log lookup
- Document production MCP startup, client connection, safe verification, and shutdown/restart procedures.
- Keep AI write tools disabled until after launch/security hardening.
- If write tools are ever added, ship them one at a time with explicit approval policy, least-privilege scope, audit logging, and rollback/review expectations.

## Later Implementation Shape

- Keep the existing manual blocker register.
- Add an automated readiness panel beside it.
- Store each automated check as pass, warning, fail, or not configured.
- Let Super Admins convert any failed check into a blocker-register item.
- Record automated check runs in the audit log.
- Do not block deployment automatically until the launch policy is explicitly defined.
