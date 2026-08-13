package ratelimit

import (
	"math"
	"math/rand"
	"sync"
	"time"
)

// TokenBucket implements a per-domain token bucket rate limiter.
// Each domain gets its own bucket with independent rate and burst limits.
// This is the Go equivalent of the Python PerDomainRateLimiter.
type TokenBucket struct {
	refillRate float64 // tokens per second
	maxBurst   int
	tokens     float64
	lastRefill time.Time
	mu         sync.Mutex
}

// NewTokenBucket creates a token bucket with the given rate and burst.
func NewTokenBucket(refillRate float64, maxBurst int) *TokenBucket {
	return &TokenBucket{
		refillRate: refillRate,
		maxBurst:   maxBurst,
		tokens:     float64(maxBurst),
		lastRefill: time.Now(),
	}
}

// Acquire acquires a token, returning the wait time in seconds.
func (tb *TokenBucket) Acquire() float64 {
	tb.mu.Lock()
	defer tb.mu.Unlock()

	now := time.Now()
	elapsed := now.Sub(tb.lastRefill).Seconds()

	// Refill tokens
	tb.tokens = math.Min(float64(tb.maxBurst), tb.tokens+elapsed*tb.refillRate)
	tb.lastRefill = now

	if tb.tokens >= 1.0 {
		tb.tokens -= 1.0
		return 0
	}

	// Wait for next token
	wait := (1.0 - tb.tokens) / tb.refillRate
	tb.tokens = 0
	return wait
}

// DomainRateLimiter maintains independent token buckets per domain.
type DomainRateLimiter struct {
	buckets     map[string]*TokenBucket
	customRates map[string]float64
	defaultRate float64
	maxBurst    int
	mu          sync.RWMutex
}

// NewDomainRateLimiter creates a per-domain rate limiter.
func NewDomainRateLimiter(defaultRate float64, maxBurst int, customRates map[string]float64) *DomainRateLimiter {
	return &DomainRateLimiter{
		buckets:     make(map[string]*TokenBucket),
		customRates: customRates,
		defaultRate: defaultRate,
		maxBurst:    maxBurst,
	}
}

// Wait blocks until a token is available for the given domain.
// Adds jitter to prevent synchronized access at scale.
func (dl *DomainRateLimiter) Wait(domain string) {
	dl.mu.RLock()
	bucket, ok := dl.buckets[domain]
	dl.mu.RUnlock()

	if !ok {
		dl.mu.Lock()
		// Double-check after acquiring write lock
		bucket, ok = dl.buckets[domain]
		if !ok {
			rate := dl.defaultRate
			if r, found := dl.customRates[domain]; found {
				rate = r
			}
			bucket = NewTokenBucket(rate, dl.maxBurst)
			dl.buckets[domain] = bucket
		}
		dl.mu.Unlock()
	}

	wait := bucket.Acquire()
	if wait > 0 {
		// Add ±20% jitter to prevent thundering herd
		jittered := wait * (1.0 + rand.Float64()*0.4 - 0.2)
		if jittered > 0 {
			time.Sleep(time.Duration(jittered * float64(time.Second)))
		}
	}
}

// ExtractDomain extracts domain from a URL string.
func ExtractDomain(urlStr string) string {
	// Simple domain extraction
	start := 0
	if after, ok := stringsCutPrefix(urlStr, "https://"); ok {
		start = len("https://")
		urlStr = after
	} else if after, ok := stringsCutPrefix(urlStr, "http://"); ok {
		start = len("http://")
		urlStr = after
	} else {
		return urlStr
	}
	_ = start

	// Take up to first /
	end := len(urlStr)
	for i, ch := range urlStr {
		if ch == '/' || ch == ':' {
			end = i
			break
		}
	}
	domain := urlStr[:end]

	// Remove www.
	if len(domain) > 4 && domain[:4] == "www." {
		domain = domain[4:]
	}

	return domain
}

func stringsCutPrefix(s, prefix string) (string, bool) {
	if len(s) >= len(prefix) && s[:len(prefix)] == prefix {
		return s[len(prefix):], true
	}
	return s, false
}

// FullJitterBackoff computes retry delay using full jitter algorithm.
// delay = random(0, min(base * 2^attempt, maxDelay))
// This is the AWS-recommended approach that prevents coordinated retry storms.
func FullJitterBackoff(attempt int, base, maxDelay time.Duration) time.Duration {
	exponential := base
	for i := 1; i < attempt; i++ {
		exponential *= 2
	}
	if exponential > maxDelay {
		exponential = maxDelay
	}
	return time.Duration(rand.Int63n(int64(exponential)))
}
