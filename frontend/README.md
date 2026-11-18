1. High-Level Project Directory Structure
text
MarketMindAI/
├── run.bat                          # One-click Windows runner (starts backend + frontend)
├── run_all.bat                      # Runs run_all.py helper
├── run_all.py                       # Automated token validation & option-chain fetcher
├── run_kite_fetch.bat               # Interactive Kite Connect login & fetch script
├── latest_nifty_chain.json          # Cached snapshot of NIFTY option-chain data
├── .venv/                           # Python 3.13 virtual environment
│
├── backend/                         # FastAPI REST & WebSocket Backend
│   ├── .env                         # API credentials (KITE_API_KEY, KITE_ACCESS_TOKEN, news feeds)
│   ├── .env.example                 # Environment template
│   ├── requirements.txt             # Python dependencies
│   ├── main.py                      # FastAPI app entry point, routing & middleware
│   ├── nifty50.csv                  # Official constituent list (50 companies & sectors)
│   ├── kite_login.py                # Standalone Kite token generation helper
│   ├── run_kite_fetch.py            # CLI script to fetch chain using Kite
│   └── services/                    # Core business logic & trading intelligence engines
│       ├── kite_client.py           # KiteConnect session manager & connection status
│       ├── kite_login.py            # Automated/interactive browser-based Kite auth
│       ├── kite_stream.py           # WebSocket live market quote streamer
│       ├── option_chain.py          # Dynamic ATM ladder, PCR, support/resistance levels
│       ├── option_model.py          # Black-Scholes Greeks (Delta, Gamma, Theta, IV)
│       ├── chart_service.py         # Multi-timeframe candlestick & historical data service
│       ├── chart_indicators.py      # Technical indicator engine (EMA, RSI, MACD, Bollinger, ATR)
│       ├── oi_signal.py             # Live Open Interest crossover & difference calculations
│       ├── dynamic_oi.py            # Dynamic multi-strike OI aggregation
│       ├── previous_oi.py           # Day-over-day OI change & baseline tracker
│       ├── oi_percent_reference.py  # % OI change reference engine
│       ├── oi_pro_rules.py          # Proprietary OI rule evaluator (Long Buildup, Short Covering)
│       ├── confluence_service.py    # Multi-factor confluence score engine (A/B score)
│       ├── weighted_setup.py        # 4-condition weighted trading setup generator
│       ├── trade_setups.py          # Rule-based buy/sell/wait setups
│       ├── sector_oi.py             # Sector-wise aggregated Open Interest calculations
│       ├── sector_recording.py      # Background recorder for sector trends
│       ├── session_recorder.py      # Historical session & tick capture engine
│       ├── direct_alerts.py         # In-memory alerts & push triggers
│       ├── live_crude.py            # MCX Crude Oil futures tracking service
│       ├── energy_service.py        # Crude & energy correlation engine
│       ├── market_overview.py       # Indices spot overview (Nifty, BankNifty, Sensex, VIX)
│       ├── market_session.py        # Indian market hours & holiday calendar filter
│       ├── market_news.py           # Live financial news collector (ET, Mint, BSE)
│       ├── global_news.py           # Macro / global sentiment processor
│       ├── news_analysis.py         # NLP sentiment classifier for headlines
│       └── news_entities.py         # Entity extraction (tagging stocks mentioned in news)
│
├── frontend/                        # React 19 + TypeScript + Vite Dashboard
│   ├── package.json                 # Node dependencies (lightweight-charts, lucide-react)
│   ├── vite.config.ts               # Vite configuration
│   ├── tsconfig.json                # TypeScript compiler config
│   ├── index.html                   # HTML entry point
│   └── src/
│       ├── main.tsx                 # React DOM mount point
│       ├── App.tsx                  # Master Dashboard layout & tab routing
│       ├── App.css                  # Global themes, tables, cards, layout styling
│       ├── nifty50.ts               # NIFTY 50 symbol array helper
│       │
│       ├── LiveMarketStrip.tsx      # Top ticker strip (Nifty, BankNifty, Sensex, VIX, Crude)
│       ├── SectorSummary.tsx        # Nifty 50 constituent scanner with sector filter & sorting
│       ├── SectorSummary.css        # Stock scanner styling
│       │
│       ├── IndicatorCandleChart.tsx # Lightweight-Charts interactive candlestick chart
│       ├── IndicatorCandleChart.css # Chart pane & indicator overlays
│       ├── OISignalChart.tsx        # Call vs. Put OI crossover chart
│       ├── AtmOiSummary.tsx         # Real-time ATM Strike OI balance card
│       ├── AtmOiCard.css            # ATM card styling
│       │
│       ├── LiveConfluencePanel.tsx  # Multi-factor confluence scoring panel
│       ├── WeightedSetupPanel.tsx   # 4-condition setup validator
│       ├── WeightedSetupPanel.css   # Weighted setup panel styling
│       ├── TradeSetupPanel.tsx      # Automated Trade signals panel
│       ├── TradeSetupPanel.css      # Signals styling
│       ├── OIProSignalPanel.tsx     # Pro OI analysis & trend detection
│       ├── OIProSignalPanel.css     # Pro OI styling
│       │
│       ├── LiveCrudeOilPanel.tsx    # MCX Crude oil live price card
│       ├── CrudePriceChart.tsx      # Crude price trend chart
│       ├── EnergyPanels.tsx         # Energy market correlation breakdown
│       ├── EnergyPanels.css         # Energy styling
│       │
│       ├── DirectAlertPanel.tsx     # Direct actionable notifications
│       ├── DirectAlertPanel.css     # Alerts styling
│       ├── OICrossoverAlerts.tsx    # OI crossover detection badges
│       ├── OIStatusNotification.tsx # System status toast notification
│       ├── KiteLoginButton.tsx      # One-click Kite Connect login trigger
│       │
│       ├── marketSession.ts         # Trading session helper (market open/close status)
│       ├── dynamicSeries.ts         # Dynamic chart series helper
│       ├── chartScrollbar.js        # Custom chart horizontal scrollbar controller
│       ├── continuousOi.js          # Continuous OI streaming utility
│       ├── oiDifference.js          # Call-Put difference algorithms
│       └── oiAlertStore.ts          # Alert state management store
│
└── tests/                           # Python Backend Test Suites
    ├── test_chart_service.py        # Unit tests for chart data & indicators
    ├── test_confluence.py           # Tests for A/B confluence scoring
    └── test_oi_signal.py            # Tests for OI signal generation
2. Backend Files Detailed Breakdown
backend/main.py

The central hub of the application:

Initializes FastAPI, sets up CORS policies for the Vite frontend (http://localhost:5173), and configures application lifespan hooks.
Hosts the primary endpoint GET /api/market/quotes:
Layer 1: Queries live prices, volume, and OI for all 50 stocks via Kite Connect.
Layer 2: Automatically falls back to the official NSE India API if the Kite session is inactive.
Layer 3: Uses the internal simulation engine so the dashboard never renders blank.
Serves endpoints for options chains (/api/options/chain), expiries (/api/options/expiries), candles (/api/chart/candles), and real-time ticks (/api/chart/tick).
Registers routers: oi_signal_router, confluence_router, energy_router, market_overview_router, and weighted_setup_router.
backend/nifty50.csv
Stores the official constituent mapping of all 50 NIFTY companies.
Columns: Company Name, Industry (Sector), Symbol, Series, ISIN Code.
Used by the scanner to categorize stocks into sectors (Financial Services, IT, Automobile, Healthcare, Energy, etc.).
backend/services/ (Core Engines)
File	Purpose
kite_client.py	Wraps the Zerodha KiteConnect SDK. Reads credentials from .env, initializes authentication, and reports connection health.
option_chain.py	Builds real-time option chains around the ATM strike. Computes total Call/Put OI, strike PCR, Support (S1), Resistance (R1), and AB Confluence Score.
chart_service.py	Fetches historical and live candles across multiple timeframes (1m, 3m, 5m, 15m, 30m, 1H, 1D, W).
chart_indicators.py	Computes technical indicators: EMA (9, 21, 50, 200), RSI (14), MACD (12, 26, 9), Bollinger Bands, and ATR.
oi_signal.py	Computes Call vs. Put Open Interest divergence and tracks institutional buildup/unwinding.
confluence_service.py	Calculates the proprietary A/B Confluence Score (0–100 scale) combining price action, option chain bias, and volume.
weighted_setup.py	Evaluates trading viability using 4 non-negotiable criteria (Trend, OI Divergence, VWAP bias, Volatility).
energy_service.py	Tracks MCX Crude Oil futures and correlates energy price movements with broad indices.
market_news.py & news_analysis.py	Scrapes RSS feeds from Economic Times, Mint, and BSE announcements; performs sentiment scoring.
3. Frontend Files Detailed Breakdown
frontend/src/App.tsx

The primary React component that orchestrates state and UI:

Top Navigation & Branding: Displays system status (BACKEND ONLINE / OFFLINE), search bar, and alerts.
State Management: Controls selected symbol (NIFTY/BANKNIFTY), active expiry, strike range (5–50 strikes), and timeframe (1m to W).
Live Refresh Polling: Periodically requests updated quotes, option chain ladders, and chart ticks.
Key Visual Components (frontend/src/)
Component	Description
LiveMarketStrip.tsx	Top summary cards showing NIFTY 50 Spot, BANK NIFTY, SENSEX, INDIA VIX, and MCX CRUDE with trend sparklines.
SectorSummary.tsx	The NIFTY 50 Stock Scanner table. Supports sector filtering, sorting by strongest/weakest, searching by name, and shows LTP, % Change, Call OI, Put OI, PCR, and Signal.
IndicatorCandleChart.tsx	High-performance interactive candlestick chart powered by TradingView's lightweight-charts. Renders EMA9, EMA21, VWAP, and RSI.
OISignalChart.tsx	Multi-strike visual representation of Put OI vs. Call OI bars for identifying support and resistance walls.
AtmOiSummary.tsx	Quick-glance widget highlighting current ATM strike shifts and Put-Call parity.
LiveConfluencePanel.tsx	Gauges whether market participants are Bullish, Bearish, or Neutral/Rangebound.
WeightedSetupPanel.tsx	Checks conditions required before entering trades (prevents overtrading in choppy markets).
LiveCrudeOilPanel.tsx	Monitors energy trends impacting inflation and domestic indices.
4. Root Launcher Scripts
run.bat: Double-click script that activates .venv, boots the FastAPI server on http://127.0.0.1:8000, and starts the React Vite dev server on http://localhost:5173.
run_all.py: Standalone Python utility that verifies your Kite API credentials, opens the login portal if your session has expired, updates the .env token, and exports latest_nifty_chain.json.
run_kite_fetch.bat: Windows batch shortcut for run_all.py.