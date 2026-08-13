package models

import "time"

// ScrapedVehicle represents a vehicle extracted from a Kenyan auction/listing site.
// This is the canonical data model shared between Go scrapers and Python pipeline.
type ScrapedVehicle struct {
	Source             string  `json:"source"`
	ScrapedAt          string  `json:"scraped_at"`
	RawPlate           string  `json:"raw_plate"`
	NormalizedPlate    string  `json:"normalized_plate"`
	CountyCode         string  `json:"county_code"`
	PlateCategory      string  `json:"plate_category"`
	Chassis            string  `json:"chassis"`
	NormalizedChassis  string  `json:"normalized_chassis"`
	Make               string  `json:"make"`
	Model              string  `json:"model"`
	Year               int     `json:"year,omitempty"`
	ReservePriceKES    *int64  `json:"reserve_price_kes,omitempty"`
	ListingType        string  `json:"listing_type"`
	ListingURL         string  `json:"listing_url"`
	AuctionDate        string  `json:"auction_date,omitempty"`
	Confidence         float64 `json:"confidence"`
}

// QueueItem represents an item in the SQLite ingestion queue.
// Go scrapers write directly to the same queue that Python reads.
type QueueItem struct {
	ID        int64  `db:"id" json:"id"`
	Payload   string `db:"payload" json:"payload"`
	Status    string `db:"status" json:"status"`
	Source    string `db:"source" json:"source"`
	CreatedAt string `db:"created_at" json:"created_at"`
}

// SourceConfig defines a scraping source with its rate limits and pagination.
type SourceConfig struct {
	ID               string        `json:"id"`
	Name             string        `json:"name"`
	BaseURLs         []string      `json:"base_urls"`
	Category         string        `json:"category"`
	Difficulty       string        `json:"difficulty"`
	PaginationPrefix string        `json:"pagination_prefix"`
	MaxPages         int           `json:"max_pages"`
	RateLimit        time.Duration `json:"rate_limit"`
	Country          string        `json:"country"`
	Enabled          bool          `json:"enabled"`
}

// ScrapingResult holds the result from a single source scrape.
type ScrapingResult struct {
	SourceID    string            `json:"source_id"`
	SourceName  string            `json:"source_name"`
	Status      string            `json:"status"`
	Vehicles    []ScrapedVehicle  `json:"vehicles"`
	URLsScraped int               `json:"urls_scraped"`
	URLsFailed  int               `json:"urls_failed"`
	DurationMs  int64             `json:"duration_ms"`
	Errors      []string          `json:"errors"`
}

// FleetMetrics holds Prometheus-style metrics for the scraping fleet.
type FleetMetrics struct {
	RequestsTotal      int            `json:"requests_total"`
	RequestsSuccess    int            `json:"requests_success"`
	RequestsFailed     int            `json:"requests_failed"`
	RequestsRateLimit  int            `json:"requests_rate_limited"`
	VehiclesFound      int            `json:"vehicles_found"`
	VehiclesQueued     int            `json:"vehicles_queued"`
	URLsScraped        int            `json:"urls_scraped"`
	RetryAttempts      int            `json:"retry_attempts"`
	ElapsedMs          int64          `json:"elapsed_ms"`
	PerSourceVehicles  map[string]int `json:"per_source_vehicles"`
}
