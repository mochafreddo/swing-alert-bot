# 📈 Roadmap — swing-alert-bot

This document defines the development roadmap for **swing-alert-bot**, including task breakdown, dependencies, priorities, sprint planning, and milestones.
The project is a **solo side project** (Geoffrey + Codex), with **no fixed deadlines**. Work will proceed iteratively in sprints.

---

## 1. Milestones

* **M1 — v1.0 (MVP)**

  * Manual watchlist input
  * Core signal engine (EMA/RSI/ATR + gap filter)
  * Telegram alerts (clear, beginner-friendly format)
  * Held tickers managed via `/buy`, `/sell`, `/list`
  * Infrastructure: AWS Lambda + EventBridge + S3 + Terraform

* **M2 — v1.1**

  * Auto screener: top N tickers by 20-day dollar volume & trend
  * Always monitor held tickers regardless of screener output
  * Improve state persistence (consider DynamoDB for concurrency)

* **M3 — v1.2**

  * Add visualization: basic chart snapshots in Telegram alerts
  * Improve UX of Telegram bot (inline buttons, summary commands)

* **M4 — v2.0**

  * Add Korean market support (via KIS Developers API)
  * Expand strategy (additional TA indicators, filters)

---

## 2. Task Breakdown (v1.0)

### A. Core Infrastructure

* [x] Setup Terraform project structure (modules for Lambda, EventBridge, S3, IAM, Secrets)
* [x] Define dev/prod environments (`tfvars`)
* [x] Use Terraform workspaces for env separation (default=dev, prod)
* [x] Create state bucket in S3 (encrypted, versioned)
* [x] Configure Lambda roles (least privilege)

### B. Data Layer

* [x] Implement Alpha Vantage client (with rate limiting)
* [x] Add caching logic (skip if data unchanged since last run)
* [x] Unit tests with mocked AV responses

### C. Signal Engine

* [x] Implement EMA(20/50), RSI(14), ATR(14), SMA(200)
* [x] Implement signal detection logic (crossovers, RSI re-cross, gap filter)
* [x] Add stop/target calculation helpers

### D. State Management

* [x] Define encrypted JSON schema (`held`, `alerts_sent`, `last_update_id`)
* [x] Implement S3 read/write helpers (with Fernet encryption)
* [x] Add optimistic locking using ETag conditional writes
* [x] Unit tests for state read/write

### E. Telegram Integration

* [x] Implement Telegram sendMessage wrapper
* [x] Implement getUpdates poller (with offset tracking)
* [ ] Implement commands:

  * [x] `/buy TICKER` → mark as held
  * [x] `/sell TICKER` → unmark
  * [ ] `/list` → show held list
* [ ] Format beginner-friendly alerts (action-oriented)

### F. Lambda Runners

* [ ] `eod_runner` → compute signals, send alerts
* [ ] `open_runner` → apply gap filter, send updates
* [ ] `command_poller` → process Telegram commands

### G. CI/CD

* [ ] Setup GitHub Actions CI (lint, typecheck, tests with `uv`)
* [ ] Setup GitHub Actions CD (Terraform plan/apply with OIDC → AWS)
* [ ] Cache uv dependencies in CI

---

## 3. Dependencies

* **Infrastructure** (A) must be completed before deploying runners (F).
* **Data Layer** (B) and **Signal Engine** (C) are independent, but C depends on B.
* **State Management** (D) must be ready before Telegram commands (E) and runners (F).
* **Telegram Integration** (E) is independent but required by runners (F).
* **CI/CD** (G) can be started early, but finalized after Infrastructure (A).

---

## 4. Priorities

1. **Infrastructure (A)** — foundation for Lambda, S3, secrets.
2. **Data Layer (B)** + **Signal Engine (C)** — core business logic.
3. **State Management (D)** — critical for correctness and persistence.
4. **Telegram Integration (E)** — enables visible output.
5. **Runners (F)** — integrate and operationalize.
6. **CI/CD (G)** — ensures reproducibility and smooth deploys.

---

## 5. Sprint Planning

Since this is a solo project with no strict deadlines, sprints are **flexible 1–2 week iterations** focused on delivering vertical slices.

* **Sprint 1**: Infra bootstrap (Terraform skeleton, S3, Lambda stubs)
* **Sprint 2**: Data layer + basic signal engine (test with sample tickers)
* **Sprint 3**: State management + Telegram commands
* **Sprint 4**: Runners wired to EventBridge, end-to-end alerts in dev
* **Sprint 5**: Polish + deploy to prod (v1.0 release)

---

## 6. Tracking

* Tasks tracked in GitHub Issues (linked to roadmap sections).
* Milestones in GitHub set for `v1.0`, `v1.1`, `v1.2`, `v2.0`.
* Progress measured by closing tasks/issues, not by calendar dates.
