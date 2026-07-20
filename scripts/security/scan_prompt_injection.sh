#!/usr/bin/env bash
# scan_prompt_injection.sh — Detect prompt injection attempts in project files
# Usage: bash scan_prompt_injection.sh [project_root]
#
# This script scans for hidden instructions, invisible characters, encoded payloads,
# and other content designed to manipulate AI coding agents that read the codebase.

set -euo pipefail

PROJECT_ROOT="${1:-.}"
FINDING_COUNT=0

RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

EXCLUDE="--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=vendor --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=venv --exclude-dir=dist --exclude-dir=build --exclude-dir=target"

finding() {
    local severity="$1" category="$2" file="$3" detail="$4"
    FINDING_COUNT=$((FINDING_COUNT + 1))
    echo -e "  ${RED}[$severity]${NC} ${MAGENTA}$category${NC} | $file"
    echo "    $detail"
}

echo "=== Security Review: Prompt Injection Scanner ==="
echo "Project: $PROJECT_ROOT"
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""
echo "This scanner detects content designed to manipulate AI coding agents."
echo "False positives are possible — review each finding in context."

# ═══════════════════════════════════════════════
# 1. INVISIBLE / ZERO-WIDTH CHARACTERS
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── [1/7] Invisible Unicode Characters ──${NC}"

# Scan all text files for zero-width and bidirectional control characters
# These are almost never legitimate in source code
ZWSP_PATTERN='[\x{200B}\x{200C}\x{200D}\x{2060}\x{FEFF}\x{00AD}]'
BIDI_PATTERN='[\x{200E}\x{200F}\x{202A}-\x{202E}\x{2066}-\x{2069}]'

while IFS= read -r file; do
    [ -z "$file" ] && continue
    # Check for zero-width characters
    if perl -ne "exit 1 if /$ZWSP_PATTERN/" "$file" 2>/dev/null; then
        : # no match
    else
        linenum=$(perl -ne "print \"\$.\n\" if /$ZWSP_PATTERN/" "$file" 2>/dev/null | head -1)
        finding "CRITICAL" "Invisible Chars" "$file" "Zero-width characters detected at line $linenum — may hide instructions from human review"
    fi
    # Check for bidirectional override characters (Trojan Source attack)
    if perl -ne "exit 1 if /$BIDI_PATTERN/" "$file" 2>/dev/null; then
        : # no match
    else
        linenum=$(perl -ne "print \"\$.\n\" if /$BIDI_PATTERN/" "$file" 2>/dev/null | head -1)
        finding "CRITICAL" "Bidi Override" "$file" "Bidirectional control characters at line $linenum — Trojan Source attack vector"
    fi
done < <(find "$PROJECT_ROOT" \( -name "*.js" -o -name "*.ts" -o -name "*.py" -o -name "*.rb" \
    -o -name "*.go" -o -name "*.java" -o -name "*.rs" -o -name "*.md" -o -name "*.txt" \
    -o -name "*.yaml" -o -name "*.yml" -o -name "*.json" -o -name "*.toml" -o -name "*.sh" \
    -o -name "*.jsx" -o -name "*.tsx" -o -name "*.html" -o -name "*.svg" -o -name "*.xml" \
    -o -name "*.css" -o -name "*.php" -o -name "*.cs" \) \
    -not -path "*/.git/*" -not -path "*/node_modules/*" -not -path "*/vendor/*" \
    -not -path "*/dist/*" -not -path "*/build/*" -not -path "*/target/*" \
    -size -1M 2>/dev/null)

# ═══════════════════════════════════════════════
# 2. AGENT-TARGETED INSTRUCTIONS IN COMMENTS/TEXT
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── [2/7] Agent-Targeted Instructions ──${NC}"

# Patterns that address AI assistants/agents directly
AI_DIRECTIVE_PATTERNS=(
    'ignore.*previous.*instruction'
    'ignore.*above.*instruction'
    'override.*(?:security|safety|restriction|permission|check)'
    'you are now'
    'new instruction'
    'system prompt'
    'forget.*(?:previous|above|earlier)'
    'disregard.*(?:previous|above|earlier|all)'
    'act as.*(?:admin|root|system|unrestricted)'
    'maintenance mode'
    'bypass.*(?:check|validation|security|auth|filter)'
    'skip.*(?:security|validation|check|auth|verification)'
    'disable.*(?:security|validation|check|auth|logging)'
    'do not.*(?:log|report|alert|notify|check)'
    '(?:AI|assistant|agent|model|Claude|GPT|LLM).*(?:execute|run|download|fetch|curl|send)'
    'IMPORTANT.*(?:AI|assistant|agent|model).*(?:ignore|override|skip|bypass)'
    '(?:hidden|secret).*instruction'
)

COMBINED_PATTERN=$(IFS='|'; echo "${AI_DIRECTIVE_PATTERNS[*]}")

results=$(grep -rniP "$COMBINED_PATTERN" "$PROJECT_ROOT" \
    $EXCLUDE \
    --include="*.md" --include="*.txt" --include="*.rst" \
    --include="*.js" --include="*.ts" --include="*.py" --include="*.rb" \
    --include="*.go" --include="*.java" --include="*.rs" --include="*.yaml" \
    --include="*.yml" --include="*.json" --include="*.toml" --include="*.html" \
    --include="*.svg" --include="*.xml" --include="*.sh" --include="*.css" \
    --include="*.jsx" --include="*.tsx" --include="*.php" \
    2>/dev/null | head -50 || true)

if [ -n "$results" ]; then
    echo "$results" | while IFS= read -r line; do
        file=$(echo "$line" | cut -d: -f1)
        linenum=$(echo "$line" | cut -d: -f2)
        content=$(echo "$line" | cut -d: -f3- | head -c 120)
        finding "CRITICAL" "Agent Directive" "$file:$linenum" "$content"
    done
else
    echo -e "  ${GREEN}✓${NC} No direct agent-targeted instructions found"
fi

# ═══════════════════════════════════════════════
# 3. CLAUDE.md AND AGENT CONFIG INTEGRITY
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── [3/7] Agent Configuration Files ──${NC}"

# Check CLAUDE.md files
for claudemd in $(find "$PROJECT_ROOT" -name "CLAUDE.md" -not -path "*/.git/*" -not -path "*/node_modules/*" 2>/dev/null); do
    echo "  Analyzing: $claudemd"

    # Check for auto-approve / skip-permission patterns
    if grep -qiP '(?:always.*approve|auto.*(?:execute|approve|accept)|skip.*(?:confirm|permission|approval))' "$claudemd" 2>/dev/null; then
        finding "CRITICAL" "Agent Config" "$claudemd" "Contains auto-approve/skip-confirmation directive"
    fi

    # Check for encoded content
    if grep -qP '(?:[A-Za-z0-9+/]{4}){12,}={0,2}' "$claudemd" 2>/dev/null; then
        finding "HIGH" "Agent Config" "$claudemd" "Contains base64-encoded block — decode and verify content"
    fi

    # Check for external URL references for "more instructions"
    if grep -qiP '(?:additional|more|extra|further).*instruction.*https?://' "$claudemd" 2>/dev/null; then
        finding "CRITICAL" "Agent Config" "$claudemd" "References external URL for additional instructions"
    fi

    # Check for shell modification directives
    if grep -qiP '(?:bashrc|zshrc|profile|shell.*config|PATH.*export)' "$claudemd" 2>/dev/null; then
        finding "HIGH" "Agent Config" "$claudemd" "References shell configuration modification"
    fi

    # Check for permission expansion
    if grep -qiP 'dangerously-skip-permissions' "$claudemd" 2>/dev/null; then
        finding "CRITICAL" "Agent Config" "$claudemd" "References --dangerously-skip-permissions flag"
    fi
done

# Check .cursorrules
for cursorrules in $(find "$PROJECT_ROOT" -name ".cursorrules" -not -path "*/.git/*" 2>/dev/null); do
    echo "  Analyzing: $cursorrules"
    if grep -qiP '(?:ignore|override|bypass|skip).*(?:security|check|validation)' "$cursorrules" 2>/dev/null; then
        finding "HIGH" "Agent Config" "$cursorrules" "Contains directive to bypass security checks"
    fi
done

# Check .claude/ directory
if [ -d "$PROJECT_ROOT/.claude" ]; then
    echo "  Analyzing: .claude/ directory"

    if [ -f "$PROJECT_ROOT/.claude/settings.json" ]; then
        # Check for overly permissive settings
        if grep -qP '"dangerously' "$PROJECT_ROOT/.claude/settings.json" 2>/dev/null; then
            finding "CRITICAL" "Agent Config" ".claude/settings.json" "Contains dangerous permission override"
        fi
    fi

    # Check custom commands
    for cmd in $(find "$PROJECT_ROOT/.claude/commands" -type f 2>/dev/null); do
        if grep -qiP '(?:curl|wget|nc|eval|exec|bash -c)' "$cmd" 2>/dev/null; then
            finding "HIGH" "Agent Config" "$cmd" "Custom command executes potentially dangerous operations"
        fi
    done
fi

if [ ! -f "$PROJECT_ROOT/CLAUDE.md" ] && [ ! -d "$PROJECT_ROOT/.claude" ]; then
    echo -e "  ${YELLOW}ℹ${NC} No CLAUDE.md or .claude/ config found (consider adding security boundaries)"
fi

# ═══════════════════════════════════════════════
# 4. ENCODED PAYLOADS IN COMMENTS
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── [4/7] Encoded Payloads in Comments ──${NC}"

# Look for suspiciously long base64 strings in comments
results=$(grep -rnP '(?://|#|/\*|\*|<!--)\s*.*(?:[A-Za-z0-9+/]{4}){15,}={0,2}' "$PROJECT_ROOT" \
    $EXCLUDE \
    --include="*.js" --include="*.ts" --include="*.py" --include="*.rb" \
    --include="*.go" --include="*.java" --include="*.rs" --include="*.sh" \
    --include="*.html" --include="*.xml" --include="*.yaml" --include="*.yml" \
    2>/dev/null | head -20 || true)

if [ -n "$results" ]; then
    echo "$results" | while IFS= read -r line; do
        file=$(echo "$line" | cut -d: -f1)
        linenum=$(echo "$line" | cut -d: -f2)
        finding "HIGH" "Encoded Payload" "$file:$linenum" "Suspicious base64 block in comment — decode and verify"
    done
else
    echo -e "  ${GREEN}✓${NC} No suspicious encoded payloads in comments"
fi

# Hex-encoded strings in comments
results=$(grep -rnP '(?://|#|/\*|\*|<!--)\s*.*(?:0x[0-9a-fA-F]{2}\s*){10,}' "$PROJECT_ROOT" \
    $EXCLUDE \
    --include="*.js" --include="*.ts" --include="*.py" --include="*.rb" \
    --include="*.go" --include="*.java" --include="*.rs" \
    2>/dev/null | head -10 || true)

if [ -n "$results" ]; then
    echo "$results" | while IFS= read -r line; do
        file=$(echo "$line" | cut -d: -f1)
        linenum=$(echo "$line" | cut -d: -f2)
        finding "MEDIUM" "Encoded Payload" "$file:$linenum" "Hex-encoded content in comment"
    done
else
    echo -e "  ${GREEN}✓${NC} No hex-encoded payloads in comments"
fi

# ═══════════════════════════════════════════════
# 5. HIDDEN ELEMENTS IN HTML/SVG/MARKDOWN
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── [5/7] Hidden Content in HTML/SVG/Markdown ──${NC}"

# Hidden text in HTML (display:none, visibility:hidden, off-screen, opacity:0, font-size:0)
for htmlfile in $(find "$PROJECT_ROOT" -name "*.html" -o -name "*.htm" -o -name "*.svg" \
    -not -path "*/.git/*" -not -path "*/node_modules/*" -not -path "*/dist/*" \
    -not -path "*/build/*" -size -1M 2>/dev/null | head -50); do

    # Check for hidden text with potential instructions
    if grep -qiP '(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0|font-size\s*:\s*0|position\s*:\s*absolute.*left\s*:\s*-\d{4,}).*(?:AI|assistant|agent|instruction|execute|ignore|override)' "$htmlfile" 2>/dev/null; then
        finding "CRITICAL" "Hidden Content" "$htmlfile" "Hidden HTML element contains AI-targeted text"
    fi

    # SVG hidden text
    if echo "$htmlfile" | grep -qi "\.svg$"; then
        if grep -qiP '<text[^>]*(?:opacity="0"|display="none"|font-size="0|x="-\d{4,})' "$htmlfile" 2>/dev/null; then
            finding "HIGH" "Hidden Content" "$htmlfile" "SVG contains hidden text element"
        fi
        # SVG script tags
        if grep -qi '<script' "$htmlfile" 2>/dev/null; then
            finding "HIGH" "Hidden Content" "$htmlfile" "SVG contains <script> tag"
        fi
        # SVG foreignObject
        if grep -qi '<foreignObject' "$htmlfile" 2>/dev/null; then
            finding "MEDIUM" "Hidden Content" "$htmlfile" "SVG contains <foreignObject> — can embed arbitrary HTML"
        fi
    fi
done

# Hidden HTML blocks in markdown
for mdfile in $(find "$PROJECT_ROOT" -name "*.md" -not -path "*/.git/*" -not -path "*/node_modules/*" -size -1M 2>/dev/null | head -50); do
    if grep -qiP '<[^>]*(?:display\s*:\s*none|visibility\s*:\s*hidden|aria-hidden|hidden)' "$mdfile" 2>/dev/null; then
        if grep -qiP '<[^>]*(?:hidden|display:none)[^>]*>.*(?:AI|assistant|agent|instruction|execute|override)' "$mdfile" 2>/dev/null; then
            finding "CRITICAL" "Hidden Content" "$mdfile" "Hidden HTML in markdown contains AI-targeted instructions"
        else
            finding "MEDIUM" "Hidden Content" "$mdfile" "Markdown contains hidden HTML elements — review content"
        fi
    fi
done

echo -e "  ${GREEN}✓${NC} Hidden content scan complete"

# ═══════════════════════════════════════════════
# 6. DEPENDENCY METADATA INJECTION
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── [6/7] Package Metadata Injection ──${NC}"

# Check package.json descriptions for injection
if [ -f "$PROJECT_ROOT/package.json" ]; then
    desc=$(python3 -c "
import json, sys
try:
    with open('$PROJECT_ROOT/package.json') as f:
        pkg = json.load(f)
    desc = pkg.get('description', '')
    keywords = ['AI', 'assistant', 'agent', 'instruction', 'execute', 'run', 'curl', 'wget', 'bash']
    flagged = [k for k in keywords if k.lower() in desc.lower()]
    if flagged:
        print(f'Suspicious keywords in description: {flagged}')
        print(f'Description: {desc[:200]}')
except Exception as e:
    pass
" 2>/dev/null || true)

    if [ -n "$desc" ]; then
        finding "MEDIUM" "Metadata Injection" "package.json" "$desc"
    fi
fi

# Check pyproject.toml descriptions
if [ -f "$PROJECT_ROOT/pyproject.toml" ]; then
    if grep -qiP 'description\s*=\s*"[^"]*(?:AI|assistant|agent|instruction|execute|curl|bash)' "$PROJECT_ROOT/pyproject.toml" 2>/dev/null; then
        finding "MEDIUM" "Metadata Injection" "pyproject.toml" "Suspicious content in description field"
    fi
fi

echo -e "  ${GREEN}✓${NC} Package metadata scan complete"

# ═══════════════════════════════════════════════
# 7. GIT HOOKS INTEGRITY
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── [7/7] Git Hooks Integrity ──${NC}"

if [ -d "$PROJECT_ROOT/.git/hooks" ]; then
    for hook in $(find "$PROJECT_ROOT/.git/hooks" -type f -executable 2>/dev/null | grep -v "\.sample$"); do
        echo "  Analyzing: $hook"

        # Check for network access
        if grep -qiP '(?:curl|wget|nc|ncat|fetch|http|ssh|scp|rsync)' "$hook" 2>/dev/null; then
            finding "HIGH" "Git Hook" "$hook" "Hook accesses network — verify this is intended"
        fi

        # Check for encoded execution
        if grep -qiP '(?:base64.*decode|eval|exec.*\$)' "$hook" 2>/dev/null; then
            finding "CRITICAL" "Git Hook" "$hook" "Hook contains encoded execution pattern"
        fi

        # Check for environment variable exfiltration
        if grep -qiP '(?:printenv|env\b|\$\{?(?:API|SECRET|KEY|TOKEN|PASSWORD|AWS))' "$hook" 2>/dev/null; then
            finding "HIGH" "Git Hook" "$hook" "Hook accesses environment variables or secrets"
        fi

        # Check for file modification outside project
        if grep -qiP '(?:~\/|/home/|/root/|/etc/|/tmp/)' "$hook" 2>/dev/null; then
            finding "MEDIUM" "Git Hook" "$hook" "Hook references paths outside project directory"
        fi
    done
else
    echo -e "  ${YELLOW}ℹ${NC} No .git/hooks directory found (not a git repository or hooks not set up)"
fi

# Also check Husky hooks
if [ -d "$PROJECT_ROOT/.husky" ]; then
    for hook in $(find "$PROJECT_ROOT/.husky" -type f -executable 2>/dev/null | grep -v "_"); do
        echo "  Analyzing Husky hook: $hook"
        if grep -qiP '(?:curl|wget|nc|ncat|eval|base64|exec.*\$)' "$hook" 2>/dev/null; then
            finding "HIGH" "Git Hook" "$hook" "Husky hook contains suspicious patterns"
        fi
    done
fi

# ═══════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════
echo -e "\n========================================="
echo "=== Prompt Injection Scan Summary ==="
echo "========================================="
if [ $FINDING_COUNT -eq 0 ]; then
    echo -e "${GREEN}No prompt injection indicators detected.${NC}"
    echo "This does not guarantee safety — sophisticated attacks may evade pattern matching."
else
    echo -e "${RED}Found $FINDING_COUNT potential prompt injection indicators.${NC}"
    echo ""
    echo "IMPORTANT: Review each finding manually. Not all findings are malicious —"
    echo "some may be legitimate security documentation or testing fixtures."
    echo "However, any file that contains instructions addressed to AI agents"
    echo "should be carefully reviewed for intent."
fi
echo ""
echo "Recommendations:"
echo "  1. Add security boundaries to CLAUDE.md (see Module 1 reference)"
echo "  2. Set up pre-commit hooks to catch injection patterns"
echo "  3. Review all findings with a human security reviewer"
echo "  4. Consider file integrity monitoring for critical config files"
