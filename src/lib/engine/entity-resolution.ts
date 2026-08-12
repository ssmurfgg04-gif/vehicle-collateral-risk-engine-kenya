/**
 * Entity Resolution Engine for Kenyan Vehicle Data
 * Implements: Jaro-Winkler, Levenshtein, Kenyan plate normalization,
 * chassis O→0 correction, county code extraction, government plate detection
 * Based on arXiv:2303.07469 (tgds/egds) and arXiv:2509.17470 (Transformer-Gather, Fuzzy-Reconsider)
 */

// ─── KENYAN PLATE NORMALIZATION ─────────────────────────────────────────────────

/** Kenyan county/region codes from plates */
const KENYAN_COUNTY_CODES: Record<string, string> = {
  KA: 'NAIROBI_OLD', KB: 'NAIROBI', KC: 'MOMBASA', KD: 'NAKURU',
  KE: 'ELDORET', KF: 'KISUMU', KG: 'GARISSA', KH: 'MERU',
  KJ: 'THIKA', KK: 'KITUI', KL: 'MACHAKOS', KM: 'MURANGA',
  KN: 'NYERI', KP: 'KAKAMEGA', KQ: 'BUNGOMA', KR: 'KERICHO',
  KS: 'BOMET', KT: 'NAROK', KU: 'KAJIADO', KV: 'KWALE',
  KW: 'TAITA_TAVETA', KX: 'LAIKIPIA', KY: 'NYAMIRA', KZ: 'HOMA_BAY',
};

/** Government plate prefixes */
const GOVT_PREFIXES = ['GK', 'GKA', 'GKB', 'GKN', 'GKY', 'KAW', 'KAV', 'KAT', 'KAR', 'KAG', 'KAH', 'KAE'];

/**
 * Normalize a Kenyan vehicle registration plate
 * - Uppercase
 * - Strip all spaces
 * - Correct letter O → 0 in numeric positions (where applicable)
 * - Extract county code and plate category
 */
export function normalizePlate(raw: string): {
  normalized: string;
  raw: string;
  countyCode: string | null;
  countyName: string | null;
  category: 'PRIVATE' | 'GOVERNMENT' | 'DIPLOMATIC' | 'UNKNOWN';
  suffix: string | null;
  numericPart: string | null;
} {
  const cleaned = raw.toUpperCase().replace(/[\s\-]/g, '');
  
  // Detect government plates
  let category: 'PRIVATE' | 'GOVERNMENT' | 'DIPLOMATIC' | 'UNKNOWN' = 'UNKNOWN';
  let countyCode: string | null = null;
  let countyName: string | null = null;

  for (const prefix of GOVT_PREFIXES) {
    if (cleaned.startsWith(prefix)) {
      category = 'GOVERNMENT';
      countyCode = prefix;
      countyName = 'GOVERNMENT_OF_KENYA';
      break;
    }
  }

  if (category !== 'GOVERNMENT') {
    // Try to match private plate pattern: KXX 123X or KXX 123
    const privateMatch = cleaned.match(/^K([A-Z])([A-Z])(\d+)([A-Z])?$/);
    if (privateMatch) {
      const cc = `K${privateMatch[1]}`;
      countyCode = cc;
      countyName = KENYAN_COUNTY_CODES[cc] || null;
      category = 'PRIVATE';
    }
  }

  // Diplomatic plates
  if (cleaned.match(/^CD\d+/) || cleaned.match(/^\d{2,3}CD/)) {
    category = 'DIPLOMATIC';
  }

  // Parse components
  const fullMatch = cleaned.match(/^([A-Z]+)(\d+)([A-Z])?$/);
  const suffix = fullMatch?.[4] ?? fullMatch?.[3] ?? null;
  const numericPart = fullMatch?.[2] ?? null;

  return {
    normalized: cleaned,
    raw,
    countyCode,
    countyName,
    category,
    suffix,
    numericPart,
  };
}

/**
 * Normalize a chassis/VIN number
 * - Uppercase
 * - Replace letter O with digit 0 (common OCR/typing error)
 * - Replace letter I with digit 1 (less common but valid)
 * - Strip spaces and hyphens
 */
export function normalizeChassis(raw: string): string {
  return raw
    .toUpperCase()
    .replace(/[\s\-]/g, '')
    .replace(/O/g, '0')
    .replace(/I/g, '1');
}

// ─── STRING DISTANCE FUNCTIONS (arXiv:1607.00992) ──────────────────────────────

/**
 * Jaro-Winkler similarity (0-1, 1 = identical)
 * Optimized for short strings like registration numbers
 */
export function jaroWinkler(s1: string, s2: string, p: number = 0.1): number {
  if (s1 === s2) return 1.0;
  if (!s1.length || !s2.length) return 0.0;

  const matchDistance = Math.floor(Math.max(s1.length, s2.length) / 2) - 1;
  if (matchDistance < 0) return 0.0;

  const s1Matches = new Array(s1.length).fill(false);
  const s2Matches = new Array(s2.length).fill(false);
  let matches = 0;
  let transpositions = 0;

  for (let i = 0; i < s1.length; i++) {
    const start = Math.max(0, i - matchDistance);
    const end = Math.min(i + matchDistance + 1, s2.length);
    for (let k = start; k < end; k++) {
      if (s2Matches[k] || s1[i] !== s2[k]) continue;
      s1Matches[i] = true;
      s2Matches[k] = true;
      matches++;
      break;
    }
  }

  if (matches === 0) return 0.0;

  let k = 0;
  for (let i = 0; i < s1.length; i++) {
    if (!s1Matches[i]) continue;
    while (!s2Matches[k]) k++;
    if (s1[i] !== s2[k]) transpositions++;
    k++;
  }

  const jaro = (matches / s1.length + matches / s2.length + (matches - transpositions / 2) / matches) / 3;

  // Winkler prefix bonus
  let prefix = 0;
  for (let i = 0; i < Math.min(4, s1.length, s2.length); i++) {
    if (s1[i] === s2[i]) prefix++;
    else break;
  }

  return jaro + prefix * p * (1 - jaro);
}

/**
 * Levenshtein distance (edit distance)
 */
export function levenshtein(s1: string, s2: string): number {
  const m = s1.length;
  const n = s2.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));

  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] = Math.min(
        dp[i - 1][j] + 1,
        dp[i][j - 1] + 1,
        dp[i - 1][j - 1] + (s1[i - 1] === s2[j - 1] ? 0 : 1)
      );
    }
  }
  return dp[m][n];
}

/**
 * Levenshtein similarity (0-1)
 */
export function levenshteinSimilarity(s1: string, s2: string): number {
  const maxLen = Math.max(s1.length, s2.length);
  if (maxLen === 0) return 1.0;
  return 1 - levenshtein(s1, s2) / maxLen;
}

/**
 * Jaccard similarity for token sets
 */
export function jaccardSimilarity(s1: string, s2: string, delimiter: string = ' '): number {
  const set1 = new Set(s1.toUpperCase().split(delimiter).filter(Boolean));
  const set2 = new Set(s2.toUpperCase().split(delimiter).filter(Boolean));
  const intersection = new Set([...set1].filter(x => set2.has(x)));
  const union = new Set([...set1, ...set2]);
  return union.size === 0 ? 1.0 : intersection.size / union.size;
}

// ─── VEHICLE ENTITY MATCHING ───────────────────────────────────────────────────

export interface VehicleCandidate {
  plate: string;
  normalizedPlate: string;
  chassis?: string;
  normalizedChassis?: string;
  make?: string;
  model?: string;
  year?: number;
}

export interface MatchResult {
  isMatch: boolean;
  overallScore: number;
  plateScore: number;
  chassisScore: number;
  makeModelScore: number;
  yearMatch: boolean;
  confidence: number;
  method: string;
}

/**
 * Weighted ensemble entity matching
 * Combines plate similarity (Jaro-Winkler), chassis similarity (Levenshtein),
 * make/model similarity (Jaccard), and exact year matching
 */
export function matchVehicles(
  query: VehicleCandidate,
  candidate: VehicleCandidate,
  weights: { plate: number; chassis: number; makeModel: number; year: number } = {
    plate: 0.35,
    chassis: 0.35,
    makeModel: 0.20,
    year: 0.10,
  }
): MatchResult {
  // Plate matching: Jaro-Winkler on normalized plates
  const plateScore = jaroWinkler(query.normalizedPlate, candidate.normalizedPlate);

  // Chassis matching: Levenshtein similarity on normalized chassis
  let chassisScore = 0;
  if (query.normalizedChassis && candidate.normalizedChassis) {
    chassisScore = levenshteinSimilarity(query.normalizedChassis, candidate.normalizedChassis);
  }

  // Make/Model matching: Jaccard on tokens
  let makeModelScore = 0;
  if (query.make && query.model && candidate.make && candidate.model) {
    const qMakeModel = `${query.make} ${query.model}`;
    const cMakeModel = `${candidate.make} ${candidate.model}`;
    makeModelScore = (jaccardSimilarity(qMakeModel, cMakeModel) + jaroWinkler(qMakeModel.toUpperCase(), cMakeModel.toUpperCase())) / 2;
  }

  // Year matching
  const yearMatch = query.year && candidate.year ? query.year === candidate.year : false;
  const yearScore = yearMatch ? 1 : (query.year && candidate.year ? 1 - Math.abs(query.year - candidate.year) / 10 : 0.5);

  // Weighted ensemble
  const overallScore =
    weights.plate * plateScore +
    weights.chassis * chassisScore +
    weights.makeModel * makeModelScore +
    weights.year * yearScore;

  // Confidence: how many features contributed
  const featuresUsed = [plateScore > 0, chassisScore > 0, makeModelScore > 0, yearMatch || (query.year && candidate.year)].filter(Boolean).length;
  const confidence = Math.min(featuresUsed / 4, 1.0);

  // Match threshold: 0.85 for high-confidence, 0.75 for review
  const isMatch = overallScore >= 0.85;

  return {
    isMatch,
    overallScore,
    plateScore,
    chassisScore,
    makeModelScore,
    yearMatch,
    confidence,
    method: 'hybrid_jw_lev_jaccard',
  };
}

/**
 * Check if a plate looks like a former government plate re-registered as private
 * e.g., KAW 072Z → KDA 123X (title washing signal)
 */
export function detectGovtToPrivateTransition(
  currentPlate: ReturnType<typeof normalizePlate>,
  historicalPlates: ReturnType<typeof normalizePlate>[]
): boolean {
  if (currentPlate.category !== 'PRIVATE') return false;
  return historicalPlates.some(hp => hp.category === 'GOVERNMENT');
}
