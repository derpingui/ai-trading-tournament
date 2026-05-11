/* AI Trading Tournament — dashboard JS */

const API = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws";

let chart = null;
let chartDatasets = {};   // agentName → {color, data: [{x, y}]}
let ws = null;
let agentList = [];       // [{id, name, model_id, color}]
let activeTab = null;     // agent_id for positions tab

// ── Init ──────────────────────────────────────────────────────────────────

async function init() {
  await loadAgents();
  await loadInitialData();
  initChart();
  connectWebSocket();
  renderPositionTabs();
  loadPositions(activeTab);
}

async function loadAgents() {
  try {
    agentList = await fetchJSON("/agents");
    if (agentList.length > 0) activeTab = agentList[0].id;
  } catch (_) {}
}

async function loadInitialData() {
  try {
    const [leaderboard, trades, chartData] = await Promise.all([
      fetchJSON("/leaderboard"),
      fetchJSON("/trades?limit=50"),
      fetchJSON("/chart"),
    ]);
    renderLeaderboard(leaderboard);
    trades.forEach(t => prependTrade(t, false));
    buildChartDataFromHistory(chartData);
  } catch (e) {
    console.error("Failed to load initial data", e);
  }
}

// ── Chart ─────────────────────────────────────────────────────────────────

function initChart() {
  const ctx = document.getElementById("portfolioChart").getContext("2d");
  chart = new Chart(ctx, {
    type: "line",
    data: { datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          labels: { color: "#8892aa", font: { size: 12 } },
        },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.dataset.label}: $${ctx.parsed.y.toLocaleString("en-US", {minimumFractionDigits: 2})}`,
          },
        },
      },
      scales: {
        x: {
          type: "time",
          time: { unit: "minute", displayFormats: { minute: "HH:mm", hour: "HH:mm", day: "MMM d" } },
          ticks: { color: "#8892aa", maxTicksLimit: 8 },
          grid: { color: "#2e3250" },
        },
        y: {
          ticks: {
            color: "#8892aa",
            callback: v => "$" + v.toLocaleString("en-US", {minimumFractionDigits: 0}),
          },
          grid: { color: "#2e3250" },
        },
      },
    },
  });
}

function buildChartDataFromHistory(data) {
  // data = { agentName: { color, data: [{timestamp, value}] } }
  chartDatasets = {};
  const datasets = [];
  for (const [name, info] of Object.entries(data)) {
    chartDatasets[name] = info;
    if (info.data.length === 0) continue;
    datasets.push({
      label: name,
      data: info.data.map(d => ({ x: new Date(d.timestamp), y: d.value })),
      borderColor: info.color,
      backgroundColor: info.color + "22",
      fill: false,
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
    });
  }
  if (chart) {
    chart.data.datasets = datasets;
    chart.update("none");
  }
}

function addChartPoint(agentName, color, timestamp, value) {
  if (!chart) return;
  const point = { x: new Date(timestamp), y: value };
  let ds = chart.data.datasets.find(d => d.label === agentName);
  if (!ds) {
    ds = {
      label: agentName,
      data: [],
      borderColor: color,
      backgroundColor: color + "22",
      fill: false,
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
    };
    chart.data.datasets.push(ds);
  }
  ds.data.push(point);
  // Keep last 500 points for performance
  if (ds.data.length > 500) ds.data.shift();
  chart.update("none");
}

// ── Leaderboard ────────────────────────────────────────────────────────────

function renderLeaderboard(entries) {
  const container = document.getElementById("leaderboard");
  container.innerHTML = "";
  entries.forEach(e => {
    const card = document.createElement("div");
    card.className = "agent-card";
    card.id = `agent-card-${e.agent_id}`;
    card.style.setProperty("--agent-color", e.color);
    const ret = e.return_pct >= 0;
    card.innerHTML = `
      <div class="agent-rank">#${e.rank} · ${e.trade_count} trade${e.trade_count !== 1 ? "s" : ""}</div>
      <div class="agent-name">${e.name}</div>
      <div class="agent-value">$${e.total_value.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
      <div class="agent-return ${ret ? "pos" : "neg"}">${ret ? "+" : ""}${e.return_pct.toFixed(2)}%</div>
      <div class="agent-meta">Cash: $${e.cash.toLocaleString("en-US", {minimumFractionDigits: 2})}</div>
    `;
    container.appendChild(card);
  });
}

function flashCard(agentId) {
  const card = document.getElementById(`agent-card-${agentId}`);
  if (!card) return;
  card.classList.remove("flash");
  void card.offsetWidth;
  card.classList.add("flash");
}

// ── Trade feed ─────────────────────────────────────────────────────────────

function prependTrade(trade, animate = true) {
  const feed = document.getElementById("tradeFeed");
  const empty = feed.querySelector(".empty-state");
  if (empty) empty.remove();

  const ts = new Date(trade.timestamp);
  const timeStr = ts.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  const isBuy = trade.action === "buy";

  const item = document.createElement("div");
  item.className = "trade-item";
  if (!animate) item.style.animation = "none";

  item.innerHTML = `
    <div class="trade-header">
      <span class="trade-agent-dot" style="background:${trade.agent_color || "#888"}"></span>
      <span class="trade-agent-name">${trade.agent_name || ""}</span>
      <span class="trade-badge ${trade.action}">${trade.action}</span>
      <span class="trade-symbol">${trade.symbol}</span>
      <span class="trade-qty">${trade.quantity} sh</span>
      <span class="trade-price">@$${(+trade.price).toFixed(2)}</span>
      <span class="trade-time">${timeStr}</span>
    </div>
    ${trade.reasoning ? `<div class="trade-reasoning">${trade.reasoning}</div>` : ""}
  `;

  feed.insertBefore(item, feed.firstChild);

  // Cap feed at 100 items
  while (feed.children.length > 100) feed.removeChild(feed.lastChild);
}

// ── Positions ──────────────────────────────────────────────────────────────

function renderPositionTabs() {
  const tabs = document.getElementById("positionTabs");
  tabs.innerHTML = "";
  agentList.forEach(a => {
    const btn = document.createElement("button");
    btn.className = "tab-btn" + (a.id === activeTab ? " active" : "");
    btn.textContent = a.name;
    btn.onclick = () => {
      activeTab = a.id;
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      loadPositions(a.id);
    };
    tabs.appendChild(btn);
  });
}

async function loadPositions(agentId) {
  if (!agentId) return;
  try {
    const snap = await fetchJSON(`/portfolio/${agentId}`);
    renderPositionsTable(snap.positions || []);
  } catch (_) {}
}

function renderPositionsTable(positions) {
  const tbody = document.getElementById("positionsBody");
  tbody.innerHTML = "";
  if (positions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No open positions — holding cash</td></tr>';
    return;
  }
  positions.forEach(p => {
    const pnl = p.unrealized_pnl;
    const cls = pnl >= 0 ? "pos" : "neg";
    const sign = pnl >= 0 ? "+" : "";
    const pnlPct = p.avg_cost > 0 ? ((p.current_price - p.avg_cost) / p.avg_cost * 100) : 0;
    tbody.innerHTML += `
      <tr>
        <td>${p.symbol}</td>
        <td>${p.quantity}</td>
        <td>$${p.avg_cost.toFixed(2)}</td>
        <td>$${p.current_price.toFixed(2)}</td>
        <td>$${p.market_value.toFixed(2)}</td>
        <td class="${cls}">${sign}$${Math.abs(pnl).toFixed(2)} (${sign}${pnlPct.toFixed(1)}%)</td>
      </tr>
    `;
  });
}

// ── WebSocket ──────────────────────────────────────────────────────────────

function connectWebSocket() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => setWsStatus(true);
  ws.onclose = () => {
    setWsStatus(false);
    setTimeout(connectWebSocket, 3000);
  };
  ws.onerror = () => setWsStatus(false);

  ws.onmessage = (evt) => {
    let msg;
    try { msg = JSON.parse(evt.data); } catch (_) { return; }

    if (msg.type === "init") {
      renderLeaderboard(msg.leaderboard);
    } else if (msg.type === "trade_executed") {
      prependTrade(msg.trade);
      addChartPoint(
        msg.agent_name, msg.agent_color,
        msg.trade.timestamp, msg.portfolio_value
      );
      flashCard(msg.agent_id);
      if (msg.agent_id === activeTab) loadPositions(activeTab);
    } else if (msg.type === "leaderboard_update") {
      renderLeaderboard(msg.leaderboard);
    }
  };
}

function setWsStatus(connected) {
  const dot = document.getElementById("wsDot");
  const label = document.getElementById("wsLabel");
  if (!dot || !label) return;
  dot.style.background = connected ? "var(--green)" : "var(--red)";
  label.textContent = connected ? "Live" : "Reconnecting…";
}

// ── Trigger button ─────────────────────────────────────────────────────────

async function triggerAll() {
  const btn = document.getElementById("triggerBtn");
  btn.disabled = true;
  btn.textContent = "Thinking…";
  try {
    await fetch(`${API}/trigger`, { method: "POST" });
  } catch (_) {}
  setTimeout(() => {
    btn.disabled = false;
    btn.textContent = "Run Analysis";
    loadPositions(activeTab);
  }, 2000);
}

// ── Helpers ────────────────────────────────────────────────────────────────

async function fetchJSON(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

document.addEventListener("DOMContentLoaded", init);
