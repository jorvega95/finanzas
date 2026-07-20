#!/usr/bin/env bash
# scan_dependencies.sh — Audit dependencies for security issues
# Usage: bash scan_dependencies.sh [project_root]

set -euo pipefail

PROJECT_ROOT="${1:-.}"
FINDING_COUNT=0

RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo "=== Security Review: Dependency & Supply Chain Scanner ==="
echo "Project: $PROJECT_ROOT"
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "---"

# ── Detect ecosystems ──
echo -e "\n${CYAN}[1/6] Detecting package ecosystems...${NC}"

ECOSYSTEMS=()
[ -f "$PROJECT_ROOT/package.json" ] && ECOSYSTEMS+=("nodejs")
[ -f "$PROJECT_ROOT/requirements.txt" ] || [ -f "$PROJECT_ROOT/pyproject.toml" ] || [ -f "$PROJECT_ROOT/Pipfile" ] && ECOSYSTEMS+=("python")
[ -f "$PROJECT_ROOT/go.mod" ] && ECOSYSTEMS+=("go")
[ -f "$PROJECT_ROOT/Cargo.toml" ] && ECOSYSTEMS+=("rust")
[ -f "$PROJECT_ROOT/Gemfile" ] && ECOSYSTEMS+=("ruby")
[ -f "$PROJECT_ROOT/composer.json" ] && ECOSYSTEMS+=("php")
[ -f "$PROJECT_ROOT/pom.xml" ] || [ -f "$PROJECT_ROOT/build.gradle" ] && ECOSYSTEMS+=("java")

if [ ${#ECOSYSTEMS[@]} -eq 0 ]; then
    echo "No recognized package ecosystems found."
    exit 0
fi

echo "Found ecosystems: ${ECOSYSTEMS[*]}"

# ── Check lockfile existence ──
echo -e "\n${CYAN}[2/6] Checking lockfile status...${NC}"

check_lockfile() {
    local manifest="$1" lockfiles="$2" ecosystem="$3"
    if [ -f "$PROJECT_ROOT/$manifest" ]; then
        local found=false
        for lf in $lockfiles; do
            if [ -f "$PROJECT_ROOT/$lf" ]; then
                found=true
                echo -e "  ${GREEN}✓${NC} $ecosystem: $lf exists"
                break
            fi
        done
        if [ "$found" = false ]; then
            echo -e "  ${RED}✗ CRITICAL:${NC} $ecosystem: $manifest exists but NO lockfile found"
            echo "    Expected one of: $lockfiles"
            FINDING_COUNT=$((FINDING_COUNT + 1))
        fi
    fi
}

check_lockfile "package.json" "package-lock.json yarn.lock pnpm-lock.yaml bun.lockb" "Node.js"
check_lockfile "requirements.txt" "requirements.txt" "Python (requirements.txt is self-locking if pinned)"
check_lockfile "pyproject.toml" "poetry.lock uv.lock pdm.lock" "Python"
check_lockfile "Pipfile" "Pipfile.lock" "Python (Pipenv)"
check_lockfile "go.mod" "go.sum" "Go"
check_lockfile "Cargo.toml" "Cargo.lock" "Rust"
check_lockfile "Gemfile" "Gemfile.lock" "Ruby"
check_lockfile "composer.json" "composer.lock" "PHP"

# ── Check .gitignore for lockfiles (they should NOT be ignored) ──
if [ -f "$PROJECT_ROOT/.gitignore" ]; then
    for lockfile in "package-lock.json" "yarn.lock" "pnpm-lock.yaml" "Cargo.lock" "go.sum" "Gemfile.lock" "composer.lock" "poetry.lock"; do
        if grep -q "$lockfile" "$PROJECT_ROOT/.gitignore" 2>/dev/null; then
            echo -e "  ${RED}✗ HIGH:${NC} $lockfile is in .gitignore — lockfiles should be committed"
            FINDING_COUNT=$((FINDING_COUNT + 1))
        fi
    done
fi

# ── Version pinning analysis ──
echo -e "\n${CYAN}[3/6] Analyzing version pinning...${NC}"

if [ -f "$PROJECT_ROOT/package.json" ]; then
    echo "  Node.js dependencies:"
    # Check for wildcard/loose versions
    wildcards=$(grep -P '"[*]"|"latest"|">=\d' "$PROJECT_ROOT/package.json" 2>/dev/null | wc -l || echo 0)
    if [ "$wildcards" -gt 0 ]; then
        echo -e "  ${RED}✗ HIGH:${NC} Found $wildcards wildcard/loose version ranges in package.json"
        grep -nP '"[*]"|"latest"|">=\d' "$PROJECT_ROOT/package.json" 2>/dev/null | head -10 || true
        FINDING_COUNT=$((FINDING_COUNT + wildcards))
    else
        echo -e "  ${GREEN}✓${NC} No wildcard versions detected"
    fi

    # Check for 0.x with caret (unstable semver)
    unstable=$(grep -P '"\^0\.' "$PROJECT_ROOT/package.json" 2>/dev/null | wc -l || echo 0)
    if [ "$unstable" -gt 0 ]; then
        echo -e "  ${YELLOW}⚠ MEDIUM:${NC} Found $unstable dependencies on ^0.x (unstable semver range)"
        FINDING_COUNT=$((FINDING_COUNT + 1))
    fi
fi

if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
    echo "  Python dependencies:"
    unpinned=$(grep -P '^[a-zA-Z]' "$PROJECT_ROOT/requirements.txt" | grep -vP '==\d' 2>/dev/null | wc -l || echo 0)
    if [ "$unpinned" -gt 0 ]; then
        echo -e "  ${RED}✗ HIGH:${NC} Found $unpinned unpinned dependencies in requirements.txt"
        grep -P '^[a-zA-Z]' "$PROJECT_ROOT/requirements.txt" | grep -vP '==\d' 2>/dev/null | head -10 || true
        FINDING_COUNT=$((FINDING_COUNT + unpinned))
    else
        echo -e "  ${GREEN}✓${NC} All Python dependencies appear pinned"
    fi
fi

# ── Run native audit tools ──
echo -e "\n${CYAN}[4/6] Running vulnerability audit...${NC}"

if [[ " ${ECOSYSTEMS[*]} " == *" nodejs "* ]] && command -v npm &>/dev/null; then
    echo "  Running npm audit..."
    cd "$PROJECT_ROOT"
    npm audit --production --json 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    vulns = data.get('vulnerabilities', {})
    critical = sum(1 for v in vulns.values() if v.get('severity') == 'critical')
    high = sum(1 for v in vulns.values() if v.get('severity') == 'high')
    moderate = sum(1 for v in vulns.values() if v.get('severity') == 'moderate')
    print(f'  npm audit: {critical} critical, {high} high, {moderate} moderate')
    if critical + high > 0:
        for name, info in vulns.items():
            if info.get('severity') in ('critical', 'high'):
                print(f'    - {name}: {info.get(\"severity\",\"?\")} — {info.get(\"via\", [{}])}')
except:
    print('  npm audit: could not parse results')
" 2>/dev/null || echo "  npm audit: not available or failed"
    cd - >/dev/null
fi

# ── Check for post-install scripts ──
echo -e "\n${CYAN}[5/6] Checking for suspicious install scripts...${NC}"

if [ -f "$PROJECT_ROOT/package.json" ]; then
    postinstall=$(python3 -c "
import json
with open('$PROJECT_ROOT/package.json') as f:
    pkg = json.load(f)
scripts = pkg.get('scripts', {})
dangerous = {k:v for k,v in scripts.items() if k in ('postinstall','preinstall','install','prepare') and any(x in v for x in ['curl','wget','sh ','bash ','eval','exec','nc ','http'])}
for k,v in dangerous.items():
    print(f'  CRITICAL: {k}: {v}')
" 2>/dev/null || true)

    if [ -n "$postinstall" ]; then
        echo -e "  ${RED}$postinstall${NC}"
        FINDING_COUNT=$((FINDING_COUNT + 1))
    else
        echo -e "  ${GREEN}✓${NC} No suspicious install scripts in package.json"
    fi
fi

# ── Check for dependency confusion risk ──
echo -e "\n${CYAN}[6/6] Checking for dependency confusion risks...${NC}"

if [ -f "$PROJECT_ROOT/.npmrc" ]; then
    if grep -q "registry=" "$PROJECT_ROOT/.npmrc"; then
        echo -e "  ${GREEN}✓${NC} Custom registry configured in .npmrc"
        # Check if scoped packages are properly configured
        if grep -qP '@[a-z]+:registry=' "$PROJECT_ROOT/.npmrc"; then
            echo -e "  ${GREEN}✓${NC} Scoped registry configuration found"
        fi
    fi
elif [ -f "$PROJECT_ROOT/package.json" ]; then
    # Check if there are scoped private packages without .npmrc
    has_private=$(grep -P '"@[a-z]+/' "$PROJECT_ROOT/package.json" 2>/dev/null | wc -l || echo 0)
    if [ "$has_private" -gt 0 ]; then
        echo -e "  ${YELLOW}⚠ MEDIUM:${NC} Found scoped packages but no .npmrc with registry config"
        echo "    This may be fine if using public scopes, but verify for private packages"
        FINDING_COUNT=$((FINDING_COUNT + 1))
    fi
fi

if [ -f "$PROJECT_ROOT/pip.conf" ] || [ -f "$PROJECT_ROOT/setup.cfg" ]; then
    if grep -q "extra-index-url" "$PROJECT_ROOT/pip.conf" 2>/dev/null; then
        echo -e "  ${YELLOW}⚠ MEDIUM:${NC} Using extra-index-url — verify private packages can't be squatted on PyPI"
        FINDING_COUNT=$((FINDING_COUNT + 1))
    fi
fi

# ── Summary ──
echo -e "\n=== Summary ==="
if [ $FINDING_COUNT -eq 0 ]; then
    echo -e "${GREEN}No supply chain issues detected.${NC}"
else
    echo -e "${RED}Found $FINDING_COUNT potential supply chain issues.${NC}"
fi
echo "Recommendation: Run dedicated tools (npm audit, pip-audit, cargo audit) for comprehensive vulnerability data."
