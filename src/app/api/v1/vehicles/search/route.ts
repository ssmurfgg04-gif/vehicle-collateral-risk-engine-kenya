import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const q = searchParams.get('q')?.toUpperCase().replace(/[\s\-]/g, '') ?? '';
  const limit = Math.min(parseInt(searchParams.get('limit') ?? '20'), 50);

  if (!q || q.length < 2) {
    return NextResponse.json({ results: [], total: 0 });
  }

  const vehicles = await db.vehicle.findMany({
    where: {
      OR: [
        { normalizedPlate: { contains: q } },
        { make: { contains: q } },
        { model: { contains: q } },
        { normalizedChassis: { contains: q } },
      ],
    },
    include: {
      loanApplications: { include: { lender: true } },
      auctionListings: { where: { isActive: true } },
      storageYardStays: { include: { yard: true }, where: { isCurrent: true } },
      flags: true,
    },
    take: limit,
    orderBy: { degreeCentrality: 'desc' },
  });

  const results = vehicles.map(v => ({
    id: v.id,
    normalized_plate: v.normalizedPlate,
    raw_plate: v.rawPlate,
    make: v.make,
    model: v.model,
    variant: v.variant,
    year: v.year,
    color: v.color,
    plate_category: v.plateCategory,
    county_code: v.countyCode,
    active_loans: v.loanApplications.filter(la => la.status === 'ACTIVE').length,
    active_auctions: v.auctionListings.length,
    fraud_flags: v.flags.map(f => f.flagType),
    current_yard: v.storageYardStays[0]?.yard.name ?? null,
    degree_centrality: v.degreeCentrality,
    fraud_ring_size: v.fraudRingSize,
  }));

  return NextResponse.json({ results, total: results.length });
}
