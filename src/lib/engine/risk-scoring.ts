/**
 * Risk Scoring Engine — B2B Vehicle Collateral Risk
 * Implements graph-based fraud detection (loan stacking, auction listing, 
 * government plate history, multi-yard appearances, rapid re-pledge)
 * 
 * ML features modeled after XGBoost on graph features (47 features)
 * Simplified to deterministic rule-based scoring for v1
 */

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type FraudFlagType =
  | 'LOAN_STACKING_SUSPECT'
  | 'ACTIVE_AUCTION_LISTING'
  | 'GOVERNMENT_PLATE_HISTORY'
  | 'MULTIPLE_STORAGE_YARD_APPEARANCES'
  | 'RAPID_RE_PLEDGE'
  | 'CHASSIS_MISMATCH'
  | 'TEMPORAL_VELOCITY_HIGH';

export interface FraudFlag {
  type: FraudFlagType;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  description: string;
  evidence: string[];
  scoreImpact: number;
}

export interface GraphAnalysis {
  connectedLoans: number;
  connectedLenders: number;
  connectedAuctions: number;
  fraudRingComponentSize: number;
  shortestPathToKnownFraud: number | null;
  storageYardCount: number;
  lenderDiversity: number;
  temporalVelocity: number; // new loans per 30 days
  govtPlateHistory: boolean;
}

export interface RiskCheckInput {
  vehicleId?: string;
  normalizedPlate: string;
  normalizedChassis?: string;
  requestorMfiId: string;
  borrowerIdHash?: string;
  loanAmountKes?: number;
  graphAnalysis: GraphAnalysis;
  existingFlags: FraudFlag[];
}

export interface RiskCheckResult {
  riskScore: number; // 0-100
  riskLevel: RiskLevel;
  confidence: number; // 0-1
  flaggedIssues: FraudFlag[];
  recommendation: 'APPROVE_LOAN' | 'REVIEW_MANUALLY' | 'REJECT_LOAN';
  scoreBreakdown: ScoreBreakdown;
}

export interface ScoreBreakdown {
  baseScore: number;
  loanStackingPenalty: number;
  auctionListingPenalty: number;
  govtPlatePenalty: number;
  multiYardPenalty: number;
  temporalVelocityPenalty: number;
  fraudRingPenalty: number;
  chassisMismatchPenalty: number;
}

/**
 * Compute risk score from graph features
 * Base score: 20 (low risk baseline)
 * Each flag adds penalty points
 * Final score clamped to 0-100
 */
export function computeRiskScore(input: RiskCheckInput): RiskCheckResult {
  const flags: FraudFlag[] = [...input.existingFlags];
  const breakdown: ScoreBreakdown = {
    baseScore: 20,
    loanStackingPenalty: 0,
    auctionListingPenalty: 0,
    govtPlatePenalty: 0,
    multiYardPenalty: 0,
    temporalVelocityPenalty: 0,
    fraudRingPenalty: 0,
    chassisMismatchPenalty: 0,
  };

  const ga = input.graphAnalysis;

  // ─── LOAN STACKING DETECTION ─────────────────────────────────────────────────
  // If vehicle has active loans from OTHER lenders, this is the primary fraud signal
  if (ga.connectedLoans > 0 && ga.connectedLenders > 0) {
    const penalty = Math.min(35, ga.connectedLenders * 15 + ga.connectedLoans * 5);
    breakdown.loanStackingPenalty = penalty;
    flags.push({
      type: 'LOAN_STACKING_SUSPECT',
      severity: ga.connectedLenders >= 3 ? 'CRITICAL' : ga.connectedLenders >= 2 ? 'HIGH' : 'MEDIUM',
      description: `Vehicle has ${ga.connectedLoans} active loan(s) from ${ga.connectedLenders} different lender(s). This indicates the same collateral is pledged multiple times across institutions, exploiting the eCitizen caveat registration delay window.`,
      evidence: [`${ga.connectedLoans} active loans`, `${ga.connectedLenders} different lenders`],
      scoreImpact: penalty,
    });
  }

  // ─── ACTIVE AUCTION LISTING ──────────────────────────────────────────────────
  // Vehicle is currently listed for auction — cannot be valid collateral
  if (ga.connectedAuctions > 0) {
    const penalty = Math.min(25, ga.connectedAuctions * 15);
    breakdown.auctionListingPenalty = penalty;
    flags.push({
      type: 'ACTIVE_AUCTION_LISTING',
      severity: 'HIGH',
      description: `Vehicle is currently listed in ${ga.connectedAuctions} active auction(s). A vehicle under repossession/auction cannot serve as valid collateral for a new loan.`,
      evidence: [`${ga.connectedAuctions} active auction listings`],
      scoreImpact: penalty,
    });
  }

  // ─── GOVERNMENT PLATE HISTORY ────────────────────────────────────────────────
  // Former govt vehicle pledged as private MFI collateral within 6 months
  if (ga.govtPlateHistory) {
    breakdown.govtPlatePenalty = 15;
    flags.push({
      type: 'GOVERNMENT_PLATE_HISTORY',
      severity: 'MEDIUM',
      description: 'Vehicle has government plate history (GK/GKA/GKB/KAW series) and is now appearing as private MFI collateral. This may indicate title washing, rapid flipping, or odometer tampering of a former government fleet vehicle.',
      evidence: ['Former government plate detected in historical records'],
      scoreImpact: 15,
    });
  }

  // ─── MULTIPLE STORAGE YARD APPEARANCES ───────────────────────────────────────
  // Listed at multiple yards = rapid flipping or geographic mismatch
  if (ga.storageYardCount > 1) {
    const penalty = Math.min(15, ga.storageYardCount * 5);
    breakdown.multiYardPenalty = penalty;
    flags.push({
      type: 'MULTIPLE_STORAGE_YARD_APPEARANCES',
      severity: ga.storageYardCount >= 3 ? 'HIGH' : 'MEDIUM',
      description: `Vehicle has appeared at ${ga.storageYardCount} different storage yards. Multiple yard appearances indicate rapid repositioning, which may signal geographic fraud (e.g., borrower in Kisumu but vehicle stored in Mombasa).`,
      evidence: [`${ga.storageYardCount} different storage yard locations`],
      scoreImpact: penalty,
    });
  }

  // ─── TEMPORAL VELOCITY (RAPID RE-PLEDGE) ─────────────────────────────────────
  // New loans appearing on same collateral within 30 days
  if (ga.temporalVelocity > 1) {
    const penalty = Math.min(20, ga.temporalVelocity * 8);
    breakdown.temporalVelocityPenalty = penalty;
    flags.push({
      type: 'RAPID_RE_PLEDGE',
      severity: ga.temporalVelocity >= 3 ? 'HIGH' : 'MEDIUM',
      description: `${ga.temporalVelocity} new loan(s) on this collateral within the last 30 days. High temporal velocity is a strong loan-stacking indicator — legitimate borrowers rarely re-pledge the same asset this quickly.`,
      evidence: [`${ga.temporalVelocity} loans in 30 days`],
      scoreImpact: penalty,
    });
  }

  // ─── FRAUD RING (WCC COMPONENT SIZE) ────────────────────────────────────────
  // Connected component size > 3 suggests coordinated fraud ring
  if (ga.fraudRingComponentSize > 3) {
    const penalty = Math.min(15, (ga.fraudRingComponentSize - 3) * 5);
    breakdown.fraudRingPenalty = penalty;
    flags.push({
      type: 'LOAN_STACKING_SUSPECT',
      severity: ga.fraudRingComponentSize >= 6 ? 'CRITICAL' : 'HIGH',
      description: `Vehicle is part of a connected component of ${ga.fraudRingComponentSize} entities, suggesting a coordinated fraud ring. Weakly Connected Components analysis identifies shared infrastructure (phones, devices, guarantors) linking multiple fraudulent applications.`,
      evidence: [`WCC component size: ${ga.fraudRingComponentSize}`],
      scoreImpact: penalty,
    });
  }

  // ─── LENDER DIVERSITY PENALTY ────────────────────────────────────────────────
  // More diverse lenders = more institutions exposed = higher systemic risk
  if (ga.lenderDiversity > 2) {
    breakdown.loanStackingPenalty += Math.min(10, (ga.lenderDiversity - 2) * 5);
  }

  // ─── COMPUTE FINAL SCORE ─────────────────────────────────────────────────────
  const rawScore = breakdown.baseScore
    + breakdown.loanStackingPenalty
    + breakdown.auctionListingPenalty
    + breakdown.govtPlatePenalty
    + breakdown.multiYardPenalty
    + breakdown.temporalVelocityPenalty
    + breakdown.fraudRingPenalty
    + breakdown.chassisMismatchPenalty;

  const riskScore = Math.max(0, Math.min(100, rawScore));

  // ─── DETERMINE RISK LEVEL ────────────────────────────────────────────────────
  let riskLevel: RiskLevel;
  if (riskScore >= 80) riskLevel = 'CRITICAL';
  else if (riskScore >= 60) riskLevel = 'HIGH';
  else if (riskScore >= 40) riskLevel = 'MEDIUM';
  else riskLevel = 'LOW';

  // ─── RECOMMENDATION ──────────────────────────────────────────────────────────
  let recommendation: RiskCheckResult['recommendation'];
  if (riskScore >= 75) recommendation = 'REJECT_LOAN';
  else if (riskScore >= 50) recommendation = 'REVIEW_MANUALLY';
  else recommendation = 'APPROVE_LOAN';

  // ─── CONFIDENCE ──────────────────────────────────────────────────────────────
  // Based on graph data completeness
  const dataPoints = [
    ga.connectedLoans > 0 || ga.connectedLoans === 0,
    ga.connectedAuctions >= 0,
    ga.storageYardCount >= 0,
    input.normalizedPlate.length > 0,
  ].filter(Boolean).length;
  const confidence = Math.min(dataPoints / 4, 1.0) * (flags.length > 0 ? 0.95 : 0.85);

  return {
    riskScore,
    riskLevel,
    confidence,
    flaggedIssues: flags,
    recommendation,
    scoreBreakdown: breakdown,
  };
}

/**
 * Format KES amount with commas
 */
export function formatKES(amount: number): string {
  return `KSh ${amount.toLocaleString('en-KE')}`;
}

/**
 * Get risk level color for UI
 */
export function getRiskLevelColor(level: RiskLevel): string {
  switch (level) {
    case 'LOW': return 'text-emerald-600';
    case 'MEDIUM': return 'text-amber-600';
    case 'HIGH': return 'text-orange-600';
    case 'CRITICAL': return 'text-red-600';
  }
}

/**
 * Get risk level badge variant for UI
 */
export function getRiskLevelBadgeVariant(level: RiskLevel): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (level) {
    case 'LOW': return 'secondary';
    case 'MEDIUM': return 'outline';
    case 'HIGH': return 'default';
    case 'CRITICAL': return 'destructive';
  }
}
