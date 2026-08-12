/**
 * Seed data: Realistic Kenyan vehicle collateral landscape
 * Includes bank auction listings, MFI collateral records, government disposals,
 * storage yards, and loan-stacking scenarios
 */

import { db } from '@/lib/db';

async function main() {
  console.log('🌱 Seeding Kenyan Vehicle Collateral Risk Engine...');

  // ─── LENDERS ──────────────────────────────────────────────────────────────────
  const familyBank = await db.lender.create({ data: { name: 'Family Bank', type: 'BANK', isRegulated: true, portalUrl: 'https://familybank.co.ke/?post_type=vehicles' } });
  const kcb = await db.lender.create({ data: { name: 'KCB Bank', type: 'BANK', isRegulated: true, portalUrl: 'https://ke.kcbgroup.com/vehicle-bids' } });
  const coopBank = await db.lender.create({ data: { name: 'Co-operative Bank', type: 'BANK', isRegulated: true, portalUrl: 'https://vehiclesales.co-opbank.co.ke' } });
  const ncba = await db.lender.create({ data: { name: 'NCBA', type: 'BANK', isRegulated: true, portalUrl: 'https://carduka.com/auction' } });
  const equity = await db.lender.create({ data: { name: 'Equity Bank', type: 'BANK', isRegulated: true, portalUrl: 'https://equitygroupholdings.com/ke/equity-assets/vehicles/' } });
  const kingdomSacco = await db.lender.create({ data: { name: 'Kingdom SACCO', type: 'SACCO', isRegulated: true } });
  const mhasibuSacco = await db.lender.create({ data: { name: 'Mhasibu SACCO', type: 'SACCO', isRegulated: true } });
  const quickCash = await db.lender.create({ data: { name: 'QuickCash Credit', type: 'MFI', isRegulated: false } });
  const flashCredit = await db.lender.create({ data: { name: 'FlashCredit Kenya', type: 'DCP', isRegulated: false } });

  // ─── BORROWERS (SHA-256 hashes only — no PII) ─────────────────────────────────
  const b1 = await db.borrower.create({ data: { idHash: 'sha256:a3f2b8c9d1e4f5a6b7c8d9e0f1a2b3c4', riskTier: 'HIGH' } });
  const b2 = await db.borrower.create({ data: { idHash: 'sha256:7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3', riskTier: 'MEDIUM' } });
  const b3 = await db.borrower.create({ data: { idHash: 'sha256:c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a', riskTier: 'LOW' } });
  const b4 = await db.borrower.create({ data: { idHash: 'sha256:1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7', riskTier: 'CRITICAL' } });
  const b5 = await db.borrower.create({ data: { idHash: 'sha256:e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c', riskTier: 'UNKNOWN' } });

  // ─── AUCTIONEERS ──────────────────────────────────────────────────────────────
  const garam = await db.auctioneer.create({ data: { name: 'Garam Investments', location: 'Nairobi', phone: '+254720123456', website: 'https://garam.co.ke', specialization: 'BANK_REPOSSESSION' } });
  const keysian = await db.auctioneer.create({ data: { name: 'Keysian Auctioneers', location: 'Cannon House, Haile Selassie Ave, Nairobi', phone: '+254722987654', specialization: 'BANK_REPOSSESSION' } });
  const phillips = await db.auctioneer.create({ data: { name: 'Phillips International', location: 'Kileleshwa, Nairobi', phone: '+254727872478', specialization: 'GOVERNMENT_DISPOSAL' } });

  // ─── STORAGE YARDS ────────────────────────────────────────────────────────────
  const valuersYard = await db.storageYard.create({ data: { name: 'Valuers Yard Enterprises', location: 'Thika Road, Nairobi', county: 'NAIROBI', phone: '+254721636213', latitude: -1.236, longitude: 36.872 } });
  const startruckYard = await db.storageYard.create({ data: { name: 'Startruck Storage Yard', location: 'Thika Road/Kiambu Road', county: 'NAIROBI', phone: '+254721310340', latitude: -1.241, longitude: 36.865 } });
  const eldoretYard = await db.storageYard.create({ data: { name: 'Eldoret Auction Centre', location: 'Eldoret', county: 'UASIN_GISHU', phone: '+254721681905', latitude: 0.514, longitude: 35.270 } });
  const mombasaYard = await db.storageYard.create({ data: { name: 'Mombasa Matriz Moves', location: 'Mombasa', county: 'MOMBASA', phone: '+254720802646', latitude: -4.043, longitude: 39.668 } });
  const greypostsYard = await db.storageYard.create({ data: { name: 'Greyposts Storage Yard', location: 'Kiambu Road, Nairobi', county: 'NAIROBI', phone: '+254708087270' } });

  // ─── VEHICLES (Core dataset with loan stacking scenarios) ─────────────────────

  // SCENARIO 1: Loan Stacking — Same Hilux pledged to 3 lenders
  const v1 = await db.vehicle.create({
    data: {
      normalizedPlate: 'KDA123X', rawPlate: 'KDA 123X', make: 'TOYOTA', model: 'HILUX', variant: 'D/CABIN SR 4WD', year: 2015, color: 'WHITE',
      normalizedChassis: 'JTEBU3JR3B5045181', rawChassis: 'JTEBU3JR3B5045181',
      plateCategory: 'PRIVATE', countyCode: 'KD', degreeCentrality: 3.5, clusteringCoeff: 0.8, fraudRingSize: 5,
    }
  });

  // SCENARIO 2: Government plate re-registered as private
  const v2 = await db.vehicle.create({
    data: {
      normalizedPlate: 'KCA456B', rawPlate: 'KCA 456B', make: 'TOYOTA', model: 'PRADO', variant: 'TXL', year: 2018, color: 'BLACK',
      normalizedChassis: 'JTEBU5JR8J5301234', rawChassis: 'JTEBU5JR8J5301234',
      plateCategory: 'PRIVATE', countyCode: 'KC', degreeCentrality: 1.2, clusteringCoeff: 0.3, fraudRingSize: 1,
    }
  });

  // SCENARIO 3: Active auction listing (repossessed)
  const v3 = await db.vehicle.create({
    data: {
      normalizedPlate: 'KBB789Y', rawPlate: 'KBB 789Y', make: 'NISSAN', model: 'X-TRAIL', variant: 'LE 2WD', year: 2020, color: 'SILVER',
      normalizedChassis: 'JN1TANT31Z0005678', rawChassis: 'JN1TANT31Z0005678',
      plateCategory: 'PRIVATE', countyCode: 'KB', degreeCentrality: 2.0, clusteringCoeff: 0.5, fraudRingSize: 2,
    }
  });

  // SCENARIO 4: Clean vehicle — low risk
  const v4 = await db.vehicle.create({
    data: {
      normalizedPlate: 'KAE321M', rawPlate: 'KAE 321M', make: 'MAZDA', model: 'CX-5', variant: '2.0L SPORT', year: 2022, color: 'RED',
      normalizedChassis: 'JMZKEW11700012345', rawChassis: 'JMZKEW11700012345',
      plateCategory: 'PRIVATE', countyCode: 'KA', degreeCentrality: 0.5, clusteringCoeff: 0.1, fraudRingSize: 0,
    }
  });

  // SCENARIO 5: Multi-yard appearance + rapid re-pledge
  const v5 = await db.vehicle.create({
    data: {
      normalizedPlate: 'KDF654Z', rawPlate: 'KDF 654Z', make: 'ISUZU', model: 'NPR', variant: 'TRUCK 3.0L', year: 2017, color: 'BLUE',
      normalizedChassis: 'JALNTF19R77001234', rawChassis: 'JALNTF19R77001234',
      plateCategory: 'PRIVATE', countyCode: 'KD', degreeCentrality: 2.8, clusteringCoeff: 0.7, fraudRingSize: 4,
    }
  });

  // SCENARIO 6: Former government plate (KAW series)
  const v6 = await db.vehicle.create({
    data: {
      normalizedPlate: 'KAW072Z', rawPlate: 'KAW 072Z', make: 'TOYOTA', model: 'COROLLA', variant: '1.6L GLI', year: 2013, color: 'WHITE',
      normalizedChassis: '1NXBRU4EXDZ000789', rawChassis: '1NXBRU4EXDZ000789',
      plateCategory: 'GOVERNMENT', countyCode: 'KAW', degreeCentrality: 0.8, clusteringCoeff: 0.2, fraudRingSize: 0,
    }
  });

  // More vehicles for the dashboard
  const v7 = await db.vehicle.create({ data: { normalizedPlate: 'KBA111A', rawPlate: 'KBA 111A', make: 'SUBARU', model: 'FORESTER', variant: '2.0I', year: 2019, color: 'GREEN', plateCategory: 'PRIVATE', countyCode: 'KB' } });
  const v8 = await db.vehicle.create({ data: { normalizedPlate: 'KCC222C', rawPlate: 'KCC 222C', make: 'HONDA', model: 'CR-V', variant: '1.5T', year: 2021, color: 'GRAY', plateCategory: 'PRIVATE', countyCode: 'KC' } });
  const v9 = await db.vehicle.create({ data: { normalizedPlate: 'GKA277G', rawPlate: 'GKA 277G', make: 'PEUGEOT', model: '406', variant: '1.8L', year: 2008, color: 'SILVER', plateCategory: 'GOVERNMENT', countyCode: 'GKA' } });
  const v10 = await db.vehicle.create({ data: { normalizedPlate: 'KEE333E', rawPlate: 'KEE 333E', make: 'MITSUBISHI', model: 'PAJERO', variant: '3.0L GLS', year: 2016, color: 'BLACK', plateCategory: 'PRIVATE', countyCode: 'KE' } });

  // ─── LOAN APPLICATIONS ────────────────────────────────────────────────────────

  // V1: Loan stacking — 3 loans from 3 lenders (the killer scenario)
  await db.loanApplication.create({ data: { vehicleId: v1.id, lenderId: familyBank.id, borrowerId: b1.id, loanAmountKes: 800000, status: 'ACTIVE', collateralType: 'LOGBOOK', caveatRegistered: true, caveatDate: new Date('2026-07-01'), disbursementDate: new Date('2026-07-01') } });
  await db.loanApplication.create({ data: { vehicleId: v1.id, lenderId: kingdomSacco.id, borrowerId: b1.id, loanAmountKes: 850000, status: 'ACTIVE', collateralType: 'CHATTELS_MORTGAGE', caveatRegistered: false, disbursementDate: new Date('2026-07-22') } });
  await db.loanApplication.create({ data: { vehicleId: v1.id, lenderId: quickCash.id, borrowerId: b1.id, loanAmountKes: 600000, status: 'ACTIVE', collateralType: 'LOGBOOK', caveatRegistered: false, disbursementDate: new Date('2026-08-05') } });

  // V2: Government plate — 1 loan after govt auction
  await db.loanApplication.create({ data: { vehicleId: v2.id, lenderId: mhasibuSacco.id, borrowerId: b2.id, loanAmountKes: 1200000, status: 'ACTIVE', collateralType: 'DUAL', caveatRegistered: true, caveatDate: new Date('2026-06-15') } });

  // V3: Single loan (being repossessed)
  await db.loanApplication.create({ data: { vehicleId: v3.id, lenderId: kcb.id, borrowerId: b3.id, loanAmountKes: 1500000, status: 'DEFAULTED', collateralType: 'LOGBOOK', caveatRegistered: true, disbursementDate: new Date('2025-06-01') } });

  // V4: Clean — single loan, well-serviced
  await db.loanApplication.create({ data: { vehicleId: v4.id, lenderId: equity.id, borrowerId: b5.id, loanAmountKes: 900000, status: 'ACTIVE', collateralType: 'LOGBOOK', caveatRegistered: true, caveatDate: new Date('2026-05-01'), disbursementDate: new Date('2026-05-01') } });

  // V5: Rapid re-pledge — 2 loans in 30 days
  await db.loanApplication.create({ data: { vehicleId: v5.id, lenderId: flashCredit.id, borrowerId: b4.id, loanAmountKes: 450000, status: 'ACTIVE', collateralType: 'LOGBOOK', caveatRegistered: false, disbursementDate: new Date('2026-07-20') } });
  await db.loanApplication.create({ data: { vehicleId: v5.id, lenderId: quickCash.id, borrowerId: b4.id, loanAmountKes: 350000, status: 'ACTIVE', collateralType: 'LOGBOOK', caveatRegistered: false, disbursementDate: new Date('2026-08-01') } });

  // ─── AUCTION LISTINGS ─────────────────────────────────────────────────────────

  // V1: Listed at Family Bank auction
  await db.auctionListing.create({ data: { vehicleId: v1.id, auctioneerId: garam.id, sourceType: 'BANK_AUCTION', sourceName: 'Family Bank', reservePriceKes: 1900000, auctionDate: new Date('2026-03-11'), listingDate: new Date('2026-03-01'), basis: 'AS_IS_WHERE_IS', bidUrl: 'https://familybank.co.ke/vehicles/toyota-hilux-kda123x', isActive: true } });

  // V3: Active repossession auction
  await db.auctionListing.create({ data: { vehicleId: v3.id, auctioneerId: keysian.id, sourceType: 'BANK_AUCTION', sourceName: 'KCB Bank', reservePriceKes: 1200000, auctionDate: new Date('2026-08-20'), listingDate: new Date('2026-08-01'), isActive: true } });

  // V6: Government disposal
  await db.auctionListing.create({ data: { vehicleId: v6.id, auctioneerId: phillips.id, sourceType: 'KRA_DISPOSAL', sourceName: 'KRA Unserviceable Vehicle Auction', reservePriceKes: 180000, auctionDate: new Date('2024-05-15'), listingDate: new Date('2024-05-01'), isActive: false } });

  // V9: Government vehicle disposal
  await db.auctionListing.create({ data: { vehicleId: v9.id, sourceType: 'GOVERNMENT_DISPOSAL', sourceName: 'ODPP Vehicle Disposal', reservePriceKes: 30000, auctionDate: new Date('2025-11-20'), isActive: false } });

  // ─── STORAGE YARD STAYS ──────────────────────────────────────────────────────
  await db.vehicleYardStay.create({ data: { vehicleId: v1.id, yardId: valuersYard.id, entryDate: new Date('2026-03-01'), isCurrent: true } });
  await db.vehicleYardStay.create({ data: { vehicleId: v3.id, yardId: startruckYard.id, entryDate: new Date('2026-08-01'), isCurrent: true } });
  await db.vehicleYardStay.create({ data: { vehicleId: v5.id, yardId: eldoretYard.id, entryDate: new Date('2026-06-15'), exitDate: new Date('2026-07-10'), isCurrent: false } });
  await db.vehicleYardStay.create({ data: { vehicleId: v5.id, yardId: mombasaYard.id, entryDate: new Date('2026-07-10'), isCurrent: true } });
  await db.vehicleYardStay.create({ data: { vehicleId: v6.id, yardId: greypostsYard.id, entryDate: new Date('2024-05-01'), exitDate: new Date('2024-06-01'), isCurrent: false } });

  // ─── DOCUMENT REFERENCES ─────────────────────────────────────────────────────
  await db.documentReference.create({ data: { vehicleId: v6.id, docType: 'KRA_NOTICE', sourceName: 'KRA Public Notices', publishedDate: new Date('2024-05-01'), confidence: 1.0 } });
  await db.documentReference.create({ data: { vehicleId: v9.id, docType: 'KENYA_GAZETTE', sourceName: 'Kenya Gazette', publishedDate: new Date('2025-11-01'), confidence: 0.9 } });
  await db.documentReference.create({ data: { vehicleId: v1.id, docType: 'BANK_NOTICE', sourceName: 'Family Bank Auction Archive', publishedDate: new Date('2026-03-11'), confidence: 1.0 } });

  // ─── FRAUD FLAGS ──────────────────────────────────────────────────────────────
  await db.fraudFlag.create({ data: { vehicleId: v1.id, flagType: 'LOAN_STACKING_SUSPECT', severity: 'CRITICAL', description: '3 active loans from 3 different lenders on same collateral', evidenceIds: '[]' } });
  await db.fraudFlag.create({ data: { vehicleId: v1.id, flagType: 'ACTIVE_AUCTION_LISTING', severity: 'HIGH', description: 'Listed at Valuers Yard Thika Road auction', evidenceIds: '[]' } });
  await db.fraudFlag.create({ data: { vehicleId: v2.id, flagType: 'GOVERNMENT_PLATE_HISTORY', severity: 'MEDIUM', description: 'Former government plate re-registered as private', evidenceIds: '[]' } });
  await db.fraudFlag.create({ data: { vehicleId: v5.id, flagType: 'MULTIPLE_STORAGE_YARD_APPEARANCES', severity: 'MEDIUM', description: 'Listed at Eldoret and Mombasa yards', evidenceIds: '[]' } });
  await db.fraudFlag.create({ data: { vehicleId: v5.id, flagType: 'RAPID_RE_PLEDGE', severity: 'HIGH', description: '2 new loans within 12 days on same collateral', evidenceIds: '[]' } });

  // ─── SCRAPING SOURCES ─────────────────────────────────────────────────────────
  await db.scrapingSource.create({ data: { name: 'Family Bank Vehicles', url: 'https://familybank.co.ke/?post_type=vehicles', category: 'BANK_PORTAL', complexity: 'LOW', lastScrapedAt: new Date(), lastStatus: 'SUCCESS', recordsFound: 37, scrapeIntervalHours: 6 } });
  await db.scrapingSource.create({ data: { name: 'Equity Bank Assets', url: 'https://equitygroupholdings.com/ke/equity-assets/vehicles/', category: 'BANK_PORTAL', complexity: 'LOW', lastScrapedAt: new Date(), lastStatus: 'SUCCESS', recordsFound: 15, scrapeIntervalHours: 6 } });
  await db.scrapingSource.create({ data: { name: 'KCB Vehicle Bids', url: 'https://ke.kcbgroup.com/vehicle-bids', category: 'BANK_PORTAL', complexity: 'MEDIUM', lastScrapedAt: new Date('2026-08-12T10:00:00'), lastStatus: 'SUCCESS', recordsFound: 67, scrapeIntervalHours: 6 } });
  await db.scrapingSource.create({ data: { name: 'Co-op Bank Auctions', url: 'https://vehiclesales.co-opbank.co.ke', category: 'BANK_PORTAL', complexity: 'HIGH', lastScrapedAt: new Date('2026-08-12T06:00:00'), lastStatus: 'PARTIAL', recordsFound: 31, scrapeIntervalHours: 6 } });
  await db.scrapingSource.create({ data: { name: 'NCBA Carduka', url: 'https://carduka.com/auction', category: 'BANK_PORTAL', complexity: 'HIGH', lastScrapedAt: new Date('2026-08-11T18:00:00'), lastStatus: 'SUCCESS', recordsFound: 80, scrapeIntervalHours: 6 } });
  await db.scrapingSource.create({ data: { name: 'Garam Investments', url: 'https://garam.co.ke', category: 'AUCTIONEER', complexity: 'MEDIUM', lastScrapedAt: new Date('2026-08-12T12:00:00'), lastStatus: 'SUCCESS', recordsFound: 25, scrapeIntervalHours: 6 } });
  await db.scrapingSource.create({ data: { name: 'Kenya Gazette', url: 'https://new.kenyalaw.org/akn/ke/officialGazette/', category: 'GOVERNMENT', complexity: 'HIGH', lastScrapedAt: new Date('2026-08-11T00:00:00'), lastStatus: 'SUCCESS', recordsFound: 12, scrapeIntervalHours: 24 } });
  await db.scrapingSource.create({ data: { name: 'KRA Public Notices', url: 'https://kra.go.ke/news-center/public-notices/', category: 'GOVERNMENT', complexity: 'MEDIUM', lastScrapedAt: new Date('2026-08-10T00:00:00'), lastStatus: 'SUCCESS', recordsFound: 8, scrapeIntervalHours: 24 } });

  // ─── DASHBOARD STATS ─────────────────────────────────────────────────────────
  await db.dashboardStats.create({ data: { totalVehicles: 10, totalLoanApps: 8, totalAuctions: 4, totalFraudFlags: 5, loanStackingDetections: 2, avgRiskScore: 54.3, sourcesActive: 8, riskChecksToday: 47 } });

  // ─── HISTORICAL RISK CHECKS ───────────────────────────────────────────────────
  await db.riskCheck.create({ data: { requestId: 'req_hist_001', vehicleId: v1.id, queryPlate: 'KDA 123X', queryChassis: 'JTEBU3JR3B5045181', requestorMfiId: 'MFI-2847', borrowerIdHash: 'sha256:a3f2b8c9d1e4f5a6b7c8d9e0f1a2b3c4', loanAmountKes: 850000, riskScore: 87, riskLevel: 'CRITICAL', confidence: 0.94, flaggedIssues: JSON.stringify(['LOAN_STACKING_SUSPECT', 'ACTIVE_AUCTION_LISTING', 'GOVERNMENT_PLATE_HISTORY']), graphAnalysis: JSON.stringify({ connectedLoans: 3, connectedLenders: 3, connectedAuctions: 1, fraudRingSize: 5, shortestPath: 2 }), recommendation: 'REJECT_LOAN', responseTimeMs: 142, createdAt: new Date('2026-08-12T15:41:00') } });
  await db.riskCheck.create({ data: { requestId: 'req_hist_002', vehicleId: v4.id, queryPlate: 'KAE 321M', requestorMfiId: 'MFI-1199', loanAmountKes: 500000, riskScore: 20, riskLevel: 'LOW', confidence: 0.88, flaggedIssues: '[]', graphAnalysis: JSON.stringify({ connectedLoans: 1, connectedLenders: 1, connectedAuctions: 0, fraudRingSize: 0 }), recommendation: 'APPROVE_LOAN', responseTimeMs: 67, createdAt: new Date('2026-08-12T14:22:00') } });
  await db.riskCheck.create({ data: { requestId: 'req_hist_003', vehicleId: v5.id, queryPlate: 'KDF 654Z', requestorMfiId: 'MFI-3301', loanAmountKes: 400000, riskScore: 68, riskLevel: 'HIGH', confidence: 0.91, flaggedIssues: JSON.stringify(['MULTIPLE_STORAGE_YARD_APPEARANCES', 'RAPID_RE_PLEDGE']), graphAnalysis: JSON.stringify({ connectedLoans: 2, connectedLenders: 2, connectedAuctions: 0, fraudRingSize: 4 }), recommendation: 'REVIEW_MANUALLY', responseTimeMs: 189, createdAt: new Date('2026-08-12T11:05:00') } });

  console.log('✅ Seed complete! 10 vehicles, 8 lenders, 5 borrowers, 8 loan apps, 4 auctions, 5 fraud flags');
}

main()
  .catch(e => { console.error(e); process.exit(1); })
  .finally(() => db.$disconnect());
