package parser

import (
	"regexp"
	"strings"
	"unicode"
)

// Kenyan plate format: KXX NNNL (e.g., KDA 123J, KCX 387A)
var PlatePattern = regexp.MustCompile(`\b([A-Z][A-Z][A-Z])\s?(\d{1,3})\s?([A-Z]{1,2})\b`)

// ISO 3779 chassis/VIN: 17 chars, no I/O/Q
var ChassisPattern = regexp.MustCompile(`\b([A-HJ-NPR-Z0-9]{17})\b`)

// Kenyan Shilling amounts: KES 1,200,000 / KSh 850,000
var KESPattern = regexp.MustCompile(`(?:KES|KSh|Ksh\.?)\s?([\d,]+)`)

// Government plate prefixes (no disposal doc = high risk)
var GovtPrefixes = []string{"GK", "GKA", "GKB", "GKN", "GKY"}

// Kenyan vehicle makes (ordered by specificity — longest first for regex)
var KenyanMakes = []string{
	"Mercedes-Benz", "Land Rover", "Range Rover", "Ashok Leyland",
	"Mercedes", "Mitsubishi", "Chevrolet", "Volkswagen", "Peugeot",
	"Toyota", "Nissan", "Isuzu", "Honda", "Mazda", "Subaru", "Hyundai",
	"Kia", "Suzuki", "Jeep", "Ford", "Volvo", "Audi", "Daihatsu",
	"Chery", "Lexus", "Porsche", "Tata", "Mahindra", "Scania",
	"Hino", "FAW", "MAN", "Iveco",
}

var listingPattern *regexp.Regexp

func init() {
	// Build alternation pattern from makes
	makesRe := strings.Join(func() []string {
		var escaped []string
		for _, m := range KenyanMakes {
			escaped = append(escaped, regexp.QuoteMeta(m))
		}
		return escaped
	}(), "|")

	listingPattern = regexp.MustCompile(
		`(` + makesRe + `)` +
			`[\s\-]+` +
			`([\w\-/\.]+)` +
			`(?:\s*\((\d{4})\))?`,
	)
}

// NormalizePlate normalizes a Kenyan registration plate with OCR corrections.
// Returns: normalized plate, county code, category (PRIVATE/GOVERNMENT/UNKNOWN)
func NormalizePlate(raw string) (normalized, countyCode, category string) {
	if raw == "" {
		return "", "", "UNKNOWN"
	}

	plate := strings.ToUpper(strings.Map(func(r rune) rune {
		if r == ' ' || r == '-' || r == '.' {
			return -1 // remove
		}
		return r
	}, raw))

	// OCR corrections in numeric positions: O→0, I→1, Q→0
	matches := PlatePattern.FindStringSubmatch(raw)
	county := ""
	if len(matches) >= 4 {
		county = matches[1]
		num := matches[2]
		suffix := matches[3]
		// Fix OCR in numeric part
		numFixed := strings.Map(func(r rune) rune {
			switch r {
			case 'O':
				return '0'
			case 'I':
				return '1'
			case 'Q':
				return '0'
			default:
				return r
			}
		}, num)
		plate = county + numFixed + suffix
	} else if len(plate) >= 2 {
		county = plate[:2]
	}

	// Detect government plates
	cat := "PRIVATE"
	for _, prefix := range GovtPrefixes {
		if strings.HasPrefix(plate, prefix) {
			cat = "GOVERNMENT"
			break
		}
	}

	return plate, county, cat
}

// NormalizeChassis normalizes a chassis/VIN number.
func NormalizeChassis(raw string) string {
	if raw == "" {
		return ""
	}
	ch := strings.ToUpper(raw)
	ch = strings.ReplaceAll(ch, " ", "")
	ch = strings.ReplaceAll(ch, "-", "")
	return ch
}

// ParseKESAmount parses a KES amount from text like "KES 1,200,000".
func ParseKESAmount(text string) *int64 {
	matches := KESPattern.FindStringSubmatch(text)
	if len(matches) < 2 {
		return nil
	}
	clean := strings.ReplaceAll(matches[1], ",", "")
	var val int64
	for _, ch := range clean {
		if !unicode.IsDigit(ch) {
			return nil
		}
		val = val*10 + int64(ch-'0')
	}
	return &val
}

// ParseVehicleFromHTML extracts vehicles from HTML content using regex patterns.
// This is the Go equivalent of the Python parse_vehicle_from_html.
func ParseVehicleFromHTML(html, url, sourceID string) []map[string]interface{} {
	var vehicles []map[string]interface{}
	seenPlates := make(map[string]bool)

	plates := PlatePattern.FindAllStringSubmatch(html, -1)
	chassisMatches := ChassisPattern.FindAllStringSubmatch(html, -1)
	kesMatches := KESPattern.FindAllStringSubmatch(html, -1)
	makeModelMatches := listingPattern.FindAllStringSubmatch(html, -1)

	// Parse KES amounts to int64
	var amountsInt []*int64
	for _, m := range kesMatches {
		if len(m) >= 2 {
			amountsInt = append(amountsInt, ParseKESAmount(m[0]))
		}
	}

	// Strategy 1: Pair plates with make/model/price by position
	for i, plateMatch := range plates {
		county := plateMatch[1]
		num := plateMatch[2]
		suffix := plateMatch[3]
		rawPlate := county + " " + num + suffix

		normalized, countyCode, plateCategory := NormalizePlate(rawPlate)

		if seenPlates[normalized] {
			continue
		}
		seenPlates[normalized] = true

		make := ""
		model := ""
		year := 0
		var price *int64

		if i < len(makeModelMatches) {
			make = strings.Title(makeModelMatches[i][1])
			model = strings.Title(makeModelMatches[i][2])
			if len(makeModelMatches[i]) >= 4 && makeModelMatches[i][3] != "" {
				y := 0
				for _, ch := range makeModelMatches[i][3] {
					y = y*10 + int(ch-'0')
				}
				if y >= 1990 && y <= 2026 {
					year = y
				}
			}
		}

		if i < len(amountsInt) {
			price = amountsInt[i]
		}

		chassis := ""
		normChassis := ""
		if i < len(chassisMatches) {
			chassis = strings.ToUpper(chassisMatches[i][1])
			normChassis = NormalizeChassis(chassis)
		}

		confidence := 0.5
		if rawPlate != "" && make != "" {
			confidence = 0.85
		}

		v := map[string]interface{}{
			"source":             sourceID,
			"raw_plate":          rawPlate,
			"normalized_plate":   normalized,
			"county_code":        countyCode,
			"plate_category":     plateCategory,
			"chassis":            chassis,
			"normalized_chassis": normChassis,
			"make":               make,
			"model":              model,
			"listing_type":       "BANK_REPOSSESSION",
			"listing_url":        url,
			"confidence":         confidence,
		}
		if year > 0 {
			v["year"] = year
		}
		if price != nil {
			v["reserve_price_kes"] = *price
		}

		vehicles = append(vehicles, v)
	}

	return vehicles
}
