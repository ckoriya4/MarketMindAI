MarketMindAI/
├── run.bat                          # One-click Windows runner (starts Backend + Frontend)
├── run_all.bat                      # Runs run_all.py helper
├── run_all.py                       # Automated token validation & option-chain fetcher
├── run_kite_fetch.bat               # Interactive Kite Connect login & fetch script
├── latest_nifty_chain.json          # Cached fallback snapshot of NIFTY option-chain data
├── latest_chain.json                # Legacy cached option-chain snapshot
│
├── backend/                         # FastAPI Python Backend
│   ├── main.py                      # Master API entry point, route definitions, and CORS setup
│   ├── nifty50.csv                  # Official constituent list (50 companies, sectors, ISINs)
│   ├── requirements.txt             # Python backend dependencies
│   ├── .env                         # API credentials (KITE_API_KEY, KITE_ACCESS_TOKEN, RSS URLs)
│   ├── .env.example                 # Template for environment variables
│   ├── run_kite_fetch.py            # CLI helper to fetch live chain using Kite
│   │
│   ├── data/                        # Local SQLite databases for historical tracking & cache
│   │   ├── direct-sum-oi-graph.sqlite3
│   │   ├── mcx-crude-quotes.sqlite3
│   │   ├── news-headlines.sqlite3
│   │   ├── oi-pro-alerts.sqlite3
│   │   ├── oi-signals.sqlite3
│   │   ├── option-oi-baselines.sqlite3
│   │   ├── previous-close-oi.sqlite3
│   │   ├── sector-oi.sqlite3
│   │   ├── sector-oi-v2.sqlite3
│   │   ├── sector-session-v3.sqlite3
│   │   ├── weighted-oi-graph.sqlite3
│   │   └── weighted-setups.sqlite3
│   │
│   └── services/                    # Trading engines & business logic
│       ├── kite_client.py           # Kite Connect client initialization & status manager
│       ├── kite_login.py            # Headless / browser-based Zerodha authentication
│       ├── kite_stream.py           # Real-time WebSocket quote streaming service
│       ├── option_chain.py          # Dynamic ATM ladder, strike PCR, S1/R1 calculations
│       ├── option_model.py          # Black-Scholes Greeks engine (IV, Delta, Theta, Gamma)
│       ├── chart_service.py         # Multi-timeframe historical candlestick data service
│       ├── chart_indicators.py      # Technical indicator engine (EMA, RSI, MACD, Bollinger, ATR)
│       ├── oi_signal.py             # Open Interest crossover and Call/Put divergence calculations
│       ├── dynamic_oi.py            # Dynamic multi-strike OI aggregation
│       ├── previous_oi.py           # Day-over-day baseline OI comparator
│       ├── oi_percent_reference.py  # % OI change reference tracker
│       ├── oi_pro_rules.py          # Proprietary rules engine (Long Buildup, Short Covering, etc.)
│       ├── confluence_service.py    # Multi-factor confluence scoring engine (0-100 A/B score)
│       ├── weighted_setup.py        # 4-condition weighted setup evaluator
│       ├── trade_setups.py          # Automated signal generation (BUY / SELL / WAIT)
│       ├── sector_oi.py             # Sector-wise Open Interest aggregation
│       ├── sector_recording.py      # Background recorder for sector OI trends
│       ├── session_recorder.py      # Session tick and state capture engine
│       ├── direct_alerts.py         # In-memory alert publisher & notification trigger
│       ├── live_crude.py            # MCX Crude Oil futures quote fetcher
│       ├── energy_service.py        # Energy & Crude correlation analytics
│       ├── market_overview.py       # Spot index overview (NIFTY, BANKNIFTY, SENSEX, INDIA VIX)
│       ├── market_session.py        # Indian market schedule & holiday filter
│       ├── market_news.py           # Financial news RSS collector (ET, Mint, BSE)
│       ├── global_news.py           # Global macro sentiment parser
│       ├── news_analysis.py         # Sentiment classification of news headlines
│       ├── news_entities.py         # Stock entity extraction from news stories
│       └── stock_option_data.py     # Individual stock option chain analytics
│
├── frontend/                        # React 19 + TypeScript + Vite Dashboard
│   ├── index.html                   # HTML entry point
│   ├── package.json                 # Node dependencies (lightweight-charts, lucide-react, etc.)
│   ├── vite.config.ts               # Vite build & development server configuration
│   ├── tsconfig.json                # TypeScript compiler configuration
│   ├── .env.development             # Frontend environment variables
│   │
│   └── src/                         # React UI Components & Client State
│       ├── main.tsx                 # React app bootstrapping & DOM mounting
│       ├── App.tsx                  # Master dashboard container, layout, and tabs
│       ├── App.css                  # Global styles, dashboard grids, colors, and animations
│       ├── nifty50.ts               # Complete list of 50 NIFTY constituent symbols
│       ├── index.css                # Base reset styling
│       │
│       ├── LiveMarketStrip.tsx      # Top ticker strip (Nifty, BankNifty, Sensex, VIX, Crude)
│       ├── SectorSummary.tsx        # NIFTY 50 Stock Scanner table with sector filter & sorting
│       ├── SectorSummary.css        # Styles for the stock scanner table
│       │
│       ├── IndicatorCandleChart.tsx # Interactive candlestick chart with EMAs & RSI overlays
│       ├── IndicatorCandleChart.css # Styles for chart panes and indicator legends
│       ├── OISignalChart.tsx        # Multi-strike Put vs Call OI divergence chart
│       ├── AtmOiSummary.tsx         # Real-time ATM strike shift & OI distribution widget
│       ├── AtmOiCard.css            # Styles for ATM OI cards
│       │
│       ├── LiveConfluencePanel.tsx  # Confluence gauge panel (A/B score & market bias)
│       ├── WeightedSetupPanel.tsx   # 4-condition trade setup validator
│       ├── WeightedSetupPanel.css   # Styles for weighted setups
│       ├── TradeSetupPanel.tsx      # Real-time trade recommendations panel
│       ├── TradeSetupPanel.css      # Styles for trade signals
│       ├── OIProSignalPanel.tsx     # Institutional buildup/unwinding signals
│       ├── OIProSignalPanel.css     # Styles for Pro OI signals
│       │
│       ├── LiveCrudeOilPanel.tsx    # Live MCX Crude Oil futures quote card
│       ├── CrudePriceChart.tsx      # Crude price trend chart
│       ├── EnergyPanels.tsx         # Energy market correlation breakdown
│       ├── EnergyPanels.css         # Styles for energy components
│       ├── SectorOIGraph.tsx        # Sector-wise visual graph of Call vs. Put OI
│       ├── SectorOIGraph.css        # Styles for sector graphs
│       │
│       ├── DirectAlertPanel.tsx     # Active notifications & trade alerts panel
│       ├── DirectAlertPanel.css     # Styles for alert boxes
│       ├── OICrossoverAlerts.tsx    # Strike-level crossover notification badges
│       ├── OIStatusNotification.tsx # System status toast notification popup
│       ├── KiteLoginButton.tsx      # One-click Kite Connect login modal trigger
│       │
│       ├── config/api.ts            # API base URL and client configuration
│       ├── marketSession.ts         # Market hours helper (09:15 to 15:30 IST detection)
│       ├── dynamicSeries.ts         # Dynamic chart series helper
│       ├── chartScrollbar.js        # Custom chart horizontal scrollbar controller
│       ├── continuousOi.js          # Continuous OI streaming utility
│       ├── oiDifference.js          # Call-Put net difference algorithms
│       ├── oiAlertStore.ts          # State store for alerts
│       ├── sectorData.ts            # Sector grouping definitions and mappings
│       ├── sectorLineData.js        # Sector line chart coordinate generator
│       └── sumOiAlert.mjs           # Aggregate OI threshold alert calculator
│
└── tests/                           # Unit & Integration Tests
    ├── test_chart_service.py        # Tests for historical candle generation & technical indicators
    ├── test_confluence.py           # Tests for A/B confluence scoring logic
    └── test_oi_signal.py            # Tests for Open Interest signals and crossover math


Root Level
run.bat: Windows batch script that simultaneously activates the Python virtual environment, launches the FastAPI backend on port 8000, and starts the React Vite frontend on port 5173.
run_all.py / run_all.bat: CLI utility that validates the Zerodha Kite session, triggers an interactive browser login if expired, writes the new access token to backend/.env, and fetches the latest option chain into latest_nifty_chain.json.
latest_nifty_chain.json: Offline fallback dataset containing 101 strikes of NIFTY options, ensuring charts and tables render even when external APIs are disconnected.
Backend Core (backend/)
backend/main.py: Central FastAPI application.
Defines the 3-layer quote resolution engine for /api/market/quotes (Kite API 
→
→ NSE India API 
→
→ Internal Dynamic Simulation).
Exposes endpoints for option chains (/api/options/chain), expiry dates (/api/options/expiries), candles (/api/chart/candles), and real-time ticks (/api/chart/tick).
Registers routers for confluence scoring, crude analytics, and weighted setups.
backend/nifty50.csv: Contains all 50 official NIFTY constituent symbols, full company names, and industry sectors (Financial Services, IT, Automobile, etc.).
backend/.env: Stores secrets including KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN, and financial news RSS endpoints.
backend/requirements.txt: Lists Python dependencies (fastapi, uvicorn, kiteconnect, requests, python-dotenv).
Backend Services (backend/services/)
kite_client.py: Manages the active Zerodha KiteConnect instance and checks token validity.
option_chain.py: Dynamic strike ladder generator. Calculates ATM strike, total Call/Put OI, strike-level PCR, and dynamically identifies Major Support (S1) and Resistance (R1).
chart_service.py: Candlestick engine supporting multiple intervals (1m to W). Features fallback simulation so charts never fail to render.
chart_indicators.py: Computes EMA 9, EMA 21, EMA 50, EMA 200, RSI 14, MACD, Bollinger Bands, and ATR.
confluence_service.py: Calculates the A/B Confluence Score (0–100) combining price trend, OI divergence, and volume confirmation.
weighted_setup.py: Evaluates trade setups against 4 mandatory criteria to filter out false breakouts in choppy markets.
live_crude.py & energy_service.py: Tracks MCX Crude Oil futures and analyzes the correlation between energy prices and equities.
market_news.py & news_analysis.py: Fetches and sentiment-tags live financial news from RSS feeds.
Frontend Core (frontend/src/)
App.tsx: Main dashboard page combining all modular panels into a dark-themed UI.
nifty50.ts: Exports an array of all 50 NIFTY constituent symbols used for frontend querying and validation.
SectorSummary.tsx: The NIFTY 50 Stock Scanner component. Features live LTP, % Change, Call/Put OI, PCR, Trend, and Signal, complete with sector dropdown filtering and strongest/weakest sorting.
IndicatorCandleChart.tsx: Candlestick chart built using TradingView's lightweight-charts, rendering real-time ticks and indicators.
OISignalChart.tsx: Put OI vs. Call OI visual bars across strikes to visualize institutional order flow walls.
LiveMarketStrip.tsx: Top banner cards displaying NIFTY 50, BANK NIFTY, SENSEX, INDIA VIX, and MCX CRUDE OIL with trend sparklines.
LiveConfluencePanel.tsx: Renders the A/B confluence meter, bias label (Bullish/Bearish/Neutral), and operational recommendation.
WeightedSetupPanel.tsx: Displays the 4-condition trade setup checklist.
KiteLoginButton.tsx: UI button to initiate the Kite authentication flow.


 ┌──────────────────────┐      ┌─────────────────────────┐
 │ Zerodha Kite Connect │  or  │      NSE India API      │
 └──────────┬───────────┘      └────────────┬────────────┘
            │                               │
            └───────────────┬───────────────┘
                            ▼
              ┌───────────────────────────┐
              │  FastAPI Backend (:8000)  │
              │  (main.py & services/)    │
              └─────────────┬─────────────┘
                            │  JSON REST & Polling
                            ▼
              ┌───────────────────────────┐
              │  React Vite App (:5173)   │
              │  (App.tsx & Components)   │
              └───────────────────────────┘

Backend: Periodically polls or streams market data from Kite Connect or NSE India.
Analysis Engines: Compute Greeks, moving averages, PCR, and confluence scores in Python.
Frontend: Queries /api/market/quotes, /api/options/chain, and /api/chart/candles to render the real-time trading dashboard.