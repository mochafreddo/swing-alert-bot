# 📄 Product Requirements Document (PRD) — Swing Trading Alert Bot (U.S. Market Only)

## 1. Purpose

* **Problem**: It’s difficult to constantly watch stock charts and not miss trading signals.
* **Goal**: Automatically detect swing trading signals from U.S. stocks **at market close** and **at market open**, then send actionable alerts via **Telegram**, so the user (Geoffrey) can decide and execute trades manually.

---

## 2. Scope

* **In-Scope**

  * U.S. stock markets (NYSE, NASDAQ).
  * Data source: **Alpha Vantage API** (daily data, 500 calls/day limit).
  * Strategy: EMA(20/50) crossover, RSI(14) signals, ATR-based stop/target, gap filter.
  * Alerts delivered via Telegram bot (beginner-friendly format).
  * Position management: via Telegram commands (`/buy`, `/sell`, `/list`).
  * **Infrastructure**: AWS Lambda functions, scheduled by EventBridge, state persisted in S3 (encrypted JSON), provisioned and managed via Terraform.

* **Out-of-Scope**

  * Korean stock market (to be considered later).
  * Automated order execution.
  * Multi-user support or public distribution (single-user only).

---

## 3. User

* **Primary User**: Geoffrey (individual retail investor).
* **Needs**:

  * Avoid missing signals without watching charts constantly.
  * Understand alerts at a glance (“Buy or not?”).
  * Manage current holdings easily.

---

## 4. Requirements

### Functional

1. **Data Collection**

   * Pull daily candles from Alpha Vantage.
   * Support up to \~200 tickers within the free 500 calls/day quota.
   * Store at least 200 days of history for indicator calculations.

2. **Signal Engine**

   * EMA(20/50) golden/death cross detection.
   * RSI(14) re-cross over 30 or under 70.
   * ATR(14)-based stop loss / take profit guide.
   * Gap filter: open price vs. previous close > ±3% or > 1×ATR triggers conditional entry rules.

3. **Position Management**

   * Manage via Telegram commands:

     * `/buy AAPL` → mark ticker as held
     * `/sell NVDA` → remove ticker from held list
     * `/list` → show all held tickers
   * Held tickers are **always monitored**, even if excluded by the screener.

4. **Alerts (Telegram)**
   Example format (buy candidate):

   ```
   🟢 [BUY CANDIDATE] AAPL
   Action today: Decide if you will enter at the next U.S. market open

   Why:
   - EMA20 crossed above EMA50 (uptrend)
   - Price above 200SMA
   - RSI(14) bounced above 30

   Plan:
   - Base: enter at next open
   - Exception: if open gap > 3% or >1×ATR → wait for intraday re-break or pullback

   Risk guide:
   - ATR(14): $3.10
   - Stop: $145.5 / Target: $159.5 (≈1:2 R:R)
   Validity: 3 trading days
   ```

5. **Operations**

   * EventBridge Scheduler triggers Lambdas at U.S. market close and open.
   * State stored in S3 bucket as **encrypted JSON**.
   * Secrets (Alpha Vantage key, Telegram token, chat ID) stored in **AWS SSM Parameter Store or Secrets Manager**.
   * Infrastructure defined and deployed via **Terraform**.
   * Deduplication of alerts per ticker per date.

---

### Non-Functional

* **Performance**: Handle \~200 tickers within Lambda timeout (15 minutes).
* **Reliability**: 99%+ alert delivery success rate.
* **Cost**: Operate within AWS Free Tier (Lambda, EventBridge, S3).
* **Security**:

  * IAM least-privilege roles.
  * Encrypted S3 bucket.
  * Secrets in SSM/Secrets Manager.
* **Scalability**: Can shard tickers across multiple Lambdas or migrate state to DynamoDB for concurrency-safe updates.

---

## 5. Success Metrics

* **Signal Coverage**: Detect major swing signals without missing.
* **Decision Efficiency**: Alerts are clear enough for a manual decision in under 5 minutes.
* **Cost Efficiency**: Maintain infra cost within Free Tier (\$0–5/month).

---

## 6. Risks & Mitigation

* **API rate limits**: 5 requests/min, 500/day → throttle requests, limit to \~200 tickers, or upgrade API plan.
* **Concurrency on S3 state**: multiple Lambdas writing simultaneously may cause lost updates → use optimistic locking (ETag) or migrate to DynamoDB in v1.1+.
* **Daylight Savings Time shifts**: handle via EventBridge time expressions + runtime validation.
* **Terraform misconfigurations**: mitigate via plan/review/approval workflow.

---

## 7. Roadmap

* **v1 (MVP)**

  * Manual watchlist (user-specified tickers).
  * Signal engine (EMA/RSI/ATR + gap filter).
  * Telegram alerts with action-oriented format.
  * Held tickers managed via `/buy`, `/sell`, `/list`.
  * **Infra: Lambda + EventBridge + S3 (Terraform-managed)**.

* **v1.1**

  * Automatic screener: select top N tickers by 20-day dollar volume & trend filter.
  * Always include held tickers in monitoring.
  * Consider DynamoDB for state to avoid concurrency issues.

* **v1.2**

  * Add visualization (basic chart images in alerts).

* **v2**

  * Add Korean market support (via KIS Developers API).

---

## 8. Deployment & Environments

* **Environments**: Two environments (dev, prod). The same Terraform code is applied with environment-specific `tfvars`. Separation is enforced using Terraform workspaces (`default` used as dev; a `prod` workspace is created for production).
* **State (Terraform)**: For a solo project on one machine, keep Terraform state **local**. If/when CI or multiple machines are used, an S3+DynamoDB remote backend can be added later.
  * Optional remote layout (when needed): S3 bucket (e.g., `sab-tfstate-<account-id>`, versioned, encrypted) + DynamoDB table `sab-tf-locks` (PK: `LockID`), with key `env/${terraform.workspace}/terraform.tfstate`.
* **App State vs TF State**: The project’s “state bucket” created by Terraform stores the app’s encrypted JSON (held tickers, dedupe keys). If using a Terraform remote backend, keep it in a separate bucket.
* **IAM (Least Privilege)**: The deploy identity has minimal permissions for provisioning resources (S3, IAM, Lambda, EventBridge, SSM/Secrets). Lambda runtime roles only receive access to S3 state, logs, and secret reads as required.
* **Operate**: Apply from `infra/terraform` with the appropriate workspace and var-file, e.g. `terraform workspace select prod && terraform apply -var-file=envs/prod.tfvars`.
