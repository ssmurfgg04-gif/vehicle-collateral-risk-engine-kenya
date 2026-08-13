import { NextResponse } from 'next/server';
import { db } from '@/lib/db';

export async function GET() {
  const [
    totalVehicles,
    totalLoanApps,
    totalAuctions,
    totalFraudFlags,
    loanStackingFlags,
    activeAuctions,
    sources,
    recentChecks,
    vehicles,
  ] = await Promise.all([
    db.vehicle.count(),
    db.loanApplication.count(),
    db.auctionListing.count({ where: { isActive: true } }),
    db.fraudFlag.count({ where: { isResolved: false } }),
    db.fraudFlag.count({ where: { flagType: 'LOAN_STACKING_SUSPECT', isResolved: false } }),
    db.auctionListing.count({ where: { isActive: true } }),
    db.scrapingSource.findMany({ where: { isActive: true } }),
    db.riskCheck.findMany({ take: 20, orderBy: { createdAt: 'desc' } }),
    db.vehicle.findMany({
      include: {
        loanApplications: { include: { lender: true } },
        auctionListings: { where: { isActive: true } },
        flags: { where: { isResolved: false } },
        storageYardStays: { include: { yard: true }, where: { isCurrent: true } },
      },
      orderBy: { degreeCentrality: 'desc' },
      take: 15,
    }),
  ]);

  // Compute avg risk score from recent checks
  const avgRiskScore = recentChecks.length > 0
    ? recentChecks.reduce((sum, rc) => sum + rc.riskScore, 0) / recentChecks.length
    : 0;

  // Risk level distribution
  const riskDistribution = { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 };
  for (const rc of recentChecks) {
    riskDistribution[rc.riskLevel as keyof typeof riskDistribution]++;
  }

  // Lender exposure map
  const lenderExposure: Record<string, number> = {};
  for (const v of vehicles) {
    for (const la of v.loanApplications) {
      if (la.status === 'ACTIVE') {
        lenderExposure[la.lender.name] = (lenderExposure[la.lender.name] ?? 0) + la.loanAmountKes;
      }
    }
  }

  // Flag type distribution
  const flagTypes: Record<string, number> = {};
  for (const v of vehicles) {
    for (const f of v.flags) {
      flagTypes[f.flagType] = (flagTypes[f.flagType] ?? 0) + 1;
    }
  }

  return NextResponse.json({
    summary: {
      totalVehicles,
      totalLoanApps,
      totalActiveAuctions: activeAuctions,
      totalFraudFlags,
      loanStackingDetections: loanStackingFlags,
      avgRiskScore: Math.round(avgRiskScore * 10) / 10,
      sourcesActive: sources.length,
      riskChecksToday: recentChecks.length,
    },
    riskDistribution,
    lenderExposure,
    flagTypes,
    recentChecks: recentChecks.map(rc => ({
      requestId: rc.requestId,
      queryPlate: rc.queryPlate,
      riskScore: rc.riskScore,
      riskLevel: rc.riskLevel,
      recommendation: rc.recommendation,
      responseTimeMs: rc.responseTimeMs,
      createdAt: rc.createdAt,
    })),
    vehicles: vehicles.map(v => ({
      id: v.id,
      plate: v.normalizedPlate,
      rawPlate: v.rawPlate,
      make: v.make,
      model: v.model,
      year: v.year,
      plateCategory: v.plateCategory,
      activeLoans: v.loanApplications.filter(la => la.status === 'ACTIVE').length,
      lenders: [...new Set(v.loanApplications.filter(la => la.status === 'ACTIVE').map(la => la.lender.name))],
      activeAuctions: v.auctionListings.length,
      fraudFlags: v.flags.map(f => ({ type: f.flagType, severity: f.severity, description: f.description })),
      currentYard: v.storageYardStays[0]?.yard.name ?? null,
      degreeCentrality: v.degreeCentrality,
      fraudRingSize: v.fraudRingSize,
    })),
    sources: sources.map(s => ({
      name: s.name,
      url: s.url,
      category: s.category,
      complexity: s.complexity,
      lastScrapedAt: s.lastScrapedAt,
      lastStatus: s.lastStatus,
      recordsFound: s.recordsFound,
      scrapeIntervalHours: s.scrapeIntervalHours,
    })),
  });
}
