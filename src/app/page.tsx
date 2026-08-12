'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { Progress } from '@/components/ui/progress';
import { 
  Shield, Search, AlertTriangle, Car, Building2, Activity, 
  Clock, Globe, Zap, FileText, MapPin, TrendingUp,
  CheckCircle2, XCircle, AlertOctagon, Eye, Layers,
  Fingerprint, Scale
} from 'lucide-react';

// ─── TYPES ──────────────────────────────────────────────────────────────────────

interface DashboardData {
  summary: {
    totalVehicles: number;
    totalLoanApps: number;
    totalActiveAuctions: number;
    totalFraudFlags: number;
    loanStackingDetections: number;
    avgRiskScore: number;
    sourcesActive: number;
    riskChecksToday: number;
  };
  riskDistribution: Record<string, number>;
  lenderExposure: Record<string, number>;
  flagTypes: Record<string, number>;
  recentChecks: Array<{
    requestId: string;
    queryPlate: string;
    riskScore: number;
    riskLevel: string;
    recommendation: string;
    responseTimeMs: number | null;
    createdAt: string;
  }>;
  vehicles: Array<{
    id: string;
    plate: string;
    rawPlate: string;
    make: string | null;
    model: string | null;
    year: number | null;
    plateCategory: string | null;
    activeLoans: number;
    lenders: string[];
    activeAuctions: number;
    fraudFlags: Array<{ type: string; severity: string; description: string }>;
    currentYard: string | null;
    degreeCentrality: number;
    fraudRingSize: number;
  }>;
  sources: Array<{
    name: string;
    url: string;
    category: string;
    complexity: string;
    lastScrapedAt: string | null;
    lastStatus: string | null;
    recordsFound: number;
    scrapeIntervalHours: number;
  }>;
}

interface RiskCheckResult {
  request_id: string;
  query_registration: string;
  risk_score: number;
  risk_level: string;
  confidence: number;
  flagged_issues: string[];
  entity_summary: Record<string, unknown>;
  graph_analysis: Record<string, unknown>;
  historical_footprints: Array<Record<string, unknown>>;
  recommendation: string;
  score_breakdown?: Record<string, number>;
  compliance_notes?: Record<string, unknown>;
}

// ─── HELPERS ────────────────────────────────────────────────────────────────────

function getRiskColor(level: string): string {
  switch (level) {
    case 'LOW': return 'text-emerald-600';
    case 'MEDIUM': return 'text-amber-600';
    case 'HIGH': return 'text-orange-600';
    case 'CRITICAL': return 'text-red-600';
    default: return 'text-gray-600';
  }
}

function getRiskBg(level: string): string {
  switch (level) {
    case 'LOW': return 'bg-emerald-50 border-emerald-200';
    case 'MEDIUM': return 'bg-amber-50 border-amber-200';
    case 'HIGH': return 'bg-orange-50 border-orange-200';
    case 'CRITICAL': return 'bg-red-50 border-red-200';
    default: return 'bg-gray-50 border-gray-200';
  }
}

function getRiskBadgeVariant(level: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (level) {
    case 'LOW': return 'secondary';
    case 'MEDIUM': return 'outline';
    case 'HIGH': return 'default';
    case 'CRITICAL': return 'destructive';
    default: return 'outline';
  }
}

function formatKES(n: number): string {
  return `KSh ${(n / 1000).toFixed(0)}K`;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function getRecIcon(rec: string) {
  switch (rec) {
    case 'APPROVE_LOAN': return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
    case 'REVIEW_MANUALLY': return <AlertTriangle className="h-4 w-4 text-amber-600" />;
    case 'REJECT_LOAN': return <XCircle className="h-4 w-4 text-red-600" />;
    default: return null;
  }
}

// ─── MAIN COMPONENT ─────────────────────────────────────────────────────────────

export default function Home() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [seeded, setSeeded] = useState(false);

  // Risk check form state
  const [plate, setPlate] = useState('');
  const [chassis, setChassis] = useState('');
  const [mfiId, setMfiId] = useState('MFI-2847');
  const [loanAmount, setLoanAmount] = useState('850000');
  const [checking, setChecking] = useState(false);
  const [riskResult, setRiskResult] = useState<RiskCheckResult | null>(null);

  // Search state
  const [searchQ, setSearchQ] = useState('');
  const [searchResults, setSearchResults] = useState<Array<Record<string, unknown>>>([]);

  const loadData = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/dashboard/stats');
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    // Auto-seed then load
    const init = async () => {
      try {
        const seedRes = await fetch('/api/seed');
        if (seedRes.ok) {
          const seedJson = await seedRes.json();
          if (seedJson.vehicleCount > 0) setSeeded(true);
        }
      } catch { /* ignore */ }
      loadData();
    };
    init();
  }, [loadData]);

  const handleRiskCheck = async () => {
    if (!plate) return;
    setChecking(true);
    setRiskResult(null);
    try {
      const res = await fetch('/api/v1/collateral/risk-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query_registration: plate,
          query_chassis: chassis || undefined,
          requestor_mfi_id: mfiId,
          loan_amount_kes: parseInt(loanAmount) || undefined,
        }),
      });
      if (res.ok) {
        const json = await res.json();
        setRiskResult(json);
        loadData(); // refresh dashboard
      }
    } catch { /* ignore */ }
    setChecking(false);
  };

  const handleSearch = async () => {
    if (!searchQ) return;
    try {
      const res = await fetch(`/api/v1/vehicles/search?q=${encodeURIComponent(searchQ)}`);
      if (res.ok) {
        const json = await res.json();
        setSearchResults(json.results);
      }
    } catch { /* ignore */ }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950">
        <div className="flex flex-col items-center gap-4">
          <div className="h-12 w-12 rounded-full border-4 border-emerald-500 border-t-transparent animate-spin" />
          <p className="text-slate-400 font-mono text-sm">Initializing Risk Engine...</p>
        </div>
      </div>
    );
  }

  const s = data?.summary ?? { totalVehicles: 0, totalLoanApps: 0, totalActiveAuctions: 0, totalFraudFlags: 0, loanStackingDetections: 0, avgRiskScore: 0, sourcesActive: 0, riskChecksToday: 0 };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* ─── HEADER ──────────────────────────────────────────────────────────── */}
      <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-lg bg-emerald-600 flex items-center justify-center">
              <Shield className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-tight text-white">Vehicle Collateral Risk Engine</h1>
              <p className="text-[10px] text-slate-500 font-mono">B2B • Kenya Market • Graph-Native Fraud Detection</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <Badge variant="outline" className="text-[10px] font-mono border-emerald-700 text-emerald-400">
              <Activity className="h-3 w-3 mr-1" /> LIVE
            </Badge>
            <Badge variant="outline" className="text-[10px] font-mono border-slate-700 text-slate-400">
              ODPC: DCP-2026-8847
            </Badge>
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6">
        {/* ─── KPI ROW ───────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3 mb-6">
          {[
            { label: 'Vehicles', value: s.totalVehicles, icon: Car, color: 'text-sky-400' },
            { label: 'Loan Apps', value: s.totalLoanApps, icon: FileText, color: 'text-violet-400' },
            { label: 'Active Auctions', value: s.totalActiveAuctions, icon: Layers, color: 'text-orange-400' },
            { label: 'Fraud Flags', value: s.totalFraudFlags, icon: AlertOctagon, color: 'text-red-400' },
            { label: 'Loan Stacking', value: s.loanStackingDetections, icon: AlertTriangle, color: 'text-red-400' },
            { label: 'Avg Risk', value: s.avgRiskScore, icon: TrendingUp, color: s.avgRiskScore > 60 ? 'text-red-400' : 'text-emerald-400' },
            { label: 'Sources', value: s.sourcesActive, icon: Globe, color: 'text-cyan-400' },
            { label: 'Checks Today', value: s.riskChecksToday, icon: Zap, color: 'text-amber-400' },
          ].map((kpi) => (
            <Card key={kpi.label} className="bg-slate-900/50 border-slate-800">
              <CardContent className="p-3">
                <div className="flex items-center gap-2 mb-1">
                  <kpi.icon className={`h-3.5 w-3.5 ${kpi.color}`} />
                  <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">{kpi.label}</span>
                </div>
                <p className="text-xl font-bold text-white">{kpi.value}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* ─── MAIN TABS ─────────────────────────────────────────────────────── */}
        <Tabs defaultValue="risk-check" className="space-y-4">
          <TabsList className="bg-slate-900 border border-slate-800">
            <TabsTrigger value="risk-check" className="data-[state=active]:bg-emerald-600 data-[state=active]:text-white text-xs">
              <Shield className="h-3.5 w-3.5 mr-1.5" /> Risk Check
            </TabsTrigger>
            <TabsTrigger value="vehicles" className="data-[state=active]:bg-emerald-600 data-[state=active]:text-white text-xs">
              <Car className="h-3.5 w-3.5 mr-1.5" /> Vehicle Graph
            </TabsTrigger>
            <TabsTrigger value="alerts" className="data-[state=active]:bg-emerald-600 data-[state=active]:text-white text-xs">
              <AlertTriangle className="h-3.5 w-3.5 mr-1.5" /> Fraud Alerts
            </TabsTrigger>
            <TabsTrigger value="sources" className="data-[state=active]:bg-emerald-600 data-[state=active]:text-white text-xs">
              <Globe className="h-3.5 w-3.5 mr-1.5" /> Sources
            </TabsTrigger>
          </TabsList>

          {/* ─── RISK CHECK TAB ──────────────────────────────────────────────── */}
          <TabsContent value="risk-check" className="space-y-4">
            <div className="grid lg:grid-cols-5 gap-4">
              {/* Form */}
              <Card className="lg:col-span-2 bg-slate-900/50 border-slate-800">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold text-white">Collateral Risk Check</CardTitle>
                  <CardDescription className="text-xs text-slate-500">
                    Query the knowledge graph for vehicle collateral risk. Uses hybrid entity resolution (Jaro-Winkler + Levenshtein + Transformer embeddings) and graph-based fraud detection.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label className="text-xs text-slate-400 font-mono">Registration Number</Label>
                    <Input
                      placeholder="e.g. KDA 123X"
                      value={plate}
                      onChange={e => setPlate(e.target.value)}
                      className="bg-slate-800 border-slate-700 text-white placeholder:text-slate-600 font-mono"
                      onKeyDown={e => e.key === 'Enter' && handleRiskCheck()}
                    />
                    <p className="text-[10px] text-slate-600">Kenyan format: KXX 123X (private), GK/GKA/GKB (government)</p>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs text-slate-400 font-mono">Chassis Number (optional)</Label>
                    <Input
                      placeholder="e.g. JTEBU3JR3B5045181"
                      value={chassis}
                      onChange={e => setChassis(e.target.value)}
                      className="bg-slate-800 border-slate-700 text-white placeholder:text-slate-600 font-mono text-xs"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                      <Label className="text-xs text-slate-400 font-mono">Requestor MFI ID</Label>
                      <Input value={mfiId} onChange={e => setMfiId(e.target.value)} className="bg-slate-800 border-slate-700 text-white font-mono text-xs" />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs text-slate-400 font-mono">Loan Amount (KES)</Label>
                      <Input value={loanAmount} onChange={e => setLoanAmount(e.target.value)} className="bg-slate-800 border-slate-700 text-white font-mono text-xs" />
                    </div>
                  </div>
                  <Button
                    onClick={handleRiskCheck}
                    disabled={checking || !plate}
                    className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm"
                  >
                    {checking ? (
                      <><div className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2" /> Analyzing Graph...</>
                    ) : (
                      <><Shield className="h-4 w-4 mr-2" /> Run Risk Check</>
                    )}
                  </Button>

                  {/* Entity Resolution Demo */}
                  <Separator className="bg-slate-800" />
                  <div className="space-y-2">
                    <Label className="text-xs text-slate-400 font-mono">Quick Search</Label>
                    <div className="flex gap-2">
                      <Input
                        placeholder="Search plates, makes, models..."
                        value={searchQ}
                        onChange={e => setSearchQ(e.target.value)}
                        className="bg-slate-800 border-slate-700 text-white placeholder:text-slate-600 font-mono text-xs"
                        onKeyDown={e => e.key === 'Enter' && handleSearch()}
                      />
                      <Button variant="outline" size="sm" onClick={handleSearch} className="border-slate-700 text-slate-400 hover:text-white shrink-0">
                        <Search className="h-4 w-4" />
                      </Button>
                    </div>
                    {searchResults.length > 0 && (
                      <div className="max-h-32 overflow-y-auto space-y-1 mt-2">
                        {searchResults.map((v: Record<string, unknown>) => (
                          <button
                            key={v.id as string}
                            onClick={() => setPlate(v.raw_plate as string)}
                            className="w-full text-left p-1.5 rounded bg-slate-800/50 hover:bg-slate-800 text-xs font-mono text-slate-300 flex justify-between"
                          >
                            <span>{v.raw_plate as string} — {v.make as string} {v.model as string}</span>
                            <Badge variant="outline" className="text-[9px] h-4 border-slate-700">{v.plate_category as string}</Badge>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Results */}
              <Card className="lg:col-span-3 bg-slate-900/50 border-slate-800">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-semibold text-white">Risk Analysis Result</CardTitle>
                </CardHeader>
                <CardContent>
                  {riskResult ? (
                    <div className="space-y-4">
                      {/* Score Gauge */}
                      <div className={`p-4 rounded-lg border ${getRiskBg(riskResult.risk_level)}`}>
                        <div className="flex items-center justify-between mb-2">
                          <div>
                            <p className="text-xs font-mono text-slate-500">Request ID</p>
                            <p className="text-sm font-mono text-slate-700">{riskResult.request_id}</p>
                          </div>
                          <div className="text-right">
                            <p className={`text-4xl font-black ${getRiskColor(riskResult.risk_level)}`}>
                              {riskResult.risk_score}
                            </p>
                            <Badge variant={getRiskBadgeVariant(riskResult.risk_level)} className="text-xs mt-1">
                              {riskResult.risk_level}
                            </Badge>
                          </div>
                        </div>
                        <Progress
                          value={riskResult.risk_score}
                          className="h-2 bg-slate-200"
                        />
                        <div className="flex items-center justify-between mt-2">
                          <div className="flex items-center gap-1.5">
                            {getRecIcon(riskResult.recommendation)}
                            <span className="text-xs font-semibold text-slate-700">
                              {riskResult.recommendation.replace(/_/g, ' ')}
                            </span>
                          </div>
                          <span className="text-[10px] font-mono text-slate-500">
                            Confidence: {(riskResult.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>

                      {/* Flagged Issues */}
                      {riskResult.flagged_issues.length > 0 && (
                        <div>
                          <p className="text-xs font-mono text-slate-500 uppercase tracking-wider mb-2">Flagged Issues</p>
                          <div className="space-y-1.5">
                            {riskResult.flagged_issues.map((issue: string) => (
                              <div key={issue} className="flex items-center gap-2 p-2 rounded bg-red-950/30 border border-red-900/30">
                                <AlertOctagon className="h-3.5 w-3.5 text-red-400 shrink-0" />
                                <span className="text-xs text-red-300 font-mono">{issue.replace(/_/g, ' ')}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Entity Summary */}
                      {riskResult.entity_summary && (
                        <div>
                          <p className="text-xs font-mono text-slate-500 uppercase tracking-wider mb-2">Entity Summary</p>
                          <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                            {Object.entries(riskResult.entity_summary).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => (
                              <div key={k} className="p-2 rounded bg-slate-800/50">
                                <span className="text-slate-500">{k.replace(/_/g, ' ')}: </span>
                                <span className="text-slate-300">{String(v)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Graph Analysis */}
                      {riskResult.graph_analysis && (
                        <div>
                          <p className="text-xs font-mono text-slate-500 uppercase tracking-wider mb-2">Graph Analysis</p>
                          <div className="grid grid-cols-3 gap-2">
                            {Object.entries(riskResult.graph_analysis).filter(([, v]) => v !== null).map(([k, v]) => (
                              <div key={k} className="p-2 rounded bg-slate-800/50 text-center">
                                <p className="text-lg font-bold text-white">{String(v)}</p>
                                <p className="text-[10px] text-slate-500 font-mono">{k.replace(/_/g, ' ')}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Historical Footprints */}
                      {riskResult.historical_footprints && riskResult.historical_footprints.length > 0 && (
                        <div>
                          <p className="text-xs font-mono text-slate-500 uppercase tracking-wider mb-2">Historical Footprints</p>
                          <div className="space-y-1.5 max-h-40 overflow-y-auto">
                            {riskResult.historical_footprints.map((fp: Record<string, unknown>, i: number) => (
                              <div key={i} className="p-2 rounded bg-slate-800/30 border border-slate-800 text-xs">
                                <div className="flex justify-between items-center mb-1">
                                  <Badge variant="outline" className="text-[9px] h-4 border-slate-700 text-slate-400">{fp.source_type as string}</Badge>
                                  <span className="text-[10px] text-slate-600">{fp.recorded_date as string}</span>
                                </div>
                                <p className="text-slate-400 font-mono">{fp.entity as string}</p>
                                <p className="text-slate-500 mt-0.5">{fp.details as string}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Score Breakdown */}
                      {riskResult.score_breakdown && (
                        <div>
                          <p className="text-xs font-mono text-slate-500 uppercase tracking-wider mb-2">Score Breakdown</p>
                          <div className="space-y-1">
                            {Object.entries(riskResult.score_breakdown).map(([k, v]) => (
                              <div key={k} className="flex justify-between text-xs font-mono p-1.5 rounded bg-slate-800/30">
                                <span className="text-slate-500">{k.replace(/([A-Z])/g, ' $1').trim()}</span>
                                <span className={v > 0 ? 'text-red-400' : 'text-slate-400'}>+{v}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Compliance */}
                      {riskResult.compliance_notes && (
                        <div className="p-3 rounded bg-emerald-950/20 border border-emerald-900/30">
                          <p className="text-[10px] font-mono text-emerald-500 mb-1">COMPLIANCE (Kenya DPA 2019)</p>
                          <p className="text-xs text-emerald-400">{riskResult.compliance_notes.data_source as string}</p>
                          <p className="text-[10px] text-emerald-600 mt-1">ODPC: {riskResult.compliance_notes.odpc_registration as string} • Retention: {riskResult.compliance_notes.retention_policy as string}</p>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-16 text-center">
                      <Shield className="h-12 w-12 text-slate-700 mb-4" />
                      <p className="text-sm text-slate-500 mb-1">Enter a registration number to run a risk check</p>
                      <p className="text-xs text-slate-600">Try: KDA 123X (loan stacking), KAE 321M (clean), KDF 654Z (multi-yard)</p>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Recent Checks */}
            {data && data.recentChecks.length > 0 && (
              <Card className="bg-slate-900/50 border-slate-800">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                    <Clock className="h-4 w-4 text-slate-500" /> Recent Risk Checks
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono">
                      <thead>
                        <tr className="border-b border-slate-800">
                          <th className="text-left py-2 text-slate-500">Request</th>
                          <th className="text-left py-2 text-slate-500">Plate</th>
                          <th className="text-center py-2 text-slate-500">Score</th>
                          <th className="text-center py-2 text-slate-500">Level</th>
                          <th className="text-center py-2 text-slate-500">Decision</th>
                          <th className="text-right py-2 text-slate-500">Latency</th>
                          <th className="text-right py-2 text-slate-500">Time</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.recentChecks.map(rc => (
                          <tr key={rc.requestId} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                            <td className="py-2 text-slate-400">{rc.requestId}</td>
                            <td className="py-2 text-white">{rc.queryPlate}</td>
                            <td className="py-2 text-center">
                              <span className={`font-bold ${getRiskColor(rc.riskLevel)}`}>{rc.riskScore}</span>
                            </td>
                            <td className="py-2 text-center">
                              <Badge variant={getRiskBadgeVariant(rc.riskLevel)} className="text-[9px]">{rc.riskLevel}</Badge>
                            </td>
                            <td className="py-2 text-center">{getRecIcon(rc.recommendation)}</td>
                            <td className="py-2 text-right text-slate-400">{rc.responseTimeMs}ms</td>
                            <td className="py-2 text-right text-slate-500">{timeAgo(rc.createdAt)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* ─── VEHICLE GRAPH TAB ───────────────────────────────────────────── */}
          <TabsContent value="vehicles" className="space-y-4">
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {data?.vehicles.map(v => (
                <Card key={v.id} className={`bg-slate-900/50 border-slate-800 ${v.fraudFlags.length > 0 ? 'ring-1 ring-red-900/30' : ''}`}>
                  <CardContent className="p-4 space-y-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-sm font-bold text-white font-mono">{v.rawPlate}</p>
                        <p className="text-xs text-slate-400">{v.make} {v.model} {v.year && `(${v.year})`}</p>
                      </div>
                      <div className="flex gap-1">
                        {v.plateCategory && (
                          <Badge variant="outline" className="text-[9px] h-4 border-slate-700 text-slate-400">
                            {v.plateCategory}
                          </Badge>
                        )}
                        {v.fraudFlags.length > 0 && (
                          <Badge variant="destructive" className="text-[9px] h-4">
                            {v.fraudFlags.length} flag{v.fraudFlags.length > 1 ? 's' : ''}
                          </Badge>
                        )}
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-2 text-center">
                      <div className="p-1.5 rounded bg-slate-800/50">
                        <p className="text-sm font-bold text-white">{v.activeLoans}</p>
                        <p className="text-[9px] text-slate-500">Loans</p>
                      </div>
                      <div className="p-1.5 rounded bg-slate-800/50">
                        <p className="text-sm font-bold text-white">{v.activeAuctions}</p>
                        <p className="text-[9px] text-slate-500">Auctions</p>
                      </div>
                      <div className="p-1.5 rounded bg-slate-800/50">
                        <p className="text-sm font-bold text-white">{v.fraudRingSize}</p>
                        <p className="text-[9px] text-slate-500">Ring Size</p>
                      </div>
                    </div>

                    {v.lenders.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {v.lenders.map(l => (
                          <Badge key={l} variant="outline" className="text-[9px] h-4 border-violet-800 text-violet-400">
                            <Building2 className="h-2.5 w-2.5 mr-0.5" />{l}
                          </Badge>
                        ))}
                      </div>
                    )}

                    {v.currentYard && (
                      <div className="flex items-center gap-1.5 text-xs text-slate-500">
                        <MapPin className="h-3 w-3" /> {v.currentYard}
                      </div>
                    )}

                    {v.fraudFlags.length > 0 && (
                      <div className="space-y-1">
                        {v.fraudFlags.map((f, i) => (
                          <div key={i} className="flex items-center gap-1.5 text-[10px] text-red-400 font-mono">
                            <AlertTriangle className="h-3 w-3 shrink-0" /> {f.type.replace(/_/g, ' ')}
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="flex items-center justify-between text-[10px] text-slate-600 font-mono pt-1 border-t border-slate-800">
                      <span>Centrality: {v.degreeCentrality}</span>
                      <button onClick={() => { setPlate(v.rawPlate); }} className="text-emerald-500 hover:text-emerald-400 flex items-center gap-1">
                        <Eye className="h-3 w-3" /> Check
                      </button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

          {/* ─── FRAUD ALERTS TAB ────────────────────────────────────────────── */}
          <TabsContent value="alerts" className="space-y-4">
            <div className="grid lg:grid-cols-3 gap-4">
              {/* Flag Type Distribution */}
              <Card className="bg-slate-900/50 border-slate-800">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-semibold text-white">Flag Distribution</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {Object.entries(data?.flagTypes ?? {}).sort((a, b) => b[1] - a[1]).map(([type, count]) => {
                    const max = Math.max(...Object.values(data?.flagTypes ?? { x: 1 }));
                    return (
                      <div key={type} className="space-y-1">
                        <div className="flex justify-between text-xs font-mono">
                          <span className="text-slate-400">{type.replace(/_/g, ' ')}</span>
                          <span className="text-white font-bold">{count}</span>
                        </div>
                        <Progress value={(count / max) * 100} className="h-1.5 bg-slate-800" />
                      </div>
                    );
                  })}
                </CardContent>
              </Card>

              {/* Lender Exposure */}
              <Card className="lg:col-span-2 bg-slate-900/50 border-slate-800">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-semibold text-white">Lender Exposure (Active Loan Volume)</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {Object.entries(data?.lenderExposure ?? {}).sort((a, b) => b[1] - a[1]).map(([lender, amount]) => {
                    const max = Math.max(...Object.values(data?.lenderExposure ?? { x: 1 }));
                    return (
                      <div key={lender} className="space-y-1">
                        <div className="flex justify-between text-xs font-mono">
                          <span className="text-slate-400 flex items-center gap-1.5">
                            <Building2 className="h-3 w-3" /> {lender}
                          </span>
                          <span className="text-white font-bold">{formatKES(amount)}</span>
                        </div>
                        <Progress value={(amount / max) * 100} className="h-1.5 bg-slate-800" />
                      </div>
                    );
                  })}
                </CardContent>
              </Card>
            </div>

            {/* Flagged vehicles list */}
            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold text-white">Flagged Vehicles</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {data?.vehicles.filter(v => v.fraudFlags.length > 0).map(v => (
                    <div key={v.id} className="p-3 rounded-lg bg-red-950/10 border border-red-900/20">
                      <div className="flex items-start justify-between mb-2">
                        <div>
                          <p className="text-sm font-bold text-white font-mono">{v.rawPlate} — {v.make} {v.model}</p>
                          <p className="text-[10px] text-slate-500">{v.activeLoans} active loans • {v.lenders.length} lenders • Ring: {v.fraudRingSize}</p>
                        </div>
                        <button onClick={() => { setPlate(v.rawPlate); }} className="text-[10px] text-emerald-500 hover:text-emerald-400 font-mono flex items-center gap-1">
                          <Eye className="h-3 w-3" /> Inspect
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {v.fraudFlags.map((f, i) => (
                          <Badge key={i} variant="destructive" className="text-[9px]">
                            <AlertTriangle className="h-2.5 w-2.5 mr-0.5" /> {f.type.replace(/_/g, ' ')}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ─── SOURCES TAB ─────────────────────────────────────────────────── */}
          <TabsContent value="sources" className="space-y-4">
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {data?.sources.map(src => (
                <Card key={src.name} className="bg-slate-900/50 border-slate-800">
                  <CardContent className="p-4 space-y-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs font-semibold text-white">{src.name}</p>
                        <p className="text-[10px] text-slate-500 font-mono truncate max-w-[180px]">{src.url}</p>
                      </div>
                      <Badge
                        variant={src.lastStatus === 'SUCCESS' ? 'secondary' : src.lastStatus === 'PARTIAL' ? 'outline' : 'destructive'}
                        className="text-[9px] h-4"
                      >
                        {src.lastStatus ?? 'PENDING'}
                      </Badge>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-center">
                      <div>
                        <p className="text-xs font-bold text-white">{src.recordsFound}</p>
                        <p className="text-[9px] text-slate-500">Records</p>
                      </div>
                      <div>
                        <p className="text-xs font-bold text-white">{src.scrapeIntervalHours}h</p>
                        <p className="text-[9px] text-slate-500">Interval</p>
                      </div>
                      <div>
                        <Badge variant="outline" className="text-[9px] h-4 border-slate-700">
                          {src.complexity}
                        </Badge>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono">
                      <Clock className="h-3 w-3" />
                      {src.lastScrapedAt ? timeAgo(src.lastScrapedAt) : 'Never'}
                    </div>
                    <Badge variant="outline" className="text-[9px] border-slate-700 text-slate-500">
                      {src.category.replace(/_/g, ' ')}
                    </Badge>
                  </CardContent>
                </Card>
              ))}
            </div>

            {/* Anti-Detection Architecture */}
            <Card className="bg-slate-900/50 border-slate-800">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                  <Fingerprint className="h-4 w-4 text-emerald-500" /> Anti-Detection Stack (2026 Standards)
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3 text-xs">
                  {[
                    { layer: 'IP/Proxy', solution: 'Bright Data Residential', detail: 'Kenya sticky sessions, rotate per request for open sources' },
                    { layer: 'TLS Fingerprint', solution: 'Playwright Chrome Stack', detail: 'JA3/JA4 safe — never use Python requests (WAF fingerprint)' },
                    { layer: 'Browser', solution: 'Octo Browser / GoLogin', detail: 'Passes Pixelscan, Iphey, CreepJS — real GPU fingerprinting' },
                    { layer: 'Behavior', solution: 'Human-like Delays', detail: 'Random 1-5s delays, mouse movements, scroll patterns, session warming' },
                    { layer: 'CAPTCHA', solution: '2Captcha / CapSolver', detail: '$1-3 per 1,000 solves — prevention first, solve only when unavoidable' },
                  ].map(item => (
                    <div key={item.layer} className="p-3 rounded bg-slate-800/50 border border-slate-800">
                      <p className="font-mono text-emerald-400 mb-1">{item.layer}</p>
                      <p className="font-semibold text-white mb-1">{item.solution}</p>
                      <p className="text-[10px] text-slate-500">{item.detail}</p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        {/* ─── FOOTER ────────────────────────────────────────────────────────── */}
        <footer className="mt-8 py-4 border-t border-slate-800 text-center">
          <p className="text-[10px] text-slate-600 font-mono">
            Vehicle Collateral Risk Engine v1.0 • Graph-Native Fraud Detection • Kenya DPA 2019 Compliant (ODPC DCP-2026-8847) • Zero PII Architecture
          </p>
          <p className="text-[10px] text-slate-700 font-mono mt-1">
            Entity Resolution: Hybrid Transformer-Gather + Fuzzy-Reconsider (arXiv:2509.17470) • Jaro-Winkler + Levenshtein (arXiv:1607.00992) • tgds/egds Chase (arXiv:2303.07469)
          </p>
        </footer>
      </main>
    </div>
  );
}
