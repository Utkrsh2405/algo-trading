"use client";

import { useEffect, useState, useCallback } from "react";
import { CurrentUser, Order, engageKillSwitch, clearKillSwitch, getCurrentUser, getOrders, getStrategies, startStrategy, stopStrategy, getPositions } from "@/lib/api";
import { usePriceFeed } from "@/lib/usePriceFeed";
import { useRouter } from "next/navigation";

// ── Helpers ────────────────────────────────────────────────────────────────

function formatPrice(n: number) {
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function statusClass(status: string) {
  switch (status.toLowerCase()) {
    case "filled":    return "filled";
    case "pending":   return "pending";
    case "placed":    return "placed";
    case "failed":    return "failed";
    case "cancelled": return "cancelled";
    default:          return "pending";
  }
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Topbar({ user, connected, feedDown }: { user: CurrentUser | null; connected: boolean; feedDown: boolean }) {
  const router = useRouter();
  const initials = user?.full_name
    ? user.full_name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase()
    : user?.email.slice(0, 2).toUpperCase() ?? "??";

  function logout() {
    localStorage.removeItem("access_token");
    router.push("/login");
  }

  return (
    <header className="topbar">
      <div className="topbar-logo">
        <div className="topbar-logo-icon">⚡</div>
        AlgoTrader
      </div>
      <div className="topbar-right">
        {feedDown && (
          <div className="feed-down-overlay">
            ⚠ Broker feed is stale or disconnected
          </div>
        )}
        <div className="feed-status" id="feed-status-indicator">
          <div className={`feed-status-dot ${connected ? "live" : ""}`} />
          {connected ? "Live" : "Disconnected"}
        </div>
        <div className="user-badge">
          <div className="user-avatar">{initials}</div>
          <span style={{ color: "var(--text-secondary)", fontSize: "0.82rem" }}>
            {user?.email ?? "..."}
          </span>
          <button className="btn-secondary" onClick={logout} style={{ padding: "4px 12px", fontSize: "0.75rem" }}>
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}

function Sidebar({ active, setActive }: { active: string, setActive: (t: string) => void }) {
  const items = [
    { id: "dashboard", label: "Dashboard",   icon: "◉" },
    { id: "prices",    label: "Live Prices", icon: "📈" },
    { id: "orders",    label: "Orders",      icon: "📋" },
    { id: "positions", label: "Positions",   icon: "⚖️" },
    { id: "strategies",label: "Strategies",  icon: "🤖" },
  ];
  return (
    <nav className="sidebar">
      <div className="nav-section-label">Main</div>
      {items.map((item) => (
        <div key={item.id} className={`nav-item ${active === item.id ? "active" : ""}`} onClick={() => setActive(item.id)}>
          <span className="nav-icon">{item.icon}</span>
          {item.label}
        </div>
      ))}
    </nav>
  );
}

function StatCards({ orders, balance }: { orders: Order[]; balance: number }) {
  const totalOrders   = orders.length;
  const filledOrders  = orders.filter((o) => o.status === "FILLED").length;
  const pendingOrders = orders.filter((o) => ["PENDING", "PLACED"].includes(o.status)).length;
  const failedOrders  = orders.filter((o) => o.status === "FAILED").length;

  return (
    <div className="stats-grid">
      <div className="stat-card blue">
        <div className="stat-label"><span className="stat-icon">💼</span> Balance</div>
        <div className="stat-value">₹{formatPrice(balance)}</div>
        <div className="stat-change">Available cash</div>
      </div>
      <div className="stat-card green">
        <div className="stat-label"><span className="stat-icon">✅</span> Filled Orders</div>
        <div className="stat-value">{filledOrders}</div>
        <div className="stat-change">of {totalOrders} total</div>
      </div>
      <div className="stat-card purple">
        <div className="stat-label"><span className="stat-icon">⏳</span> Pending</div>
        <div className="stat-value">{pendingOrders}</div>
        <div className="stat-change">awaiting execution</div>
      </div>
      <div className="stat-card red">
        <div className="stat-label"><span className="stat-icon">❌</span> Failed</div>
        <div className="stat-value">{failedOrders}</div>
        <div className="stat-change">risk-blocked or rejected</div>
      </div>
    </div>
  );
}

function PricesPanel({ quotes, connected }: { quotes: ReturnType<typeof usePriceFeed>["quotes"]; connected: boolean }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          📈 Live Prices
          {!connected && (
            <span style={{ fontSize: "0.72rem", color: "var(--accent-orange)", marginLeft: 8 }}>
              reconnecting…
            </span>
          )}
        </div>
        <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
          {quotes.length} symbols
        </span>
      </div>
      <div className="panel-body">
        {quotes.length === 0 ? (
          <div className="empty-state">
            <span className="empty-state-icon">📡</span>
            Waiting for live prices…
          </div>
        ) : (
          <table className="price-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Last Price</th>
                <th>Change</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {quotes.map((q) => (
                <tr key={q.symbol}>
                  <td className="symbol-cell">{q.symbol}</td>
                  <td>
                    <span className={`price-cell ${q.direction ?? "neutral"}`}>
                      ₹{formatPrice(q.last_price)}
                    </span>
                  </td>
                  <td>
                    {q.direction === "up" && <span className="change-badge up">▲ UP</span>}
                    {q.direction === "down" && <span className="change-badge down">▼ DN</span>}
                    {(!q.direction || q.direction === "neutral") && (
                      <span style={{ color: "var(--text-muted)", fontSize: "0.75rem" }}>—</span>
                    )}
                  </td>
                  <td style={{ color: "var(--text-muted)", fontSize: "0.75rem", fontFamily: "JetBrains Mono, monospace" }}>
                    {formatTime(q.timestamp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function OrdersPanel({ orders, loading }: { orders: Order[]; loading: boolean }) {
  const recent = orders.slice(0, 10);
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">📋 Recent Orders</div>
        <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
          {orders.length} total
        </span>
      </div>
      <div className="panel-body">
        {loading ? (
          <div className="empty-state">
            <span className="empty-state-icon">⏳</span>
            Loading orders…
          </div>
        ) : recent.length === 0 ? (
          <div className="empty-state">
            <span className="empty-state-icon">📭</span>
            No orders yet
          </div>
        ) : (
          <table className="orders-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Type</th>
                <th>Status</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((o) => (
                <tr key={o.id}>
                  <td style={{ fontWeight: 600, color: "var(--text-primary)" }}>{o.symbol}</td>
                  <td>
                    <span className={`side-badge ${o.side.toLowerCase()}`}>{o.side}</span>
                  </td>
                  <td style={{ fontFamily: "JetBrains Mono, monospace" }}>
                    {o.filled_quantity}/{o.quantity}
                  </td>
                  <td style={{ color: "var(--text-muted)", fontSize: "0.78rem" }}>{o.order_type}</td>
                  <td>
                    <span className={`status-badge ${statusClass(o.status)}`}>{o.status}</span>
                  </td>
                  <td style={{ color: "var(--text-muted)", fontSize: "0.75rem", fontFamily: "JetBrains Mono, monospace" }}>
                    {formatTime(o.placed_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function StrategiesPanel({ feedDown }: { feedDown: boolean }) {
  const [strategies, setStrategies] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const loadStrats = useCallback(() => {
    getStrategies()
      .then((data) => { setStrategies(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadStrats();
    const interval = setInterval(loadStrats, 5000);
    return () => clearInterval(interval);
  }, [loadStrats]);

  async function handleToggle(strat: any) {
    if (feedDown && !strat.is_running) {
      alert("Cannot start strategy: Broker feed is currently down.");
      return;
    }
    try {
      if (strat.is_running) {
        await stopStrategy(strat.id);
      } else {
        await startStrategy(strat.id);
      }
      loadStrats();
    } catch (e) {
      alert(`Strategy toggle failed: ${e}`);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">🤖 Trading Strategies</div>
      </div>
      <div className="panel-body">
        {loading ? (
           <div className="empty-state">Loading strategies...</div>
        ) : strategies.length === 0 ? (
           <div className="empty-state">No strategies available</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {strategies.map(s => (
              <div key={s.id} style={{ padding: 16, border: "1px solid var(--border-color)", borderRadius: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h3 style={{ margin: "0 0 8px 0" }}>{s.name}</h3>
                  <div style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: 8 }}>
                    Symbol: <strong>{s.config.symbol}</strong> | Qty: {s.config.quantity} | Windows: {s.config.fast_window}/{s.config.slow_window}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div className={`feed-status-dot ${s.is_running ? "live" : ""}`} style={{ background: s.is_running ? "var(--accent-green)" : "var(--text-muted)" }} />
                    <span style={{ fontSize: "0.85rem" }}>{s.status_message}</span>
                  </div>
                </div>
                <button 
                  className={s.is_running ? "btn-secondary" : "btn-primary"} 
                  onClick={() => handleToggle(s)}
                  style={{ minWidth: 100 }}
                >
                  {s.is_running ? "Stop" : "Start"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function PositionsPanel() {
  const [positions, setPositions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const loadPos = useCallback(() => {
    getPositions()
      .then((data) => { setPositions(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadPos();
    const interval = setInterval(loadPos, 5000);
    return () => clearInterval(interval);
  }, [loadPos]);

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">⚖️ Open Positions</div>
      </div>
      <div className="panel-body">
        {loading ? (
          <div className="empty-state">Loading positions...</div>
        ) : positions.length === 0 ? (
          <div className="empty-state">No open positions</div>
        ) : (
          <table className="price-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Quantity</th>
                <th>Avg Price</th>
                <th>P&L</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => (
                <tr key={i}>
                  <td className="symbol-cell">{p.symbol}</td>
                  <td>{p.quantity}</td>
                  <td>₹{formatPrice(p.average_price)}</td>
                  <td style={{ color: p.pnl > 0 ? "var(--accent-green)" : p.pnl < 0 ? "var(--accent-red)" : "inherit" }}>
                    ₹{formatPrice(p.pnl || 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}


function AlertsPanel({ orders, feedDown }: { orders: Order[]; feedDown: boolean }) {
  const riskBlocked = orders.filter((o) => o.status === "FAILED" && o.rejection_reason?.toLowerCase().includes("risk")).length;
  const alerts = [];

  if (feedDown) {
    alerts.push({ type: "critical", text: "Broker price feed is down or stale. Strategies may be halted." });
  }
  if (riskBlocked > 0) {
    alerts.push({ type: "warn", text: `${riskBlocked} order(s) blocked by risk controls today.` });
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">🔔 Alerts</div>
      </div>
      <div className="alert-list">
        {alerts.length === 0 ? (
          <div className="empty-state" style={{ padding: "20px" }}>
            <span className="empty-state-icon">✅</span>
            No active alerts
          </div>
        ) : (
          alerts.map((a, i) => (
            <div key={i} className={`alert-item ${a.type}`}>
              <div className={`alert-dot ${a.type}`} />
              <span>{a.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [orders, setOrders] = useState<Order[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(true);
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [killLoading, setKillLoading] = useState(false);
  const { quotes, connected, feedDown } = usePriceFeed();

  useEffect(() => {
    getCurrentUser()
      .then(setUser)
      .catch(() => router.push("/login"));
  }, [router]);

  const loadOrders = useCallback(() => {
    getOrders()
      .then((data) => { setOrders(data); setOrdersLoading(false); })
      .catch(() => setOrdersLoading(false));
  }, []);

  useEffect(() => {
    loadOrders();
    const interval = setInterval(loadOrders, 10_000);
    return () => clearInterval(interval);
  }, [loadOrders]);

  async function handleKillSwitch() {
    if (!confirm("⚠ This will cancel ALL pending orders and halt all strategies immediately. Are you sure?")) return;
    setKillLoading(true);
    try {
      await engageKillSwitch();
      setKillSwitchActive(true);
      loadOrders();
    } catch (e) {
      alert(`Kill switch failed: ${e}`);
    } finally {
      setKillLoading(false);
    }
  }

  async function handleClearKillSwitch() {
    if (!confirm("Clear the kill switch? Trading will be re-enabled for your account.")) return;
    try {
      await clearKillSwitch();
      setKillSwitchActive(false);
    } catch (e) {
      alert(`Failed to clear kill switch: ${e}`);
    }
  }

  return (
    <div className="app-shell">
      <Topbar user={user} connected={connected} feedDown={feedDown} />
      <Sidebar active={activeTab} setActive={setActiveTab} />
      <main className="main-content">

        {/* Kill Switch Banner */}
        {killSwitchActive && (
          <div className="kill-switch-banner">
            <p>🔴 Kill switch engaged — all trading is halted. No new orders will be placed.</p>
            <button className="btn-secondary" onClick={handleClearKillSwitch}>
              Re-enable Trading
            </button>
          </div>
        )}

        {/* Stats */}
        <StatCards orders={orders} balance={100_000} />

        {/* Kill Switch */}
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            id="kill-switch-button"
            className="btn-kill"
            onClick={handleKillSwitch}
            disabled={killLoading || killSwitchActive}
          >
            {killLoading ? "⏳ Engaging…" : "🛑 Kill Switch — Stop All Trading"}
          </button>
        </div>

        {activeTab === "dashboard" && (
          <div className="two-col">
            <PricesPanel quotes={quotes} connected={connected} />
            <AlertsPanel orders={orders} feedDown={feedDown} />
          </div>
        )}

        {activeTab === "prices" && (
          <PricesPanel quotes={quotes} connected={connected} />
        )}

        {activeTab === "orders" && (
          <OrdersPanel orders={orders} loading={ordersLoading} />
        )}

        {activeTab === "strategies" && (
          <StrategiesPanel feedDown={feedDown} />
        )}

        {activeTab === "positions" && (
          <PositionsPanel />
        )}
        
        {/* On dashboard, show recent orders at bottom */}
        {activeTab === "dashboard" && (
          <OrdersPanel orders={orders} loading={ordersLoading} />
        )}

      </main>
    </div>
  );
}
