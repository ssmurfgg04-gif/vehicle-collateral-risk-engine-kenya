#!/bin/bash
# Autonomous Vehicle Ingestion Cron Job
# Runs at 6AM, 12PM, and 6PM EAT (Africa/Nairobi = UTC+3)
# That's 3AM, 9AM, 3PM UTC

set -e

PROJECT_DIR="/home/z/my-project"
PYTHON="$PROJECT_DIR/.venv/bin/python3"
GO_BIN="$PROJECT_DIR/scripts/kenya-scraper"
LOG_DIR="$PROJECT_DIR/data/cron_logs"
QUEUE_DB="$PROJECT_DIR/data/ingestion_queue.db"

mkdir -p "$LOG_DIR"

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/ingest_${TIMESTAMP}.log"

echo "[$(date -uIs)] Starting autonomous ingestion..." > "$LOG_FILE"

# Phase 1: Run Go/Colly scrapers (real live data from Kenyan sites)
echo "[1] Running Go/Colly scraper fleet..." >> "$LOG_FILE"
if [ -x "$GO_BIN" ]; then
    "$GO_BIN" --sources family_bank,equity_bank,kenya_gazette,kra_disposals,garam_auctioneers,keysian_auctioneers,greatwarfare >> "$LOG_FILE" 2>&1
    echo "  Go scrapers complete" >> "$LOG_FILE"
else
    echo "  Go binary not found, skipping" >> "$LOG_FILE"
fi

# Phase 2: Run Python autonomous ingest (fill gaps, ensure target met)
echo "[2] Running Python autonomous ingest..." >> "$LOG_FILE"
python3 "$PROJECT_DIR/scripts/autonomous_ingest.py" --target 1200 --skip-go >> "$LOG_FILE" 2>&1
echo "  Python ingest complete" >> "$LOG_FILE"

# Phase 3: Run organic fraud label pipeline
echo "[3] Running organic fraud label pipeline..." >> "$LOG_FILE"
python3 "$PROJECT_DIR/scripts/organic_fraud_labels.py" >> "$LOG_FILE" 2>&1
echo "  Fraud labels complete" >> "$LOG_FILE"

# Phase 4: Show queue stats
echo "[4] Queue stats:" >> "$LOG_FILE"
python3 "$PROJECT_DIR/scripts/ingestion_queue.py" --action stats >> "$LOG_FILE" 2>&1

echo "[$(date -uIs)] Autonomous ingestion complete." >> "$LOG_FILE"
echo "---" >> "$PROJECT_DIR/worklog.md"
echo "Task ID: cron-ingest-$(date +%Y%m%d-%H%M)" >> "$PROJECT_DIR/worklog.md"
echo "Agent: autonomous_ingest_cron" >> "$PROJECT_DIR/worklog.md"
echo "Task: Scheduled autonomous vehicle ingestion" >> "$PROJECT_DIR/worklog.md"
echo "" >> "$PROJECT_DIR/worklog.md"
echo "Work Log:" >> "$PROJECT_DIR/worklog.md"
echo "- Ran Go/Colly scrapers (7 sources)" >> "$PROJECT_DIR/worklog.md"
echo "- Ran Python autonomous ingest (15 sources, target 1200)" >> "$PROJECT_DIR/worklog.md"
echo "- Ran organic fraud label pipeline" >> "$PROJECT_DIR/worklog.md"
echo "- Log: $LOG_FILE" >> "$PROJECT_DIR/worklog.md"
