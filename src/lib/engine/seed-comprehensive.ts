/**
 * Comprehensive Seed Data for Kenya Vehicle Collateral Risk Engine
 * 
 * 50+ vehicles with realistic Kenyan registration patterns
 * Multiple loan-stacking scenarios, government plates, fraud rings
 * Real Kenyan banks, auctioneers, counties, storage yards
 */

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

// ─── Kenyan Data ─────────────────────────────────────────────────────

const VEHICLES = [
  // ── Loan Stacking Vehicles (CRITICAL risk) ──
  { rawPlate: 'KDA 123J', make: 'Toyota', model: 'Hilux', variant: 'Double Cab', year: 2021, chassis: 'MR0DB3C240001', countyCode: 'KD', plateCategory: 'PRIVATE' },
  { rawPlate: 'KCB 456M', make: 'Nissan', model: 'Patrol', variant: 'LE', year: 2020, chassis: 'JN1TANSZ100001', countyCode: 'KC', plateCategory: 'PRIVATE' },
  { rawPlate: 'KNA 789L', make: 'Mitsubishi', model: 'Pajero', variant: 'GLS', year: 2019, chassis: 'JMB0NV240W001', countyCode: 'KN', plateCategory: 'PRIVATE' },
  { rawPlate: 'KDA 321P', make: 'Isuzu', model: 'DMAX', variant: 'LS', year: 2022, chassis: 'MPATFS400001', countyCode: 'KD', plateCategory: 'PRIVATE' },
  { rawPlate: 'KBA 654K', make: 'Toyota', model: 'Fortuner', variant: 'LEG', year: 2021, chassis: 'MR0KB3A230001', countyCode: 'KB', plateCategory: 'PRIVATE' },

  // ── Government Plate Vehicles (title-washing risk) ──
  { rawPlate: 'GKA 072Z', make: 'Toyota', model: 'Land Cruiser', variant: 'V8', year: 2018, chassis: 'JTMCY7AJ500001', countyCode: null, plateCategory: 'GOVERNMENT' },
  { rawPlate: 'GKB 145A', make: 'Nissan', model: 'Patrol', variant: 'SE', year: 2017, chassis: 'JN1TANSZ100002', countyCode: null, plateCategory: 'GOVERNMENT' },
  { rawPlate: 'GKN 234B', make: 'Toyota', model: 'Hilux', variant: '4WD', year: 2019, chassis: 'MR0DB3C240002', countyCode: null, plateCategory: 'GOVERNMENT' },
  { rawPlate: 'GK 567C', make: 'Mitsubishi', model: 'Canter', variant: 'FB', year: 2015, chassis: 'JA3MR4S200001', countyCode: null, plateCategory: 'GOVERNMENT' },
  { rawPlate: 'GKY 891D', make: 'Toyota', model: 'Corolla', variant: 'XLi', year: 2020, chassis: 'NMT512L200001', countyCode: null, plateCategory: 'GOVERNMENT' },

  // ── Active Auction Vehicles ──
  { rawPlate: 'KDF 100X', make: 'Toyota', model: 'Prado', variant: 'TXL', year: 2019, chassis: 'JTMCY7AJ500002', countyCode: 'KD', plateCategory: 'PRIVATE' },
  { rawPlate: 'KNA 200Y', make: 'Mercedes', model: 'C200', variant: 'W205', year: 2018, chassis: 'WDD205020001', countyCode: 'KN', plateCategory: 'PRIVATE' },
  { rawPlate: 'KEA 300Z', make: 'BMW', model: '320i', variant: 'G20', year: 2020, chassis: 'WBA3R1102001', countyCode: 'KE', plateCategory: 'PRIVATE' },
  { rawPlate: 'KMA 400A', make: 'Volkswagen', model: 'Amarok', variant: 'Trendline', year: 2021, chassis: 'WV2ZZZ2KZ0001', countyCode: 'KM', plateCategory: 'PRIVATE' },

  // ── Multi-Storage-Yard Vehicles ──
  { rawPlate: 'KDF 654Z', make: 'Toyota', model: 'Hiace', variant: 'Matatu', year: 2016, chassis: 'JTFSS22P90001', countyCode: 'KD', plateCategory: 'PRIVATE' },
  { rawPlate: 'KNA 111B', make: 'Nissan', model: 'Urvan', variant: 'Panel Van', year: 2017, chassis: 'JN1FSZHR2001', countyCode: 'KN', plateCategory: 'PRIVATE' },
  { rawPlate: 'KKA 222C', make: 'Isuzu', model: 'NQR', variant: 'Lorry', year: 2015, chassis: 'JALNE1R15001', countyCode: 'KK', plateCategory: 'PRIVATE' },

  // ── Clean Vehicles (LOW risk) ──
  { rawPlate: 'KAE 321M', make: 'Toyota', model: 'Vitz', variant: '1.5', year: 2023, chassis: 'NMT510L300001', countyCode: 'KA', plateCategory: 'PRIVATE' },
  { rawPlate: 'KBE 432N', make: 'Honda', model: 'Fit', variant: 'RS', year: 2022, chassis: 'JHMGE8H200001', countyCode: 'KB', plateCategory: 'PRIVATE' },
  { rawPlate: 'KCE 543O', make: 'Mazda', model: 'Demio', variant: '15S', year: 2023, chassis: 'MZDE12A2001', countyCode: 'KC', plateCategory: 'PRIVATE' },
  { rawPlate: 'KDE 654P', make: 'Subaru', model: 'Impreza', variant: 'G4', year: 2022, chassis: 'JF1GE7LC7001', countyCode: 'KD', plateCategory: 'PRIVATE' },
  { rawPlate: 'KEE 765Q', make: 'Suzuki', model: 'Swift', variant: 'GLX', year: 2023, chassis: 'TSMMZC11S001', countyCode: 'KE', plateCategory: 'PRIVATE' },
  { rawPlate: 'KFE 876R', make: 'Hyundai', model: 'Accent', variant: 'GLS', year: 2022, chassis: 'KMHD84LH6001', countyCode: 'KF', plateCategory: 'PRIVATE' },
  { rawPlate: 'KGE 987S', make: 'Kia', model: 'Rio', variant: 'EX', year: 2023, chassis: 'KNADM213001', countyCode: 'KG', plateCategory: 'PRIVATE' },
  { rawPlate: 'KHE 135T', make: 'Toyota', model: 'Corolla', variant: 'GLi', year: 2021, chassis: 'NMT512L300001', countyCode: 'KH', plateCategory: 'PRIVATE' },
  { rawPlate: 'KIE 246U', make: 'Nissan', model: 'Note', variant: 'Nismo', year: 2022, chassis: 'JN1FCEDM2001', countyCode: 'KI', plateCategory: 'PRIVATE' },
  { rawPlate: 'KJE 357V', make: 'Honda', model: 'Civic', variant: 'RS', year: 2023, chassis: 'JHMFC1630001', countyCode: 'KJ', plateCategory: 'PRIVATE' },

  // ── Rapid Re-Pledge Vehicles ──
  { rawPlate: 'KUA 888W', make: 'Toyota', model: 'RAV4', variant: 'AXV', year: 2021, chassis: 'JTFKK3D500001', countyCode: 'KU', plateCategory: 'PRIVATE' },
  { rawPlate: 'KVA 999X', make: 'Mazda', model: 'CX-5', variant: '2.0', year: 2020, chassis: 'JMZKE2W10001', countyCode: 'KV', plateCategory: 'PRIVATE' },
  { rawPlate: 'KWA 111Y', make: 'Subaru', model: 'Forester', variant: 'i', year: 2021, chassis: 'JF1SJ9LC6001', countyCode: 'KW', plateCategory: 'PRIVATE' },

  // ── Chassis Mismatch Vehicles ──
  { rawPlate: 'KZA 222Z', make: 'Toyota', model: 'Land Cruiser', variant: 'Prado', year: 2018, chassis: 'JTMCY7AJ500003', countyCode: 'KZ', plateCategory: 'PRIVATE' },

  // ── Fraud Ring Vehicles (connected through shared borrower) ──
  { rawPlate: 'KLA 333A', make: 'Toyota', model: 'Camry', variant: 'XLE', year: 2020, chassis: 'NMT252L40001', countyCode: 'KL', plateCategory: 'PRIVATE' },
  { rawPlate: 'KLB 444B', make: 'Nissan', model: 'X-Trail', variant: 'ST-L', year: 2021, chassis: 'JN1TANT310001', countyCode: 'KL', plateCategory: 'PRIVATE' },
  { rawPlate: 'KLC 555C', make: 'Honda', model: 'CR-V', variant: '2.0L', year: 2020, chassis: 'JHMRE4H700001', countyCode: 'KL', plateCategory: 'PRIVATE' },
  { rawPlate: 'KLD 666D', make: 'Mazda', model: 'BT-50', variant: 'GSX', year: 2021, chassis: 'MM0KSD210001', countyCode: 'KL', plateCategory: 'PRIVATE' },
  { rawPlate: 'KLE 777E', make: 'Isuzu', model: 'MU-X', variant: 'LS', year: 2020, chassis: 'MPATFR320001', countyCode: 'KL', plateCategory: 'PRIVATE' },

  // ── Additional vehicles for realistic density ──
  { rawPlate: 'KPA 100F', make: 'Toyota', model: 'Auris', variant: '1.8', year: 2019, chassis: 'NZE181000001', countyCode: 'KP', plateCategory: 'PRIVATE' },
  { rawPlate: 'KQA 200G', make: 'Mercedes', model: 'E250', variant: 'W213', year: 2020, chassis: 'WDD213020001', countyCode: 'KQ', plateCategory: 'PRIVATE' },
  { rawPlate: 'KRA 300H', make: 'BMW', model: 'X3', variant: 'xDrive30i', year: 2021, chassis: 'WBAJV1102001', countyCode: 'KR', plateCategory: 'PRIVATE' },
  { rawPlate: 'KSA 400I', make: 'Audi', model: 'A4', variant: '35 TFSI', year: 2020, chassis: 'WAUZZZ8KZ0002', countyCode: 'KS', plateCategory: 'PRIVATE' },
  { rawPlate: 'KTA 500J', make: 'Volvo', model: 'XC60', variant: 'T5', year: 2021, chassis: 'YV1CZA800001', countyCode: 'KT', plateCategory: 'PRIVATE' },
  { rawPlate: 'KUA 600K', make: 'Land Rover', model: 'Discovery', variant: 'Sport', year: 2020, chassis: 'SALGS54G7001', countyCode: 'KU', plateCategory: 'PRIVATE' },
  { rawPlate: 'KVA 700L', make: 'Jeep', model: 'Grand Cherokee', variant: 'Limited', year: 2019, chassis: '1C4RJFBG1001', countyCode: 'KV', plateCategory: 'PRIVATE' },
  { rawPlate: 'KWA 800M', make: 'Ford', model: 'Ranger', variant: 'Wildtrak', year: 2022, chassis: 'WF0XXXGPX2001', countyCode: 'KW', plateCategory: 'PRIVATE' },
  { rawPlate: 'KXA 900N', make: 'Chevrolet', model: 'Trailblazer', variant: 'LTZ', year: 2018, chassis: 'KL1VMA126001', countyCode: 'KX', plateCategory: 'PRIVATE' },
  { rawPlate: 'KYA 010O', make: 'Peugeot', model: '3008', variant: 'GT', year: 2021, chassis: 'VR3ESDHZK001', countyCode: 'KY', plateCategory: 'PRIVATE' },

  // ── Military/Polic plates (informational, not collateral) ──
  { rawPlate: 'KAW 100P', make: 'Toyota', model: 'Land Cruiser', variant: 'Troop Carrier', year: 2016, chassis: 'JTMCY7AJ500010', countyCode: null, plateCategory: 'MILITARY' },
  { rawPlate: 'KAP 200Q', make: 'Nissan', model: 'Patrol', variant: 'Pursuit', year: 2018, chassis: 'JN1TANSZ100010', countyCode: null, plateCategory: 'GOVERNMENT' },

  // ── SACCO/DCP loan vehicles ──
  { rawPlate: 'KNE 111R', make: 'Toyota', model: 'Probox', variant: '1.5', year: 2020, chassis: 'NCP510000001', countyCode: 'KN', plateCategory: 'PRIVATE' },
  { rawPlate: 'KME 222S', make: 'Nissan', model: 'AD Van', variant: '1.6i', year: 2019, chassis: 'JN1FANZM2001', countyCode: 'KM', plateCategory: 'PRIVATE' },

  // ── More loan-stacking scenarios ──
  { rawPlate: 'KFA 333T', make: 'Toyota', model: 'Noah', variant: 'GL', year: 2021, chassis: 'JTFK53C200001', countyCode: 'KF', plateCategory: 'PRIVATE' },
  { rawPlate: 'KGA 444U', make: 'Toyota', model: 'Voxy', variant: 'G', year: 2022, chassis: 'JTFK33C200001', countyCode: 'KG', plateCategory: 'PRIVATE' },
];

const LENDERS = [
  { lenderId: 'EQUITY', name: 'Equity Bank Kenya', type: 'BANK', regulated: true },
  { lenderId: 'FAMILY', name: 'Family Bank', type: 'BANK', regulated: true },
  { lenderId: 'COOP', name: 'Co-operative Bank', type: 'BANK', regulated: true },
  { lenderId: 'KCB', name: 'KCB Bank Kenya', type: 'BANK', regulated: true },
  { lenderId: 'NCBA', name: 'NCBA Bank', type: 'BANK', regulated: true },
  { lenderId: 'UNAITAS', name: 'Unaitas SACCO', type: 'SACCO', regulated: true },
  { lenderId: 'STIMA', name: 'Stima SACCO', type: 'SACCO', regulated: true },
  { lenderId: 'KWFT', name: 'Kenya Women Microfinance', type: 'MFI', regulated: true },
  { lenderId: 'TALA', name: 'Tala (Mobile Lending)', type: 'DCP', regulated: false },
  { lenderId: 'BRANCH', name: 'Branch (Mobile Lending)', type: 'DCP', regulated: false },
];

const BORROWERS = [
  { idHash: 'a1b2c3d4e5f6', riskTier: 'HIGH', knownAliases: ['John Kiprop', 'J. Kiprop'] },
  { idHash: 'f6e5d4c3b2a1', riskTier: 'MEDIUM', knownAliases: ['Mary Wanjiku'] },
  { idHash: '112233445566', riskTier: 'LOW', knownAliases: ['Peter Ochieng'] },
  { idHash: '665544332211', riskTier: 'HIGH', knownAliases: ['Grace Achieng', 'G. Akinyi'] },
  { idHash: 'aabb11223344', riskTier: 'CRITICAL', knownAliases: ['Samuel Mwangi', 'S. Kamau', 'Sam Mwangi'] },
  { idHash: '44332211bbaa', riskTier: 'LOW', knownAliases: ['Fatuma Hassan'] },
  { idHash: 'ccdd55667788', riskTier: 'MEDIUM', knownAliases: ['David Kimutai'] },
  { idHash: '88776655ddcc', riskTier: 'LOW', knownAliases: ['Anne Njeri'] },
  { idHash: 'eeff99001122', riskTier: 'HIGH', knownAliases: ['Michael Odhiambo', 'M. Ochieng'] },
  { idHash: '22110099ffee', riskTier: 'MEDIUM', knownAliases: ['Charity Wambui'] },
];

const AUCTIONEERS = [
  { auctioneerId: 'GARAM', name: 'Garam Auctioneers', licenseNumber: 'AUC-KE-2019-001', county: 'Nairobi' },
  { auctioneerId: 'KEYSIAN', name: 'Keysian Auctioneers', licenseNumber: 'AUC-KE-2019-002', county: 'Nairobi' },
  { auctioneerId: 'PHILLIPS', name: 'Phillips International', licenseNumber: 'AUC-KE-2018-003', county: 'Mombasa' },
  { auctioneerId: 'LEAKEY', name: 'Leakey Auctioneers', licenseNumber: 'AUC-KE-2020-004', county: 'Nakuru' },
];

const STORAGE_YARDS = [
  { yardId: 'SY001', name: 'Central Vehicle Yard', county: 'Nairobi', latitude: -1.2921, longitude: 36.8219, capacity: 500 },
  { yardId: 'SY002', name: 'Eastern Auto Storage', county: 'Machakos', latitude: -1.5177, longitude: 37.2634, capacity: 300 },
  { yardId: 'SY003', name: 'Coast Vehicle Depot', county: 'Mombasa', latitude: -4.0435, longitude: 39.6682, capacity: 200 },
  { yardId: 'SY004', name: 'Rift Valley Yard', county: 'Nakuru', latitude: -0.3031, longitude: 36.0800, capacity: 250 },
  { yardId: 'SY005', name: 'Nyanza Auto Storage', county: 'Kisumu', latitude: -0.0917, longitude: 34.7684, capacity: 150 },
];

const SCRAPING_SOURCES = [
  { sourceId: 'family_bank', name: 'Family Bank', url: 'https://www.familybank.co.ke/vehicle-finance', type: 'BANK', status: 'ACTIVE', lastScrapedAt: new Date(Date.now() - 3600000).toISOString(), recordsCount: 15, scrapeIntervalMinutes: 360, errorRate: 0.02 },
  { sourceId: 'equity_bank', name: 'Equity Bank', url: 'https://ke.equitybankgroup.com/vehicle-loans', type: 'BANK', status: 'ACTIVE', lastScrapedAt: new Date(Date.now() - 7200000).toISOString(), recordsCount: 25, scrapeIntervalMinutes: 360, errorRate: 0.01 },
  { sourceId: 'coop_bank', name: 'Co-operative Bank', url: 'https://www.co-opbank.co.ke/auto-loans', type: 'BANK', status: 'ACTIVE', lastScrapedAt: new Date(Date.now() - 14400000).toISOString(), recordsCount: 30, scrapeIntervalMinutes: 720, errorRate: 0.05 },
  { sourceId: 'kcb_bank', name: 'KCB Bank', url: 'https://kcbgroup.com/vehicle-loans', type: 'BANK', status: 'ACTIVE', lastScrapedAt: new Date(Date.now() - 10800000).toISOString(), recordsCount: 20, scrapeIntervalMinutes: 360, errorRate: 0.01 },
  { sourceId: 'ncba_bank', name: 'NCBA Bank', url: 'https://ncbagroup.com/auto-finance', type: 'BANK', status: 'ACTIVE', lastScrapedAt: new Date(Date.now() - 5400000).toISOString(), recordsCount: 15, scrapeIntervalMinutes: 360, errorRate: 0.03 },
  { sourceId: 'garam_auctioneers', name: 'Garam Auctioneers', url: 'https://www.garam.co.ke/auctions', type: 'AUCTIONEER', status: 'ACTIVE', lastScrapedAt: new Date(Date.now() - 1800000).toISOString(), recordsCount: 40, scrapeIntervalMinutes: 180, errorRate: 0.02 },
  { sourceId: 'kenya_gazette', name: 'Kenya Gazette', url: 'https://gazettes.africa.go.ke', type: 'GOVERNMENT', status: 'ACTIVE', lastScrapedAt: new Date(Date.now() - 86400000).toISOString(), recordsCount: 50, scrapeIntervalMinutes: 1440, errorRate: 0.08 },
  { sourceId: 'kra_disposals', name: 'KRA Government Disposals', url: 'https://www.kra.go.ke/public-notices', type: 'GOVERNMENT', status: 'PLANNED', lastScrapedAt: null, recordsCount: 0, scrapeIntervalMinutes: 1440, errorRate: 0 },
];

// ─── Seed Function ───────────────────────────────────────────────────

export async function seedDatabase() {
  console.log('🌱 Seeding Kenya Vehicle Collateral Risk Engine...');

  // Create vehicles
  const vehicleRecords = [];
  for (const v of VEHICLES) {
    const normalizedPlate = v.rawPlate.toUpperCase().replace(/\s/g, '');
    const normalizedChassis = v.chassis.toUpperCase();
    
    // Compute graph features based on vehicle role
    const isLoanStacking = ['KDA123J', 'KCB456M', 'KNA789L', 'KDA321P', 'KBA654K', 'KFA333T', 'KGA444U'].includes(normalizedPlate);
    const isGovtPlate = v.plateCategory === 'GOVERNMENT' || v.plateCategory === 'MILITARY';
    const isAuction = ['KDF100X', 'KNA200Y', 'KEA300Z', 'KMA400A'].includes(normalizedPlate);
    const isFraudRing = ['KLA333A', 'KLB444B', 'KLC555C', 'KLD666D', 'KLE777E'].includes(normalizedPlate);

    const vehicle = await prisma.vehicle.upsert({
      where: { normalizedPlate },
      update: {},
      create: {
        rawPlate: v.rawPlate,
        normalizedPlate,
        make: v.make,
        model: v.model,
        variant: v.variant,
        year: v.year,
        chassis: v.chassis,
        normalizedChassis,
        plateCategory: v.plateCategory,
        countyCode: v.countyCode,
        resolutionConfidence: isGovtPlate ? 0.95 : 0.90,
        degreeCentrality: isLoanStacking ? 4.2 : isFraudRing ? 3.5 : isAuction ? 2.1 : 1.0,
        clusteringCoefficient: isFraudRing ? 0.72 : isLoanStacking ? 0.45 : 0.12,
        fraudRingSize: isFraudRing ? 5 : isLoanStacking ? 2 : 0,
      },
    });
    vehicleRecords.push(vehicle);
  }
  console.log(`  ✅ ${vehicleRecords.length} vehicles seeded`);

  // Create lenders
  const lenderRecords = [];
  for (const l of LENDERS) {
    const lender = await prisma.lender.upsert({
      where: { lenderId: l.lenderId },
      update: {},
      create: l,
    });
    lenderRecords.push(lender);
  }
  console.log(`  ✅ ${lenderRecords.length} lenders seeded`);

  // Create borrowers
  const borrowerRecords = [];
  for (const b of BORROWERS) {
    const borrower = await prisma.borrower.upsert({
      where: { idHash: b.idHash },
      update: {},
      create: b,
    });
    borrowerRecords.push(borrower);
  }
  console.log(`  ✅ ${borrowerRecords.length} borrowers seeded`);

  // Create auctioneers
  for (const a of AUCTIONEERS) {
    await prisma.auctioneer.upsert({
      where: { auctioneerId: a.auctioneerId },
      update: {},
      create: a,
    });
  }
  console.log(`  ✅ ${AUCTIONEERS.length} auctioneers seeded`);

  // Create storage yards
  for (const sy of STORAGE_YARDS) {
    await prisma.storageYard.upsert({
      where: { yardId: sy.yardId },
      update: {},
      create: sy,
    });
  }
  console.log(`  ✅ ${STORAGE_YARDS.length} storage yards seeded`);

  // Create scraping sources
  for (const s of SCRAPING_SOURCES) {
    await prisma.scrapingSource.upsert({
      where: { sourceId: s.sourceId },
      update: {},
      create: s,
    });
  }
  console.log(`  ✅ ${SCRAPING_SOURCES.length} scraping sources seeded`);

  // Create loan applications
  const loanApps = [
    // Loan stacking: KDA 123J — 3 different lenders
    { vehiclePlate: 'KDA123J', lenderId: 'EQUITY', borrowerIdHash: 'a1b2c3d4e5f6', amountKes: 2500000, status: 'ACTIVE' },
    { vehiclePlate: 'KDA123J', lenderId: 'FAMILY', borrowerIdHash: 'a1b2c3d4e5f6', amountKes: 1800000, status: 'ACTIVE' },
    { vehiclePlate: 'KDA123J', lenderId: 'UNAITAS', borrowerIdHash: 'a1b2c3d4e5f6', amountKes: 800000, status: 'ACTIVE' },

    // Loan stacking: KCB 456M — 2 lenders
    { vehiclePlate: 'KCB456M', lenderId: 'KCB', borrowerIdHash: 'f6e5d4c3b2a1', amountKes: 3500000, status: 'ACTIVE' },
    { vehiclePlate: 'KCB456M', lenderId: 'COOP', borrowerIdHash: 'f6e5d4c3b2a1', amountKes: 2200000, status: 'ACTIVE' },

    // Loan stacking: KNA 789L
    { vehiclePlate: 'KNA789L', lenderId: 'NCBA', borrowerIdHash: '112233445566', amountKes: 4000000, status: 'ACTIVE' },
    { vehiclePlate: 'KNA789L', lenderId: 'EQUITY', borrowerIdHash: '112233445566', amountKes: 1500000, status: 'ACTIVE' },

    // Loan stacking: KDA 321P
    { vehiclePlate: 'KDA321P', lenderId: 'FAMILY', borrowerIdHash: '665544332211', amountKes: 2800000, status: 'ACTIVE' },
    { vehiclePlate: 'KDA321P', lenderId: 'KWFT', borrowerIdHash: '665544332211', amountKes: 500000, status: 'ACTIVE' },

    // Loan stacking: KBA 654K
    { vehiclePlate: 'KBA654K', lenderId: 'KCB', borrowerIdHash: 'aabb11223344', amountKes: 3200000, status: 'ACTIVE' },
    { vehiclePlate: 'KBA654K', lenderId: 'TALA', borrowerIdHash: 'aabb11223344', amountKes: 200000, status: 'ACTIVE' },

    // Government plates with loans (suspicious)
    { vehiclePlate: 'GKA072Z', lenderId: 'STIMA', borrowerIdHash: 'ccdd55667788', amountKes: 5000000, status: 'ACTIVE' },
    { vehiclePlate: 'GKB145A', lenderId: 'KWFT', borrowerIdHash: '88776655ddcc', amountKes: 1500000, status: 'ACTIVE' },

    // Fraud ring: 5 vehicles, same borrower, different lenders
    { vehiclePlate: 'KLA333A', lenderId: 'EQUITY', borrowerIdHash: 'eeff99001122', amountKes: 2000000, status: 'ACTIVE' },
    { vehiclePlate: 'KLB444B', lenderId: 'KCB', borrowerIdHash: 'eeff99001122', amountKes: 2500000, status: 'ACTIVE' },
    { vehiclePlate: 'KLC555C', lenderId: 'COOP', borrowerIdHash: 'eeff99001122', amountKes: 1800000, status: 'ACTIVE' },
    { vehiclePlate: 'KLD666D', lenderId: 'NCBA', borrowerIdHash: 'eeff99001122', amountKes: 3000000, status: 'ACTIVE' },
    { vehiclePlate: 'KLE777E', lenderId: 'FAMILY', borrowerIdHash: 'eeff99001122', amountKes: 2200000, status: 'ACTIVE' },

    // Clean vehicles with single loans
    { vehiclePlate: 'KAE321M', lenderId: 'EQUITY', borrowerIdHash: '44332211bbaa', amountKes: 800000, status: 'ACTIVE' },
    { vehiclePlate: 'KBE432N', lenderId: 'KCB', borrowerIdHash: '22110099ffee', amountKes: 650000, status: 'ACTIVE' },
    { vehiclePlate: 'KCE543O', lenderId: 'COOP', borrowerIdHash: '44332211bbaa', amountKes: 550000, status: 'REPAID' },
    { vehiclePlate: 'KDE654P', lenderId: 'FAMILY', borrowerIdHash: '22110099ffee', amountKes: 900000, status: 'ACTIVE' },

    // Rapid re-pledge vehicles
    { vehiclePlate: 'KUA888W', lenderId: 'EQUITY', borrowerIdHash: 'a1b2c3d4e5f6', amountKes: 1800000, status: 'ACTIVE' },
    { vehiclePlate: 'KVA999X', lenderId: 'KCB', borrowerIdHash: 'f6e5d4c3b2a1', amountKes: 2200000, status: 'ACTIVE' },

    // SACCO/DCP vehicles
    { vehiclePlate: 'KNE111R', lenderId: 'UNAITAS', borrowerIdHash: '665544332211', amountKes: 400000, status: 'ACTIVE' },
    { vehiclePlate: 'KME222S', lenderId: 'BRANCH', borrowerIdHash: 'ccdd55667788', amountKes: 150000, status: 'ACTIVE' },

    // More loan-stacking with SACCO/DCP
    { vehiclePlate: 'KFA333T', lenderId: 'EQUITY', borrowerIdHash: 'aabb11223344', amountKes: 2500000, status: 'ACTIVE' },
    { vehiclePlate: 'KFA333T', lenderId: 'STIMA', borrowerIdHash: 'aabb11223344', amountKes: 600000, status: 'ACTIVE' },
    { vehiclePlate: 'KGA444U', lenderId: 'KCB', borrowerIdHash: 'eeff99001122', amountKes: 3000000, status: 'ACTIVE' },
    { vehiclePlate: 'KGA444U', lenderId: 'TALA', borrowerIdHash: 'eeff99001122', amountKes: 100000, status: 'ACTIVE' },
  ];

  for (let i = 0; i < loanApps.length; i++) {
    const la = loanApps[i];
    await prisma.loanApplication.create({
      data: {
        applicationId: `LA-${String(i + 1).padStart(4, '0')}`,
        vehicle: { connect: { normalizedPlate: la.vehiclePlate } },
        lender: { connect: { lenderId: la.lenderId } },
        borrower: { connect: { idHash: la.borrowerIdHash } },
        amountKes: la.amountKes,
        status: la.status,
        caveatRegistered: la.status === 'ACTIVE' && la.lenderId !== 'TALA' && la.lenderId !== 'BRANCH',
        caveatDate: la.status === 'ACTIVE' ? new Date().toISOString() : null,
        createdAt: new Date(Date.now() - Math.random() * 90 * 86400000).toISOString(),
      },
    });
  }
  console.log(`  ✅ ${loanApps.length} loan applications seeded`);

  // Create auction listings
  const auctions = [
    { vehiclePlate: 'KDF100X', auctioneerId: 'GARAM', amountKes: 3500000, auctionDate: new Date(Date.now() + 14 * 86400000).toISOString(), listingType: 'BANK_REPOSSESSION' },
    { vehiclePlate: 'KNA200Y', auctioneerId: 'KEYSIAN', amountKes: 4200000, auctionDate: new Date(Date.now() + 21 * 86400000).toISOString(), listingType: 'BANK_REPOSSESSION' },
    { vehiclePlate: 'KEA300Z', auctioneerId: 'PHILLIPS', amountKes: 2800000, auctionDate: new Date(Date.now() + 7 * 86400000).toISOString(), listingType: 'BANK_REPOSSESSION' },
    { vehiclePlate: 'KMA400A', auctioneerId: 'GARAM', amountKes: 3100000, auctionDate: new Date(Date.now() + 30 * 86400000).toISOString(), listingType: 'GOVERNMENT_DISPOSAL' },
    { vehiclePlate: 'GKA072Z', auctioneerId: 'LEAKEY', amountKes: 8000000, auctionDate: new Date(Date.now() + 10 * 86400000).toISOString(), listingType: 'GOVERNMENT_DISPOSAL' },
  ];

  for (const a of auctions) {
    await prisma.auctionListing.create({
      data: {
        listingId: `AUC-${Math.random().toString(36).substring(2, 8).toUpperCase()}`,
        vehicle: { connect: { normalizedPlate: a.vehiclePlate } },
        auctioneer: { connect: { auctioneerId: a.auctioneerId } },
        reservePriceKes: a.amountKes,
        auctionDate: a.auctionDate,
        listingType: a.listingType,
        isLive: true,
      },
    });
  }
  console.log(`  ✅ ${auctions.length} auction listings seeded`);

  // Create fraud flags
  const fraudFlags = [
    { vehiclePlate: 'KDA123J', flagType: 'LOAN_STACKING_SUSPECT', severity: 'CRITICAL', description: '3 active loans from different lenders (Equity, Family, Unaitas) totaling KES 5.1M' },
    { vehiclePlate: 'KCB456M', flagType: 'LOAN_STACKING_SUSPECT', severity: 'HIGH', description: '2 active loans from different lenders (KCB, Co-op) totaling KES 5.7M' },
    { vehiclePlate: 'KNA789L', flagType: 'LOAN_STACKING_SUSPECT', severity: 'HIGH', description: '2 active loans from different lenders (NCBA, Equity) totaling KES 5.5M' },
    { vehiclePlate: 'GKA072Z', flagType: 'GOVERNMENT_PLATE_HISTORY', severity: 'HIGH', description: 'Former government vehicle (GKA prefix) used as private collateral without disposal docs' },
    { vehiclePlate: 'GKB145A', flagType: 'GOVERNMENT_PLATE_HISTORY', severity: 'MEDIUM', description: 'Former government vehicle (GKB prefix) — disposal documentation verification needed' },
    { vehiclePlate: 'KDF100X', flagType: 'ACTIVE_AUCTION_LISTING', severity: 'HIGH', description: 'Vehicle listed for auction by Garam Auctioneers while active loan exists' },
    { vehiclePlate: 'KNA200Y', flagType: 'ACTIVE_AUCTION_LISTING', severity: 'HIGH', description: 'Vehicle listed for auction by Keysian Auctioneers while active loan exists' },
    { vehiclePlate: 'KDF654Z', flagType: 'MULTIPLE_STORAGE_YARD_APPEARANCES', severity: 'MEDIUM', description: 'Vehicle appeared at 3 different storage yards across 2 counties' },
    { vehiclePlate: 'KUA888W', flagType: 'RAPID_RE_PLEDGE', severity: 'HIGH', description: 'Vehicle re-pledged as collateral within 7 days of previous loan' },
    { vehiclePlate: 'KZA222Z', flagType: 'CHASSIS_MISMATCH', severity: 'CRITICAL', description: 'Chassis number on registration differs from physical inspection' },
    { vehiclePlate: 'KLA333A', flagType: 'LOAN_STACKING_SUSPECT', severity: 'CRITICAL', description: 'Part of fraud ring — 5 vehicles connected through shared borrower' },
    { vehiclePlate: 'KLB444B', flagType: 'LOAN_STACKING_SUSPECT', severity: 'CRITICAL', description: 'Part of fraud ring — 5 vehicles connected through shared borrower' },
  ];

  for (const f of fraudFlags) {
    await prisma.fraudFlag.create({
      data: {
        flagId: `FLAG-${Math.random().toString(36).substring(2, 8).toUpperCase()}`,
        vehicle: { connect: { normalizedPlate: f.vehiclePlate } },
        flagType: f.flagType,
        severity: f.severity,
        description: f.description,
        isResolved: false,
      },
    });
  }
  console.log(`  ✅ ${fraudFlags.length} fraud flags seeded`);

  // Create risk checks (historical)
  const riskChecks = [
    { plate: 'KDA123J', score: 95, level: 'CRITICAL' },
    { plate: 'KCB456M', score: 78, level: 'HIGH' },
    { plate: 'GKA072Z', score: 85, level: 'CRITICAL' },
    { plate: 'KAE321M', score: 22, level: 'LOW' },
    { plate: 'KBE432N', score: 18, level: 'LOW' },
    { plate: 'KDF100X', score: 72, level: 'HIGH' },
    { plate: 'KUA888W', score: 68, level: 'HIGH' },
    { plate: 'KNA789L', score: 82, level: 'CRITICAL' },
  ];

  for (const rc of riskChecks) {
    await prisma.riskCheck.create({
      data: {
        checkId: `RC-${Math.random().toString(36).substring(2, 8).toUpperCase()}`,
        queryRegistration: rc.plate,
        riskScore: rc.score,
        riskLevel: rc.level,
        flaggedIssues: [],
        graphAnalysis: {},
        historicalFootprints: {},
        recommendation: rc.level === 'LOW' ? 'APPROVE_LOAN' : rc.level === 'MEDIUM' ? 'REVIEW_MANUALLY' : 'REJECT_LOAN',
        requestorMfiId: 'EQUITY',
        responseTimeMs: 85 + Math.floor(Math.random() * 65),
        dataFreshness: new Date().toISOString(),
      },
    });
  }
  console.log(`  ✅ ${riskChecks.length} risk checks seeded`);

  // Create dashboard stats
  const totalVehicles = await prisma.vehicle.count();
  const totalLoans = await prisma.loanApplication.count();
  const activeLoans = await prisma.loanApplication.count({ where: { status: 'ACTIVE' } });
  const totalFlags = await prisma.fraudFlag.count();
  const avgRisk = Math.round(riskChecks.reduce((s, r) => s + r.score, 0) / riskChecks.length);

  await prisma.dashboardStats.upsert({
    where: { id: 'main' },
    update: {},
    create: {
      id: 'main',
      totalVehicles,
      totalLoanApplications: totalLoans,
      activeAuctions: auctions.length,
      fraudFlagsCount: totalFlags,
      loanStackingCount: fraudFlags.filter(f => f.flagType === 'LOAN_STACKING_SUSPECT').length,
      averageRiskScore: avgRisk,
      checksToday: riskChecks.length,
      activeLoansCount: activeLoans,
    },
  });

  console.log('\n✅ Kenya Vehicle Collateral Risk Engine seeded successfully!');
  console.log(`   ${totalVehicles} vehicles | ${totalLoans} loans | ${totalFlags} fraud flags | ${riskChecks.length} risk checks`);
}

// Run if called directly
if (require.main === module) {
  seedDatabase()
    .then(() => process.exit(0))
    .catch((e) => { console.error(e); process.exit(1); });
}
