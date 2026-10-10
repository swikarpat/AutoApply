# AutoApply Master Blueprint & Agent Memory Store

> **CRITICAL DIRECTIVE FOR ALL AI AGENTS**:
> This document is the **single source of truth** and **live dynamic memory** for the AutoApply codebase.
> Whenever you (the AI assistant) introduce new automation agents, modify LinkedIn DOM selectors, update form-filling heuristics, alter the truth matrix schema, or adjust operational guardrails, **you are strictly required to update this file in the same turn**.
> Before executing commands or refactoring code, cross-verify this document against the physical workspace (`main.py`, `src/agents/form_agent.py`, `src/agents/discovery_agent.py`, `config/settings.yaml`, `config/truth_matrix.yaml`) to ensure zero hallucinations.

---

## 1. System Design & Architecture Overview

AutoApply is a high-reliability, zero-manual-intervention **Autonomous Job Application Engine and LinkedIn Easy Apply Daemon**. It combines browser automation (Playwright Chromium with anti-bot stealth countermeasures), deterministic rule engines, an intelligent Truth Matrix, and Gemini 2.5 Flash Large Language Model inference to autonomously discover, qualify, fill, and submit job applications at scale.

The architecture strictly decouples job stream discovery, form field introspection, question classification, and application state persistence through a finite state machine (FSM) backed by an ACID SQLite write-ahead logging (WAL) database.

### High-Level System Topology

```
                               ┌────────────────────────────────────────────────────────┐
                               │   Master Unified CLI Entry Point (main.py)              │
                               │   • login: Interactive LinkedIn browser session setup  │
                               │   • stream: Continuous discovery & auto-apply loop     │
                               │   • apply --url: Single targeted job execution         │
                               │   • stats: Real-time rich terminal telemetry report    │
                               └───────────────────────────┬────────────────────────────┘
                                                           │
                                                           ▼
                               ┌────────────────────────────────────────────────────────┐
                               │   Persistent Browser Context (Playwright Chromium)     │
                               │   • Path: data/browser_profile (Session Cookies/State) │
                               │   • Anti-Bot Armor: --disable-blink-features=...       │
                               │   • Randomized humanized micro-delays (250ms - 1500ms) │
                               └──────────────┬──────────────────────────┬──────────────┘
                                              │                          │
                         Search & Job Stream  │                          │ Form Navigation & DOM
                                              ▼                          ▼
 ┌────────────────────────────────────────────────────┐  ┌──────────────────────────────────────────────┐
 │ Discovery Agent (src/agents/discovery_agent.py)    │  │ Form Automation Agent (src/agents/form_agent)│
 │ • Scrapes LinkedIn search results (keywords/loc)  │  │ • 100% Autonomous Easy Apply execution       │
 │ • Identifies "Easy Apply" badges vs external links │  │ • Step-by-step modal traversal (Next/Review) │
 │ • De-duplicates against local SQLite database      │  │ • Master Resume attachment (PDF upload)      │
 │ • Emits qualified jobs to form processing pipeline │  │ • 🛡️ Dual-layer Anti-Follow Protection       │
 └────────────────────────────────────────────────────┘  └──────────────────────┬───────────────────────┘
                                                                                │
                                                            Question Context    │ Candidate Truth Matrix
                                                            & Unmapped Fields   ▼
                                                         ┌──────────────────────────────────────────────┐
                                                         │ 3-Tier Intelligent Form Answering Engine     │
                                                         │ 1. Deterministic Truth Matrix (truth_matrix) │
                                                         │ 2. Semantic Heuristic Pattern Matcher        │
                                                         │ 3. Gemini 2.5 Flash Schema Fallback          │
                                                         └──────────────────────┬───────────────────────┘
                                                                                │
                                                            State Transitions   │ Audit Logging
                                                            & Error Telemetry   ▼
                                                         ┌──────────────────────────────────────────────┐
                                                         │ Application State Store & FSM (SQLite WAL)   │
                                                         │ • Path: data/applications.db (WAL Mode)      │
                                                         │ • FSM States: DISCOVERED -> EVALUATED ->     │
                                                         │   FORM_MAPPED -> IN_PROGRESS -> SUBMITTED    │
                                                         │ • Full proof screenshot audit trail          │
                                                         └──────────────────────────────────────────────┘
```

---

## 2. Core Component & Directory Map

| Component | Path | Language / Runtime | Core Responsibilities |
| :--- | :--- | :--- | :--- |
| **Unified CLI** | [`main.py`](file:///Users/swikar/TechProject/AutoApply/main.py) | Python 3.14+ | Canonical entry point providing subcommands: `stream`, `apply`, `login`, `stats`, `daemon`, `single`. |
| **Form Automation** | [`src/agents/form_agent.py`](file:///Users/swikar/TechProject/AutoApply/src/agents/form_agent.py) | Python 3.14+ / Playwright | Multi-step form inspection, DOM input/radio/dropdown synthesis, question answering, follow-checkbox guardrail, and auto-submit. |
| **Discovery Agent** | [`src/agents/discovery_agent.py`](file:///Users/swikar/TechProject/AutoApply/src/agents/discovery_agent.py) | Python 3.14+ / Playwright | LinkedIn search pagination, infinite scroll card extraction, Easy Apply filtering, and queue dispatching. |
| **State Machine (FSM)**| [`src/core/fsm.py`](file:///Users/swikar/TechProject/AutoApply/src/core/fsm.py) | Python 3.14+ | Finite State Machine governing valid transitions (`DISCOVERED`, `EVALUATED`, `FORM_MAPPED`, `SUBMITTED`, `FAILED`, `SKIPPED`). |
| **State Database** | [`src/core/database.py`](file:///Users/swikar/TechProject/AutoApply/src/core/database.py) | SQLite 3 (WAL Mode) | Persistent storage for job postings, company names, submission timestamps, error traces, and status metrics. |
| **Human Pacing Engine** | [`src/core/human_pacing.py`](file:///Users/swikar/TechProject/AutoApply/src/core/human_pacing.py) | Python 3.14+ | Rolling 24-hour application ceiling, stochastic daily targets, operating hours window (09:00-21:30), reading delays, step delays, and keystroke cadence. |
| **Alert Notifier** | [`src/core/notifier.py`](file:///Users/swikar/TechProject/AutoApply/src/core/notifier.py) | Python 3.14+ / osascript | Native macOS desktop banner and audio chime dispatch with daily deduplication for application cap events. |
| **System Telemetry** | [`src/core/telemetry.py`](file:///Users/swikar/TechProject/AutoApply/src/core/telemetry.py) / [`telemetry_collector.py`](file:///Users/swikar/TechProject/AutoApply/telemetry_collector.py) | Python 3.14+ / psutil | Continuous system resource telemetry recording (CPU, RAM, Disk, Network) to streaming JSON Lines (.jsonl). |
| **LLM Reasoning** | [`src/core/llm_client.py`](file:///Users/swikar/TechProject/AutoApply/src/core/llm_client.py) | Google GenAI SDK | Gemini 2.5 Flash integration for open-ended or unforeseen application questions with strict candidate truth grounding. |
| **Candidate Profile** | [`config/truth_matrix.yaml`](file:///Users/swikar/TechProject/AutoApply/config/truth_matrix.yaml) | YAML | Candidate ground truth: contact details, work authorization, salary expectations, skills experience years, EEO responses. |
| **Operational Config** | [`config/settings.yaml`](file:///Users/swikar/TechProject/AutoApply/config/settings.yaml) | YAML | Search queries, target locations, stealth delay ranges, auto-submit flags, and rate limiting parameters. |
| **Automated Tests** | [`tests/`](file:///Users/swikar/TechProject/AutoApply/tests/) | Pytest / Asyncio | Unit and integration test suites: `test_follow_checkbox.py`, `test_form_agent.py`, `test_database.py`, `test_llm_client.py`. |
| **Browser Storage** | `data/browser_profile/` | Chromium Profile | Persistent user directory holding active LinkedIn authentication cookies and session state. |

---

## 3. End-to-End Autonomous Workflow Lifecycle

```
[Start Stream / Apply] ──> [Attach Persistent Chromium] ──> [Navigate to Job URL / Search]
                                                                        │
                                                                        ▼
                                                         [Detect "Easy Apply" Button]
                                                                        │
                                               ┌────────────────────────┴────────────────────────┐
                                               ▼                                                 ▼
                                     [External Link / No Apply]                        [Easy Apply Present]
                                               │                                                 │
                                               ▼                                                 ▼
                                     [Mark SKIPPED in DB]                              [Click Easy Apply]
                                                                                                 │
                                                                                                 ▼
                                                                           ┌───────────────────────────────────────────┐
                                                                           │ Loop: Process Modal Application Step      │
                                                                           ├───────────────────────────────────────────┤
                                                                           │ 1. Fill Text Inputs & Phone Number        │
                                                                           │ 2. Select Dropdowns & Radio Buttons       │
                                                                           │ 3. Resolve Experience / Work Auth Qs      │
                                                                           │ 4. Attach Resume PDF (if requested)       │
                                                                           │ 5. 🛡️ Uncheck Follow-Company Checkbox     │
                                                                           └─────────────────────┬─────────────────────┘
                                                                                                 │
                                                                       ┌─────────────────────────┴─────────────────────────┐
                                                                       ▼                                                   ▼
                                                            ["Next" Button Active]                              ["Review" Button Active]
                                                                       │                                                   │
                                                                       ▼                                                   ▼
                                                            [Click Next & Continue]                             [Advance to Review Screen]
                                                                                                                           │
                                                                                                                           ▼
                                                                                                        ┌───────────────────────────────────────────┐
                                                                                                        │ Review Screen Guardrails                  │
                                                                                                        ├───────────────────────────────────────────┤
                                                                                                        │ 1. Scroll to Modal Bottom                 │
                                                                                                        │ 2. 🛡️ Force Uncheck Follow Company Check  │
                                                                                                        │ 3. Verify All Fields Complete             │
                                                                                                        └─────────────────────┬─────────────────────┘
                                                                                                                              │
                                                                                                                              ▼
                                                                                                                  [Click "Submit application"]
                                                                                                                              │
                                                                                                                              ▼
                                                                                                                  [Capture Proof Screenshot]
                                                                                                                              │
                                                                                                                              ▼
                                                                                                                  [Dismiss Done / Confirmation]
                                                                                                                              │
                                                                                                                              ▼
                                                                                                                  [Commit SUBMITTED to SQLite]
```

---

## 4. Architectural Decision Records (ADRs)

### ADR-001: 100% Autonomous LinkedIn Easy Apply (Zero-Manual-Intervention & Complete HITL Deprecation)
* **Status**: Accepted & Enforced
* **Decision**: Permanently eliminate all manual "Human-In-The-Loop" (HITL) prompt pauses and the `PENDING_HITL` state. The system operates in 100% autonomous mode (`auto_submit = True` unconditionally) across both stream discovery and single application workflows.
* **Engineering Rationale**:
  1. Manual confirmation dialogs and review pauses disrupt autonomous operation and conflict with candidate requirements.
  2. The candidate's Truth Matrix (`truth_matrix.yaml`) combined with semantic fallbacks and Gemini 2.5 Flash handles 100% of standard Easy Apply fields reliably.
  3. No artificial execution timers (e.g. 2-minute or 30-minute throttles) are enforced; jobs are processed continuously per `settings.yaml` boundaries.
  4. Edge cases and unresolvable validation errors are captured cleanly and recorded as `FAILED` in SQLite without blocking subsequent stream jobs.

### ADR-002: Dual-Layer Anti-Follow Guarantee (Never Follow Any Company)
* **Status**: Accepted & Enforced
* **Decision**: Implement an unbending, multi-layer verification routine (`uncheck_follow_company`) ensuring that the candidate **never follows any company page** during or after application submission.
* **Engineering Rationale**:
  1. LinkedIn defaults the `Follow <company> to stay up to date with their page` checkbox to `checked` on almost every Easy Apply form.
  2. Following hundreds of applied companies clutters the candidate's professional feed and exposes automation footprints.
  3. **Implementation Invariant**: Dual-layer inspection combines direct DOM JavaScript execution (`chk.checked = false; chk.dispatchEvent(...)`) with Playwright locators across every intermediate form step, the review screen, and immediately prior to clicking "Submit application". It verifies state before clicking so it *never* accidentally toggles a checkbox back on.

### ADR-003: Playwright Persistent Browser Context over Ephemeral Automation Sessions
* **Status**: Accepted & Enforced
* **Decision**: Launch browser instances using `playwright.chromium.launch_persistent_context()` pointing to `data/browser_profile/` with anti-bot arguments (`--disable-blink-features=AutomationControlled`).
* **Engineering Rationale**:
  1. Ephemeral browser contexts require re-logging in on every run, which immediately triggers LinkedIn OTP challenges and security checkpoints.
  2. Persistent contexts maintain valid session cookies, localStorage, and device trust fingerprints.
  3. A dedicated `python main.py login` command allows the user to perform interactive biometric/2FA verification once, after which all headless and headful runs reuse the authenticated profile.

### ADR-004: Hierarchical 3-Tier Question Resolution Engine
* **Status**: Accepted & Enforced
* **Decision**: Resolve form questions using a strict 3-tier cascade:
  * **Tier 1 (Deterministic Truth Matrix)**: Exact key lookup in `truth_matrix.yaml` (Name, Email, Phone, City, Work Authorization, Sponsorship).
  * **Tier 2 (Semantic Heuristic Matching)**: Normalized string heuristics for standard industry prompts (Years of experience mapped from skill dict, background check consent = Yes, drug test consent = Yes, felony/convictions = No, EEO/diversity = "Decline to specify").
  * **Tier 3 (Gemini 2.5 Flash Fallback)**: For novel or open-ended company questions, format a structured JSON prompt with candidate credentials and query Gemini Flash to select or draft the optimal response.
* **Engineering Rationale**: Prevents unnecessary LLM API calls and latency on 95% of standard questions while maintaining high adaptability for complex questionnaires.

### ADR-005: SQLite Write-Ahead Logging (WAL) State Store & Terminal Status Invariant
* **Status**: Accepted & Enforced
* **Decision**: Store all job postings, evaluation logs, and application states in a local SQLite database (`data/applications.db`) configured with `PRAGMA journal_mode=WAL;`. Enforce terminal immutability: once an application transitions to `SUBMITTED`, its status cannot be regressed or overwritten by subsequent scraped duplicate cards or render retries.
* **Engineering Rationale**:
  1. Fast, zero-dependency, crash-resilient ACID storage suitable for single-node daemon processes.
  2. WAL mode allows concurrent reads (e.g. `main.py stats`) while the daemon writes application updates without table locking.
  3. Terminal immutability guarantees historical submission audit records remain accurate even when LinkedIn search streams re-render identical cards.


### ADR-006: Unified Master CLI Architecture
* **Status**: Accepted & Enforced
* **Decision**: Standardize all CLI interactions into `main.py` with structured argparse subcommands (`stream`, `apply`, `login`, `stats`), while retaining `daemon.py` and `test_single.py` as lightweight shims.
* **Engineering Rationale**: Eliminates fractured entry scripts and ensures all operational workflows share identical initialization, configuration loading, and error handling.

### ADR-007: Enterprise Employer Boundary (Strict $\ge 5,000$ Employees Invariant)
* **Status**: Accepted & Enforced
* **Decision**: Enforce a mandatory minimum company size threshold of **5,000 employees** across all job discovery and stream operations.
* **Engineering Rationale**:
  1. The candidate exclusively targets large-scale enterprise companies offering robust engineering infrastructure, career mobility, and compensation parity.
  2. Sub-5000 size brackets (`1-10`, `11-50`, `51-200`, `201-500`, `501-1,000`, `1,001-5,000 employees`) and job postings with unverified employee counts are immediately rejected before application mapping.
  3. Valid size tiers are strictly constrained to `5,001-10,000 employees`, `10,001+ employees`, or explicit employee counts verified $\ge 5,000$.

### ADR-008: High-Speed Zero-Disturbance Execution (Headless Mode & Instant Pre-Filter)
* **Status**: Accepted & Enforced
* **Decision**: Execute all browser automation in headless mode by default (`headless_browser: true`) with single-pass JavaScript card pre-filtering and multi-page stream pagination.
* **Engineering Rationale**:
  1. Prevents browser window popups from disturbing the user's workflow or stealing window focus.
  2. Single-pass JS card extraction triages 25 search cards in $<50\text{ ms}$, instantly filtering out California locations, already-applied jobs, staffing agencies, and non-Easy-Apply postings without triggering sequential 1.2s card clicks.
  3. Automatic multi-page stream pagination advances to subsequent result pages (`&start=25`, `&start=50`, etc.) to sustain continuous autonomous application throughput.

### ADR-009: Human-Like Behavioral Mimicry and 24-Hour Rolling Quota Enforcement
* **Status**: Accepted & Enforced
* **Decision**: Enforce a comprehensive Human Behavioral Mimicry and Anti-Bot Pacing Engine (`HumanPacingEngine`) across all discovery, form filling, and stream operations.
* **Engineering Rationale**:
  1. **Strict 24-Hour Application Ceiling**: LinkedIn enforces an internal rate limit ceiling (~50 applications per 24 hours). The engine queries `ApplicationStateStore.count_recent_submissions(hours=24)` and enforces a hard ceiling of **48 applications** within any rolling 24-hour window, preventing account restriction.
  2. **Stochastic Daily Quota**: To mimic natural human job-hunting variability, compute a floating daily target seeded deterministically by `date.toordinal()`:
     - Weekdays (Mon-Fri): Gaussian distribution clamped between 42 and 47 applications ($\mu = 45, \sigma = 2$).
     - Weekends (Sat-Sun): Balanced volume between 12 and 20 applications.
  3. **Natural Operating Hours Window**: Applications are strictly restricted to local hours between 09:00 and 21:30. Stream loops cleanly idle or halt outside this window.
  4. **Micro-Jitter & Natural Delays**:
     - Pre-apply reading delay: 12 to 28 seconds of dwell time on the posting before clicking Easy Apply.
     - Step transition delay: 1.8 to 3.8 seconds between modal form steps.
     - Inter-application delay: 45 to 110 seconds between applications, with a 15% probability of an extended 6 to 12 minute break (360-720s).
     - Keystroke cadence: Text inputs use Playwright's `press_sequentially(text, delay=random.randint(60, 130))` with automatic fallback to instant fill on failure.

### ADR-010: Emergency Security Checkpoint / CAPTCHA Circuit Breaker
* **Status**: Accepted & Enforced
* **Decision**: Implement an immediate fail-safe circuit breaker abort upon encountering any LinkedIn security challenge, checkpoint URL, Arkose Labs iframe, or CAPTCHA container.
* **Engineering Rationale**:
  1. Prevents automated headless daemons from attempting inputs during account security verification, preventing permanent account restriction.
  2. Dispatches an urgent macOS desktop notification with sound `"Sosumi"` alerting the user that manual verification is required.
  3. Creates an emergency lockfile at `data/.checkpoint_lock`. While active, all subsequent `main.py stream` and `apply` invocations abort immediately at startup without generating network traffic.
  4. Once manually resolved via `./autoapply login`, the candidate clears the lock using `./autoapply unlock`.

### ADR-011: Robust macOS Sleep/Wake & Abrupt Disconnect Recovery
* **Status**: Accepted & Enforced
* **Decision**: Harden browser lifecycle management against intermittent laptop sessions, lid closes, and sleep/wake network disconnects.
* **Engineering Rationale**:
  1. **Singleton Stale Lock Pruning**: Abrupt laptop sleep or kill signals leave Chromium `SingletonLock`, `SingletonCookie`, and `SingletonSocket` symlinks. `StealthBrowserTool` proactively purges these stale locks prior to launching `launch_persistent_context()`.
  2. **Graceful Disconnection Handling**: Catch `TargetClosedError` and `PlaywrightError` ("browser closed", "connection closed") mid-stream. If the laptop lid closes during an active application, the runner logs a warning, releases browser resources cleanly, and halts without leaving zombie processes.
  3. **30-Minute Re-engagement Frequency**: The macOS `launchd` daemon executes on an 1800-second (30 minute) recurring interval, allowing the application engine to automatically resume whenever the laptop wakes within active operating hours.

### ADR-012: Simplified Native Search Scope & Zero-Filter Policy (United States vs. California)
* **Status**: Accepted & Enforced
* **Decision**: Eliminate complex, fragile city-by-city post-filtering in favor of simplified, native LinkedIn location search targeting (`target_location: "United States"` covering all US states including California, or `"California"`). By default, zero post-filtering is applied (`all_ca` pass-through), ensuring every discovered job matching role and enterprise criteria is eligible for application.
* **Engineering Rationale**:
  1. Manual city lists fail to capture the breadth of metropolitan areas and create fragile maintenance bottlenecks.
  2. LinkedIn's native search engine handles geographic clustering natively when passed `"United States"` (all 50 states including California) or `"California"`.
  3. All locations within the search scope are accepted directly without post-filtering.
  4. **Backward Compatibility**: If an explicit `california_policy` (`exclude_ca`, `bay_area_only`, or `all_ca`) is provided, `DiscoveryAgent.evaluate_location_policy` continues to honor it without breaking existing configurations.


---

## 5. Live Dynamic Memory & Active Operational Invariants

### 🧠 Persistent Knowledge Vault

1. **Enterprise Employer Invariant ($\ge 5,000$ Employees)**:
   - Only companies with verified $\ge 5,000$ employees (`5,001-10,000 employees`, `10,001+ employees`, or confirmed numeric totals $\ge 5,000$) are eligible.
   - Any posting with $< 5,000$ employees or unverified employee count is marked `SKIPPED` in SQLite.

2. **Anti-Follow Invariant**:
   - `input#follow-company-checkbox` or any checkbox with label containing `"Follow"` or `"stay up to date"` must **ALWAYS** be unchecked.
   - Verification must occur:
     - On initial step load
     - After filling fields
     - After scrolling to bottom
     - On the Final Review screen
     - Milliseconds prior to clicking `"Submit application"`

3. **LinkedIn Easy Apply DOM Selectors**:
   - Easy Apply Button:
     - `button.jobs-apply-button`
     - `button[aria-label*="Easy Apply"]`
     - `.jobs-s-apply button`
   - Form Modal Container:
     - `div.jobs-easy-apply-modal`
     - `div[data-test-modal-id="easy-apply-modal"]`
     - `div[role="dialog"]`
   - Navigation Buttons:
     - Next: `button[aria-label="Continue to next step"]`, `button:has-text("Next")`
     - Review: `button[aria-label="Review your application"]`, `button:has-text("Review")`
     - Submit: `button[aria-label="Submit application"]`, `button:has-text("Submit application")`
     - Dismiss: `button[aria-label="Dismiss"]`, `button:has-text("Done")`

4. **Stealth & Anti-Detection Rules (ADR-009 Pacing Standards)**:
   - Never use fixed delays. Enforce natural randomized timing distributions:
     - Pre-apply reading pause: `12.0s - 28.0s`
     - Modal step transitions: `1.8s - 3.8s`
     - Typing simulation cadence: `60ms - 130ms` per keystroke (`25ms - 50ms` for long essays)
     - Inter-job delays: `45.0s - 110.0s` with 15% chance of 6-12 minute rest break (`360s - 720s`)
     - Operating window: `09:00 - 21:30` local time only
     - Rolling 24h cap: Hard ceiling `48` applications (strictly below LinkedIn's 50 limit)
   - Always run with viewport `1280x800` or higher to prevent mobile responsive layouts from hiding desktop action buttons.
   - User agent string must match contemporary macOS Chrome desktop.

5. **Secrets & Privacy Isolation**:
   - The following files contain private identity, credentials, or session cookies and **MUST NEVER BE COMMITTED TO GIT**:
     - `data/` (contains `applications.db`, resume PDFs, and `browser_profile/`)
     - `.env` (contains `GEMINI_API_KEY`)
     - `config/truth_matrix.yaml` (contains real candidate phone, email, address, and demographic data)
     - `archive/` (contains experimental scripts and scraped dumps)

6. **Timezone Alignment Invariant**:
   - Operating hours (`09:00 - 21:30`) strictly evaluate against the **user's current local timezone** (`datetime.now().time()`) rather than remote server clocks or US employer timezones.

7. **Concurrency & Log Hygiene**:
   - Database operations enforce SQLite Write-Ahead Logging (`PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;`) so CLI commands like `./autoapply stats` never lock the database during active background daemon execution.
   - `data/stream_out.log` and `data/stream_err.log` are automatically monitored and rotated if size exceeds 15MB.

8. **Daily Cap Alert System**:
   - Dispatches a native macOS desktop banner notification with audio chime (`Glass`) whenever the stochastic daily quota or hard 24h ceiling is reached.
   - Enforces calendar-date deduplication (`data/.last_cap_alert`) ensuring the user receives exactly one notification per day rather than repetitive alerts on recurring launchd intervals.

9. **Security Checkpoint Circuit Breaker Invariant**:
   - URL patterns (`/checkpoint/`, `/challenge/`, `/uas/consumer-captcha`) or DOM indicators (Arkose Labs iframes, `#captcha-internal`, `"quick security check"`, `"verify it's you"`) immediately trip the circuit breaker.
   - Creates `data/.checkpoint_lock` and sounds an urgent `"Sosumi"` macOS audio chime.
   - All subsequent autonomous runs remain strictly paused until manually cleared with `./autoapply unlock`.

10. **Simplified Native Search Scope & Zero Post-Filtering Invariant**:
    - By default, searches target `target_location: "United States"` (covering all 50 states including California) or `"California"` natively on LinkedIn.
    - Post-filtering is disabled (`all_ca` pass-through), so all qualified enterprise jobs within the search scope are accepted directly.
    - If explicit legacy policy is supplied (`exclude_ca` or `bay_area_only`), `evaluate_location_policy` continues to honor it backward-compatibly.

---

## 6. Development, Testing & Production Runbook

### Environment Setup
```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies (if updated)
pip install -r requirements.txt
playwright install chromium
```

### Operational Commands
```bash
# You can use './autoapply' directly or '.venv/bin/python main.py' (or 'source .venv/bin/activate')

# 1. Interactive LinkedIn Login (Run once to establish session)
./autoapply login

# 2. Continuous Stream Auto-Apply
./autoapply stream

# 3. Dry-Run Stream (Autofills everything, pauses on Review screen without submitting)
./autoapply stream --dry-run

# 4. Apply to a Specific Job URL (Targeted execution)
./autoapply apply --url "https://www.linkedin.com/jobs/view/<JOB_ID>/"

# 5. Dry-Run Single Job (Autofills, unchecks follow-company, and holds for inspection)
./autoapply apply --url "https://www.linkedin.com/jobs/view/<JOB_ID>/" --dry-run

# 6. View Live Application Metrics & Statistics
./autoapply stats

# 7. Reset Emergency Checkpoint Lock (After manual login / CAPTCHA resolution)
./autoapply unlock

# 8. Continuous System Telemetry Logging (CPU, RAM, Disk, Net to JSONL)
./autoapply telemetry --log-file data/telemetry_log.jsonl --interval 5
# Or via standalone script:
python telemetry_collector.py --log-file telemetry_log.jsonl --interval 5
```

### Automated Test Suite
```bash
# Run all automated tests
.venv/bin/pytest tests/

# Test anti-follow checkbox guardrail specifically
.venv/bin/pytest tests/test_follow_checkbox.py

# Test form automation agent logic
.venv/bin/pytest tests/test_form_agent.py

# Test database CRUD and FSM state persistence
.venv/bin/pytest tests/test_database.py

# Test system telemetry collector
.venv/bin/pytest tests/test_telemetry.py

# Test browser recovery and sleep/wake resilience
.venv/bin/pytest tests/test_browser_recovery.py
```

### Background Daemon Automation (`launchd` on macOS)
```bash
# 1. Template located in repository:
templates/com.autoapply.stream.plist

# 2. Installed at:
~/Library/LaunchAgents/com.autoapply.stream.plist

# 3. Load / Register the 30-minute recurring background service:
launchctl load ~/Library/LaunchAgents/com.autoapply.stream.plist

# 4. Inspect live stdout / stderr logs:
tail -f data/stream_out.log
tail -f data/stream_err.log

# 5. Check real-time application database metrics:
./autoapply stats

# 6. Stop / Unload the background service:
launchctl unload ~/Library/LaunchAgents/com.autoapply.stream.plist
```

---

## 7. Key References & Associated Artifacts

* **Unified CLI Ingress**: [`main.py`](file:///Users/swikar/TechProject/AutoApply/main.py)
* **Form Automation Engine**: [`src/agents/form_agent.py`](file:///Users/swikar/TechProject/AutoApply/src/agents/form_agent.py)
* **Job Discovery Engine**: [`src/agents/discovery_agent.py`](file:///Users/swikar/TechProject/AutoApply/src/agents/discovery_agent.py)
* **State Machine & States**: [`src/core/fsm.py`](file:///Users/swikar/TechProject/AutoApply/src/core/fsm.py)
* **Database Layer**: [`src/core/database.py`](file:///Users/swikar/TechProject/AutoApply/src/core/database.py)
* **System Telemetry Collector**: [`src/core/telemetry.py`](file:///Users/swikar/TechProject/AutoApply/src/core/telemetry.py) / [`telemetry_collector.py`](file:///Users/swikar/TechProject/AutoApply/telemetry_collector.py)
* **Truth Matrix Configuration**: [`config/truth_matrix.yaml`](file:///Users/swikar/TechProject/AutoApply/config/truth_matrix.yaml)
* **System Settings**: [`config/settings.yaml`](file:///Users/swikar/TechProject/AutoApply/config/settings.yaml)
