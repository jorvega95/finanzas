#!/usr/bin/env bash
# scan_configs.sh — Audit configuration files for security issues
# Usage: bash scan_configs.sh [project_root]

set -euo pipefail

PROJECT_ROOT="${1:-.}"
FINDING_COUNT=0

RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

finding() {
    local severity="$1" category="$2" file="$3" detail="$4"
    FINDING_COUNT=$((FINDING_COUNT + 1))
    echo -e "  ${RED}[$severity]${NC} $category | $file: $detail"
}

echo "=== Security Review: Configuration Auditor ==="
echo "Project: $PROJECT_ROOT"
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ═══════════════════════════════════════════════
# DOCKERFILE SECURITY
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Docker Configuration ──${NC}"

for dockerfile in $(find "$PROJECT_ROOT" -name "Dockerfile*" -not -path "*/.git/*" -not -path "*/node_modules/*" 2>/dev/null); do
    echo "  Scanning: $dockerfile"

    # Check for :latest tag
    if grep -qP '^FROM\s+\S+:latest' "$dockerfile" 2>/dev/null; then
        finding "HIGH" "Docker" "$dockerfile" "Using :latest tag — pin to specific version"
    fi
    if grep -qP '^FROM\s+\S+\s*$' "$dockerfile" 2>/dev/null; then
        finding "HIGH" "Docker" "$dockerfile" "No tag specified (implies :latest)"
    fi

    # Check for root user
    if ! grep -q '^USER ' "$dockerfile" 2>/dev/null; then
        finding "HIGH" "Docker" "$dockerfile" "No USER directive — container runs as root"
    fi

    # Check for secrets in ENV/ARG
    if grep -qiP '(?:ENV|ARG)\s+(?:.*(?:PASSWORD|SECRET|KEY|TOKEN|CREDENTIAL))\s*=' "$dockerfile" 2>/dev/null; then
        finding "CRITICAL" "Docker" "$dockerfile" "Sensitive value in ENV/ARG directive"
    fi

    # Check for COPY . .
    if grep -qP '^COPY\s+\.\s+' "$dockerfile" 2>/dev/null; then
        if ! [ -f "$(dirname "$dockerfile")/.dockerignore" ]; then
            finding "MEDIUM" "Docker" "$dockerfile" "COPY . without .dockerignore — may copy secrets"
        fi
    fi

    # Check for ADD with URL (prefer COPY + explicit download)
    if grep -qP '^ADD\s+https?://' "$dockerfile" 2>/dev/null; then
        finding "MEDIUM" "Docker" "$dockerfile" "ADD with URL — use COPY + explicit download with checksum"
    fi
done

# docker-compose
for composefile in $(find "$PROJECT_ROOT" -name "docker-compose*.yml" -o -name "docker-compose*.yaml" -o -name "compose.yml" -o -name "compose.yaml" 2>/dev/null | head -10); do
    echo "  Scanning: $composefile"

    if grep -q "privileged:\s*true" "$composefile" 2>/dev/null; then
        finding "CRITICAL" "Docker" "$composefile" "Container running in privileged mode"
    fi
    if grep -q "network_mode:\s*host" "$composefile" 2>/dev/null; then
        finding "HIGH" "Docker" "$composefile" "Container using host network mode"
    fi
    if grep -qP "docker\.sock" "$composefile" 2>/dev/null; then
        finding "CRITICAL" "Docker" "$composefile" "Docker socket mounted — container escape risk"
    fi
    if grep -qP '^\s+-\s+/:/\w' "$composefile" 2>/dev/null; then
        finding "CRITICAL" "Docker" "$composefile" "Host root filesystem mounted"
    fi
    # Inline env vars with secrets
    if grep -qiP '(?:PASSWORD|SECRET|KEY|TOKEN)=(?!\$\{)[^\s]+' "$composefile" 2>/dev/null; then
        finding "HIGH" "Docker" "$composefile" "Hardcoded credential in environment directive"
    fi
done

# ═══════════════════════════════════════════════
# CI/CD SECURITY
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── CI/CD Pipeline Configuration ──${NC}"

# GitHub Actions
for workflow in $(find "$PROJECT_ROOT/.github/workflows" -name "*.yml" -o -name "*.yaml" 2>/dev/null); do
    echo "  Scanning: $workflow"

    # Unpinned actions (using @v3 instead of @sha256:...)
    unpinned=$(grep -P 'uses:\s+[^@]+@v\d' "$workflow" 2>/dev/null | wc -l || echo 0)
    if [ "$unpinned" -gt 0 ]; then
        finding "MEDIUM" "CI/CD" "$workflow" "$unpinned actions pinned to tag instead of SHA"
    fi

    # pull_request_target with checkout
    if grep -q "pull_request_target" "$workflow" 2>/dev/null; then
        if grep -qP 'ref.*pull_request\.head' "$workflow" 2>/dev/null; then
            finding "CRITICAL" "CI/CD" "$workflow" "pull_request_target with PR head checkout — RCE risk"
        else
            finding "HIGH" "CI/CD" "$workflow" "pull_request_target trigger — review carefully for injection"
        fi
    fi

    # Overly permissive permissions
    if grep -qP 'permissions:\s*write-all' "$workflow" 2>/dev/null; then
        finding "HIGH" "CI/CD" "$workflow" "Workflow has write-all permissions"
    fi

    # Script injection via github context
    if grep -qP '\$\{\{\s*github\.event\.' "$workflow" 2>/dev/null; then
        finding "MEDIUM" "CI/CD" "$workflow" "GitHub event context used — check for injection"
    fi

    # Self-hosted runners
    if grep -qP 'runs-on:\s*self-hosted' "$workflow" 2>/dev/null; then
        finding "MEDIUM" "CI/CD" "$workflow" "Self-hosted runners — ensure isolated from untrusted PRs"
    fi
done

# GitLab CI
if [ -f "$PROJECT_ROOT/.gitlab-ci.yml" ]; then
    echo "  Scanning: .gitlab-ci.yml"

    if grep -qiP '(?:PASSWORD|SECRET|TOKEN|KEY)\s*:\s*(?!\$)' "$PROJECT_ROOT/.gitlab-ci.yml" 2>/dev/null; then
        finding "CRITICAL" "CI/CD" ".gitlab-ci.yml" "Hardcoded secret in pipeline config"
    fi
    if grep -q "allow_failure:\s*true" "$PROJECT_ROOT/.gitlab-ci.yml" 2>/dev/null; then
        # Check if it's on a security-related job
        if grep -B5 "allow_failure:\s*true" "$PROJECT_ROOT/.gitlab-ci.yml" | grep -qi "security\|scan\|audit\|sast\|dast" 2>/dev/null; then
            finding "HIGH" "CI/CD" ".gitlab-ci.yml" "Security scanning job allows failure"
        fi
    fi
fi

# ═══════════════════════════════════════════════
# TERRAFORM / IAC
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Infrastructure-as-Code ──${NC}"

for tffile in $(find "$PROJECT_ROOT" -name "*.tf" -not -path "*/.terraform/*" 2>/dev/null | head -30); do
    # Open security groups
    if grep -qP 'cidr_blocks\s*=\s*\["0\.0\.0\.0/0"\]' "$tffile" 2>/dev/null; then
        if grep -B10 'cidr_blocks\s*=\s*\["0.0.0.0/0"\]' "$tffile" | grep -qP 'from_port\s*=\s*(22|3389|3306|5432|27017)' 2>/dev/null; then
            finding "CRITICAL" "IaC" "$tffile" "Security group allows 0.0.0.0/0 on management/DB port"
        fi
    fi

    # Hardcoded secrets
    if grep -qiP '(?:password|secret_key|access_key)\s*=\s*"(?!\$\{)' "$tffile" 2>/dev/null; then
        finding "CRITICAL" "IaC" "$tffile" "Hardcoded credential in Terraform"
    fi

    # Public S3 buckets
    if grep -q "acl.*public" "$tffile" 2>/dev/null; then
        finding "HIGH" "IaC" "$tffile" "S3 bucket with public ACL"
    fi

    # Unencrypted storage
    if grep -q "encrypted\s*=\s*false" "$tffile" 2>/dev/null; then
        finding "HIGH" "IaC" "$tffile" "Resource with encryption disabled"
    fi
done

# Check for .tfvars with secrets
for tfvars in $(find "$PROJECT_ROOT" -name "*.tfvars" -not -path "*/.git/*" 2>/dev/null); do
    if grep -qiP '(?:password|secret|key|token)\s*=' "$tfvars" 2>/dev/null; then
        finding "CRITICAL" "IaC" "$tfvars" ".tfvars file contains credentials — should use vault"
    fi
done

# Check terraform state in repo
if find "$PROJECT_ROOT" -name "*.tfstate" -not -path "*/.git/*" 2>/dev/null | head -1 | grep -q .; then
    finding "CRITICAL" "IaC" "*.tfstate" "Terraform state file in project — contains secrets, must be remote"
fi

# ═══════════════════════════════════════════════
# KUBERNETES
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Kubernetes Configuration ──${NC}"

for k8sfile in $(find "$PROJECT_ROOT" -name "*.yaml" -o -name "*.yml" 2>/dev/null | xargs grep -l "kind:\s*\(Deployment\|Pod\|DaemonSet\|StatefulSet\)" 2>/dev/null | head -20); do
    echo "  Scanning: $k8sfile"

    if grep -q "privileged:\s*true" "$k8sfile" 2>/dev/null; then
        finding "CRITICAL" "K8s" "$k8sfile" "Privileged container"
    fi
    if ! grep -q "runAsNonRoot:\s*true" "$k8sfile" 2>/dev/null; then
        finding "HIGH" "K8s" "$k8sfile" "Missing runAsNonRoot: true"
    fi
    if ! grep -q "readOnlyRootFilesystem:\s*true" "$k8sfile" 2>/dev/null; then
        finding "MEDIUM" "K8s" "$k8sfile" "Missing readOnlyRootFilesystem: true"
    fi
    if grep -q "hostPath:" "$k8sfile" 2>/dev/null; then
        finding "HIGH" "K8s" "$k8sfile" "hostPath volume mount — potential node escape"
    fi
    if grep -q "hostNetwork:\s*true" "$k8sfile" 2>/dev/null; then
        finding "HIGH" "K8s" "$k8sfile" "hostNetwork enabled"
    fi
    if ! grep -q "resources:" "$k8sfile" 2>/dev/null; then
        finding "LOW" "K8s" "$k8sfile" "No resource limits — DoS risk"
    fi
done

# Check for plaintext secrets in K8s manifests
for k8sfile in $(find "$PROJECT_ROOT" -name "*.yaml" -o -name "*.yml" 2>/dev/null | xargs grep -l "kind:\s*Secret" 2>/dev/null | head -10); do
    finding "HIGH" "K8s" "$k8sfile" "Kubernetes Secret manifest — should use sealed-secrets or external-secrets"
done

# ═══════════════════════════════════════════════
# PACKAGE MANAGER CONFIGS
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Package Manager Configuration ──${NC}"

# .npmrc with auth tokens
if [ -f "$PROJECT_ROOT/.npmrc" ]; then
    if grep -qP '_authToken|_auth\s*=' "$PROJECT_ROOT/.npmrc" 2>/dev/null; then
        finding "CRITICAL" "Config" ".npmrc" "Auth token in .npmrc — use environment variable"
    fi
fi

# pip.conf with credentials
if [ -f "$PROJECT_ROOT/pip.conf" ]; then
    if grep -qiP '(?:password|token)' "$PROJECT_ROOT/pip.conf" 2>/dev/null; then
        finding "HIGH" "Config" "pip.conf" "Credentials in pip.conf"
    fi
fi

# ═══════════════════════════════════════════════
# CORS AND SECURITY HEADERS
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Security Headers & CORS ──${NC}"

# Wide-open CORS
grep -rnP "Access-Control-Allow-Origin.*\*|cors\(\s*\)|origin:\s*(?:true|\*|['\"]?\*)" \
    "$PROJECT_ROOT" --include="*.js" --include="*.ts" --include="*.py" \
    --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=vendor 2>/dev/null | head -10 | while IFS= read -r line; do
    finding "HIGH" "CORS" "$(echo "$line" | cut -d: -f1)" "Unrestricted CORS — allows any origin"
done

# ═══════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════
echo -e "\n=== Summary ==="
if [ $FINDING_COUNT -eq 0 ]; then
    echo -e "${GREEN}No configuration issues detected.${NC}"
else
    echo -e "${RED}Found $FINDING_COUNT configuration security issues.${NC}"
fi
