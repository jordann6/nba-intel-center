# NBA Intel Center

A real-time player prop analysis engine that pairs live betting lines with historical NBA data, powered by Azure OpenAI GPT-4o and a vector-based memory system for context-aware intelligence across sessions.

![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?style=flat-square)
![Azure OpenAI](https://img.shields.io/badge/Azure-OpenAI-0078D4?style=flat-square)
![Qdrant](https://img.shields.io/badge/Vector_DB-Qdrant-DC244C?style=flat-square)
![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC?style=flat-square)

---

## Overview

The NBA Intel Center is a dual-layered analytics platform. The infrastructure layer handles full lifecycle management of Azure resources via Terraform, including Cognitive Services, Budgets, and Resource Groups. The application layer exposes a FastAPI backend that fetches live odds, queries season and recent-game statistics, and synthesizes analysis through a RAG pipeline backed by Qdrant vector storage. Each analysis is embedded and persisted, so follow-up questions draw on accumulated context rather than starting from scratch.

---

## Key Features

**Prop Analysis** — Weighs 2025-26 season averages against 5-game rolling trends to generate directional leans on player props including Points, Assists, Rebounds, and more.

**RAG-Powered Chat** — Qdrant stores each analysis as a vector embedding. Chat queries retrieve prior context so the AI delivers consistent, session-aware responses.

**Live Odds Integration** — Pulls today's game schedules, matchups, and moneyline data in real time from The Odds API.

**Cost Governance** — Built-in budget monitoring caps cloud spend at $20.00/month with automated email alerts when thresholds are approached.

---

## Tech Stack

| Layer            | Technology                                     |
| ---------------- | ---------------------------------------------- |
| Backend          | FastAPI (Python)                               |
| Infrastructure   | Terraform (HCL)                                |
| AI / LLM         | Azure OpenAI — GPT-4o + Text Embedding 3 Small |
| Vector Database  | Qdrant (VectorParams / Cosine Distance)        |
| Statistical Data | nba_api                                        |
| Market Data      | The Odds API                                   |
| Cloud Provider   | Microsoft Azure                                |

---

## API Endpoints

| Route      | Method | Description                                                                                   |
| ---------- | ------ | --------------------------------------------------------------------------------------------- |
| `/analyze` | `POST` | Deep-dive analysis of a player prop. Result is embedded and persisted to the vector database. |
| `/chat`    | `POST` | Contextual chat interface. Retrieves relevant past analyses before generating a response.     |
| `/games`   | `GET`  | Returns all NBA games scheduled for the current date.                                         |
| `/health`  | `GET`  | Reports API status and Qdrant collection connectivity.                                        |

---

## Installation and Setup

### 1. Deploy Infrastructure

From the root directory, initialize Terraform and apply the Azure environment. Provide your subscription ID, tenant ID, and alert email as variables.

```bash
terraform init
terraform apply \
  -var="subscription_id=your_id" \
  -var="tenant_id=your_id" \
  -var="alert_email=your@email.com"
```

### 2. Configure Environment

Create a `.env` file in the project root with the following credentials.

```env
AZURE_OPENAI_KEY=your_key
AZURE_OPENAI_ENDPOINT=your_endpoint
AZURE_OPENAI_DEPLOYMENT=gpt-4o
ODDS_API_KEY=your_odds_api_key
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

### 3. Run the Application

Install dependencies and start the development server.

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

---

## Statistical Mapping

The system translates common betting vernacular into official NBA statistical categories.

| Betting Term    | NBA Stat     |
| --------------- | ------------ |
| Points          | `PTS`        |
| Assists         | `AST`        |
| Rebounds        | `REB`        |
| Three Pointers  | `FG3M`       |
| Defensive Stats | `STL`, `BLK` |
