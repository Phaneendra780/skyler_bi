---
title: Skyler BI - Skylark Drones
emoji: 🚁
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
---

# 🚁 Skyler BI — Skylark Drones Business Intelligence Platform

Skyler is an autonomous Business Intelligence and Strategic Decision Intelligence agent built for **Skylark Drones**. It interfaces with Monday.com sales pipeline and work order execution boards, using **Gemini 3.5 Flash** with dynamic function calling and tool execution to provide instant executive insights.

---

## 🌟 Key Features

1. **💬 Conversational Executive AI Agent**:
   - Dynamic GraphQL function calling against live Monday.com boards (*Deals: 342 records, Work Orders: 175 projects*).
   - Word-by-word streaming typewriter animations with token shimmer.
   - Contextual follow-up chips and Plotly chart generation.

2. **📋 Deals Board & Pipeline Intelligence**:
   - Full sales pipeline inspection with stage, status, and sector breakdowns.
   - Elastic spring-physics probability bars and 60fps number counter.
   - Slide-over record inspector drawer with detailed financial splits.

3. **⚙️ Work Orders & Operational Execution**:
   - Live revenue realization, unbilled amounts, receivables, and execution duration tracking.
   - Interactive filtering by execution status (*Ongoing, Completed, Paused, Stuck*) and Nature of Work.

4. **👔 Leadership & Executive Briefing**:
   - Cross-board synthesis (Deals Signed vs Work Orders Active).
   - On-demand AI board briefing generation with key risk warnings.
   - Interactive chart drill-downs.

---

## 🛠️ Architecture & Tech Stack

- **Backend:** FastAPI (Python 3.12, Uvicorn)
- **Frontend:** Responsive Single Page Application (Inter typography, Plotly.js, marked.js, Canvas Confetti)
- **Data Source:** Monday.com GraphQL API (`items_page` cursor pagination with 5-minute cache)
- **LLM Engine:** `gemini-3.5-flash-lite` via `google-genai` SDK (`temperature = 0`)

---

## ⚙️ Environment Variables & Secrets

To run this application, set the following secrets in your Hugging Face Space / environment:

```bash
MONDAY_API_KEY="your_monday_jwt_token"
GEMINI_API_KEY="your_gemini_api_key"
```

---

## 🚀 Local Development

```bash
# 1. Clone repository
git clone <repo_url>
cd skyler

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env file with your API keys
echo MONDAY_API_KEY=your_key >> .env
echo GEMINI_API_KEY=your_key >> .env

# 4. Launch FastAPI server
uvicorn server:app --host 0.0.0.0 --port 8000
```
