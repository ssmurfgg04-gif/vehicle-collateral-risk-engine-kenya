import { NextResponse } from 'next/server';
import { db } from '@/lib/db';

export async function GET() {
  const sources = await db.scrapingSource.findMany({
    where: { isActive: true },
    orderBy: { lastScrapedAt: 'desc' },
  });

  return NextResponse.json({
    sources: sources.map(s => ({
      id: s.id,
      name: s.name,
      url: s.url,
      category: s.category,
      complexity: s.complexity,
      lastScrapedAt: s.lastScrapedAt,
      lastStatus: s.lastStatus,
      recordsFound: s.recordsFound,
      scrapeIntervalHours: s.scrapeIntervalHours,
    })),
    summary: {
      total: sources.length,
      success: sources.filter(s => s.lastStatus === 'SUCCESS').length,
      partial: sources.filter(s => s.lastStatus === 'PARTIAL').length,
      failed: sources.filter(s => s.lastStatus === 'FAILED').length,
      byCategory: {
        BANK_PORTAL: sources.filter(s => s.category === 'BANK_PORTAL').length,
        GOVERNMENT: sources.filter(s => s.category === 'GOVERNMENT').length,
        AUCTIONEER: sources.filter(s => s.category === 'AUCTIONEER').length,
        FINTECH_DEV: sources.filter(s => s.category === 'FINTECH_DEV').length,
      },
    },
  });
}
