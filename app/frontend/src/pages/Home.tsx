import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeftRight,
  Banknote,
  CheckCircle2,
  ClipboardList,
  GripVertical,
  PackageCheck,
  Settings2,
  ShoppingCart,
  Sparkles,
  TrendingUp,
  X,
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

type CardId = "net_sales" | "owed" | "exceptions" | "receiving" | "cycle_count" | "pt_files" | "barcode";

interface DashboardCard {
  id: CardId;
  label: string;
  value: React.ReactNode;
  sub: string;
  icon: React.ReactNode;
  purpose: string;
  built: boolean;
  points: number[];
}

const DASH_ORDER_KEY = "kdps-dashboard-card-order";
const DASH_VISIBLE_KEY = "kdps-dashboard-card-visible";

function Kpi({
  id,
  icon,
  label,
  value,
  sub,
  built,
  onOpen,
  onDragStart,
  onDrop,
}: {
  id: string;
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  sub?: string;
  built: boolean;
  onOpen: () => void;
  onDragStart: () => void;
  onDrop: () => void;
}) {
  return (
    <button
      className="kpi card"
      onClick={onOpen}
      draggable
      onDragStart={onDragStart}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); onDrop(); }}
      data-testid={`kpi-tile-${id}`}
    >
      <div className="kpi-top">
        <span className="kpi-ic">{icon}</span>
        <span className="kpi-label">
          {label} {!built && <span className="sample-tag">Coming soon</span>}
        </span>
        <GripVertical size={14} className="kpi-grip" />
      </div>
      <div className="kpi-value mono">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </button>
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

interface Health {
  balanced: boolean;
  trial_balance_paise: number;
  assets_paise: number;
  liabilities_paise: number;
  leg_count: number;
  voucher_count: number;
}

function TrialBalancePanel() {
  const [h, setH] = useState<Health | null>(null);
  const [denied, setDenied] = useState(false);
  useEffect(() => {
    api.get("/finledger/health").then((r) => setH(r.data)).catch(() => setDenied(true));
  }, []);
  if (denied) return null;
  const balanced = h?.balanced ?? true;
  return (
    <div className="card panel" data-testid="trial-balance-panel">
      <div className="panel-head">
        <p className="eyebrow">Books health · value ledger</p>
        <h3 className="h3">Equation of state</h3>
      </div>
      <div
        data-testid="trial-balance-state"
        style={{
          display: "flex", gap: 12, alignItems: "center", padding: "12px 14px",
          borderRadius: 12, marginBottom: 12,
          background: balanced ? "rgba(var(--green-rgb), 0.08)" : "rgba(var(--rust-rgb), 0.10)",
          color: balanced ? "var(--green)" : "var(--rust)",
        }}
      >
        {balanced ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <b>{balanced ? "Books tie" : "Out of balance"}</b>
          <span style={{ fontSize: 13, opacity: 0.85 }}>
            Trial balance <b className="mono"><Money paise={h?.trial_balance_paise ?? 0} /></b>
            {" "}· {h?.voucher_count ?? 0} vouchers · {h?.leg_count ?? 0} legs
          </span>
        </div>
      </div>
      <div className="net-grid">
        <div className="net-cell">
          <span className="net-num mono"><Money paise={h?.assets_paise ?? 0} short /></span>
          <span className="net-label">Inventory + SOR stock</span>
        </div>
        <div className="net-cell">
          <span className="net-num mono"><Money paise={h?.liabilities_paise ?? 0} short /></span>
          <span className="net-label">Payables + GRNI + contra</span>
        </div>
      </div>
    </div>
  );
}

function CollectionsBand() {
  return (
    <div className="band band-edge">
      <div className="band-head">
        <h3 className="h3">Collections</h3>
        <span className="chip chip-blue">Coming soon</span>
      </div>
      <p className="ai-line">
        This section will show cash, UPI, card clearing, deposits, and bank-audit status once the collections slice is enabled.
      </p>
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
        Coming soon: this area will show a suggest-only morning summary for sales, stock,
        exceptions, and follow-ups. Every operational action will still need human approval.
      </p>
      <div className="ai-fence">
        ✦ AI never writes stock, money or Tally. It opens drafts a human approves.
      </div>
    </div>
  );
}

function readOrder(defaultIds: CardId[]): CardId[] {
  try {
    const saved = JSON.parse(localStorage.getItem(DASH_ORDER_KEY) || "[]") as CardId[];
    return [...saved.filter((id) => defaultIds.includes(id)), ...defaultIds.filter((id) => !saved.includes(id))];
  } catch {
    return defaultIds;
  }
}

function readVisible(defaultIds: CardId[]): CardId[] {
  try {
    const saved = JSON.parse(localStorage.getItem(DASH_VISIBLE_KEY) || "[]") as CardId[];
    return saved.length ? saved.filter((id) => defaultIds.includes(id)) : defaultIds.slice(0, 3);
  } catch {
    return defaultIds.slice(0, 3);
  }
}

function MiniGraph({ points }: { points: number[] }) {
  const max = Math.max(...points, 1);
  return (
    <div className="mini-graph" data-testid="dashboard-card-graph">
      {points.map((p, i) => <span key={i} style={{ height: `${Math.max(16, (p / max) * 100)}%` }} />)}
    </div>
  );
}

function DashboardConfigurator({
  cards,
  visible,
  onToggle,
  onClose,
}: {
  cards: DashboardCard[];
  visible: CardId[];
  onToggle: (id: CardId) => void;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" data-testid="dashboard-config-modal">
      <div className="modal dashboard-modal">
        <div className="modal-head">
          <div><p className="eyebrow">Dashboard</p><h3 className="h3">Choose cards</h3></div>
          <button className="btn btn-sm" onClick={onClose} data-testid="dashboard-config-close"><X size={14} /> Close</button>
        </div>
        <div className="dash-card-list">
          {cards.map((c) => (
            <label className="dash-card-choice" key={c.id}>
              <input type="checkbox" checked={visible.includes(c.id)} onChange={() => onToggle(c.id)} data-testid={`dashboard-card-toggle-${c.id}`} />
              <span><b>{c.label}</b><small>{c.purpose}</small></span>
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

function QuickActions({ items }: { items: { label: string; to: string; icon: React.ReactNode; cta?: boolean }[] }) {
  const navigate = useNavigate();
  return (
    <div className="quick-grid">
      {items.map((a) => (
        <button
          key={a.label}
          className={`quick-btn ${a.cta ? "quick-cta" : ""}`}
          onClick={() => navigate(a.to)}
          data-testid={`quick-${a.label.toLowerCase()}`}
        >
          <span className="quick-ic">{a.icon}</span>
          {a.label}
        </button>
      ))}
    </div>
  );
}

interface QueueCounts {
  awaiting_pt: number;
  pt_in_progress: number;
}

export function Home() {
  const { user, activeStore } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [queueCounts, setQueueCounts] = useState<QueueCounts | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [selectedCard, setSelectedCard] = useState<DashboardCard | null>(null);
  const [dragCard, setDragCard] = useState<CardId | null>(null);

  useEffect(() => {
    api.get("/masters/summary").then((r) => setSummary(r.data)).catch(() => undefined);
    // The inbound work queue badge (Q9) — 403 for store roles is fine, card stays generic.
    api.get("/inbound/queue").then((r) => setQueueCounts(r.data.counts)).catch(() => undefined);
  }, []);

  const variant = user?.landing_page ?? "owner";
  const cardCatalog: DashboardCard[] = variant === "store" ? [
    { id: "net_sales", icon: <TrendingUp size={18} />, label: "Net sales today", value: <Money paise={284500_00} short />, sub: "Sales view coming from POS ingest", purpose: "Shows store sales once POS ingestion is connected.", built: false, points: [22, 28, 20, 31, 36, 29, 38] },
    { id: "receiving", icon: <PackageCheck size={18} />, label: "Items to receive", value: "3 shipments", sub: "GRN workflow is live", purpose: "Opens receiving workload and GRN progress.", built: true, points: [2, 3, 4, 1, 3, 2, 3] },
    { id: "cycle_count", icon: <ClipboardList size={18} />, label: "Cycle count due", value: "1 bin", sub: "Counting is live — the due-bin signal is not", purpose: "Counting sessions work now (Stock Count); what is still to come is the signal that says which bin is due.", built: false, points: [1, 2, 1, 1, 3, 1, 1] },
  ] : variant === "warehouse" ? [
    { id: "receiving", icon: <PackageCheck size={18} />, label: "Arrivals awaiting PT", value: queueCounts ? `${queueCounts.awaiting_pt}` : "—", sub: queueCounts ? "Live from the inbound work queue — make the PT to clear" : "GRN and PT mapper workflows are live", purpose: "Arrivals (GRNs) with no PT yet — goods are sellable only after their PT posts.", built: true, points: [4, 6, 7, 5, 8, 6, 7] },
    { id: "pt_files", icon: <ClipboardList size={18} />, label: "PTs in progress", value: queueCounts ? `${queueCounts.pt_in_progress}` : "—", sub: queueCounts ? "Mapping or awaiting Patna posting" : "PT File Operation is live", purpose: "PT files linked to an arrival, still being mapped or awaiting Patna.", built: true, points: [2, 3, 2, 5, 4, 3, 4] },
    { id: "barcode", icon: <AlertTriangle size={18} />, label: "Barcode clashes", value: "2", sub: "Controls screen coming soon", purpose: "Will highlight barcode exceptions needing resolution.", built: false, points: [1, 1, 0, 2, 1, 3, 2] },
  ] : [
    { id: "net_sales", icon: <TrendingUp size={18} />, label: "Net sales today", value: <Money paise={1842000_00} short />, sub: "POS ingest coming soon", purpose: "Shows network sales once selling floor data is connected.", built: false, points: [18, 22, 21, 24, 26, 23, 29] },
    { id: "owed", icon: <Banknote size={18} />, label: "Owed to brands", value: <Money paise={4260000_00} short />, sub: "Vendor ledger ageing is live", purpose: "Opens vendor payable health and ageing movement.", built: true, points: [42, 39, 44, 41, 43, 40, 46] },
    { id: "exceptions", icon: <AlertTriangle size={18} />, label: "Open exceptions", value: "5", sub: "Exception inbox coming soon", purpose: "Will show imports, approvals, and mismatches needing action.", built: false, points: [3, 4, 5, 4, 6, 5, 5] },
  ];
  const allIds = cardCatalog.map((c) => c.id);
  const [cardOrder, setCardOrder] = useState<CardId[]>(() => readOrder(allIds));
  const [visibleCards, setVisibleCards] = useState<CardId[]>(() => readVisible(allIds));
  const cardsById = new Map(cardCatalog.map((c) => [c.id, c]));
  const orderedCards = cardOrder.map((id) => cardsById.get(id)).filter(Boolean) as DashboardCard[];
  const dashboardCards = orderedCards.filter((c) => visibleCards.includes(c.id));

  if (!user) return null;
  const name = (user.full_name || user.username).split(" ")[0];
  const ctx = activeStore ? `${activeStore.code} · ${activeStore.name}, ${activeStore.state_name}` : "All stores · network view";

  function toggleDashboardCard(id: CardId) {
    const next = visibleCards.includes(id) ? visibleCards.filter((x) => x !== id) : [...visibleCards, id];
    setVisibleCards(next);
    localStorage.setItem(DASH_VISIBLE_KEY, JSON.stringify(next));
  }

  function moveDashboardCard(target: CardId) {
    if (!dragCard || dragCard === target) return;
    const next = [...cardOrder];
    const from = next.indexOf(dragCard);
    const to = next.indexOf(target);
    if (from < 0 || to < 0) return;
    const [picked] = next.splice(from, 1);
    next.splice(to, 0, picked);
    setCardOrder(next);
    localStorage.setItem(DASH_ORDER_KEY, JSON.stringify(next));
  }

  function renderDashboardCards() {
    return (
      <div className="kpi-row" data-testid="dashboard-card-grid">
        {dashboardCards.map((card) => (
          <Kpi
            key={card.id}
            id={card.id}
            icon={card.icon}
            label={card.label}
            value={card.value}
            sub={card.sub}
            built={card.built}
            onOpen={() => setSelectedCard(card)}
            onDragStart={() => setDragCard(card.id)}
            onDrop={() => moveDashboardCard(card.id)}
          />
        ))}
      </div>
    );
  }

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
        <button className="btn btn-sm dash-config-btn" onClick={() => setConfigOpen(true)} data-testid="dashboard-config-button">
          <Settings2 size={14} /> Configure dashboard
        </button>
      </header>

      {variant === "store" ? (
        <>
          <QuickActions
            items={[
              { label: "Sell", to: "/sell", icon: <ShoppingCart size={20} />, cta: true },
              { label: "Receive", to: "/receive", icon: <PackageCheck size={20} /> },
              { label: "Count", to: "/stock-count", icon: <ClipboardList size={20} /> },
              { label: "Transfer", to: "/transfer", icon: <ArrowLeftRight size={20} /> },
            ]}
          />
          {renderDashboardCards()}
          <div className="home-cols">
            <NetworkPanel s={summary} />
            <MorningBrief />
          </div>
        </>
      ) : variant === "warehouse" ? (
        <>
          <QuickActions
            items={[
              { label: "Receive", to: "/receive", icon: <PackageCheck size={20} />, cta: true },
              { label: "Count", to: "/stock-count", icon: <ClipboardList size={20} /> },
              { label: "Transfer", to: "/transfer", icon: <ArrowLeftRight size={20} /> },
            ]}
          />
          {renderDashboardCards()}
          <div className="home-cols">
            <NetworkPanel s={summary} />
            <MorningBrief />
          </div>
        </>
      ) : (
        <>
          {renderDashboardCards()}
          <div className="home-cols">
            <div className="home-stack">
              <TrialBalancePanel />
              <CollectionsBand />
            </div>
            <div className="home-stack">
              <NetworkPanel s={summary} />
              <MorningBrief />
            </div>
          </div>
        </>
      )}
      {configOpen && <DashboardConfigurator cards={orderedCards} visible={visibleCards} onToggle={toggleDashboardCard} onClose={() => setConfigOpen(false)} />}
      {selectedCard && (
        <div className="modal-backdrop" data-testid="dashboard-card-modal">
          <div className="modal dashboard-modal">
            <div className="modal-head">
              <div><p className="eyebrow">{selectedCard.built ? "Live / alpha" : "Coming soon"}</p><h3 className="h3">{selectedCard.label}</h3></div>
              <button className="btn btn-sm" onClick={() => setSelectedCard(null)} data-testid="dashboard-card-modal-close"><X size={14} /> Close</button>
            </div>
            <MiniGraph points={selectedCard.points} />
            <p className="lead" style={{ marginTop: 14 }}>{selectedCard.purpose}</p>
          </div>
        </div>
      )}
    </div>
  );
}
