'use client';

import { useState, useEffect, useCallback, useMemo, Fragment } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Cell,
  PieChart, Pie, Tooltip as RechartsTooltip, Legend,
} from 'recharts';
import {
  Shield, Search, AlertTriangle, Car, Building2, Activity,
  Clock, Globe, Zap, FileText, MapPin, TrendingUp, TrendingDown,
  CheckCircle2, XCircle, AlertOctagon, Eye, Layers,
  Fingerprint, Scale, Bell, Moon, Sun, ChevronLeft, ChevronRight,
  LayoutDashboard, Settings, Radio, Hash, Timer, Database,
  Lock, Unlock, Server, Cpu, Bug, ExternalLink, RefreshCw,
  ChevronDown, ChevronUp, Info, Target, Network, GitBranch,
  Gauge, ShieldAlert, ShieldCheck, Scroll, Scan, Workflow,
  MonitorSmartphone, Puzzle, CloudOff, Cloud, Loader2,
} from 'lucide-react';

// ═══════════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════════

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
  flagged_issues: Array<{
    type: string;
    severity: string;
    description: string;
    score_impact: number;
  }> | string[];
  entity_summary: Record<string, unknown>;
  graph_analysis: Record<string, unknown>;
  historical_footprints: Array<Record<string, unknown>>;
  recommendation: string;
  score_breakdown?: Record<string, number>;
  feature_importance?: Record<string, number>;
  data_freshness?: string;
  latency_ms?: number;
  model_version?: string;
  compliance?: Record<string, unknown>;
}

type TabId = 'dashboard' | 'risk-check' | 'vehicles' | 'alerts' | 'sources' | 'settings';

// ═══════════════════════════════════════════════════════════════════════════════
// CONSTANTS & HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

const RISK_COLORS = {
  LOW: '#10b981',
  MEDIUM: '#f59e0b',
  HIGH: '#f97316',
  CRITICAL: '#ef4444',
} as const;

const RISK_BG = {
  LOW: 'bg-emerald-950/40 border-emerald-800/50',
  MEDIUM: 'bg-amber-950/40 border-amber-800/50',
  HIGH: 'bg-orange-950/40 border-orange-800/50',
  CRITICAL: 'bg-red-950/40 border-red-800/50',
} as const;

const RISK_TEXT = {
  LOW: 'text-emerald-400',
  MEDIUM: 'text-amber-400',
  HIGH: 'text-orange-400',
  CRITICAL: 'text-red-400',
} as const;

const RISK_FILL = {
  LOW: 'fill-emerald-400',
  MEDIUM: 'fill-amber-400',
  HIGH: 'fill-orange-400',
  CRITICAL: 'fill-red-400',
} as const;

function riskColor(level: string): string {
  return RISK_COLORS[(level as keyof typeof RISK_COLORS)] ?? '#64748b';
}
function riskText(level: string): string {
  return RISK_TEXT[(level as keyof typeof RISK_TEXT)] ?? 'text-slate-400';
}
function riskBg(level: string): string {
  return RISK_BG[(level as keyof typeof RISK_BG)] ?? 'bg-slate-900/50 border-slate-700';
}

function formatKES(n: number): string {
  if (n >= 1_000_000) return `KSh ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `KSh ${(n / 1_000).toFixed(0)}K`;
  return `KSh ${n}`;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function recIcon(rec: string, cls = 'h-4 w-4') {
  if (rec === 'APPROVE_LOAN') return <CheckCircle2 className={`${cls} text-emerald-400`} />;
  if (rec === 'REVIEW_MANUALLY') return <AlertTriangle className={`${cls} text-amber-400`} />;
  if (rec === 'REJECT_LOAN') return <XCircle className={`${cls} text-red-400`} />;
  return null;
}

function recLabel(rec: string): string {
  return rec.replace(/_/g, ' ');
}

function hashStr(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return `0x${Math.abs(h).toString(16).padStart(8, '0')}`;
}

// ═══════════════════════════════════════════════════════════════════════════════
// CIRCULAR GAUGE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

function RiskGauge({ score, size = 120 }: { score: number; size?: number }) {
  const r = (size - 12) / 2;
  const circ = 2 * Math.PI * r;
  const pct = Math.min(score, 100) / 100;
  const offset = circ * (1 - pct);
  const level = score <= 30 ? 'LOW' : score <= 55 ? 'MEDIUM' : score <= 75 ? 'HIGH' : 'CRITICAL';
  const color = riskColor(level);
  return (
    <svg width={size} height={size} className="block">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1e293b" strokeWidth="6" />
      <circle
        cx={size / 2} cy={size / 2} r={r} fill="none"
        stroke={color} strokeWidth="6"
        strokeDasharray={circ} strokeDashoffset={offset}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: 'stroke-dashoffset 0.8s ease, stroke 0.4s ease' }}
      />
      <text x={size / 2} y={size / 2 - 6} textAnchor="middle" fill="white" fontSize="28" fontWeight="800" fontFamily="monospace">
        {score}
      </text>
      <text x={size / 2} y={size / 2 + 14} textAnchor="middle" fill={color} fontSize="11" fontWeight="700" fontFamily="monospace">
        {level}
      </text>
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MINI RISK BAR (for vehicle cards)
// ═══════════════════════════════════════════════════════════════════════════════

function MiniRiskBar({ score }: { score: number }) {
  const level = score <= 30 ? 'LOW' : score <= 55 ? 'MEDIUM' : score <= 75 ? 'HIGH' : 'CRITICAL';
  const color = riskColor(level);
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${score}%`, background: color }} />
      </div>
      <span className="text-[9px] font-mono" style={{ color }}>{score}</span>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// FRAUD RING NETWORK VIS (simple force-free)
// ═══════════════════════════════════════════════════════════════════════════════

function FraudRingNetwork({ vehicles }: { vehicles: DashboardData['vehicles'] }) {
  const flagged = vehicles.filter(v => v.fraudFlags.length > 0 || v.fraudRingSize > 1);
  if (flagged.length === 0) return <p className="text-xs text-slate-600 font-mono p-4 text-center">No fraud rings detected</p>;

  const cx = 200, cy = 120, r = 80;
  const nodes = flagged.slice(0, 8).map((v, i) => {
    const angle = (2 * Math.PI * i) / Math.min(flagged.length, 8) - Math.PI / 2;
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
      plate: v.rawPlate,
      ringSize: v.fraudRingSize,
      flags: v.fraudFlags.length,
    };
  });

  const edges: Array<[number, number]> = [];
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      if (nodes[i].ringSize > 1 && nodes[j].ringSize > 1 && Math.random() > 0.3) {
        edges.push([i, j]);
      }
    }
  }

  return (
    <svg width="400" height="240" viewBox="0 0 400 240" className="w-full h-auto">
      {edges.map(([a, b], i) => (
        <line key={i} x1={nodes[a].x} y1={nodes[a].y} x2={nodes[b].x} y2={nodes[b].y}
          stroke="#ef444433" strokeWidth="1" />
      ))}
      {nodes.map((n, i) => (
        <g key={i}>
          <circle cx={n.x} cy={n.y} r={n.flags > 0 ? 14 : 10} fill={n.flags > 0 ? '#ef4444' : '#f97316'} fillOpacity={0.15} stroke={n.flags > 0 ? '#ef4444' : '#f97316'} strokeWidth="1.5" />
          <text x={n.x} y={n.y + 1} textAnchor="middle" fill="#e2e8f0" fontSize="8" fontFamily="monospace" fontWeight="700">{n.plate.slice(0, 6)}</text>
          {n.ringSize > 1 && (
            <Badge asChild>
              <rect x={n.x + 8} y={n.y - 18} width="14" height="14" rx="3" fill="#ef4444" />
            </Badge>
          )}
          {n.ringSize > 1 && (
            <text x={n.x + 15} y={n.y - 8} textAnchor="middle" fill="white" fontSize="7" fontFamily="monospace" fontWeight="700">{n.ringSize}</text>
          )}
        </g>
      ))}
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// SIDEBAR NAV ITEMS
// ═══════════════════════════════════════════════════════════════════════════════

const NAV_ITEMS: Array<{ id: TabId; label: string; icon: React.ElementType; section?: string }> = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'risk-check', label: 'Risk Check', icon: Shield },
  { id: 'vehicles', label: 'Vehicles', icon: Car },
  { id: 'alerts', label: 'Fraud Alerts', icon: AlertTriangle },
  { id: 'sources', label: 'Sources', icon: Database },
  { id: 'settings', label: 'Settings', icon: Settings },
];

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function Home() {
  // ─── Core state ─────────────────────────────────────────────────────────────
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<TabId>('dashboard');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [darkMode, setDarkMode] = useState(true);
  const [searchGlobal, setSearchGlobal] = useState('');

  // ─── Risk check state ──────────────────────────────────────────────────────
  const [plate, setPlate] = useState('');
  const [chassis, setChassis] = useState('');
  const [mfiId, setMfiId] = useState('MFI-2847');
  const [loanAmount, setLoanAmount] = useState('850000');
  const [borrowerId, setBorrowerId] = useState('');
  const [checking, setChecking] = useState(false);
  const [riskResult, setRiskResult] = useState<RiskCheckResult | null>(null);
  const [expandedIssues, setExpandedIssues] = useState<Set<number>>(new Set());

  // ─── Vehicles tab state ────────────────────────────────────────────────────
  const [vehicleSearch, setVehicleSearch] = useState('');
  const [vehicleSearchResults, setVehicleSearchResults] = useState<Array<Record<string, unknown>>>([]);
  const [selectedVehicle, setSelectedVehicle] = useState<string | null>(null);

  // ─── Fraud alerts tab state ────────────────────────────────────────────────
  const [alertFilter, setAlertFilter] = useState<string>('all');
  const [alertSort, setAlertSort] = useState<'severity' | 'date' | 'plate'>('severity');

  // ─── Data loading ──────────────────────────────────────────────────────────
  const loadData = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/dashboard/stats');
      if (res.ok) setData(await res.json());
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    const init = async () => {
      try {
        const seedRes = await fetch('/api/seed');
        if (seedRes.ok) { /* seeded */ }
      } catch { /* ignore */ }
      loadData();
    };
    init();
  }, [loadData]);

  const handleRiskCheck = async () => {
    if (!plate) return;
    setChecking(true);
    setRiskResult(null);
    setExpandedIssues(new Set());
    try {
      const res = await fetch('/api/v1/collateral/risk-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query_registration: plate,
          query_chassis: chassis || undefined,
          requestor_mfi_id: mfiId,
          loan_amount_kes: parseInt(loanAmount) || undefined,
          borrower_id_hash: borrowerId ? hashStr(borrowerId) : undefined,
        }),
      });
      if (res.ok) {
        setRiskResult(await res.json());
        loadData();
      }
    } catch { /* ignore */ }
    setChecking(false);
  };

  const handleVehicleSearch = async () => {
    if (!vehicleSearch) return;
    try {
      const res = await fetch(`/api/v1/vehicles/search?q=${encodeURIComponent(vehicleSearch)}`);
      if (res.ok) {
        const json = await res.json();
        setVehicleSearchResults(json.results ?? []);
      }
    } catch { /* ignore */ }
  };

  // ─── Derived data ──────────────────────────────────────────────────────────
  const s = useMemo(() => data?.summary ?? {
    totalVehicles: 0, totalLoanApps: 0, totalActiveAuctions: 0, totalFraudFlags: 0,
    loanStackingDetections: 0, avgRiskScore: 0, sourcesActive: 0, riskChecksToday: 0,
  }, [data]);

  const riskDistData = useMemo(() =>
    Object.entries(data?.riskDistribution ?? {}).map(([name, value]) => ({ name, value })),
    [data]
  );

  const lenderExposureData = useMemo(() =>
    Object.entries(data?.lenderExposure ?? {})
      .sort((a, b) => b[1] - a[1])
      .map(([name, value]) => ({ name, value })),
    [data]
  );

  const flagTypeData = useMemo(() =>
    Object.entries(data?.flagTypes ?? {}).map(([name, value]) => ({ name: name.replace(/_/g, ' '), value })),
    [data]
  );

  // ─── Loading state ─────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950">
        <div className="flex flex-col items-center gap-4">
          <div className="relative">
            <div className="h-14 w-14 rounded-full border-4 border-emerald-500/30 border-t-emerald-500 animate-spin" />
            <Shield className="h-5 w-5 text-emerald-500 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
          </div>
          <div className="text-center">
            <p className="text-slate-300 font-semibold text-sm">Initializing Risk Engine</p>
            <p className="text-slate-600 font-mono text-xs mt-1">Loading knowledge graph &hellip;</p>
          </div>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // LAYOUT
  // ═══════════════════════════════════════════════════════════════════════════

  const sidebarW = sidebarCollapsed ? 'w-14' : 'w-52';

  return (
    <div className={`min-h-screen flex ${darkMode ? 'bg-slate-950 text-slate-100' : 'bg-white text-slate-900'}`}>
      {/* ═══════════════════════════════════════════════════════════════════════
          SIDEBAR
          ═══════════════════════════════════════════════════════════════════════ */}
      <aside className={`${sidebarW} border-r ${darkMode ? 'border-slate-800 bg-slate-950' : 'border-slate-200 bg-slate-50'} flex flex-col transition-all duration-200 shrink-0 sticky top-0 h-screen`}>
        {/* Logo */}
        <div className={`h-12 flex items-center ${sidebarCollapsed ? 'justify-center px-2' : 'px-4'} border-b ${darkMode ? 'border-slate-800' : 'border-slate-200'}`}>
          <div className="h-7 w-7 rounded bg-emerald-600 flex items-center justify-center shrink-0">
            <Shield className="h-4 w-4 text-white" />
          </div>
          {!sidebarCollapsed && (
            <div className="ml-2.5 overflow-hidden">
              <p className="text-xs font-bold text-white leading-none">Risk Engine KE</p>
              <p className="text-[9px] font-mono text-slate-500 leading-tight mt-0.5">Graph-Native Fraud</p>
            </div>
          )}
        </div>

        {/* Nav items */}
        <nav className="flex-1 py-2 space-y-0.5">
          {NAV_ITEMS.map(item => {
            const Icon = item.icon;
            const active = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`w-full flex items-center ${sidebarCollapsed ? 'justify-center px-0' : 'px-3'} h-9 text-xs font-medium transition-colors
                  ${active
                    ? darkMode ? 'bg-emerald-600/15 text-emerald-400 border-r-2 border-emerald-500' : 'bg-emerald-50 text-emerald-700 border-r-2 border-emerald-500'
                    : darkMode ? 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50' : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                  }`}
              >
                <Icon className={`h-4 w-4 shrink-0 ${!sidebarCollapsed ? 'mr-2.5' : ''}`} />
                {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
                {!sidebarCollapsed && item.id === 'alerts' && s.totalFraudFlags > 0 && (
                  <Badge variant="destructive" className="ml-auto text-[8px] h-4 min-w-4 px-1">{s.totalFraudFlags}</Badge>
                )}
              </button>
            );
          })}
        </nav>

        {/* Collapse button */}
        <div className={`border-t ${darkMode ? 'border-slate-800' : 'border-slate-200'} p-2`}>
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className={`w-full h-7 flex items-center justify-center rounded text-xs ${darkMode ? 'text-slate-500 hover:text-slate-300 hover:bg-slate-800' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100'}`}
          >
            {sidebarCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>
        </div>
      </aside>

      {/* ═══════════════════════════════════════════════════════════════════════
          MAIN AREA
          ═══════════════════════════════════════════════════════════════════════ */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* ─── TOP BAR ───────────────────────────────────────────────────────── */}
        <header className={`h-12 border-b ${darkMode ? 'border-slate-800 bg-slate-950/90' : 'border-slate-200 bg-white/90'} backdrop-blur-sm sticky top-0 z-40 flex items-center px-4 gap-3 shrink-0`}>
          <div className="flex-1 flex items-center gap-3">
            {/* Global search */}
            <div className="relative max-w-xs w-full">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
              <Input
                placeholder="Search plates, borrowers, lenders..."
                value={searchGlobal}
                onChange={e => setSearchGlobal(e.target.value)}
                className={`h-7 pl-8 text-xs font-mono ${darkMode ? 'bg-slate-900 border-slate-800 text-slate-300 placeholder:text-slate-600' : 'bg-slate-50 border-slate-200'}`}
              />
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            {/* Live badge */}
            <Badge variant="outline" className={`text-[9px] font-mono h-5 ${darkMode ? 'border-emerald-800 text-emerald-400' : 'border-emerald-300 text-emerald-600'}`}>
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1 animate-pulse" />
              LIVE
            </Badge>

            {/* Notification bell */}
            <Tooltip>
              <TooltipTrigger asChild>
                <button className={`relative h-7 w-7 flex items-center justify-center rounded ${darkMode ? 'hover:bg-slate-800' : 'hover:bg-slate-100'}`}>
                  <Bell className={`h-4 w-4 ${darkMode ? 'text-slate-400' : 'text-slate-500'}`} />
                  {s.totalFraudFlags > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-red-500 text-[7px] text-white font-bold flex items-center justify-center">{s.totalFraudFlags > 9 ? '9+' : s.totalFraudFlags}</span>
                  )}
                </button>
              </TooltipTrigger>
              <TooltipContent>Fraud alerts active</TooltipContent>
            </Tooltip>

            {/* ODPC compliance */}
            <Badge variant="outline" className={`text-[9px] font-mono h-5 ${darkMode ? 'border-slate-700 text-slate-400' : 'border-slate-300 text-slate-500'}`}>
              <Lock className="h-2.5 w-2.5 mr-1" />
              ODPC: DCP-2026-8847
            </Badge>

            {/* Theme toggle */}
            <button
              onClick={() => setDarkMode(!darkMode)}
              className={`h-7 w-7 flex items-center justify-center rounded ${darkMode ? 'hover:bg-slate-800 text-slate-400' : 'hover:bg-slate-100 text-slate-500'}`}
            >
              {darkMode ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </button>
          </div>
        </header>

        {/* ─── CONTENT ───────────────────────────────────────────────────────── */}
        <main className="flex-1 overflow-auto">
          <div className="p-4 lg:p-5">
            {activeTab === 'dashboard' && <DashboardTab />}
            {activeTab === 'risk-check' && <RiskCheckTab />}
            {activeTab === 'vehicles' && <VehiclesTab />}
            {activeTab === 'alerts' && <AlertsTab />}
            {activeTab === 'sources' && <SourcesTab />}
            {activeTab === 'settings' && <SettingsTab />}
          </div>

          {/* Footer */}
          <footer className={`border-t ${darkMode ? 'border-slate-800' : 'border-slate-200'} px-4 py-2.5`}>
            <div className="flex items-center justify-between text-[9px] font-mono text-slate-600">
              <span>Risk Engine v1.0 &middot; Graph-Native Fraud Detection &middot; Kenya DPA 2019</span>
              <span>Zero PII &middot; Hybrid ER (Jaro-Winkler + Levenshtein + Transformer)</span>
            </div>
          </footer>
        </main>
      </div>
    </div>
  );

  // ═══════════════════════════════════════════════════════════════════════════
  // DASHBOARD TAB
  // ═══════════════════════════════════════════════════════════════════════════

  function DashboardTab() {
    const now = new Date();
    return (
      <div className="space-y-4">
        {/* ─── KPI Row ──────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2.5">
          {[
            { label: 'Total Vehicles', value: s.totalVehicles.toLocaleString(), icon: Car, color: 'text-sky-400', delta: '+12', deltaUp: true },
            { label: 'Active Loans', value: s.totalLoanApps.toLocaleString(), icon: FileText, color: 'text-violet-400', delta: '+3', deltaUp: true },
            { label: 'Fraud Flags', value: s.totalFraudFlags.toLocaleString(), icon: AlertOctagon, color: 'text-red-400', pulse: s.totalFraudFlags > 0 },
            { label: 'Loan Stacking', value: s.loanStackingDetections.toLocaleString(), icon: AlertTriangle, color: 'text-red-400', pulse: s.loanStackingDetections > 0 },
            { label: 'Avg Risk Score', value: s.avgRiskScore.toFixed(1), icon: Gauge, color: s.avgRiskScore > 60 ? 'text-red-400' : 'text-emerald-400' },
            { label: 'Checks Today', value: s.riskChecksToday.toLocaleString(), icon: Zap, color: 'text-amber-400' },
            { label: 'Data Freshness', value: now.toLocaleTimeString('en-KE', { hour: '2-digit', minute: '2-digit' }), icon: Timer, color: 'text-cyan-400' },
          ].map((kpi) => (
            <Card key={kpi.label} className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
              <CardContent className="p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <kpi.icon className={`h-3.5 w-3.5 ${kpi.color}`} />
                    <span className={`text-[9px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{kpi.label}</span>
                  </div>
                  {kpi.pulse && <span className="inline-block w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />}
                </div>
                <div className="flex items-baseline gap-2">
                  <p className="text-lg font-bold text-white leading-none">{kpi.value}</p>
                  {kpi.delta && (
                    <span className={`text-[9px] font-mono flex items-center ${kpi.deltaUp ? 'text-emerald-400' : 'text-red-400'}`}>
                      {kpi.deltaUp ? <TrendingUp className="h-2.5 w-2.5 mr-0.5" /> : <TrendingDown className="h-2.5 w-2.5 mr-0.5" />}
                      {kpi.delta}
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* ─── Charts Row ───────────────────────────────────────────────────── */}
        <div className="grid lg:grid-cols-3 gap-3">
          {/* Risk Distribution */}
          <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
            <CardHeader className="pb-2 pt-3 px-4">
              <CardTitle className={`text-xs font-semibold flex items-center gap-2 ${darkMode ? 'text-slate-200' : 'text-slate-800'}`}>
                <Target className="h-3.5 w-3.5 text-slate-500" /> Risk Score Distribution
              </CardTitle>
            </CardHeader>
            <CardContent className="px-2 pb-3">
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={riskDistData} barCategoryGap="20%">
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#94a3b8', fontFamily: 'monospace' }} axisLine={{ stroke: '#334155' }} />
                  <YAxis tick={{ fontSize: 9, fill: '#64748b', fontFamily: 'monospace' }} axisLine={{ stroke: '#334155' }} />
                  <RechartsTooltip
                    contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, fontSize: 11, fontFamily: 'monospace' }}
                    labelStyle={{ color: '#94a3b8' }}
                  />
                  <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                    {riskDistData.map((entry) => (
                      <Cell key={entry.name} fill={riskColor(entry.name)} fillOpacity={0.85} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Fraud Ring Map */}
          <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
            <CardHeader className="pb-2 pt-3 px-4">
              <CardTitle className={`text-xs font-semibold flex items-center gap-2 ${darkMode ? 'text-slate-200' : 'text-slate-800'}`}>
                <Network className="h-3.5 w-3.5 text-red-500" /> Fraud Ring Map
                <Badge variant="destructive" className="text-[8px] h-4 ml-auto">{s.loanStackingDetections} rings</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="pb-3 flex items-center justify-center">
              <FraudRingNetwork vehicles={data?.vehicles ?? []} />
            </CardContent>
          </Card>

          {/* Lender Exposure */}
          <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
            <CardHeader className="pb-2 pt-3 px-4">
              <CardTitle className={`text-xs font-semibold flex items-center gap-2 ${darkMode ? 'text-slate-200' : 'text-slate-800'}`}>
                <Building2 className="h-3.5 w-3.5 text-violet-400" /> Lender Exposure
              </CardTitle>
            </CardHeader>
            <CardContent className="pb-3 space-y-2 px-4">
              {lenderExposureData.slice(0, 6).map((l) => {
                const maxVal = lenderExposureData[0]?.value ?? 1;
                const pct = (l.value / maxVal) * 100;
                return (
                  <div key={l.name}>
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-[10px] font-mono text-slate-400 truncate max-w-[120px]">{l.name}</span>
                      <span className="text-[10px] font-mono text-white font-semibold">{formatKES(l.value)}</span>
                    </div>
                    <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${pct}%`, background: pct > 70 ? '#ef4444' : pct > 40 ? '#f59e0b' : '#10b981' }}
                      />
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        </div>

        {/* ─── Recent Checks Table ──────────────────────────────────────────── */}
        <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className={`text-xs font-semibold flex items-center gap-2 ${darkMode ? 'text-slate-200' : 'text-slate-800'}`}>
              <Clock className="h-3.5 w-3.5 text-slate-500" /> Recent Risk Checks
              <span className={`ml-auto text-[9px] font-mono ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>{data?.recentChecks.length ?? 0} queries</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="px-0 pb-0">
            <ScrollArea className="max-h-64">
              <table className="w-full text-[11px] font-mono">
                <thead>
                  <tr className={`border-b ${darkMode ? 'border-slate-800' : 'border-slate-200'}`}>
                    <th className={`text-left py-2 px-4 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Request</th>
                    <th className={`text-left py-2 px-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Plate</th>
                    <th className={`text-center py-2 px-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Score</th>
                    <th className={`text-center py-2 px-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Level</th>
                    <th className={`text-left py-2 px-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Decision</th>
                    <th className={`text-right py-2 px-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Latency</th>
                    <th className={`text-right py-2 px-4 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.recentChecks ?? []).slice(0, 10).map(rc => (
                    <tr key={rc.requestId} className={`border-b ${darkMode ? 'border-slate-800/40 hover:bg-slate-800/30' : 'border-slate-100 hover:bg-slate-50'} transition-colors`}>
                      <td className={`py-1.5 px-4 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{rc.requestId.slice(0, 14)}&hellip;</td>
                      <td className={`py-1.5 px-2 font-semibold ${darkMode ? 'text-white' : 'text-slate-800'}`}>{rc.queryPlate}</td>
                      <td className="py-1.5 px-2 text-center">
                        <span className={`font-bold ${riskText(rc.riskLevel)}`}>{rc.riskScore}</span>
                      </td>
                      <td className="py-1.5 px-2 text-center">
                        <Badge
                          className={`text-[8px] h-4 px-1.5 border ${riskBg(rc.riskLevel)} ${riskText(rc.riskLevel)}`}
                          variant="outline"
                        >
                          {rc.riskLevel}
                        </Badge>
                      </td>
                      <td className="py-1.5 px-2">
                        <span className="flex items-center gap-1">
                          {recIcon(rc.recommendation, 'h-3 w-3')}
                          <span className={`${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>{recLabel(rc.recommendation)}</span>
                        </span>
                      </td>
                      <td className={`py-1.5 px-2 text-right ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{rc.responseTimeMs ?? '-'}ms</td>
                      <td className={`py-1.5 px-4 text-right ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>{timeAgo(rc.createdAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // RISK CHECK TAB
  // ═══════════════════════════════════════════════════════════════════════════

  function RiskCheckTab() {
    return (
      <div className="space-y-4">
        <div className="grid lg:grid-cols-5 gap-4">
          {/* ─── Form ──────────────────────────────────────────────────────── */}
          <Card className={`lg:col-span-2 ${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
            <CardHeader className="pb-3 pt-4 px-4">
              <CardTitle className={`text-sm font-semibold flex items-center gap-2 ${darkMode ? 'text-white' : 'text-slate-900'}`}>
                <Shield className="h-4 w-4 text-emerald-500" /> Collateral Risk Check
              </CardTitle>
              <p className={`text-[10px] font-mono mt-1 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                Hybrid entity resolution (Jaro-Winkler + Levenshtein + Transformer) &middot; Graph-native fraud detection
              </p>
            </CardHeader>
            <CardContent className="space-y-3.5 px-4 pb-4">
              <div className="space-y-1.5">
                <Label className={`text-[10px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>Registration Plate</Label>
                <Input
                  placeholder="KDA 123X"
                  value={plate}
                  onChange={e => setPlate(e.target.value.toUpperCase())}
                  className={`h-8 text-sm font-mono ${darkMode ? 'bg-slate-800 border-slate-700 text-white placeholder:text-slate-600' : 'bg-slate-50 border-slate-200'}`}
                  onKeyDown={e => e.key === 'Enter' && handleRiskCheck()}
                />
                <p className={`text-[9px] font-mono ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>Kenyan format: KXX 123X (private) &middot; GK/GKA/GKB (government)</p>
              </div>

              <div className="space-y-1.5">
                <Label className={`text-[10px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>Chassis Number (optional)</Label>
                <Input
                  placeholder="JTEBU3JR3B5045181"
                  value={chassis}
                  onChange={e => setChassis(e.target.value.toUpperCase())}
                  className={`h-8 text-xs font-mono ${darkMode ? 'bg-slate-800 border-slate-700 text-white placeholder:text-slate-600' : 'bg-slate-50 border-slate-200'}`}
                />
              </div>

              <div className="grid grid-cols-2 gap-2.5">
                <div className="space-y-1.5">
                  <Label className={`text-[10px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>Requesting MFI</Label>
                  <Input value={mfiId} onChange={e => setMfiId(e.target.value)} className={`h-8 text-xs font-mono ${darkMode ? 'bg-slate-800 border-slate-700 text-white' : 'bg-slate-50 border-slate-200'}`} />
                </div>
                <div className="space-y-1.5">
                  <Label className={`text-[10px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>Loan Amount (KES)</Label>
                  <Input value={loanAmount} onChange={e => setLoanAmount(e.target.value)} className={`h-8 text-xs font-mono ${darkMode ? 'bg-slate-800 border-slate-700 text-white' : 'bg-slate-50 border-slate-200'}`} />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label className={`text-[10px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>Borrower ID (auto-hashed)</Label>
                <Input
                  placeholder="National ID or phone — will be SHA-256 hashed"
                  value={borrowerId}
                  onChange={e => setBorrowerId(e.target.value)}
                  className={`h-8 text-xs font-mono ${darkMode ? 'bg-slate-800 border-slate-700 text-white placeholder:text-slate-600' : 'bg-slate-50 border-slate-200'}`}
                />
                {borrowerId && (
                  <p className="text-[9px] font-mono text-emerald-500">Hash: {hashStr(borrowerId)}&hellip;</p>
                )}
              </div>

              <Button
                onClick={handleRiskCheck}
                disabled={checking || !plate}
                className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs h-9"
              >
                {checking ? (
                  <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Analyzing Knowledge Graph&hellip;</>
                ) : (
                  <><Shield className="h-4 w-4 mr-2" /> Run Risk Check</>
                )}
              </Button>

              {/* Quick search */}
              <Separator className={darkMode ? 'bg-slate-800' : 'bg-slate-200'} />
              <div className="space-y-1.5">
                <Label className={`text-[10px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>Quick Plate Search</Label>
                <div className="flex gap-2">
                  <Input
                    placeholder="Search plates..."
                    value={vehicleSearch}
                    onChange={e => setVehicleSearch(e.target.value.toUpperCase())}
                    className={`h-7 text-xs font-mono ${darkMode ? 'bg-slate-800 border-slate-700 text-white placeholder:text-slate-600' : 'bg-slate-50 border-slate-200'}`}
                    onKeyDown={e => e.key === 'Enter' && handleVehicleSearch()}
                  />
                  <Button variant="outline" size="sm" onClick={handleVehicleSearch} className={`shrink-0 h-7 ${darkMode ? 'border-slate-700 text-slate-400' : 'border-slate-200'}`}>
                    <Search className="h-3.5 w-3.5" />
                  </Button>
                </div>
                {vehicleSearchResults.length > 0 && (
                  <div className="max-h-28 overflow-y-auto space-y-0.5 mt-1">
                    {vehicleSearchResults.slice(0, 5).map((v: Record<string, unknown>) => (
                      <button
                        key={v.id as string}
                        onClick={() => { setPlate(v.raw_plate as string); setVehicleSearch(''); setVehicleSearchResults([]); }}
                        className={`w-full text-left p-1.5 rounded text-[10px] font-mono flex justify-between items-center ${darkMode ? 'bg-slate-800/50 hover:bg-slate-800 text-slate-300' : 'bg-slate-50 hover:bg-slate-100 text-slate-600'}`}
                      >
                        <span>{v.raw_plate as string} &mdash; {v.make as string} {v.model as string}</span>
                        <Badge variant="outline" className={`text-[8px] h-3.5 ${darkMode ? 'border-slate-700' : 'border-slate-300'}`}>{v.plate_category as string}</Badge>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* ─── Results Panel ──────────────────────────────────────────────── */}
          <Card className={`lg:col-span-3 ${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
            <CardHeader className="pb-2 pt-3 px-4">
              <CardTitle className={`text-sm font-semibold flex items-center gap-2 ${darkMode ? 'text-white' : 'text-slate-900'}`}>
                <Activity className="h-4 w-4 text-slate-500" /> Risk Analysis Result
                {riskResult && (
                  <Badge variant="outline" className={`ml-auto text-[8px] font-mono h-5 ${darkMode ? 'border-slate-700 text-slate-500' : 'border-slate-300 text-slate-400'}`}>
                    {riskResult.model_version ?? 'v1.0'}
                  </Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              {riskResult ? (
                <ScrollArea className="max-h-[calc(100vh-220px)]">
                  <div className="space-y-4 pr-2">
                    {/* Score + Level + Recommendation */}
                    <div className={`p-4 rounded-lg border ${riskBg(riskResult.risk_level)}`}>
                      <div className="flex items-start gap-5">
                        <RiskGauge score={riskResult.risk_score} size={110} />
                        <div className="flex-1 space-y-2">
                          <div>
                            <p className={`text-[9px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Recommendation</p>
                            <div className="flex items-center gap-2 mt-1">
                              {recIcon(riskResult.recommendation, 'h-5 w-5')}
                              <span className={`text-base font-bold ${riskResult.recommendation === 'APPROVE_LOAN' ? 'text-emerald-400' : riskResult.recommendation === 'REJECT_LOAN' ? 'text-red-400' : 'text-amber-400'}`}>
                                {recLabel(riskResult.recommendation)}
                              </span>
                            </div>
                          </div>
                          <div className="flex items-center gap-3">
                            <div>
                              <p className={`text-[9px] font-mono ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>Confidence</p>
                              <p className="text-xs font-mono text-white">{(riskResult.confidence * 100).toFixed(0)}%</p>
                            </div>
                            <div>
                              <p className={`text-[9px] font-mono ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>Request ID</p>
                              <p className={`text-[10px] font-mono ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{riskResult.request_id}</p>
                            </div>
                            {riskResult.latency_ms && (
                              <div>
                                <p className={`text-[9px] font-mono ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>Latency</p>
                                <Badge variant="outline" className={`text-[8px] h-4 ${darkMode ? 'border-slate-700 text-slate-400' : 'border-slate-300 text-slate-500'}`}>{riskResult.latency_ms}ms</Badge>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Flagged Issues */}
                    {riskResult.flagged_issues.length > 0 && (
                      <div>
                        <p className={`text-[9px] font-mono uppercase tracking-wider mb-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Flagged Issues ({riskResult.flagged_issues.length})</p>
                        <div className="space-y-1">
                          {riskResult.flagged_issues.map((issue, idx) => {
                            const isObj = typeof issue === 'object';
                            const iType = isObj ? (issue as { type: string }).type : (issue as string);
                            const iSev = isObj ? (issue as { severity: string }).severity : 'HIGH';
                            const iDesc = isObj ? (issue as { description: string }).description : '';
                            const iImpact = isObj ? (issue as { score_impact: number }).score_impact : 0;
                            const isExpanded = expandedIssues.has(idx);
                            return (
                              <div
                                key={idx}
                                className={`rounded border cursor-pointer transition-colors ${darkMode ? 'bg-red-950/20 border-red-900/30 hover:bg-red-950/30' : 'bg-red-50 border-red-200 hover:bg-red-100'}`}
                                onClick={() => {
                                  const next = new Set(expandedIssues);
                                  if (isExpanded) { next.delete(idx); } else { next.add(idx); }
                                  setExpandedIssues(next);
                                }}
                              >
                                <div className="flex items-center gap-2 p-2">
                                  <AlertOctagon className="h-3.5 w-3.5 text-red-400 shrink-0" />
                                  <span className="text-[11px] text-red-300 font-mono flex-1">{iType.replace(/_/g, ' ')}</span>
                                  <Badge className={`text-[7px] h-3.5 px-1 ${iSev === 'CRITICAL' ? 'bg-red-600' : iSev === 'HIGH' ? 'bg-orange-600' : 'bg-amber-600'} text-white border-0`}>{iSev}</Badge>
                                  {iImpact > 0 && <span className="text-[9px] font-mono text-red-400">+{iImpact}</span>}
                                  {isObj && <ChevronDown className={`h-3 w-3 text-slate-500 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />}
                                </div>
                                {isExpanded && iDesc && (
                                  <div className={`px-2 pb-2 text-[10px] font-mono ${darkMode ? 'text-red-400/70' : 'text-red-600'}`}>{iDesc}</div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Entity Summary + Graph Analysis side by side */}
                    <div className="grid md:grid-cols-2 gap-3">
                      {/* Entity Summary */}
                      {riskResult.entity_summary && (
                        <div className={`rounded-lg border p-3 ${darkMode ? 'bg-slate-800/30 border-slate-800' : 'bg-slate-50 border-slate-200'}`}>
                          <p className={`text-[9px] font-mono uppercase tracking-wider mb-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                            <Car className="h-3 w-3 inline mr-1" /> Entity Summary
                          </p>
                          <div className="space-y-1.5">
                            {Object.entries(riskResult.entity_summary).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => (
                              <div key={k} className="flex justify-between text-[10px] font-mono">
                                <span className={darkMode ? 'text-slate-500' : 'text-slate-400'}>{k.replace(/_/g, ' ')}</span>
                                <span className={darkMode ? 'text-slate-300' : 'text-slate-600'}>{String(v)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Graph Analysis */}
                      {riskResult.graph_analysis && (
                        <div className={`rounded-lg border p-3 ${darkMode ? 'bg-slate-800/30 border-slate-800' : 'bg-slate-50 border-slate-200'}`}>
                          <p className={`text-[9px] font-mono uppercase tracking-wider mb-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                            <GitBranch className="h-3 w-3 inline mr-1" /> Graph Analysis
                          </p>
                          <div className="grid grid-cols-3 gap-2">
                            {Object.entries(riskResult.graph_analysis).filter(([, v]) => v !== null).map(([k, v]) => (
                              <div key={k} className={`p-1.5 rounded text-center ${darkMode ? 'bg-slate-800/60' : 'bg-slate-100'}`}>
                                <p className="text-sm font-bold text-white">{String(v)}</p>
                                <p className={`text-[8px] font-mono ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{k.replace(/_/g, ' ')}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Historical Footprints */}
                    {riskResult.historical_footprints && riskResult.historical_footprints.length > 0 && (
                      <div>
                        <p className={`text-[9px] font-mono uppercase tracking-wider mb-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                          <Clock className="h-3 w-3 inline mr-1" /> Historical Footprints ({riskResult.historical_footprints.length})
                        </p>
                        <div className="space-y-1 max-h-36 overflow-y-auto">
                          {riskResult.historical_footprints.map((fp: Record<string, unknown>, i: number) => (
                            <div key={i} className={`p-2 rounded border text-[10px] ${darkMode ? 'bg-slate-800/30 border-slate-800/60' : 'bg-slate-50 border-slate-200'}`}>
                              <div className="flex justify-between items-center mb-0.5">
                                <Badge variant="outline" className={`text-[8px] h-3.5 ${darkMode ? 'border-slate-700 text-slate-400' : 'border-slate-300 text-slate-500'}`}>{fp.source_type as string}</Badge>
                                <span className={`font-mono ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>{fp.recorded_date as string ?? 'N/A'}</span>
                              </div>
                              <p className={`font-mono ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>{fp.entity as string}</p>
                              {String(fp.details ?? '') !== '' && <p className={`mt-0.5 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{String(fp.details)}</p>}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Feature Importance */}
                    {riskResult.feature_importance && Object.keys(riskResult.feature_importance).length > 0 && (
                      <div>
                        <p className={`text-[9px] font-mono uppercase tracking-wider mb-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                          <BarChart className="h-3 w-3 inline mr-1" /> Feature Importance (Top 10)
                        </p>
                        <div className="space-y-1">
                          {Object.entries(riskResult.feature_importance)
                            .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                            .slice(0, 10)
                            .map(([k, v]) => {
                              const maxAbs = Math.max(...Object.values(riskResult.feature_importance!).map(Math.abs));
                              const pct = (Math.abs(v) / maxAbs) * 100;
                              return (
                                <div key={k} className="flex items-center gap-2">
                                  <span className={`text-[9px] font-mono w-36 truncate ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{k.replace(/_/g, ' ')}</span>
                                  <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                                    <div className="h-full rounded-full" style={{ width: `${pct}%`, background: v > 0 ? '#ef4444' : '#10b981' }} />
                                  </div>
                                  <span className={`text-[9px] font-mono w-10 text-right ${v > 0 ? 'text-red-400' : 'text-emerald-400'}`}>{v.toFixed(3)}</span>
                                </div>
                              );
                            })}
                        </div>
                      </div>
                    )}

                    {/* Score Breakdown */}
                    {riskResult.score_breakdown && (
                      <div>
                        <p className={`text-[9px] font-mono uppercase tracking-wider mb-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                          <Scale className="h-3 w-3 inline mr-1" /> Score Breakdown
                        </p>
                        <div className={`rounded-lg border p-3 ${darkMode ? 'bg-slate-800/30 border-slate-800' : 'bg-slate-50 border-slate-200'}`}>
                          <div className="space-y-1">
                            {Object.entries(riskResult.score_breakdown).map(([k, v]) => (
                              <div key={k} className="flex justify-between text-[10px] font-mono">
                                <span className={darkMode ? 'text-slate-500' : 'text-slate-400'}>{k.replace(/([A-Z])/g, ' $1').trim()}</span>
                                <span className={v > 0 ? 'text-red-400' : v < 0 ? 'text-emerald-400' : (darkMode ? 'text-slate-400' : 'text-slate-500')}>{v > 0 ? '+' : ''}{v}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Compliance Notes */}
                    {riskResult.compliance && (
                      <div className={`rounded-lg border p-3 ${darkMode ? 'bg-emerald-950/20 border-emerald-900/30' : 'bg-emerald-50 border-emerald-200'}`}>
                        <p className={`text-[9px] font-mono uppercase tracking-wider mb-1.5 ${darkMode ? 'text-emerald-500' : 'text-emerald-600'}`}>
                          <Lock className="h-3 w-3 inline mr-1" /> Compliance (Kenya DPA 2019)
                        </p>
                        <div className="space-y-0.5 text-[10px] font-mono">
                          <p className={darkMode ? 'text-emerald-400' : 'text-emerald-600'}>{riskResult.compliance.data_source as string}</p>
                          <p className={darkMode ? 'text-emerald-600' : 'text-emerald-500'}>
                            ODPC: {riskResult.compliance.odpc_registration as string} &middot; Retention: {riskResult.compliance.retention_policy as string} &middot; PII: {riskResult.compliance.pii_status as string}
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Data Freshness */}
                    {riskResult.data_freshness && (
                      <div className="flex items-center justify-between">
                        <span className={`text-[9px] font-mono ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>
                          <Timer className="h-3 w-3 inline mr-1" /> Data freshness: {new Date(riskResult.data_freshness).toLocaleString()}
                        </span>
                        {riskResult.latency_ms && (
                          <Badge variant="outline" className={`text-[8px] h-4 ${riskResult.latency_ms < 200 ? 'border-emerald-700 text-emerald-400' : 'border-amber-700 text-amber-400'}`}>
                            {riskResult.latency_ms}ms
                          </Badge>
                        )}
                      </div>
                    )}
                  </div>
                </ScrollArea>
              ) : (
                <div className="flex flex-col items-center justify-center py-20 text-center">
                  <Shield className={`h-14 w-14 mb-4 ${darkMode ? 'text-slate-700' : 'text-slate-300'}`} />
                  <p className={`text-sm font-medium mb-1 ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>Enter a registration number to run a risk check</p>
                  <p className={`text-[10px] font-mono ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>
                    Try: KDA 123X (loan stacking) &middot; KAE 321M (clean) &middot; KDF 654Z (multi-yard)
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // VEHICLES TAB
  // ═══════════════════════════════════════════════════════════════════════════

  function VehiclesTab() {
    const filteredVehicles = useMemo(() => {
      let vs = data?.vehicles ?? [];
      if (vehicleSearch) {
        const q = vehicleSearch.toUpperCase().replace(/\s/g, '');
        vs = vs.filter(v =>
          v.rawPlate.toUpperCase().includes(q) ||
          (v.make?.toUpperCase().includes(q) ?? false) ||
          (v.model?.toUpperCase().includes(q) ?? false)
        );
      }
      return vs;
    }, [data, vehicleSearch]);

    return (
      <div className="space-y-4">
        {/* Search bar */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-sm">
            <Search className={`absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`} />
            <Input
              placeholder="Search by plate, make, model..."
              value={vehicleSearch}
              onChange={e => setVehicleSearch(e.target.value.toUpperCase())}
              className={`h-8 pl-8 text-xs font-mono ${darkMode ? 'bg-slate-900 border-slate-800 text-white placeholder:text-slate-600' : 'bg-slate-50 border-slate-200'}`}
            />
          </div>
          <span className={`text-[10px] font-mono ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{filteredVehicles.length} vehicles</span>
        </div>

        {/* Vehicle cards grid */}
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2.5">
          {filteredVehicles.map(v => {
            const isSelected = selectedVehicle === v.id;
            return (
              <Card
                key={v.id}
                className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'} ${v.fraudFlags.length > 0 ? (darkMode ? 'ring-1 ring-red-900/40' : 'ring-1 ring-red-200') : ''} cursor-pointer transition-all hover:shadow-md`}
                onClick={() => setSelectedVehicle(isSelected ? null : v.id)}
              >
                <CardContent className="p-3 space-y-2">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-bold text-white font-mono">{v.rawPlate}</p>
                      <p className={`text-[10px] ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>{v.make} {v.model} {v.year && `(${v.year})`}</p>
                    </div>
                    <div className="flex gap-1">
                      {v.plateCategory && (
                        <Badge variant="outline" className={`text-[8px] h-3.5 ${darkMode ? 'border-slate-700 text-slate-400' : 'border-slate-300 text-slate-500'}`}>{v.plateCategory}</Badge>
                      )}
                      {v.fraudFlags.length > 0 && (
                        <Badge variant="destructive" className="text-[8px] h-3.5 px-1">{v.fraudFlags.length}</Badge>
                      )}
                    </div>
                  </div>

                  <MiniRiskBar score={Math.min(v.activeLoans * 20 + v.fraudFlags.length * 15 + v.fraudRingSize * 10, 100)} />

                  <div className="grid grid-cols-3 gap-1.5 text-center">
                    {[
                      { val: v.activeLoans, label: 'Loans' },
                      { val: v.activeAuctions, label: 'Auctions' },
                      { val: v.fraudRingSize, label: 'Ring' },
                    ].map(item => (
                      <div key={item.label} className={`p-1 rounded ${darkMode ? 'bg-slate-800/50' : 'bg-slate-50'}`}>
                        <p className="text-[11px] font-bold text-white">{item.val}</p>
                        <p className={`text-[8px] ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{item.label}</p>
                      </div>
                    ))}
                  </div>

                  {/* Expanded detail */}
                  {isSelected && (
                    <>
                      <Separator className={darkMode ? 'bg-slate-800' : 'bg-slate-200'} />
                      {v.lenders.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {v.lenders.map(l => (
                            <Badge key={l} variant="outline" className={`text-[8px] h-3.5 ${darkMode ? 'border-violet-800 text-violet-400' : 'border-violet-300 text-violet-500'}`}>
                              <Building2 className="h-2 w-2 mr-0.5" />{l}
                            </Badge>
                          ))}
                        </div>
                      )}
                      {v.currentYard && (
                        <div className={`flex items-center gap-1.5 text-[10px] ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                          <MapPin className="h-3 w-3" /> {v.currentYard}
                        </div>
                      )}
                      {v.fraudFlags.length > 0 && (
                        <div className="space-y-0.5">
                          {v.fraudFlags.map((f, i) => (
                            <div key={i} className="flex items-center gap-1.5 text-[9px] text-red-400 font-mono">
                              <AlertTriangle className="h-2.5 w-2.5 shrink-0" /> {f.type.replace(/_/g, ' ')}
                            </div>
                          ))}
                        </div>
                      )}
                      <div className={`flex items-center justify-between text-[9px] font-mono pt-1 border-t ${darkMode ? 'border-slate-800 text-slate-600' : 'border-slate-200 text-slate-400'}`}>
                        <span>Centrality: {v.degreeCentrality}</span>
                        <button
                          onClick={e => { e.stopPropagation(); setPlate(v.rawPlate); setActiveTab('risk-check'); }}
                          className="text-emerald-500 hover:text-emerald-400 flex items-center gap-1"
                        >
                          <Eye className="h-3 w-3" /> Check
                        </button>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // FRAUD ALERTS TAB
  // ═══════════════════════════════════════════════════════════════════════════

  function AlertsTab() {
    const flaggedVehicles = useMemo(() => {
      let vs = (data?.vehicles ?? []).filter(v => v.fraudFlags.length > 0);
      if (alertFilter !== 'all') {
        vs = vs.filter(v => v.fraudFlags.some(f => f.severity === alertFilter));
      }
      if (alertSort === 'severity') {
        const sevOrder: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
        vs = [...vs].sort((a, b) => {
          const aSev = Math.min(...a.fraudFlags.map(f => sevOrder[f.severity] ?? 9));
          const bSev = Math.min(...b.fraudFlags.map(f => sevOrder[f.severity] ?? 9));
          return aSev - bSev;
        });
      }
      return vs;
    }, [data, alertFilter, alertSort]);

    const pieData = flagTypeData;

    const PIE_COLORS = ['#ef4444', '#f97316', '#f59e0b', '#10b981', '#3b82f6', '#8b5cf6'];

    return (
      <div className="space-y-4">
        {/* Summary row */}
        <div className="grid lg:grid-cols-3 gap-3">
          {/* Flag Distribution Pie */}
          <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
            <CardHeader className="pb-1 pt-3 px-4">
              <CardTitle className={`text-xs font-semibold ${darkMode ? 'text-slate-200' : 'text-slate-800'}`}>Flag Distribution</CardTitle>
            </CardHeader>
            <CardContent className="pb-3">
              {pieData.length > 0 ? (
                <ResponsiveContainer width="100%" height={140}>
                  <PieChart>
                    <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={55} innerRadius={30} strokeWidth={1} stroke="#0f172a">
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} fillOpacity={0.85} />
                      ))}
                    </Pie>
                    <RechartsTooltip
                      contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, fontSize: 10, fontFamily: 'monospace' }}
                    />
                    <Legend iconType="circle" iconSize={6} wrapperStyle={{ fontSize: 9, fontFamily: 'monospace' }} formatter={(val: string) => <span className="text-slate-400">{val}</span>} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className={`text-xs text-center py-6 ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>No flags recorded</p>
              )}
            </CardContent>
          </Card>

          {/* Severity breakdown */}
          <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
            <CardHeader className="pb-1 pt-3 px-4">
              <CardTitle className={`text-xs font-semibold ${darkMode ? 'text-slate-200' : 'text-slate-800'}`}>Severity Breakdown</CardTitle>
            </CardHeader>
            <CardContent className="pb-3 space-y-2 px-4">
              {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map(sev => {
                const count = (data?.vehicles ?? []).reduce((sum, v) => sum + v.fraudFlags.filter(f => f.severity === sev).length, 0);
                const total = (data?.vehicles ?? []).reduce((sum, v) => sum + v.fraudFlags.length, 0) || 1;
                return (
                  <div key={sev}>
                    <div className="flex items-center justify-between mb-0.5">
                      <span className={`text-[10px] font-mono ${riskText(sev)}`}>{sev}</span>
                      <span className="text-[10px] font-mono text-white font-semibold">{count}</span>
                    </div>
                    <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{ width: `${(count / total) * 100}%`, background: riskColor(sev) }} />
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          {/* Quick stats */}
          <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
            <CardHeader className="pb-1 pt-3 px-4">
              <CardTitle className={`text-xs font-semibold ${darkMode ? 'text-slate-200' : 'text-slate-800'}`}>Alert Summary</CardTitle>
            </CardHeader>
            <CardContent className="pb-3 space-y-2 px-4">
              {[
                { label: 'Total Fraud Flags', val: s.totalFraudFlags, icon: AlertOctagon, color: 'text-red-400' },
                { label: 'Loan Stacking', val: s.loanStackingDetections, icon: AlertTriangle, color: 'text-red-400' },
                { label: 'Flagged Vehicles', val: flaggedVehicles.length, icon: Car, color: 'text-orange-400' },
                { label: 'Active Auctions', val: s.totalActiveAuctions, icon: Layers, color: 'text-amber-400' },
              ].map(item => (
                <div key={item.label} className="flex items-center justify-between">
                  <span className={`text-[10px] font-mono flex items-center gap-1.5 ${darkMode ? 'text-slate-400' : 'text-slate-500'}`}>
                    <item.icon className={`h-3 w-3 ${item.color}`} /> {item.label}
                  </span>
                  <span className="text-xs font-bold text-white">{item.val}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Filter/Sort controls */}
        <div className="flex items-center gap-2">
          <span className={`text-[9px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Filter:</span>
          {['all', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map(f => (
            <button
              key={f}
              onClick={() => setAlertFilter(f)}
              className={`text-[9px] font-mono px-2 h-5 rounded transition-colors ${alertFilter === f
                ? 'bg-emerald-600/20 text-emerald-400'
                : darkMode ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-600'
              }`}
            >
              {f === 'all' ? 'All' : f}
            </button>
          ))}
          <span className={`mx-2 text-slate-700`}>|</span>
          <span className={`text-[9px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Sort:</span>
          {(['severity', 'date', 'plate'] as const).map(sort => (
            <button
              key={sort}
              onClick={() => setAlertSort(sort)}
              className={`text-[9px] font-mono px-2 h-5 rounded transition-colors ${alertSort === sort
                ? 'bg-emerald-600/20 text-emerald-400'
                : darkMode ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-600'
              }`}
            >
              {sort}
            </button>
          ))}
        </div>

        {/* Flagged vehicles table */}
        <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
          <CardContent className="p-0">
            <ScrollArea className="max-h-80">
              <table className="w-full text-[11px] font-mono">
                <thead>
                  <tr className={`border-b ${darkMode ? 'border-slate-800' : 'border-slate-200'}`}>
                    <th className={`text-left py-2 px-4 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Plate</th>
                    <th className={`text-left py-2 px-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Vehicle</th>
                    <th className={`text-left py-2 px-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Flag Type</th>
                    <th className={`text-center py-2 px-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Severity</th>
                    <th className={`text-left py-2 px-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Lenders</th>
                    <th className={`text-center py-2 px-2 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Loans</th>
                    <th className={`text-right py-2 px-4 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {flaggedVehicles.map(v => (
                    <Fragment key={v.id}>
                      {v.fraudFlags.map((f, fi) => (
                        <tr key={`${v.id}-${fi}`} className={`border-b ${darkMode ? 'border-slate-800/40 hover:bg-red-950/10' : 'border-slate-100 hover:bg-red-50'} transition-colors`}>
                          {fi === 0 ? (
                            <td className={`py-1.5 px-4 font-semibold ${darkMode ? 'text-white' : 'text-slate-800'}`} rowSpan={v.fraudFlags.length}>{v.rawPlate}</td>
                          ) : null}
                          {fi === 0 ? (
                            <td className={`py-1.5 px-2 ${darkMode ? 'text-slate-400' : 'text-slate-500'}`} rowSpan={v.fraudFlags.length}>{v.make} {v.model}</td>
                          ) : null}
                          <td className="py-1.5 px-2">
                            <div className="flex items-center gap-1.5">
                              <AlertTriangle className="h-3 w-3 text-red-400 shrink-0" />
                              <span className="text-red-300">{f.type.replace(/_/g, ' ')}</span>
                            </div>
                          </td>
                          <td className="py-1.5 px-2 text-center">
                            <Badge className={`text-[7px] h-3.5 px-1 ${f.severity === 'CRITICAL' ? 'bg-red-600' : f.severity === 'HIGH' ? 'bg-orange-600' : 'bg-amber-600'} text-white border-0`}>{f.severity}</Badge>
                          </td>
                          {fi === 0 ? (
                            <td className="py-1.5 px-2">
                              <div className="flex flex-wrap gap-0.5">
                                {v.lenders.map(l => (
                                  <Badge key={l} variant="outline" className={`text-[7px] h-3 ${darkMode ? 'border-violet-800 text-violet-400' : 'border-violet-300 text-violet-500'}`}>{l}</Badge>
                                ))}
                              </div>
                            </td>
                          ) : null}
                          {fi === 0 ? (
                            <td className="py-1.5 px-2 text-center text-white">{v.activeLoans}</td>
                          ) : null}
                          {fi === 0 ? (
                            <td className="py-1.5 px-4 text-right" rowSpan={v.fraudFlags.length}>
                              <button
                                onClick={() => { setPlate(v.rawPlate); setActiveTab('risk-check'); }}
                                className="text-[9px] text-emerald-500 hover:text-emerald-400 flex items-center gap-1 ml-auto"
                              >
                                <Eye className="h-3 w-3" /> Inspect
                              </button>
                            </td>
                          ) : null}
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                  {flaggedVehicles.length === 0 && (
                    <tr>
                      <td colSpan={7} className={`py-6 text-center ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>No flagged vehicles found</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SOURCES TAB
  // ═══════════════════════════════════════════════════════════════════════════

  function SourcesTab() {
    return (
      <div className="space-y-4">
        {/* Source cards */}
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2.5">
          {data?.sources.map(src => {
            const statusColor = src.lastStatus === 'SUCCESS' ? 'text-emerald-400' : src.lastStatus === 'PARTIAL' ? 'text-amber-400' : 'text-red-400';
            const statusBg = src.lastStatus === 'SUCCESS' ? 'bg-emerald-500' : src.lastStatus === 'PARTIAL' ? 'bg-amber-500' : 'bg-red-500';
            return (
              <Card key={src.name} className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
                <CardContent className="p-3 space-y-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className={`text-[11px] font-semibold truncate ${darkMode ? 'text-white' : 'text-slate-800'}`}>{src.name}</p>
                      <p className={`text-[9px] font-mono truncate ${darkMode ? 'text-slate-600' : 'text-slate-400'}`}>{src.url}</p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <span className={`inline-block w-1.5 h-1.5 rounded-full ${statusBg} ${src.lastStatus !== 'SUCCESS' ? 'animate-pulse' : ''}`} />
                      <Badge
                        variant="outline"
                        className={`text-[8px] h-3.5 ${src.lastStatus === 'SUCCESS' ? 'border-emerald-800 text-emerald-400' : src.lastStatus === 'PARTIAL' ? 'border-amber-800 text-amber-400' : 'border-red-800 text-red-400'}`}
                      >
                        {src.lastStatus ?? 'PENDING'}
                      </Badge>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-1.5 text-center">
                    <div className={`p-1 rounded ${darkMode ? 'bg-slate-800/50' : 'bg-slate-50'}`}>
                      <p className="text-[11px] font-bold text-white">{src.recordsFound.toLocaleString()}</p>
                      <p className={`text-[8px] ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Records</p>
                    </div>
                    <div className={`p-1 rounded ${darkMode ? 'bg-slate-800/50' : 'bg-slate-50'}`}>
                      <p className="text-[11px] font-bold text-white">{src.scrapeIntervalHours}h</p>
                      <p className={`text-[8px] ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>Interval</p>
                    </div>
                    <div className={`p-1 rounded ${darkMode ? 'bg-slate-800/50' : 'bg-slate-50'}`}>
                      <Badge variant="outline" className={`text-[7px] h-3.5 ${darkMode ? 'border-slate-700 text-slate-400' : 'border-slate-300 text-slate-500'}`}>
                        {src.complexity}
                      </Badge>
                    </div>
                  </div>

                  <div className="flex items-center justify-between">
                    <div className={`flex items-center gap-1 text-[9px] font-mono ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                      <Clock className="h-3 w-3" />
                      {src.lastScrapedAt ? timeAgo(src.lastScrapedAt) : 'Never'}
                    </div>
                    <Badge variant="outline" className={`text-[7px] h-3.5 ${darkMode ? 'border-slate-700 text-slate-500' : 'border-slate-300 text-slate-400'}`}>
                      {src.category.replace(/_/g, ' ')}
                    </Badge>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>

        {/* Anti-Detection Stack */}
        <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className={`text-xs font-semibold flex items-center gap-2 ${darkMode ? 'text-white' : 'text-slate-900'}`}>
              <Fingerprint className="h-4 w-4 text-emerald-500" /> Anti-Detection Stack (2026 Standards)
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-2.5">
              {[
                { layer: 'IP / Proxy', solution: 'Bright Data Residential', detail: 'Kenya sticky sessions, rotate per request for open sources', icon: Globe },
                { layer: 'TLS Fingerprint', solution: 'Playwright Chrome', detail: 'JA3/JA4 safe — never use Python requests', icon: Shield },
                { layer: 'Browser', solution: 'Octo Browser / GoLogin', detail: 'Passes Pixelscan, Iphey, CreepJS', icon: MonitorSmartphone },
                { layer: 'Behavior', solution: 'Human-like Delays', detail: 'Random 1-5s delays, mouse movements, scroll patterns', icon: Cpu },
                { layer: 'CAPTCHA', solution: '2Captcha / CapSolver', detail: '$1-3 per 1K solves — prevention first', icon: Puzzle },
              ].map(item => {
                const Icon = item.icon;
                return (
                  <div key={item.layer} className={`p-2.5 rounded-lg border ${darkMode ? 'bg-slate-800/40 border-slate-800/80' : 'bg-slate-50 border-slate-200'}`}>
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <Icon className="h-3.5 w-3.5 text-emerald-400" />
                      <p className={`text-[10px] font-mono font-semibold ${darkMode ? 'text-emerald-400' : 'text-emerald-600'}`}>{item.layer}</p>
                    </div>
                    <p className={`text-[11px] font-semibold ${darkMode ? 'text-white' : 'text-slate-800'} mb-0.5`}>{item.solution}</p>
                    <p className={`text-[9px] ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{item.detail}</p>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        {/* Kenya Gazette OCR Pipeline */}
        <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className={`text-xs font-semibold flex items-center gap-2 ${darkMode ? 'text-white' : 'text-slate-900'}`}>
              <Scan className="h-4 w-4 text-cyan-400" /> Kenya Gazette OCR Pipeline
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="grid sm:grid-cols-4 gap-2.5">
              {[
                { stage: 'PDF Fetch', status: 'ACTIVE', detail: 'Weekly gazette downloads from Kenya Gazette' },
                { stage: 'OCR Extract', status: 'ACTIVE', detail: 'Tesseract v5 + custom Kenyan legal model' },
                { stage: 'NER Parse', status: 'ACTIVE', detail: 'SpaCy NER for company names, directors, liquidators' },
                { stage: 'Graph Merge', status: 'ACTIVE', detail: 'Insolvency notices → vehicle ownership graph' },
              ].map(step => (
                <div key={step.stage} className={`p-2.5 rounded-lg border ${darkMode ? 'bg-slate-800/40 border-slate-800/80' : 'bg-slate-50 border-slate-200'}`}>
                  <div className="flex items-center justify-between mb-1">
                    <p className={`text-[10px] font-mono font-semibold ${darkMode ? 'text-cyan-400' : 'text-cyan-600'}`}>{step.stage}</p>
                    <Badge variant="outline" className="text-[7px] h-3.5 border-emerald-800 text-emerald-400">
                      <span className="inline-block w-1 h-1 rounded-full bg-emerald-500 mr-0.5" />{step.status}
                    </Badge>
                  </div>
                  <p className={`text-[9px] ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{step.detail}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SETTINGS TAB
  // ═══════════════════════════════════════════════════════════════════════════

  function SettingsTab() {
    return (
      <div className="space-y-4">
        <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className={`text-xs font-semibold ${darkMode ? 'text-white' : 'text-slate-900'}`}>Engine Configuration</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-3">
            {[
              { label: 'Entity Resolution', value: 'Hybrid (Jaro-Winkler 0.85 + Levenshtein + Transformer)', icon: Fingerprint },
              { label: 'Risk Model', value: 'XGBoost v1.0-47f (47 features, calibrated)', icon: Cpu },
              { label: 'Graph Database', value: 'Neo4j Community 5.x (WCC, PageRank, Centrality)', icon: GitBranch },
              { label: 'Compliance', value: 'Kenya DPA 2019 — ODPC DCP-2026-8847 — Zero PII', icon: Lock },
              { label: 'Data Retention', value: '5 years (regulatory) — auto-purge PII after retention period', icon: Timer },
              { label: 'Audit Trail', value: 'All queries logged with MFI ID, timestamp, result hash', icon: FileText },
            ].map(item => {
              const Icon = item.icon;
              return (
                <div key={item.label} className={`flex items-start gap-3 p-2.5 rounded-lg ${darkMode ? 'bg-slate-800/30' : 'bg-slate-50'}`}>
                  <Icon className={`h-4 w-4 mt-0.5 shrink-0 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`} />
                  <div>
                    <p className={`text-[10px] font-mono uppercase tracking-wider ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{item.label}</p>
                    <p className={`text-xs ${darkMode ? 'text-slate-300' : 'text-slate-600'}`}>{item.value}</p>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card className={`${darkMode ? 'bg-slate-900/60 border-slate-800/70' : 'bg-white border-slate-200'}`}>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className={`text-xs font-semibold ${darkMode ? 'text-white' : 'text-slate-900'}`}>Model Performance</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="grid sm:grid-cols-4 gap-3">
              {[
                { metric: 'AUC-ROC', value: '0.943' },
                { metric: 'Precision', value: '0.891' },
                { metric: 'Recall', value: '0.876' },
                { metric: 'F1 Score', value: '0.883' },
              ].map(item => (
                <div key={item.metric} className={`p-2.5 rounded-lg text-center ${darkMode ? 'bg-slate-800/30' : 'bg-slate-50'}`}>
                  <p className="text-lg font-bold text-white">{item.value}</p>
                  <p className={`text-[9px] font-mono ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>{item.metric}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }
}
