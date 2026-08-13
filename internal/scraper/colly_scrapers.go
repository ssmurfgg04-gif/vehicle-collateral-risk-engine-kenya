package scraper

import (
        "fmt"
        "time"

        "github.com/gocolly/colly/v2"
        "github.com/kenya-risk-engine/scraper/internal/models"
        "github.com/kenya-risk-engine/scraper/internal/parser"
        "github.com/kenya-risk-engine/scraper/internal/queue"
        "github.com/kenya-risk-engine/scraper/internal/ratelimit"
        "go.uber.org/zap"
)

// FamilyBankScraper scrapes Family Bank Kenya vehicle repossession listings.
// Colly handles concurrency, rate limiting, and retry automatically.
// On a single core, Colly processes 1000+ pages/sec vs Python's ~200.
type FamilyBankScraper struct {
        c           *colly.Collector
        queue       *queue.SQLiteQueue
        rateLimiter *ratelimit.DomainRateLimiter
        vehicles    []models.ScrapedVehicle
        errors      []string
        log         *zap.Logger
}

var familyBankURLs = []string{
        "https://www.familybank.co.ke/?post_type=vehicles",
        "https://www.familybank.co.ke/?post_type=vehicles&page=2",
        "https://www.familybank.co.ke/?post_type=vehicles&page=3",
        "https://www.familybank.co.ke/vehicle-finance",
        "https://www.familybank.co.ke/vehicle-finance/page/2",
}

// NewFamilyBankScraper creates a Colly-based Family Bank scraper.
func NewFamilyBankScraper(q *queue.SQLiteQueue, rl *ratelimit.DomainRateLimiter) *FamilyBankScraper {
        c := colly.NewCollector(
                colly.UserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
                colly.MaxDepth(1),
                colly.Async(true),
        )

        // Colly's built-in rate limiting — 1 request per 3 seconds for Family Bank
        c.Limit(&colly.LimitRule{
                DomainGlob:  "familybank.co.ke",
                Delay:       3 * time.Second,
                RandomDelay: 1 * time.Second, // Jitter!
        })

        // Retry on rate-limit responses (Colly handles this natively)
        c.OnError(func(r *colly.Response, err error) {
                if r.StatusCode == 429 || r.StatusCode == 503 {
                        // Full jitter backoff
                        delay := ratelimit.FullJitterBackoff(1, 4*time.Second, 60*time.Second)
                        time.Sleep(delay)
                        r.Request.Retry()
                }
        })

        return &FamilyBankScraper{
                c:           c,
                queue:       q,
                rateLimiter: rl,
                log:         zap.L().Named("family_bank"),
        }
}

// Scrape runs the Family Bank scraper and returns all vehicles found.
func (s *FamilyBankScraper) Scrape() *models.ScrapingResult {
        start := time.Now()
        s.vehicles = nil
        s.errors = nil

        // Parse each page as it loads
        s.c.OnResponse(func(r *colly.Response) {
                url := r.Request.URL.String()
                s.log.Info("page fetched", zap.String("url", url), zap.Int("size", len(r.Body)))

                // Use our universal Kenyan vehicle parser
                parsedVehicles := parser.ParseVehicleFromHTML(string(r.Body), url, "family_bank")

                for _, v := range parsedVehicles {
                        normalized, countyCode, plateCategory := parser.NormalizePlate(
                                fmt.Sprintf("%v", v["raw_plate"]),
                        )
                        sv := models.ScrapedVehicle{
                                Source:            "family_bank",
                                ScrapedAt:         time.Now().UTC().Format(time.RFC3339),
                                RawPlate:          fmt.Sprintf("%v", v["raw_plate"]),
                                NormalizedPlate:   normalized,
                                CountyCode:        countyCode,
                                PlateCategory:     plateCategory,
                                Make:              fmt.Sprintf("%v", v["make"]),
                                Model:             fmt.Sprintf("%v", v["model"]),
                                ListingType:       "BANK_REPOSSESSION",
                                ListingURL:        url,
                                Confidence:        0.85,
                        }
                        if ch, ok := v["chassis"].(string); ok {
                                sv.Chassis = ch
                                sv.NormalizedChassis = parser.NormalizeChassis(ch)
                        }
                        if price, ok := v["reserve_price_kes"].(int64); ok {
                                sv.ReservePriceKES = &price
                        }
                        if year, ok := v["year"].(int); ok {
                                sv.Year = year
                        }

                        s.vehicles = append(s.vehicles, sv)
                }

                s.log.Info("page parsed", zap.String("url", url), zap.Int("vehicles", len(parsedVehicles)))

                if len(parsedVehicles) == 0 {
                        s.log.Warn("zero result page", zap.String("url", url))
                }
        })

        // Visit all pages
        for _, url := range familyBankURLs {
                if err := s.c.Visit(url); err != nil {
                        s.errors = append(s.errors, fmt.Sprintf("%s: %v", url, err))
                }
        }

        s.c.Wait() // Wait for all async requests to complete

        duration := time.Since(start)
        status := "SUCCESS"
        if len(s.errors) > 0 {
                status = "PARTIAL"
        }

        result := &models.ScrapingResult{
                SourceID:    "family_bank",
                SourceName:  "Family Bank Kenya",
                Status:      status,
                Vehicles:    s.vehicles,
                URLsScraped: len(familyBankURLs) - len(s.errors),
                URLsFailed:  len(s.errors),
                DurationMs:  duration.Milliseconds(),
                Errors:      s.errors,
        }

        // Queue to SQLite for Python pipeline
        if s.queue != nil && len(s.vehicles) > 0 {
                batch := make([]map[string]interface{}, len(s.vehicles))
                for i, v := range s.vehicles {
                        batch[i] = vehicleToMap(v)
                }
                count, err := s.queue.EnqueueBatch(batch, "family_bank")
                if err != nil {
                        s.log.Error("queue failed", zap.Error(err))
                } else {
                        s.log.Info("vehicles queued", zap.Int("count", count))
                }
        }

        return result
}

// EquityBankScraper scrapes Equity Bank Kenya vehicle listings.
type EquityBankScraper struct {
        c           *colly.Collector
        queue       *queue.SQLiteQueue
        rateLimiter *ratelimit.DomainRateLimiter
        vehicles    []models.ScrapedVehicle
        errors      []string
        log         *zap.Logger
}

var equityBankURLs = []string{
        "https://equitybank.co.ke/vehicle-logbook-loans",
}

// NewEquityBankScraper creates a Colly-based Equity Bank scraper.
func NewEquityBankScraper(q *queue.SQLiteQueue, rl *ratelimit.DomainRateLimiter) *EquityBankScraper {
        c := colly.NewCollector(
                colly.UserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
                colly.Async(true),
        )

        c.Limit(&colly.LimitRule{
                DomainGlob:  "equitybank.co.ke",
                Delay:       3 * time.Second,
                RandomDelay: 1 * time.Second,
        })

        c.OnError(func(r *colly.Response, err error) {
                if r.StatusCode == 429 || r.StatusCode == 503 {
                        delay := ratelimit.FullJitterBackoff(1, 4*time.Second, 60*time.Second)
                        time.Sleep(delay)
                        r.Request.Retry()
                }
        })

        return &EquityBankScraper{
                c:           c,
                queue:       q,
                rateLimiter: rl,
                log:         zap.L().Named("equity_bank"),
        }
}

// Scrape runs the Equity Bank scraper.
func (s *EquityBankScraper) Scrape() *models.ScrapingResult {
        start := time.Now()
        s.vehicles = nil
        s.errors = nil

        s.c.OnResponse(func(r *colly.Response) {
                url := r.Request.URL.String()
                s.log.Info("page fetched", zap.String("url", url), zap.Int("size", len(r.Body)))

                parsedVehicles := parser.ParseVehicleFromHTML(string(r.Body), url, "equity_bank")

                for _, v := range parsedVehicles {
                        normalized, countyCode, plateCategory := parser.NormalizePlate(
                                fmt.Sprintf("%v", v["raw_plate"]),
                        )
                        sv := models.ScrapedVehicle{
                                Source:            "equity_bank",
                                ScrapedAt:         time.Now().UTC().Format(time.RFC3339),
                                RawPlate:          fmt.Sprintf("%v", v["raw_plate"]),
                                NormalizedPlate:   normalized,
                                CountyCode:        countyCode,
                                PlateCategory:     plateCategory,
                                Make:              fmt.Sprintf("%v", v["make"]),
                                Model:             fmt.Sprintf("%v", v["model"]),
                                ListingType:       "BANK_REPOSSESSION",
                                ListingURL:        url,
                                Confidence:        0.85,
                        }
                        s.vehicles = append(s.vehicles, sv)
                }

                s.log.Info("page parsed", zap.String("url", url), zap.Int("vehicles", len(parsedVehicles)))
        })

        for _, url := range equityBankURLs {
                if err := s.c.Visit(url); err != nil {
                        s.errors = append(s.errors, fmt.Sprintf("%s: %v", url, err))
                }
        }

        s.c.Wait()

        duration := time.Since(start)
        status := "SUCCESS"
        if len(s.errors) > 0 {
                status = "PARTIAL"
        }

        result := &models.ScrapingResult{
                SourceID:    "equity_bank",
                SourceName:  "Equity Bank",
                Status:      status,
                Vehicles:    s.vehicles,
                URLsScraped: len(equityBankURLs) - len(s.errors),
                URLsFailed:  len(s.errors),
                DurationMs:  duration.Milliseconds(),
                Errors:      s.errors,
        }

        if s.queue != nil && len(s.vehicles) > 0 {
                batch := make([]map[string]interface{}, len(s.vehicles))
                for i, v := range s.vehicles {
                        batch[i] = vehicleToMap(v)
                }
                count, err := s.queue.EnqueueBatch(batch, "equity_bank")
                if err != nil {
                        s.log.Error("queue failed", zap.Error(err))
                } else {
                        s.log.Info("vehicles queued", zap.Int("count", count))
                }
        }

        return result
}

// KenyaGazetteScraper scrapes Kenya Gazette notices for vehicle repossession notices.
type KenyaGazetteScraper struct {
        c        *colly.Collector
        queue    *queue.SQLiteQueue
        vehicles []models.ScrapedVehicle
        errors   []string
        log      *zap.Logger
}

// NewKenyaGazetteScraper creates a Colly-based Kenya Gazette scraper.
func NewKenyaGazetteScraper(q *queue.SQLiteQueue) *KenyaGazetteScraper {
        c := colly.NewCollector(
                colly.UserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
                colly.Async(true),
        )

        // Government sites need extra politeness
        c.Limit(&colly.LimitRule{
                DomainGlob:  "gazettes.africa",
                Delay:       10 * time.Second,
                RandomDelay: 3 * time.Second,
        })

        // Retry on rate-limit responses (government sites frequently rate-limit)
        c.OnError(func(r *colly.Response, err error) {
                if r.StatusCode == 429 || r.StatusCode == 503 || r.StatusCode == 502 {
                        delay := ratelimit.FullJitterBackoff(1, 8*time.Second, 120*time.Second)
                        time.Sleep(delay)
                        r.Request.Retry()
                }
        })

        return &KenyaGazetteScraper{
                c:     c,
                queue: q,
                log:   zap.L().Named("kenya_gazette"),
        }
}

// Scrape runs the Kenya Gazette scraper.
func (s *KenyaGazetteScraper) Scrape() *models.ScrapingResult {
        start := time.Now()
        s.vehicles = nil
        s.errors = nil

        s.c.OnResponse(func(r *colly.Response) {
                url := r.Request.URL.String()
                parsedVehicles := parser.ParseVehicleFromHTML(string(r.Body), url, "kenya_gazette")

                for _, v := range parsedVehicles {
                        normalized, countyCode, plateCategory := parser.NormalizePlate(
                                fmt.Sprintf("%v", v["raw_plate"]),
                        )
                        sv := models.ScrapedVehicle{
                                Source:            "kenya_gazette",
                                ScrapedAt:         time.Now().UTC().Format(time.RFC3339),
                                RawPlate:          fmt.Sprintf("%v", v["raw_plate"]),
                                NormalizedPlate:   normalized,
                                CountyCode:        countyCode,
                                PlateCategory:     plateCategory,
                                Make:              fmt.Sprintf("%v", v["make"]),
                                Model:             fmt.Sprintf("%v", v["model"]),
                                ListingType:       "GOVERNMENT_GAZETTE",
                                ListingURL:        url,
                                Confidence:        0.7, // Gazette parsing is less reliable
                        }
                        s.vehicles = append(s.vehicles, sv)
                }
        })

        urls := []string{"https://gazettes.africa/go/kenya"}
        for _, url := range urls {
                if err := s.c.Visit(url); err != nil {
                        s.errors = append(s.errors, fmt.Sprintf("%s: %v", url, err))
                }
        }
        s.c.Wait()

        duration := time.Since(start)
        status := "SUCCESS"
        if len(s.errors) > 0 {
                status = "PARTIAL"
        }

        return &models.ScrapingResult{
                SourceID:    "kenya_gazette",
                SourceName:  "Kenya Gazette Notices",
                Status:      status,
                Vehicles:    s.vehicles,
                URLsScraped: len(urls) - len(s.errors),
                URLsFailed:  len(s.errors),
                DurationMs:  duration.Milliseconds(),
                Errors:      s.errors,
        }
}

// KRADisposalsScraper scrapes KRA (Kenya Revenue Authority) government vehicle disposal notices.
// KRA publishes public notices when government vehicles are sold/disposed.
// These vehicles entering the private market are HIGH fraud risk — often no proper
// discharge certificate, creating loan stacking opportunities.
type KRADisposalsScraper struct {
        c        *colly.Collector
        queue    *queue.SQLiteQueue
        vehicles []models.ScrapedVehicle
        errors   []string
        log      *zap.Logger
}

var kraDisposalURLs = []string{
        "https://www.kra.go.ke/public-notices",
        "https://www.kra.go.ke/public-notices/vehicle-disposals",
        "https://www.kra.go.ke/services/customs-and-border-control",
}

// NewKRADisposalsScraper creates a Colly-based KRA government disposal scraper.
func NewKRADisposalsScraper(q *queue.SQLiteQueue) *KRADisposalsScraper {
        c := colly.NewCollector(
                colly.UserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
                colly.Async(true),
                colly.MaxDepth(2), // Follow pagination links on KRA notices
        )

        // Government sites require extra politeness — KRA is especially sensitive
        c.Limit(&colly.LimitRule{
                DomainGlob:  "kra.go.ke",
                Delay:       10 * time.Second,
                RandomDelay: 5 * time.Second, // High jitter for government sites
        })

        // Retry on rate-limit or server errors
        c.OnError(func(r *colly.Response, err error) {
                if r.StatusCode == 429 || r.StatusCode == 503 || r.StatusCode == 502 {
                        delay := ratelimit.FullJitterBackoff(1, 8*time.Second, 120*time.Second)
                        time.Sleep(delay)
                        r.Request.Retry()
                }
        })

        return &KRADisposalsScraper{
                c:     c,
                queue: q,
                log:   zap.L().Named("kra_disposals"),
        }
}

// Scrape runs the KRA government vehicle disposal scraper.
// KRA disposal notices contain:
//   - Government plate numbers (GK, GKA, GKB, GKN, GKY prefixes)
//   - Vehicle make/model/year
//   - Disposal date and reserve price
//   - Discharge certificate status (if available)
func (s *KRADisposalsScraper) Scrape() *models.ScrapingResult {
        start := time.Now()
        s.vehicles = nil
        s.errors = nil

        s.c.OnResponse(func(r *colly.Response) {
                url := r.Request.URL.String()
                s.log.Info("page fetched", zap.String("url", url), zap.Int("size", len(r.Body)))

                parsedVehicles := parser.ParseVehicleFromHTML(string(r.Body), url, "kra_disposals")

                for _, v := range parsedVehicles {
                        normalized, countyCode, plateCategory := parser.NormalizePlate(
                                fmt.Sprintf("%v", v["raw_plate"]),
                        )

                        // All KRA-disposed vehicles are government plates entering private market
                        // This is a STRONG fraud signal — loan stacking risk is high
                        listingType := "GOVERNMENT_DISPOSAL"
                        if plateCategory == "PRIVATE" {
                                // Private plate on KRA disposal page = plate swap detected
                                listingType = "GOVT_PLATE_SWAP_SUSPECT"
                                s.log.Warn("private plate on KRA disposal page",
                                        zap.String("plate", normalized),
                                        zap.String("url", url))
                        }

                        sv := models.ScrapedVehicle{
                                Source:            "kra_disposals",
                                ScrapedAt:         time.Now().UTC().Format(time.RFC3339),
                                RawPlate:          fmt.Sprintf("%v", v["raw_plate"]),
                                NormalizedPlate:   normalized,
                                CountyCode:        countyCode,
                                PlateCategory:     plateCategory,
                                Make:              fmt.Sprintf("%v", v["make"]),
                                Model:             fmt.Sprintf("%v", v["model"]),
                                ListingType:       listingType,
                                ListingURL:        url,
                                Confidence:        0.9, // KRA is authoritative for govt disposals
                        }

                        if ch, ok := v["chassis"].(string); ok {
                                sv.Chassis = ch
                                sv.NormalizedChassis = parser.NormalizeChassis(ch)
                        }
                        if price, ok := v["reserve_price_kes"].(int64); ok {
                                sv.ReservePriceKES = &price
                        }
                        if year, ok := v["year"].(int); ok {
                                sv.Year = year
                        }

                        s.vehicles = append(s.vehicles, sv)
                }

                s.log.Info("page parsed", zap.String("url", url), zap.Int("vehicles", len(parsedVehicles)))
        })

        // Follow pagination links on KRA notice pages
        s.c.OnHTML("a[href]", func(e *colly.HTMLElement) {
                link := e.Attr("href")
                // Only follow pagination and notice detail links
                if e.Request.AbsoluteURL(link) != "" &&
                        (parser.ContainsNoticeLink(link) || parser.ContainsPaginationLink(link)) {
                        e.Request.Visit(link)
                }
        })

        for _, url := range kraDisposalURLs {
                if err := s.c.Visit(url); err != nil {
                        s.errors = append(s.errors, fmt.Sprintf("%s: %v", url, err))
                }
        }

        s.c.Wait()

        duration := time.Since(start)
        status := "SUCCESS"
        if len(s.errors) > 0 {
                status = "PARTIAL"
        }
        if len(s.vehicles) == 0 {
                status = "NO_VEHICLES"
                s.log.Warn("no vehicles found on KRA disposal pages — site may require JS rendering")
        }

        result := &models.ScrapingResult{
                SourceID:    "kra_disposals",
                SourceName:  "KRA Government Disposals",
                Status:      status,
                Vehicles:    s.vehicles,
                URLsScraped: len(kraDisposalURLs) - len(s.errors),
                URLsFailed:  len(s.errors),
                DurationMs:  duration.Milliseconds(),
                Errors:      s.errors,
        }

        if s.queue != nil && len(s.vehicles) > 0 {
                batch := make([]map[string]interface{}, len(s.vehicles))
                for i, v := range s.vehicles {
                        batch[i] = vehicleToMap(v)
                }
                count, err := s.queue.EnqueueBatch(batch, "kra_disposals")
                if err != nil {
                        s.log.Error("queue failed", zap.Error(err))
                } else {
                        s.log.Info("vehicles queued", zap.Int("count", count))
                }
        }

        return result
}

// vehicleToMap converts a ScrapedVehicle to a map for JSON serialization.
func vehicleToMap(v models.ScrapedVehicle) map[string]interface{} {
        m := map[string]interface{}{
                "source":             v.Source,
                "scraped_at":         v.ScrapedAt,
                "raw_plate":          v.RawPlate,
                "normalized_plate":   v.NormalizedPlate,
                "county_code":        v.CountyCode,
                "plate_category":     v.PlateCategory,
                "chassis":            v.Chassis,
                "normalized_chassis": v.NormalizedChassis,
                "make":               v.Make,
                "model":              v.Model,
                "listing_type":       v.ListingType,
                "listing_url":        v.ListingURL,
                "confidence":         v.Confidence,
        }
        if v.Year > 0 {
                m["year"] = v.Year
        }
        if v.ReservePriceKES != nil {
                m["reserve_price_kes"] = *v.ReservePriceKES
        }
        if v.AuctionDate != "" {
                m["auction_date"] = v.AuctionDate
        }
        return m
}
