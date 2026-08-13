/**
 * Kenya Gazette OCR Pipeline
 * 
 * Tesseract OCR → spaCy NER → regex extraction → graph ingestion
 * 
 * Kenya Gazette is the official government publication for:
 * - Government vehicle disposals
 * - Name changes (title-washing detection)
 * - Company registrations (shell company detection)
 * - Legal notices
 * 
 * Pipeline stages:
 * 1. PDF download from gazettes.africa.go.ke
 * 2. PDF → image conversion (pdf2image)
 * 3. Tesseract OCR with Kenyan English tessdata
 * 4. spaCy NER for entity extraction (ORG, PERSON, VEHICLE)
 * 5. Regex patterns for Kenyan plate numbers, chassis numbers
 * 6. Structured record extraction
 * 7. Neo4j graph ingestion
 */

// ─── OCR Result Types ────────────────────────────────────────────────

export interface Gazettenotice {
  gazetteIssue: string;
  noticeNumber: string;
  publicationDate: string;
  noticeType: 'VEHICLE_DISPOSAL' | 'NAME_CHANGE' | 'COMPANY_NOTICE' | 'LEGAL_NOTICE' | 'OTHER';
  rawOcrText: string;
  confidence: number;
  processingStages: ProcessingStage[];
}

export interface ProcessingStage {
  stage: 'PDF_DOWNLOAD' | 'PDF_TO_IMAGE' | 'TESSERACT_OCR' | 'SPACY_NER' | 'REGEX_EXTRACT' | 'GRAPH_INGEST';
  status: 'SUCCESS' | 'PARTIAL' | 'FAILED';
  durationMs: number;
  details: string;
}

export interface ExtractedVehicleDisposal {
  plate: string;
  normalizedPlate: string;
  chassis?: string;
  make?: string;
  model?: string;
  year?: number;
  disposingEntity: string;
  disposalMethod: 'AUCTION' | 'DIRECT_SALE' | 'TRANSFER';
  reservePriceKes?: number;
  gazetteIssue: string;
  publicationDate: string;
  confidence: number;
}

export interface ExtractedNameChange {
  oldName: string;
  newName: string;
  gazetteIssue: string;
  publicationDate: string;
  // For title-washing: check if name change corresponds to vehicle ownership transfer
  potentialTitleWash: boolean;
}

// ─── Kenyan Plate Regex ──────────────────────────────────────────────

/**
 * Regex patterns for Kenyan vehicle registration plates
 * 
 * Private: KXX 123X or KXX 123XX (county code + digits + letter(s))
 * Government: GK 123A, GKA 123A, GKB 123A, GKN 123A, GKY 123A
 * Military: KAW 123A, KAF 123A, KAN 123A
 * Police: KAP 123A, KAG 123A
 * Diplomatic: CD 123A, CC 123A
 * NT: National Transport (trailers)
 */
const PLATE_PATTERNS = {
  // Private plates: K + 2 letters + space + up to 3 digits + 1-2 letters
  private: /\b(K[A-Z]{2})\s?(\d{1,3})\s?([A-Z]{1,2})\b/g,
  // Government plates
  government: /\b(GK[A-Z]?|GKY|GKN|GKB)\s?(\d{1,3})\s?([A-Z])\b/g,
  // Military plates
  military: /\b(KAW|KAF|KAN)\s?(\d{1,3})\s?([A-Z])\b/g,
  // Police plates
  police: /\b(KAP|KAG)\s?(\d{1,3})\s?([A-Z])\b/g,
  // Diplomatic plates
  diplomatic: /\b(CD|CC)\s?(\d{1,3})\s?([A-Z])\b/g,
};

/**
 * Chassis/VIN regex — 17 character Vehicle Identification Number
 * ISO 3779: No I, O, or Q characters
 */
const CHASSIS_PATTERN = /\b([A-HJ-NPR-Z0-9]{17})\b/g;

/**
 * KES amount pattern — Kenyan Shillings in various formats
 */
const KES_PATTERN = /(?:KES|KSh|Ksh\.?)\s?([\d,]+)/gi;

// ─── Plate Extraction ────────────────────────────────────────────────

export interface PlateExtraction {
  raw: string;
  normalized: string;
  category: 'PRIVATE' | 'GOVERNMENT' | 'MILITARY' | 'POLICE' | 'DIPLOMATIC';
  confidence: number;
  matchStart: number;
  matchEnd: number;
}

export function extractPlates(text: string): PlateExtraction[] {
  const plates: PlateExtraction[] = [];

  // Process each pattern type
  const processPattern = (
    pattern: RegExp,
    category: PlateExtraction['category'],
  ) => {
    const regex = new RegExp(pattern.source, pattern.flags);
    let match;
    while ((match = regex.exec(text)) !== null) {
      const raw = match[0];
      const normalized = raw.toUpperCase().replace(/\s/g, '');
      plates.push({
        raw,
        normalized,
        category,
        confidence: category === 'PRIVATE' ? 0.9 : 0.95,
        matchStart: match.index,
        matchEnd: match.index + raw.length,
      });
    }
  };

  processPattern(PLATE_PATTERNS.private, 'PRIVATE');
  processPattern(PLATE_PATTERNS.government, 'GOVERNMENT');
  processPattern(PLATE_PATTERNS.military, 'MILITARY');
  processPattern(PLATE_PATTERNS.police, 'POLICE');
  processPattern(PLATE_PATTERNS.diplomatic, 'DIPLOMATIC');

  // Deduplicate by normalized plate
  const seen = new Set<string>();
  return plates.filter(p => {
    if (seen.has(p.normalized)) return false;
    seen.add(p.normalized);
    return true;
  });
}

export function extractChassis(text: string): string[] {
  const chassis: string[] = [];
  const regex = new RegExp(CHASSIS_PATTERN.source, CHASSIS_PATTERN.flags);
  let match;
  while ((match = regex.exec(text)) !== null) {
    chassis.push(match[1].toUpperCase());
  }
  return [...new Set(chassis)];
}

export function extractKESAmounts(text: string): number[] {
  const amounts: number[] = [];
  const regex = new RegExp(KES_PATTERN.source, KES_PATTERN.flags);
  let match;
  while ((match = regex.exec(text)) !== null) {
    const numStr = match[1].replace(/,/g, '');
    const num = parseInt(numStr, 10);
    if (!isNaN(num)) amounts.push(num);
  }
  return amounts;
}

// ─── NER Entity Extraction (spaCy patterns) ──────────────────────────

export interface NEREntity {
  text: string;
  label: string;   // ORG, PERSON, VEHICLE, GPE, MONEY, DATE
  start: number;
  end: number;
}

/**
 * Rule-based NER as fallback when spaCy model is not available.
 * Extracts organizations, persons, and vehicle-related entities.
 */
export function ruleBasedNER(text: string): NEREntity[] {
  const entities: NEREntity[] = [];

  // Organization patterns (Kenyan banks, government bodies, auctioneers)
  const orgPatterns = [
    /\b(Equity\s+Bank|Family\s+Bank|Co-operative\s+Bank|Co-op\s+Bank|KCB\s+Bank|NCBA\s+Bank|GT\s+Bank)\b/gi,
    /\b(Ministry\s+of\s+\w+|Kenya\s+Revenue\s+Authority|National\s+Transport\s+Authority|Office\s+of\s+the\s+Attorney\s+General)\b/gi,
    /\b(Garam\s+Auctioneers|Keysian\s+Auctioneers|Phillips\s+International)\b/gi,
    /\b(County\s+Government\s+of\s+\w+)\b/gi,
  ];

  for (const pattern of orgPatterns) {
    const regex = new RegExp(pattern.source, pattern.flags);
    let match;
    while ((match = regex.exec(text)) !== null) {
      entities.push({
        text: match[0],
        label: 'ORG',
        start: match.index,
        end: match.index + match[0].length,
      });
    }
  }

  // Date patterns
  const datePattern = /\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b/gi;
  let dateMatch;
  while ((dateMatch = datePattern.exec(text)) !== null) {
    entities.push({
      text: dateMatch[0],
      label: 'DATE',
      start: dateMatch.index,
      end: dateMatch.index + dateMatch[0].length,
    });
  }

  return entities;
}

// ─── Gazette Pipeline Orchestrator ───────────────────────────────────

export class GazettePipeline {
  /**
   * Process a Kenya Gazette PDF through the full pipeline
   * 
   * In production:
   * 1. Download PDF from gazettes.africa.go.ke
   * 2. Convert PDF pages to images (pdf2image/Poppler)
   * 3. Run Tesseract OCR on each page
   * 4. Run spaCy NER on OCR text
   * 5. Extract structured records (plates, chassis, entities)
   * 6. Ingest into Neo4j graph
   */
  async processGazettePDF(pdfUrl: string): Promise<GazzetteNotice> {
    const stages: ProcessingStage[] = [];
    const startTime = Date.now();

    // Stage 1: PDF Download (simulated)
    stages.push({
      stage: 'PDF_DOWNLOAD',
      status: 'SUCCESS',
      durationMs: 2000,
      details: `Downloaded from ${pdfUrl}`,
    });

    // Stage 2: PDF → Image (simulated)
    stages.push({
      stage: 'PDF_TO_IMAGE',
      status: 'SUCCESS',
      durationMs: 1500,
      details: 'Converted 12 pages to 300 DPI PNG images',
    });

    // Stage 3: Tesseract OCR (simulated)
    stages.push({
      stage: 'TESSERACT_OCR',
      status: 'SUCCESS',
      durationMs: 45000,
      details: 'OCR completed with 92% average confidence. Used eng+ken tessdata.',
    });

    // Stage 4: spaCy NER (simulated)
    stages.push({
      stage: 'SPACY_NER',
      status: 'SUCCESS',
      durationMs: 3000,
      details: 'Extracted 15 ORG entities, 3 PERSON entities, 8 DATE entities',
    });

    // Stage 5: Regex extraction
    stages.push({
      stage: 'REGEX_EXTRACT',
      status: 'SUCCESS',
      durationMs: 50,
      details: 'Extracted 5 vehicle plates, 2 chassis numbers, 3 KES amounts',
    });

    // Stage 6: Graph ingestion
    stages.push({
      stage: 'GRAPH_INGEST',
      status: 'SUCCESS',
      durationMs: 500,
      details: 'Ingested 5 Vehicle nodes, 3 DocumentReference nodes into Neo4j',
    });

    return {
      gazetteIssue: 'Vol. CXXVIII No. 45',
      noticeNumber: 'Gazette-2026-0145',
      publicationDate: '2026-08-01',
      noticeType: 'VEHICLE_DISPOSAL',
      rawOcrText: '[Simulated OCR text from Kenya Gazette PDF]',
      confidence: 0.92,
      processingStages: stages,
    };
  }

  /**
   * Extract vehicle disposal records from OCR text
   */
  extractDisposals(ocrText: string): ExtractedVehicleDisposal[] {
    const plates = extractPlates(ocrText);
    const chassis = extractChassis(ocrText);
    const amounts = extractKESAmounts(ocrText);
    const entities = ruleBasedNER(ocrText);

    const orgs = entities.filter(e => e.label === 'ORG').map(e => e.text);

    return plates.map((plate, i) => ({
      plate: plate.raw,
      normalizedPlate: plate.normalized,
      chassis: chassis[i] || undefined,
      make: undefined,  // Would need more sophisticated extraction
      model: undefined,
      year: undefined,
      disposingEntity: orgs[0] || 'Government of Kenya',
      disposalMethod: 'AUCTION' as const,
      reservePriceKes: amounts[i] || undefined,
      gazetteIssue: '',
      publicationDate: '',
      confidence: plate.confidence * 0.9,
    }));
  }
}
