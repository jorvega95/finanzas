#!/usr/bin/env bash
# scan_code_patterns.sh — Detect common vulnerability patterns in source code
# Usage: bash scan_code_patterns.sh [project_root]

set -euo pipefail

PROJECT_ROOT="${1:-.}"
FINDING_COUNT=0

RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

EXCLUDE="--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=vendor --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=venv --exclude-dir=dist --exclude-dir=build --exclude-dir=.next --exclude-dir=target --exclude-dir=.tox"

scan_pattern() {
    local severity="$1" category="$2" description="$3" pattern="$4" includes="$5"
    local results
    results=$(grep -rnP $EXCLUDE $includes "$pattern" "$PROJECT_ROOT" 2>/dev/null | head -20 || true)
    if [ -n "$results" ]; then
        local count
        count=$(echo "$results" | wc -l)
        FINDING_COUNT=$((FINDING_COUNT + count))
        echo -e "\n${RED}[$severity]${NC} $category: $description ($count instances)"
        echo "$results" | while IFS= read -r line; do
            echo "  $line"
        done
    fi
}

echo "=== Security Review: Code Pattern Scanner ==="
echo "Project: $PROJECT_ROOT"
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ═══════════════════════════════════════════════
# SQL INJECTION
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── SQL Injection (CWE-89) ──${NC}"

scan_pattern "CRITICAL" "SQLi" "String interpolation in SQL query (JS/TS)" \
    '(?:query|execute|raw)\s*\(\s*`[^`]*\$\{' \
    "--include=*.js --include=*.ts --include=*.jsx --include=*.tsx"

scan_pattern "CRITICAL" "SQLi" "String concatenation in SQL query (JS/TS)" \
    '(?:query|execute)\s*\(\s*['"'"'"][^'"'"'"]*['"'"'"]\s*\+' \
    "--include=*.js --include=*.ts"

scan_pattern "CRITICAL" "SQLi" "f-string/format in SQL query (Python)" \
    '(?:execute|cursor\.execute|\.query)\s*\(\s*f['"'"'"]' \
    "--include=*.py"

scan_pattern "CRITICAL" "SQLi" "%-format in SQL query (Python)" \
    'execute\s*\(\s*['"'"'"][^'"'"'"]*%s[^'"'"'"]*['"'"'"]\s*%' \
    "--include=*.py"

scan_pattern "CRITICAL" "SQLi" "String format in SQL (Go)" \
    'fmt\.Sprintf\s*\(\s*"(?:SELECT|INSERT|UPDATE|DELETE|DROP)' \
    "--include=*.go"

# ═══════════════════════════════════════════════
# XSS
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Cross-Site Scripting (CWE-79) ──${NC}"

scan_pattern "HIGH" "XSS" "dangerouslySetInnerHTML usage" \
    'dangerouslySetInnerHTML' \
    "--include=*.jsx --include=*.tsx --include=*.js --include=*.ts"

scan_pattern "HIGH" "XSS" "innerHTML assignment" \
    '\.innerHTML\s*=' \
    "--include=*.js --include=*.ts --include=*.jsx --include=*.tsx"

scan_pattern "HIGH" "XSS" "document.write with dynamic content" \
    'document\.write\s*\(' \
    "--include=*.js --include=*.ts --include=*.html"

scan_pattern "MEDIUM" "XSS" "jQuery .html() with variable" \
    '\.\s*html\s*\(\s*[a-zA-Z]' \
    "--include=*.js --include=*.ts"

# ═══════════════════════════════════════════════
# COMMAND INJECTION
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Command Injection (CWE-78) ──${NC}"

scan_pattern "CRITICAL" "CMDi" "shell=True in subprocess (Python)" \
    'subprocess\.\w+\s*\([^)]*shell\s*=\s*True' \
    "--include=*.py"

scan_pattern "CRITICAL" "CMDi" "os.system() usage (Python)" \
    'os\.system\s*\(' \
    "--include=*.py"

scan_pattern "CRITICAL" "CMDi" "os.popen() usage (Python)" \
    'os\.popen\s*\(' \
    "--include=*.py"

scan_pattern "HIGH" "CMDi" "exec() with template literal (JS)" \
    'exec\s*\(\s*`' \
    "--include=*.js --include=*.ts"

scan_pattern "HIGH" "CMDi" "exec() with concatenation (JS)" \
    'exec\s*\(\s*['"'"'"][^'"'"'"]*['"'"'"]\s*\+' \
    "--include=*.js --include=*.ts"

scan_pattern "HIGH" "CMDi" "eval() usage" \
    '\beval\s*\(' \
    "--include=*.js --include=*.ts --include=*.py --include=*.rb --include=*.php"

# ═══════════════════════════════════════════════
# INSECURE DESERIALIZATION
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Insecure Deserialization (CWE-502) ──${NC}"

scan_pattern "CRITICAL" "Deser" "pickle.loads on potentially untrusted data (Python)" \
    'pickle\.loads?\s*\(' \
    "--include=*.py"

scan_pattern "HIGH" "Deser" "yaml.load without safe_load (Python)" \
    'yaml\.load\s*\(' \
    "--include=*.py"

scan_pattern "HIGH" "Deser" "Marshal.load (Ruby)" \
    'Marshal\.load\s*\(' \
    "--include=*.rb"

# ═══════════════════════════════════════════════
# CRYPTOGRAPHIC ISSUES
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Cryptographic Issues (CWE-327/326) ──${NC}"

scan_pattern "HIGH" "Crypto" "MD5 usage for security" \
    '(?:hashlib\.md5|MD5\.Create|MessageDigest.*MD5|crypto\.createHash\s*\(\s*['"'"'"]md5)' \
    "--include=*.py --include=*.js --include=*.ts --include=*.java --include=*.cs --include=*.go"

scan_pattern "HIGH" "Crypto" "SHA1 usage for security" \
    '(?:hashlib\.sha1|SHA1\.Create|MessageDigest.*SHA-1|crypto\.createHash\s*\(\s*['"'"'"]sha1)' \
    "--include=*.py --include=*.js --include=*.ts --include=*.java --include=*.cs"

scan_pattern "HIGH" "Crypto" "Math.random() for security-sensitive operations" \
    'Math\.random\s*\(\s*\)' \
    "--include=*.js --include=*.ts"

scan_pattern "HIGH" "Crypto" "random module for security (Python)" \
    'import random[^_]|from random import' \
    "--include=*.py"

scan_pattern "CRITICAL" "Crypto" "TLS certificate verification disabled" \
    '(?:verify\s*=\s*False|rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['"'"'"]0|InsecureSkipVerify\s*:\s*true)' \
    "--include=*.py --include=*.js --include=*.ts --include=*.go"

# ═══════════════════════════════════════════════
# PATH TRAVERSAL
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Path Traversal (CWE-22) ──${NC}"

scan_pattern "HIGH" "PathTrav" "Potential path traversal in file operations (JS)" \
    '(?:readFile|writeFile|createReadStream|readFileSync)\s*\(\s*(?:req\.|params\.|query\.|body\.)' \
    "--include=*.js --include=*.ts"

scan_pattern "HIGH" "PathTrav" "Potential path traversal in file operations (Python)" \
    '(?:open|Path)\s*\(\s*(?:request\.|form\.|args\.)' \
    "--include=*.py"

# ═══════════════════════════════════════════════
# SSRF
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── SSRF (CWE-918) ──${NC}"

scan_pattern "HIGH" "SSRF" "HTTP request with user-controlled URL (Python)" \
    '(?:requests\.get|requests\.post|urllib\.request\.urlopen|httpx\.\w+)\s*\(\s*(?:request\.|form\.|args\.|data\.)' \
    "--include=*.py"

scan_pattern "HIGH" "SSRF" "fetch/axios with user-controlled URL (JS)" \
    '(?:fetch|axios\.\w+|http\.get|https\.get)\s*\(\s*(?:req\.|params\.|query\.|body\.)' \
    "--include=*.js --include=*.ts"

# ═══════════════════════════════════════════════
# XXE
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── XML External Entity (CWE-611) ──${NC}"

scan_pattern "HIGH" "XXE" "XML parsing without entity restriction (Python)" \
    '(?:etree\.parse|minidom\.parse|sax\.parse|xml\.dom\.minidom\.parseString)\s*\(' \
    "--include=*.py"

scan_pattern "HIGH" "XXE" "XML parsing without safe factory (Java)" \
    'DocumentBuilderFactory\.newInstance\s*\(' \
    "--include=*.java"

# ═══════════════════════════════════════════════
# ERROR HANDLING / INFO DISCLOSURE
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── Information Disclosure (CWE-209) ──${NC}"

scan_pattern "MEDIUM" "InfoDisc" "Stack trace sent in response" \
    '(?:res\.(?:send|json|write)\s*\(\s*(?:err|error)\.(?:stack|message)|traceback\.format_exc)' \
    "--include=*.js --include=*.ts --include=*.py"

scan_pattern "MEDIUM" "InfoDisc" "Debug mode enabled" \
    '(?:DEBUG\s*=\s*True|app\.debug\s*=\s*True|debug:\s*true)' \
    "--include=*.py --include=*.js --include=*.ts --include=*.json --include=*.yaml --include=*.yml"

# ═══════════════════════════════════════════════
# NOSQL INJECTION
# ═══════════════════════════════════════════════
echo -e "\n${CYAN}── NoSQL Injection (CWE-943) ──${NC}"

scan_pattern "HIGH" "NoSQLi" "MongoDB query with direct request body" \
    '\.find\s*\(\s*(?:req\.body|req\.query|req\.params)' \
    "--include=*.js --include=*.ts"

scan_pattern "HIGH" "NoSQLi" "MongoDB where clause with user input" \
    '\$where.*(?:req\.|params\.|query\.|body\.)' \
    "--include=*.js --include=*.ts"

# ═══════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════
echo -e "\n=== Summary ==="
if [ $FINDING_COUNT -eq 0 ]; then
    echo -e "${GREEN}No vulnerability patterns detected.${NC}"
else
    echo -e "${RED}Found $FINDING_COUNT potential vulnerability patterns.${NC}"
    echo "Each finding requires manual review to confirm exploitability."
fi
echo "Note: This is pattern-based scanning. It catches common cases but cannot"
echo "replace data-flow analysis or dynamic testing."
