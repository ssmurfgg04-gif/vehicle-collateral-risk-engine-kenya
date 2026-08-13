package queue

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"go.uber.org/zap"
)

// SQLiteQueue bridges Go scrapers to the Python ingestion pipeline.
// Both Go and Python read/write the same SQLite database, creating
// a zero-config bridge between the two runtimes.
//
// Go writes scraped vehicles → Python reads via dequeue_for_splink()
//
// This is the KEY integration point: Go handles scraping at 10,000+ sites/sec,
// Python handles Splink entity resolution + Neo4j ingestion + XGBoost inference.
type SQLiteQueue struct {
	db   *sql.DB
	path string
	mu   sync.Mutex
	log  *zap.Logger
}

// NewSQLiteQueue creates or opens the shared ingestion queue.
func NewSQLiteQueue(dbPath string) (*SQLiteQueue, error) {
	if dbPath == "" {
		dbPath = os.Getenv("QUEUE_DB_PATH")
		if dbPath == "" {
			dbPath = "/home/z/my-project/data/ingestion_queue.db"
		}
	}

	// Ensure directory exists
	dir := filepath.Dir(dbPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("create queue dir: %w", err)
	}

	db, err := sql.Open("sqlite3", dbPath+"?_journal_mode=WAL&_busy_timeout=5000")
	if err != nil {
		return nil, fmt.Errorf("open queue db: %w", err)
	}

	q := &SQLiteQueue{
		db:   db,
		path: dbPath,
		log:  zap.L().Named("queue"),
	}

	if err := q.initSchema(); err != nil {
		return nil, fmt.Errorf("init schema: %w", err)
	}

	return q, nil
}

func (q *SQLiteQueue) initSchema() error {
	_, err := q.db.Exec(`
		CREATE TABLE IF NOT EXISTS ingestion_queue (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			payload TEXT NOT NULL,
			status TEXT NOT NULL DEFAULT 'pending',
			source TEXT NOT NULL,
			created_at TEXT NOT NULL,
			resolved_at TEXT,
			ingested_at TEXT,
			error TEXT
		);
		CREATE INDEX IF NOT EXISTS idx_status ON ingestion_queue(status);
		CREATE INDEX IF NOT EXISTS idx_source ON ingestion_queue(source);
		CREATE INDEX IF NOT EXISTS idx_created ON ingestion_queue(created_at);
	`)
	return err
}

// EnqueueVehicle adds a single scraped vehicle to the ingestion queue.
func (q *SQLiteQueue) EnqueueVehicle(vehicle map[string]interface{}, source string) (int64, error) {
	payload, err := json.Marshal(vehicle)
	if err != nil {
		return 0, fmt.Errorf("marshal vehicle: %w", err)
	}

	q.mu.Lock()
	defer q.mu.Unlock()

	result, err := q.db.Exec(
		"INSERT INTO ingestion_queue (payload, status, source, created_at) VALUES (?, 'pending', ?, ?)",
		string(payload), source, time.Now().UTC().Format(time.RFC3339),
	)
	if err != nil {
		return 0, fmt.Errorf("insert queue item: %w", err)
	}

	return result.LastInsertId()
}

// EnqueueBatch adds multiple vehicles to the queue in a single transaction.
// This is 10-50x faster than individual inserts at scale.
func (q *SQLiteQueue) EnqueueBatch(vehicles []map[string]interface{}, source string) (int, error) {
	q.mu.Lock()
	defer q.mu.Unlock()

	tx, err := q.db.Begin()
	if err != nil {
		return 0, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	stmt, err := tx.Prepare(
		"INSERT INTO ingestion_queue (payload, status, source, created_at) VALUES (?, 'pending', ?, ?)",
	)
	if err != nil {
		return 0, fmt.Errorf("prepare stmt: %w", err)
	}
	defer stmt.Close()

	now := time.Now().UTC().Format(time.RFC3339)
	count := 0
	for _, v := range vehicles {
		payload, err := json.Marshal(v)
		if err != nil {
			q.log.Warn("marshal failed", zap.Error(err))
			continue
		}
		if _, err := stmt.Exec(string(payload), source, now); err != nil {
			q.log.Warn("insert failed", zap.Error(err))
			continue
		}
		count++
	}

	if err := tx.Commit(); err != nil {
		return 0, fmt.Errorf("commit tx: %w", err)
	}

	q.log.Info("batch queued", zap.Int("count", count), zap.String("source", source))
	return count, nil
}

// GetStats returns counts by status.
func (q *SQLiteQueue) GetStats() (map[string]int, error) {
	rows, err := q.db.Query("SELECT status, count(*) FROM ingestion_queue GROUP BY status")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	stats := make(map[string]int)
	for rows.Next() {
		var status string
		var cnt int
		if err := rows.Scan(&status, &cnt); err != nil {
			continue
		}
		stats[status] = cnt
	}
	return stats, nil
}

// Close closes the database connection.
func (q *SQLiteQueue) Close() error {
	return q.db.Close()
}
