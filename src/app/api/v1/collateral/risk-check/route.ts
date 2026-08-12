import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { normalizePlate, normalizeChassis, jaroWinkler, levenshteinSimilarity } from '@/lib/engine/entity-resolution';
import { computeRiskScore, type GraphAnalysis } from '@/lib/engine/risk-scoring';

export async function POST(req: NextRequest) {
  const startTime = Date.now();
  
  try {
    const body = await req.json();
    const { query_registration, query_chassis, requestor_mfi_id, borrower_id_hash, loan_amount_kes } = body;

    if (!query_registration) {
      return NextResponse.json({ error: 'query_registration is required' }, { status: 400 });
    }

    const normalizedPlate = normalizePlate(query_registration);
    const normalizedChassis = query_chassis ? normalizeChassis(query_chassis) : null;

    // ─── FIND VEHICLE IN GRAPH ────────────────────────────────────────────────────
    const vehicle = await db.vehicle.findFirst({
      where: { normalizedPlate: normalizedPlate.normalized },
      include: {
        loanApplications: { include: { lender: true, borrower: true } },
        auctionListings: true,
        storageYardStays: { include: { yard: true } },
        flags: true,
        documents: true,
      },
    });

    if (!vehicle) {
      // Vehicle not found — return low risk with "no records" note
      const requestId = `req_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
      return NextResponse.json({
        request_id: requestId,
        query_registration: query_registration,
        risk_score: 15,
        risk_level: 'LOW',
        confidence: 0.5,
        flagged_issues: [],
        entity_summary: {
          normalized_plate: normalizedPlate.normalized,
          plate_category: normalizedPlate.category,
          county: normalizedPlate.countyName,
          vehicle_found: false,
        },
        graph_analysis: { connected_loans: 0, connected_lenders: 0, connected_auctions: 0, fraud_ring_component_size: 0, shortest_path_to_known_fraud: null },
        historical_footprints: [],
        recommendation: 'APPROVE_LOAN',
        compliance_notes: { data_source: 'Public records only. No PII indexed.', odpc_registration: 'DCP-2026-8847', retention_policy: '7_years' },
      });
    }

    // ─── COMPUTE GRAPH ANALYSIS ──────────────────────────────────────────────────
    const activeLoans = vehicle.loanApplications.filter(la => la.status === 'ACTIVE');
    const connectedLenders = new Set(activeLoans.map(la => la.lenderId));
    const activeAuctions = vehicle.auctionListings.filter(al => al.isActive);
    const uniqueYards = new Set(vehicle.storageYardStays.map(s => s.yardId));

    // Temporal velocity: loans in last 30 days
    const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
    const recentLoans = activeLoans.filter(la => la.disbursementDate && la.disbursementDate >= thirtyDaysAgo);

    const graphAnalysis: GraphAnalysis = {
      connectedLoans: activeLoans.length,
      connectedLenders: connectedLenders.size,
      connectedAuctions: activeAuctions.length,
      fraudRingComponentSize: vehicle.fraudRingSize,
      shortestPathToKnownFraud: vehicle.fraudRingSize > 0 ? 2 : null,
      storageYardCount: uniqueYards.size,
      lenderDiversity: connectedLenders.size,
      temporalVelocity: recentLoans.length,
      govtPlateHistory: vehicle.plateCategory === 'GOVERNMENT' || vehicle.flags.some(f => f.flagType === 'GOVERNMENT_PLATE_HISTORY'),
    };

    // ─── COMPUTE RISK SCORE ──────────────────────────────────────────────────────
    const riskResult = computeRiskScore({
      vehicleId: vehicle.id,
      normalizedPlate: vehicle.normalizedPlate,
      normalizedChassis: vehicle.normalizedChassis ?? undefined,
      requestorMfiId: requestor_mfi_id,
      borrowerIdHash: borrower_id_hash,
      loanAmountKes: loan_amount_kes,
      graphAnalysis,
      existingFlags: vehicle.flags.map(f => ({
        type: f.flagType as any,
        severity: f.severity as any,
        description: f.description,
        evidence: f.evidenceIds ? JSON.parse(f.evidenceIds) : [],
        scoreImpact: 0,
      })),
    });

    // ─── BUILD HISTORICAL FOOTPRINTS ─────────────────────────────────────────────
    const historicalFootprints = [];

    for (const listing of vehicle.auctionListings) {
      historicalFootprints.push({
        source_type: listing.sourceType,
        entity: listing.sourceName,
        recorded_date: listing.listingDate?.toISOString().split('T')[0],
        details: `Reserve: KSh ${(listing.reservePriceKes ?? 0).toLocaleString()}. ${listing.basis}.`,
        evidence_url: listing.bidUrl,
        confidence: 1.0,
      });
    }

    for (const doc of vehicle.documents) {
      historicalFootprints.push({
        source_type: doc.docType,
        entity: doc.sourceName,
        recorded_date: doc.publishedDate?.toISOString().split('T')[0],
        details: 'Public record document reference.',
        confidence: doc.confidence,
      });
    }

    for (const loan of activeLoans) {
      historicalFootprints.push({
        source_type: 'MFI_COLLATERAL_PLEDGE',
        entity: loan.lender.name,
        recorded_date: loan.disbursementDate?.toISOString().split('T')[0],
        details: `Logbook pledged for KSh ${loan.loanAmountKes.toLocaleString()} loan. ${loan.caveatRegistered ? 'Caveat registered.' : 'NO caveat registered — loan-stacking window open.'}`,
        confidence: loan.caveatRegistered ? 1.0 : 0.85,
      });
    }

    // ─── PERSIST RISK CHECK ──────────────────────────────────────────────────────
    const requestId = `req_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    const responseTimeMs = Date.now() - startTime;

    await db.riskCheck.create({
      data: {
        requestId,
        vehicleId: vehicle.id,
        queryPlate: query_registration,
        queryChassis: query_chassis,
        requestorMfiId: requestor_mfi_id,
        borrowerIdHash: borrower_id_hash,
        loanAmountKes: loan_amount_kes,
        riskScore: riskResult.riskScore,
        riskLevel: riskResult.riskLevel,
        confidence: riskResult.confidence,
        flaggedIssues: JSON.stringify(riskResult.flaggedIssues.map(f => f.type)),
        graphAnalysis: JSON.stringify(graphAnalysis),
        historicalFootprints: JSON.stringify(historicalFootprints),
        recommendation: riskResult.recommendation,
        responseTimeMs,
      },
    });

    // ─── BUILD RESPONSE ──────────────────────────────────────────────────────────
    return NextResponse.json({
      request_id: requestId,
      query_registration: query_registration,
      risk_score: riskResult.riskScore,
      risk_level: riskResult.riskLevel,
      confidence: riskResult.confidence,
      flagged_issues: riskResult.flaggedIssues.map(f => f.type),
      entity_summary: {
        normalized_plate: vehicle.normalizedPlate,
        vehicle_make: vehicle.make,
        vehicle_model: vehicle.model,
        vehicle_variant: vehicle.variant,
        vehicle_year: vehicle.year,
        chassis_match_confidence: normalizedChassis && vehicle.normalizedChassis ? levenshteinSimilarity(normalizedChassis, vehicle.normalizedChassis) : null,
        normalized_chassis: vehicle.normalizedChassis,
        plate_category: vehicle.plateCategory,
        county: vehicle.countyCode,
      },
      graph_analysis: {
        connected_loans: graphAnalysis.connectedLoans,
        connected_lenders: graphAnalysis.connectedLenders,
        connected_auctions: graphAnalysis.connectedAuctions,
        fraud_ring_component_size: graphAnalysis.fraudRingComponentSize,
        shortest_path_to_known_fraud: graphAnalysis.shortestPathToKnownFraud,
        storage_yard_count: graphAnalysis.storageYardCount,
        temporal_velocity: graphAnalysis.temporalVelocity,
      },
      historical_footprints: historicalFootprints,
      recommendation: riskResult.recommendation,
      score_breakdown: riskResult.scoreBreakdown,
      compliance_notes: {
        data_source: 'Public records only. No PII indexed.',
        odpc_registration: 'DCP-2026-8847',
        retention_policy: '7_years',
        response_time_ms: responseTimeMs,
      },
    });
  } catch (error) {
    console.error('Risk check error:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
