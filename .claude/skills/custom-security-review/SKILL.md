---
name: custom-security-review
description: >
  Run a comprehensive security audit of the project using all 8 specialized security sub-agents.
  Scans agent environment, secrets, code vulnerabilities, supply chain, injection, auth/crypto,
  infrastructure, and prompt injection defense. Returns a prioritized report with remediation.
  Use when performing a full security review, vulnerability assessment, or pre-deployment
  security check.
disable-model-invocation: true
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
  - Agents
---

# Full Security Audit

Run a comprehensive, multi-domain security review of this project. Use ALL 8 security
sub-agents to cover every attack surface. $ARGUMENTS

## Step 1: Project Discovery

First, understand what we're scanning. Run:

```bash
echo "=== Project Discovery ==="
echo "Languages:"
for ext in js ts jsx tsx py rb go java rs php cs sh; do
  count=$(find . -name "*.$ext" -not -path "*/.git/*" -not -path "*/node_modules/*" -not -path "*/vendor/*" -not -path "*/dist/*" -not -path "*/build/*" -not -path "*/target/*" 2>/dev/null | wc -l)
  [ "$count" -gt 0 ] && echo "  .$ext: $count files"
done
echo ""
echo "Config files:"
for f in package.json requirements.txt pyproject.toml go.mod Cargo.toml Gemfile composer.json Dockerfile docker-compose.yml docker-compose.yaml .gitlab-ci.yml CLAUDE.md .cursorrules; do
  [ -e "$f" ] && echo "  ✓ $f"
done
[ -d ".github/workflows" ] && echo "  ✓ .github/workflows/"
[ -d ".claude" ] && echo "  ✓ .claude/"
find . -name "*.tf" -maxdepth 2 2>/dev/null | head -1 | grep -q . && echo "  ✓ Terraform files"
echo ""
echo "Lockfiles:"
for f in package-lock.json yarn.lock pnpm-lock.yaml poetry.lock Pipfile.lock go.sum Cargo.lock Gemfile.lock composer.lock; do
  [ -e "$f" ] && echo "  ✓ $f"
done
```

## Step 2: Launch Security Sub-Agents

Delegate to ALL of these security sub-agents. Launch them simultaneously in the background
to maximize parallelism. Each agent has its own clean context and domain expertise:

1. **security-agent-env** — Audit CLAUDE.md, hooks, MCP config, permissions, .cursorrules
2. **security-secrets** — Scan for hardcoded API keys, credentials, .env files, private keys
3. **security-code-vulns** — Check OWASP Top 10, CWEs, AI-specific vulnerability patterns
4. **security-supply-chain** — Audit dependencies, lockfiles, version pinning, typosquatting
5. **security-injection** — Detect SQLi, XSS, command injection, SSRF, path traversal
6. **security-auth-crypto** — Review authentication, JWT, crypto, sessions, access control
7. **security-infrastructure** — Audit Docker, K8s, CI/CD pipelines, Terraform, cloud config
8. **security-prompt-injection** — Detect hidden instructions, unicode attacks, encoded payloads

Tell each agent to scan the project root directory and use the scanner scripts in
`scripts/security/` if they exist.

If the user specified a specific area with $ARGUMENTS (e.g. "secrets only", "just auth"),
run only the relevant agent(s) instead of all 8.

## Step 3: Synthesize Report

After all sub-agents return their findings:

1. **Collect** all findings from every agent
2. **Deduplicate** — same file + line + category = one finding (keep highest severity)
3. **Sort** by severity: CRITICAL → HIGH → MEDIUM → LOW → INFO
4. **Calculate risk score**: CRITICAL×25 + HIGH×10 + MEDIUM×3 + LOW×1 (cap at 100)

Present the report in this format:

### Executive Summary
- Overall risk level (CRITICAL/HIGH/MEDIUM/LOW)
- Risk score: X/100
- Finding counts by severity
- Top 3 most critical findings (one line each)

### Findings by Severity

For each finding:
- **[SEVERITY]** Title — CWE/ASI ID
- File: `path/to/file:line`
- Description (what's wrong and why it matters)
- Remediation (concrete, copy-pasteable fix)

### Remediation Priority
- P0 (immediate): CRITICAL findings
- P1 (this sprint): HIGH findings
- P2 (next sprint): MEDIUM findings

## Step 4: Offer Next Steps

After presenting the report:
1. Offer to **auto-fix** CRITICAL and HIGH findings where safe to do so
2. Offer to **install security hooks** by running `bash scripts/security/install_hooks.sh .`
3. Suggest adding the security agents to CI/CD for continuous scanning
