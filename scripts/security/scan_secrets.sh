#!/usr/bin/env bash
# scan_secrets.sh — Detects hardcoded secrets, API keys, and credentials
# Usage: bash scan_secrets.sh [project_root]
# Output: JSON findings to stdout

set -euo pipefail

PROJECT_ROOT="${1:-.}"
FINDINGS=()
FINDING_COUNT=0

# Colors for terminal
RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
NC='\033[0m'

log_finding() {
    local severity="$1" file="$2" line="$3" pattern="$4" match="$5"
    FINDING_COUNT=$((FINDING_COUNT + 1))
    # Mask the actual secret value (show first 4 and last 4 chars)
    local masked
    if [ ${#match} -gt 12 ]; then
        masked="${match:0:4}...${match: -4}"
    else
        masked="[REDACTED]"
    fi
    echo "{\"id\":$FINDING_COUNT,\"severity\":\"$severity\",\"file\":\"$file\",\"line\":$line,\"pattern\":\"$pattern\",\"match\":\"$masked\"}"
}

echo "=== Security Review: Secrets & Credentials Scanner ==="
echo "Project: $PROJECT_ROOT"
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "---"
echo "["

# File extensions to scan
SCAN_EXTENSIONS="js,ts,jsx,tsx,py,rb,go,java,rs,php,cs,swift,kt,sh,bash,json,yaml,yml,toml,ini,cfg,conf,properties,xml,env,md,txt,ipynb,tf,tfvars,dockerfile,Makefile"

# Build find command excluding common non-essential directories
EXCLUDE_DIRS="-not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/vendor/*' -not -path '*/__pycache__/*' -not -path '*/.venv/*' -not -path '*/venv/*' -not -path '*/.tox/*' -not -path '*/dist/*' -not -path '*/build/*' -not -path '*/.next/*' -not -path '*/target/*'"

# ── AWS Keys ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "CRITICAL" "$file" "$line" "AWS Access Key" "$match"
done < <(grep -rnP '(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── Private Keys ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "CRITICAL" "$file" "$line" "Private Key" "$match"
done < <(grep -rnP '-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" --include="*.pem" --include="*.key" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── Anthropic API Keys ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "CRITICAL" "$file" "$line" "Anthropic API Key" "$match"
done < <(grep -rnP 'sk-ant-[a-zA-Z0-9_-]{20,}' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── OpenAI API Keys ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "CRITICAL" "$file" "$line" "OpenAI API Key" "$match"
done < <(grep -rnP 'sk-[a-zA-Z0-9]{48,}' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── GitHub Tokens ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "CRITICAL" "$file" "$line" "GitHub Token" "$match"
done < <(grep -rnP 'gh[pousr]_[A-Za-z0-9_]{36,}' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── Database Connection Strings ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "CRITICAL" "$file" "$line" "Database Connection String" "$match"
done < <(grep -rnP '(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis|amqp)://[^\s'"'"'"]+:[^\s'"'"'"]+@' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── Stripe Keys ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "HIGH" "$file" "$line" "Stripe Key" "$match"
done < <(grep -rnP '[sr]k_(?:live|test)_[A-Za-z0-9]{20,}' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── Slack Tokens ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "HIGH" "$file" "$line" "Slack Token" "$match"
done < <(grep -rnP 'xox[boaprs]-[0-9a-zA-Z-]{10,}' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── Google API Keys ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "HIGH" "$file" "$line" "Google API Key" "$match"
done < <(grep -rnP 'AIza[0-9A-Za-z_-]{35}' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── SendGrid Keys ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "HIGH" "$file" "$line" "SendGrid API Key" "$match"
done < <(grep -rnP 'SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── Generic Password/Secret Assignments ──
while IFS=: read -r file line match; do
    # Filter false positives
    if echo "$match" | grep -qiP '(example|placeholder|changeme|xxx|test|dummy|TODO|your.?key|INSERT|REPLACE)'; then
        continue
    fi
    [ -n "$file" ] && log_finding "HIGH" "$file" "$line" "Hardcoded Secret" "$match"
done < <(grep -rnP '(?i)(?:api[_-]?key|api[_-]?secret|access[_-]?key|secret[_-]?key|auth[_-]?token|password|passwd)\s*[=:]\s*['"'"'"][A-Za-z0-9+/=_-]{16,}['"'"'"]' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -100 || true)

# ── .env files committed ──
while IFS= read -r envfile; do
    if [ -f "$envfile" ]; then
        local_count=$(grep -cP '^\s*[A-Z_]+=\S+' "$envfile" 2>/dev/null || echo "0")
        if [ "$local_count" -gt 0 ]; then
            log_finding "HIGH" "$envfile" "0" ".env file with secrets" "$local_count variables found"
        fi
    fi
done < <(find "$PROJECT_ROOT" -name ".env" -o -name ".env.local" -o -name ".env.production" \
    -not -name ".env.example" -not -name ".env.template" -not -name ".env.sample" \
    ${EXCLUDE_DIRS} 2>/dev/null || true)

# ── MCP Config with hardcoded credentials ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "CRITICAL" "$file" "$line" "MCP Hardcoded Credential" "$match"
done < <(grep -rnP '"(?:password|secret|key|token|api_key)":\s*"(?!\$\{)[^"]{8,}"' "$PROJECT_ROOT" \
    --include="*mcp*.json" --include="*claude*.json" --include="settings.json" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -50 || true)

# ── JWT Tokens in source ──
while IFS=: read -r file line match; do
    [ -n "$file" ] && log_finding "MEDIUM" "$file" "$line" "JWT Token in Source" "$match"
done < <(grep -rnP 'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}' "$PROJECT_ROOT" \
    --include="*.{$SCAN_EXTENSIONS}" \
    ${EXCLUDE_DIRS} 2>/dev/null | head -30 || true)

echo "]"
echo "---"
echo "Total findings: $FINDING_COUNT"

if [ $FINDING_COUNT -eq 0 ]; then
    echo -e "${GREEN}No secrets detected.${NC}"
else
    echo -e "${RED}Found $FINDING_COUNT potential secrets. Review each finding carefully.${NC}"
fi
