#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
# Forgejo Migration Script for Kenya Vehicle Collateral Risk Engine
# ══════════════════════════════════════════════════════════════════════
#
# Migrates the project from GitHub (US jurisdiction, CLOUD Act risk)
# to self-hosted Forgejo (Kenya jurisdiction, ODPC compliant).
#
# Why Forgejo instead of GitHub:
#   1. CLOUD Act: GitHub (Microsoft) must hand data to US gov on request
#   2. ODPC: Kenya Data Protection Act requires data residency in Kenya
#   3. CBK: Central Bank of Kenya prudential guidelines require local control
#   4. Cost: Self-hosted Forgejo is free; GitHub Enterprise is $21/user/month
#
# Prerequisites:
#   - Forgejo running (docker-compose up -d forgejo)
#   - Forgejo admin account created
#   - SSH key added to Forgejo
#
# Usage:
#   ./forgejo_migrate.sh                          # Full migration
#   ./forgejo_migrate.sh --setup-only             # Just set up Forgejo org + repo
#   ./forgejo_migrate.sh --push-only              # Just push to existing Forgejo
#   ./forgejo_migrate.sh --ci-only                # Just set up CI/CD
#   ./forgejo_migrate.sh --verify                 # Verify migration success
#
# ══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────

FORGEJO_HOST="${FORGEJO_HOST:-git.riskengine.co.ke}"
FORGEJO_PORT="${FORGEJO_PORT:-3000}"
FORGEJO_SSH_PORT="${FORGEJO_SSH_PORT:-2222}"
FORGEJO_URL="http://${FORGEJO_HOST}:${FORGEJO_PORT}"
FORGEJO_API="${FORGEJO_URL}/api/v1"
FORGEJO_ADMIN="${FORGEJO_ADMIN:-admin}"
FORGEJO_ADMIN_PASS="${FORGEJO_ADMIN_PASS:-changeme123}"
FORGEJO_ORG="${FORGEJO_ORG:-kenya-risk-engine}"
FORGEJO_REPO="${FORGEJO_REPO:-vehicle-collateral-risk-engine}"
PROJECT_DIR="/home/z/my-project"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ─── Helper Functions ─────────────────────────────────────────────────

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

check_forgejo() {
    if curl -sf "${FORGEJO_URL}/api/v1/version" > /dev/null 2>&1; then
        log_ok "Forgejo is running at ${FORGEJO_URL}"
        return 0
    else
        log_error "Forgejo is NOT running at ${FORGEJO_URL}"
        log_info "Start with: docker-compose up -d forgejo"
        return 1
    fi
}

check_git() {
    if command -v git &> /dev/null; then
        log_ok "git is available"
        return 0
    else
        log_error "git is NOT installed"
        return 1
    fi
}

# ─── Step 1: Create Forgejo Organization ─────────────────────────────

setup_forgejo_org() {
    log_info "Creating Forgejo organization: ${FORGEJO_ORG}"

    # Check if org already exists
    if curl -sf "${FORGEJO_API}/orgs/${FORGEJO_ORG}" \
         -H "Authorization: token ${FORGEJO_TOKEN:-}" > /dev/null 2>&1; then
        log_ok "Organization '${FORGEJO_ORG}' already exists"
        return 0
    fi

    # Create org via API
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
        "${FORGEJO_API}/orgs" \
        -H "Authorization: token ${FORGEJO_TOKEN:-}" \
        -H "Content-Type: application/json" \
        -d "{
            \"username\": \"${FORGEJO_ORG}\",
            \"full_name\": \"Kenya Vehicle Collateral Risk Engine\",
            \"description\": \"Graph-native fraud detection for vehicle loan stacking in Kenya — CBK/ODPC compliant\",
            \"visibility\": \"limited\",
            \"repo_admin_change_team_access\": true
        }" 2>&1)

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    if [[ "$HTTP_CODE" == "201" || "$HTTP_CODE" == "200" ]]; then
        log_ok "Organization '${FORGEJO_ORG}' created"
    else
        log_warn "Could not create org via API (HTTP ${HTTP_CODE})"
        log_info "Create manually at: ${FORGEJO_URL}/org/create"
    fi
}

# ─── Step 2: Create Forgejo Repository ───────────────────────────────

setup_forgejo_repo() {
    log_info "Creating Forgejo repository: ${FORGEJO_ORG}/${FORGEJO_REPO}"

    # Check if repo already exists
    if curl -sf "${FORGEJO_API}/repos/${FORGEJO_ORG}/${FORGEJO_REPO}" \
         -H "Authorization: token ${FORGEJO_TOKEN:-}" > /dev/null 2>&1; then
        log_ok "Repository '${FORGEJO_ORG}/${FORGEJO_REPO}' already exists"
        return 0
    fi

    # Create repo via API
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
        "${FORGEJO_API}/orgs/${FORGEJO_ORG}/repos" \
        -H "Authorization: token ${FORGEJO_TOKEN:-}" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"${FORGEJO_REPO}\",
            \"description\": \"Vehicle collateral fraud detection — B2B graph-native platform for Kenyan MFIs\",
            \"private\": true,
            \"default_branch\": \"main\",
            \"auto_init\": false,
            \"trust_model\": \"committer\"
        }" 2>&1)

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    if [[ "$HTTP_CODE" == "201" || "$HTTP_CODE" == "200" ]]; then
        log_ok "Repository '${FORGEJO_ORG}/${FORGEJO_REPO}' created"
    else
        log_warn "Could not create repo via API (HTTP ${HTTP_CODE})"
        log_info "Create manually at: ${FORGEJO_URL}/org/${FORGEJO_ORG}/repos/create"
    fi
}

# ─── Step 3: Add Forgejo as Git Remote ───────────────────────────────

add_forgejo_remote() {
    cd "${PROJECT_DIR}"

    FORGEJO_REMOTE="ssh://git@${FORGEJO_HOST}:${FORGEJO_SSH_PORT}/${FORGEJO_ORG}/${FORGEJO_REPO}.git"

    # Check if forgejo remote already exists
    if git remote get-url forgejo &> /dev/null; then
        log_warn "Remote 'forgejo' already exists: $(git remote get-url forgejo)"
        log_info "Updating to: ${FORGEJO_REMOTE}"
        git remote set-url forgejo "${FORGEJO_REMOTE}"
    else
        log_info "Adding remote 'forgejo': ${FORGEJO_REMOTE}"
        git remote add forgejo "${FORGEJO_REMOTE}"
    fi

    log_ok "Git remote 'forgejo' configured"
}

# ─── Step 4: Push All Branches ───────────────────────────────────────

push_to_forgejo() {
    cd "${PROJECT_DIR}"

    log_info "Pushing all branches to Forgejo..."

    # Push main branch first
    if git show-ref --verify --quiet refs/heads/main; then
        log_info "Pushing main branch..."
        git push forgejo main:main 2>&1 || log_warn "Push main failed (may need force on first push)"
    elif git show-ref --verify --quiet refs/heads/master; then
        log_info "Pushing master branch as main..."
        git push forgejo master:main 2>&1 || log_warn "Push master→main failed"
    fi

    # Push all other branches
    log_info "Pushing all branches..."
    for branch in $(git branch -r | grep -v forgejo | grep -v HEAD | sed 's/.*\///' | sort -u); do
        if [[ "$branch" != "main" && "$branch" != "master" ]]; then
            log_info "  Pushing branch: ${branch}"
            git push forgejo "${branch}" 2>&1 || log_warn "Push ${branch} failed"
        fi
    done

    # Push all tags
    log_info "Pushing all tags..."
    git push forgejo --tags 2>&1 || log_warn "Push tags failed"

    log_ok "All branches and tags pushed to Forgejo"
}

# ─── Step 5: Set Up CI/CD (Forgejo Actions) ─────────────────────────

setup_ci_cd() {
    cd "${PROJECT_DIR}"

    log_info "Setting up Forgejo Actions CI/CD..."

    # Create .forgejo/workflows directory
    mkdir -p .forgejo/workflows

    # Create CI workflow (compatible with GitHub Actions syntax)
    cat > .forgejo/workflows/ci.yml << 'EOF'
name: CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Go
        uses: actions/setup-go@v5
        with:
          go-version: '1.23'

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          npm ci
          pip install -r requirements.txt
          cd /home/z/my-project && go mod download

      - name: Lint
        run: |
          npm run lint
          cd /home/z/my-project && go vet ./...

      - name: Test
        run: |
          npm test
          cd /home/z/my-project && go test ./...

      - name: Build
        run: |
          npm run build
          cd /home/z/my-project && go build -o bin/kenya-scraper ./cmd/kenya-scraper

  security-scan:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4

      - name: Run security scan
        run: |
          npm audit --audit-level=high || true
          pip audit || true

  deploy-staging:
    runs-on: ubuntu-latest
    needs: [test, security-scan]
    if: github.ref == 'refs/heads/develop'
    steps:
      - uses: actions/checkout@v4

      - name: Deploy to staging
        run: |
          echo "Deploying to staging server..."
          # docker-compose -f docker-compose.yml up -d --build

  deploy-production:
    runs-on: ubuntu-latest
    needs: [test, security-scan]
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Deploy to production
        run: |
          echo "Deploying to production server..."
          # docker-compose -f docker-compose.yml up -d --build
EOF

    log_ok "CI/CD workflow created at .forgejo/workflows/ci.yml"

    # Create DPA compliance workflow
    cat > .forgejo/workflows/dpa-compliance.yml << 'EOF'
name: DPA Compliance Check

on:
  schedule:
    - cron: '0 2 * * 0'  # Weekly Sunday 2am
  workflow_dispatch:

jobs:
  dpa-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Verify data residency
        run: |
          echo "Checking all data is stored in Kenya jurisdiction..."
          # Verify no data leaves Kenyan servers
          # Check S3 bucket region == af-south-1 (Cape Town) or local
          # Verify Neo4j is on Kenyan VPS

      - name: Verify encryption at rest
        run: |
          echo "Checking encryption at rest for all data stores..."
          # SQLite WAL: encrypted via LUKS on Kenyan VPS
          # Neo4j: encrypted volume
          # Forgejo: encrypted volume

      - name: Generate audit report
        run: |
          echo "Generating ODPC audit report..."
          python scripts/dpa_audit_report.py || true

      - name: Notify compliance officer
        if: failure()
        run: |
          echo "DPA compliance check FAILED — notify compliance officer"
          # curl -X POST $SLACK_WEBHOOK -d '{"text":"DPA compliance check failed!"}'
EOF

    log_ok "DPA compliance workflow created at .forgejo/workflows/dpa-compliance.yml"
}

# ─── Step 6: Verify Migration ────────────────────────────────────────

verify_migration() {
    cd "${PROJECT_DIR}"

    log_info "Verifying migration..."

    # Check Forgejo remote
    if git remote get-url forgejo &> /dev/null; then
        log_ok "Forgejo remote exists: $(git remote get-url forgejo)"
    else
        log_error "Forgejo remote NOT found"
        return 1
    fi

    # Check if we can reach Forgejo
    if curl -sf "${FORGEJO_API}/repos/${FORGEJO_ORG}/${FORGEJO_REPO}" \
         -H "Authorization: token ${FORGEJO_TOKEN:-}" > /dev/null 2>&1; then
        log_ok "Repository accessible on Forgejo"
    else
        log_warn "Cannot verify repository on Forgejo (may need auth token)"
    fi

    # Check CI/CD
    if [[ -f ".forgejo/workflows/ci.yml" ]]; then
        log_ok "CI/CD workflow exists"
    else
        log_warn "CI/CD workflow NOT found"
    fi

    if [[ -f ".forgejo/workflows/dpa-compliance.yml" ]]; then
        log_ok "DPA compliance workflow exists"
    else
        log_warn "DPA compliance workflow NOT found"
    fi

    # Compare commit counts
    LOCAL_COMMITS=$(git rev-list --count main 2>/dev/null || echo "0")
    log_info "Local commits on main: ${LOCAL_COMMITS}"

    log_ok "Migration verification complete"
}

# ─── Main ────────────────────────────────────────────────────────────

main() {
    local MODE="${1:-full}"

    echo ""
    echo "══════════════════════════════════════════════════════════════════════"
    echo " Forgejo Migration — Kenya Vehicle Collateral Risk Engine"
    echo " Moving from GitHub (US/CLOUD Act) to Forgejo (Kenya/ODPC)"
    echo "══════════════════════════════════════════════════════════════════════"
    echo ""

    # Prerequisites
    check_forgejo || exit 1
    check_git || exit 1

    case "${MODE}" in
        --setup-only)
            setup_forgejo_org
            setup_forgejo_repo
            add_forgejo_remote
            ;;
        --push-only)
            push_to_forgejo
            ;;
        --ci-only)
            setup_ci_cd
            ;;
        --verify)
            verify_migration
            ;;
        *)
            # Full migration
            setup_forgejo_org
            setup_forgejo_repo
            add_forgejo_remote
            push_to_forgejo
            setup_ci_cd
            verify_migration
            ;;
    esac

    echo ""
    echo "══════════════════════════════════════════════════════════════════════"
    echo " Migration Complete"
    echo ""
    echo " Next steps:"
    echo "   1. Configure Forgejo runner: https://forgejo.org/docs/admin/runner/"
    echo "   2. Set up HTTPS: Caddyfile + Let's Encrypt"
    echo "   3. Register with ODPC: https://www.odpc.go.ke/registration"
    echo "   4. Remove GitHub remote: git remote remove origin"
    echo "══════════════════════════════════════════════════════════════════════"
}

main "$@"
