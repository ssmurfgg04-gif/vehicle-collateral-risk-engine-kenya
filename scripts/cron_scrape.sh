#!/bin/bash
# Kenya Vehicle Risk Engine — 6-Hour Re-Scraping Cron Job
#
# This script runs every 6 hours to:
#   1. Re-scrape all sources for fresh vehicle data
#   2. Update the plate appearance tracker
#   3. Run loan stacking fraud detection
#   4. Log results for time-series analysis
#
# Set up with: crontab -e
#   0 */6 * * * /home/z/my-project/scripts/cron_scrape.sh >> /home/z/my-project/logs/cron_scrape.log 2>&1
#
# Or run manually: bash /home/z/my-project/scripts/cron_scrape.sh

set -euo pipefail

PROJECT_DIR="/home/z/my-project"
SCRIPTS_DIR="$PROJECT_DIR/scripts"
LOGS_DIR="$PROJECT_DIR/logs"
DATA_DIR="$PROJECT_DIR/data"

mkdir -p "$LOGS_DIR" "$DATA_DIR"

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
LOG_FILE="$LOGS_DIR/scrape_${TIMESTAMP}.log"

echo "══════════════════════════════════════════════════════════" | tee -a "$LOG_FILE"
echo " Kenya Vehicle Risk Engine — Cron Scrape" | tee -a "$LOG_FILE"
echo " Timestamp: $TIMESTAMP (UTC)" | tee -a "$LOG_FILE"
echo "══════════════════════════════════════════════════════════" | tee -a "$LOG_FILE"

# Step 1: Run the real vehicle scraper
echo "" | tee -a "$LOG_FILE"
echo "▶ Step 1: Scraping all sources..." | tee -a "$LOG_FILE"
cd "$PROJECT_DIR"
python3 "$SCRIPTS_DIR/real_vehicle_scraper.py" 2>&1 | tee -a "$LOG_FILE"

# Step 2: Run loan stacking fraud detection
echo "" | tee -a "$LOG_FILE"
echo "▶ Step 2: Running fraud detection..." | tee -a "$LOG_FILE"
python3 "$SCRIPTS_DIR/loan_stacking_detector.py" 2>&1 | tee -a "$LOG_FILE"

# Step 3: Check for new fraud cases and alert
FRAUD_CASES="$DATA_DIR/fraud_cases.json"
if [ -f "$FRAUD_CASES" ]; then
    FRAUD_COUNT=$(python3 -c "import json; print(len(json.load(open('$FRAUD_CASES'))))")
    echo "" | tee -a "$LOG_FILE"
    echo "▶ Step 3: Fraud cases: $FRAUD_COUNT" | tee -a "$LOG_FILE"
    if [ "$FRAUD_COUNT" -gt 0 ]; then
        echo "⚠⚠⚠ NEW FRAUD CASES DETECTED: $FRAUD_COUNT ⚠⚠⚠" | tee -a "$LOG_FILE"
    fi
fi

# Step 4: Summary
QUEUE_COUNT=$(python3 -c "
import sqlite3
db = sqlite3.connect('$DATA_DIR/ingestion_queue.db')
print(db.execute('SELECT COUNT(DISTINCT json_extract(payload, \"$.normalized_plate\")) FROM ingestion_queue').fetchone()[0])
db.close()
")

echo "" | tee -a "$LOG_FILE"
echo "══════════════════════════════════════════════════════════" | tee -a "$LOG_FILE"
echo " Summary: $QUEUE_COUNT unique plates | $FRAUD_COUNT fraud cases" | tee -a "$LOG_FILE"
echo " Next scrape: +6 hours" | tee -a "$LOG_FILE"
echo "══════════════════════════════════════════════════════════" | tee -a "$LOG_FILE"
