import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeftRight,
  Banknote,
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
  const [configOpen, setConfigOpen] = useState(false);
  const [selectedCard, setSelectedCard] = useState<DashboardCard | null>(null);
  const [dragCard, setDragCard] = useState<CardId | null>(null);

  useEffect(() => {
    api.get("/masters/summary").then((r) => setSummary(r.data)).catch(() => undefined);
  }, []);

  const variant = user?.landing_page ?? "owner";
  const cardCatalog: DashboardCard[] = variant === "store" ? [
    { id: "net_sales", icon: <TrendingUp size={18} />, label: "Net sales today", value: <Money paise={284500_00} short />, sub: "Sales view coming from POS ingest", purpose: "Shows store sales once POS ingestion is connected.", built: false, points: [22, 28, 20, 31, 36, 29, 38] },
    { id: "receiving", icon: <PackageCheck size={18} />, label: "Items to receive", value: "3 shipments", sub: "GRN workflow is live", purpose: "Opens receiving workload and GRN progress.", built: true, points: [2, 3, 4, 1, 3, 2, 3] },
    { id: "cycle_count", icon: <ClipboardList size={18} />, label: "Cycle count due", value: "1 bin", sub: "Stock-count screen coming soon", purpose: "Will show cycle-count tasks and ageing bins.", built: false, points: [1, 2, 1, 1, 3, 1, 1] },
  ] : variant === "warehouse" ? [
    { id: "receiving", icon: <PackageCheck size={18} />, label: "Inbound queue", value: "7 shipments", sub: "GRN and PT mapper workflows are live", purpose: "Shows receiving workload and GRN/PT status.", built: true, points: [4, 6, 7, 5, 8, 6, 7] },
    { id: "pt_files", icon: <ClipboardList size={18} />, label: "PTs to convert", value: "4", sub: "PT Mapper is live", purpose: "Tracks PT conversion files awaiting review.", built: true, points: [2, 3, 2, 5, 4, 3, 4] },
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
              { label: "Sell", icon: <ShoppingCart size={20} />, cta: true },
              { label: "Receive", icon: <PackageCheck size={20} /> },
              { label: "Count", icon: <ClipboardList size={20} /> },
              { label: "Transfer", icon: <ArrowLeftRight size={20} /> },
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
              { label: "Receive", icon: <PackageCheck size={20} />, cta: true },
              { label: "Count", icon: <ClipboardList size={20} /> },
              { label: "Transfer", icon: <ArrowLeftRight size={20} /> },
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
              <CollectionsBand />
              <MorningBrief />
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
