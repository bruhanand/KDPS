import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeftRight,
  Banknote,
  ClipboardList,
  PackageCheck,
  ShoppingCart,
  Sparkles,
  TrendingUp,
} from "lucide-react";

import { api } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { Money } from "../lib/format";
import "./Home.css";

interface Summary {
  entities: number;
  gstins: number;
  stores: number;
  warehouses: number;
  brands: number;
  seasons: number;
  open_season: string | null;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}
const today = new Date().toLocaleDateString("en-IN", {
  weekday: "long",
  day: "numeric",
  month: "long",
});

function Sample() {
  return (
    <span className="sample-tag" title="Sample — live once the Sales/Payments slices ship">
      sample
    </span>
  );
}

function Kpi({
  icon,
  label,
  value,
  sub,
  sample,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  sub?: string;
  sample?: boolean;
}) {
  return (
    <div className="kpi card" data-testid="kpi-tile">
      <div className="kpi-top">
        <span className="kpi-ic">{icon}</span>
        <span className="kpi-label">
          {label} {sample && <Sample />}
        </span>
      </div>
      <div className="kpi-value mono">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

function NetworkPanel({ s }: { s: Summary | null }) {
  const rows: [string, React.ReactNode][] = [
    ["Legal entities", s?.entities ?? "—"],
    ["State GSTINs", s?.gstins ?? "—"],
    ["Stores", s?.stores ?? "—"],
    ["Warehouses", s?.warehouses ?? "—"],
    ["Brands", s?.brands ?? "—"],
    ["Seasons", s?.seasons ?? "—"],
  ];
  return (
    <div className="card panel">
      <div className="panel-head">
        <p className="eyebrow">Live master data</p>
        <h3 className="h3">Network at a glance</h3>
      </div>
      <div className="net-grid">
        {rows.map(([k, v]) => (
          <div className="net-cell" key={k}>
            <span className="net-num mono">{v}</span>
            <span className="net-label">{k}</span>
          </div>
        ))}
      </div>
      {s?.open_season && (
        <div className="net-foot">
          Open season <span className="chip chip-green">{s.open_season}</span>
        </div>
      )}
    </div>
  );
}

const BUILD_STATUS: { label: string; state: string; tone: string }[] = [
  { label: "Foundation · shell, auth, roles, masters", state: "Live", tone: "green" },
  { label: "Inbound · GRN → PT → stock", state: "Phase 1", tone: "amber" },
  { label: "Selling floor · POS ingest", state: "Phase 2", tone: "grey" },
  { label: "Money in · collection & bank audit", state: "Phase 3", tone: "grey" },
  { label: "Payments · vendor settlement", state: "Phase 5", tone: "grey" },
  { label: "Tally bridge · statutory feed", state: "Phase 6", tone: "grey" },
];

function BuildPanel() {
  return (
    <div className="card panel">
      <div className="panel-head">
        <p className="eyebrow">Roadmap</p>
        <h3 className="h3">Build status</h3>
      </div>
      <div className="build-list">
        {BUILD_STATUS.map((b) => (
          <div className="build-row" key={b.label}>
            <span>{b.label}</span>
            <span className={`chip chip-${b.tone}`}>{b.state}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CollectionsBand() {
  return (
    <div className="band band-edge">
      <div className="band-head">
        <h3 className="h3">Today's collections <Sample /></h3>
        <span className="chip chip-blue">Edge · 3-rail</span>
      </div>
      <div className="band-rows">
        <div className="band-row">
          <span>Cash &amp; UPI</span>
          <span className="mono"><Money paise={1618400_00} /></span>
          <span className="chip chip-green">deposited</span>
        </div>
        <div className="band-row">
          <span>Card (net of MDR)</span>
          <span className="mono"><Money paise={842000_00} /></span>
          <span className="chip chip-amber">2 to clear</span>
        </div>
      </div>
    </div>
  );
}

function MorningBrief() {
  return (
    <div className="band band-ai">
      <div className="band-head">
        <h3 className="h3">Morning brief</h3>
        <span className="chip chip-purple">
          <Sparkles size={12} /> AI · preview
        </span>
      </div>
      <p className="ai-line">
        The intelligence layer (suggest-only) gets a home here. It surfaces &amp; drafts —
        every commit stays a human decision. Built in a later phase.
      </p>
      <div className="ai-fence">
        ✦ AI never writes stock, money or Tally. It opens drafts a human approves.
      </div>
    </div>
  );
}

function QuickActions({ items }: { items: { label: string; icon: React.ReactNode; cta?: boolean }[] }) {
  const navigate = useNavigate();
  return (
    <div className="quick-grid">
      {items.map((a) => (
        <button
          key={a.label}
          className={`quick-btn ${a.cta ? "quick-cta" : ""}`}
          onClick={() => navigate("/store/" + a.label.toLowerCase())}
          data-testid={`quick-${a.label.toLowerCase()}`}
        >
          <span className="quick-ic">{a.icon}</span>
          {a.label}
        </button>
      ))}
    </div>
  );
}

export function Home() {
  const { user, activeStore } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);

  useEffect(() => {
    api.get("/masters/summary").then((r) => setSummary(r.data)).catch(() => undefined);
  }, []);

  if (!user) return null;
  const variant = user.landing_page;
  const name = (user.full_name || user.username).split(" ")[0];
  const ctx = activeStore ? `${activeStore.code} · ${activeStore.name}, ${activeStore.state_name}` : "All stores · network view";

  return (
    <div className="page-pad home">
      <header className="home-greet">
        <h1 className="h1" data-testid="greeting">
          {greeting()}, {name}
        </h1>
        <p className="lead">
          {today} · here's your {variant === "store" || variant === "warehouse" ? "shift" : "day"} at a glance
          <span className="ctx-chip">{ctx}</span>
        </p>
      </header>

      {variant === "store" ? (
        <>
          <QuickActions
            items={[
              { label: "Sell", icon: <ShoppingCart size={20} />, cta: true },
              { label: "Receive", icon: <PackageCheck size={20} /> },
              { label: "Count", icon: <ClipboardList size={20} /> },
              { label: "Transfer", icon: <ArrowLeftRight size={20} /> },
            ]}
          />
          <div className="kpi-row">
            <Kpi icon={<TrendingUp size={18} />} label="Net sales today" value={<Money paise={284500_00} short />} sub="▲ 12% vs 14-day avg" sample />
            <Kpi icon={<PackageCheck size={18} />} label="Items to receive" value="3 shipments" sub="awaiting door scan" sample />
            <Kpi icon={<ClipboardList size={18} />} label="Cycle count due" value="1 bin" sub="oldest season first" sample />
          </div>
          <div className="home-cols">
            <NetworkPanel s={summary} />
            <BuildPanel />
          </div>
        </>
      ) : variant === "warehouse" ? (
        <>
          <QuickActions
            items={[
              { label: "Receive", icon: <PackageCheck size={20} />, cta: true },
              { label: "Count", icon: <ClipboardList size={20} /> },
              { label: "Transfer", icon: <ArrowLeftRight size={20} /> },
            ]}
          />
          <div className="kpi-row">
            <Kpi icon={<PackageCheck size={18} />} label="Inbound queue" value="7 shipments" sub="3 booking-less" sample />
            <Kpi icon={<ClipboardList size={18} />} label="PTs to convert" value="4" sub="branded format" sample />
            <Kpi icon={<AlertTriangle size={18} />} label="Barcode clashes" value="2" sub="need resolution" sample />
          </div>
          <div className="home-cols">
            <NetworkPanel s={summary} />
            <BuildPanel />
          </div>
        </>
      ) : (
        <>
          <div className="kpi-row">
            <Kpi icon={<TrendingUp size={18} />} label="Net sales today" value={<Money paise={1842000_00} short />} sub="▲ 12% vs 14-day avg" sample />
            <Kpi icon={<Banknote size={18} />} label="Owed to brands" value={<Money paise={4260000_00} short />} sub="3 due this week" sample />
            <Kpi icon={<AlertTriangle size={18} />} label="Open exceptions" value="5" sub="2 need a decision" sample />
          </div>
          <div className="home-cols">
            <div className="home-stack">
              <CollectionsBand />
              <MorningBrief />
            </div>
            <div className="home-stack">
              <NetworkPanel s={summary} />
              <BuildPanel />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
