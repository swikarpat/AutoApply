# Multi Agentic Automate Job Applications AI ⚡

An autonomous, agentic LinkedIn job application engine designed to stream, evaluate, and submit LinkedIn "Easy Apply" applications end-to-end. Built with Playwright Async API, Google Gemini Flash, and deterministic heuristic fallback pipelines.

---

## 🏗️ System Architecture & Execution Flow

```mermaid
flowchart TD
    %% Global Styling
    classDef input fill:#1e293b,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;
    classDef filter fill:#312e81,stroke:#818cf8,stroke-width:2px,color:#f8fafc;
    classDef decision fill:#701a75,stroke:#f472b6,stroke-width:2px,color:#f8fafc;
    classDef core fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#f8fafc;
    classDef action fill:#831843,stroke:#fb7185,stroke-width:2px,color:#f8fafc;
    classDef storage fill:#7c2d12,stroke:#fb923c,stroke-width:2px,color:#f8fafc;

    subgraph INGESTION ["1. In-Search Stream Ingestion"]
        A["LinkedIn Stream Engine<br/>(sortBy=DD, f_TPR=r86400)"]:::input
        B["Multi-Role Boolean Harvester<br/>(Staff, Senior, AI/ML SWE)"]:::input
        A --> B
    end

    subgraph PRE_QUAL ["2. Gatekeeper & Pre-Qualification"]
        C{"Eligibility Check"}:::decision
        C1["Public Company Filter"]:::filter
        C2["Headcount &gt; 200 Employees"]:::filter
        C3["No Third-Party Agencies"]:::filter
        C4["Exclude California / Bay Area"]:::filter
        
        B --> C
        C --> C1
        C --> C2
        C --> C3
        C --> C4
    end

    subgraph HEURISTICS ["3. Form Automation & Heuristic Engine"]
        D["Modal Traversal Engine<br/>(Playwright Async)"]:::core
        E["Master Truth Matrix<br/>(truth_matrix.yaml)"]:::storage
        F["Deterministic Matcher"]:::core
        G["Master PDF Resume<br/>(ResumeSoftwareEngineer.pdf)"]:::storage
        
        C1 & C2 & C3 & C4 -->|Passed| D
        E --> F
        F --> D
        G --> D
    end

    subgraph STATE_MACHINE ["4. Step-by-Step Field Resolution"]
        H["Contact & Phone (+1)"]:::action
        I["City Typeahead (San Francisco, CA)"]:::action
        J["Skill Experience (Strict Integers)"]:::action
        K["EEO & Hispanic/Latino (Force No/Decline)"]:::action
        L["Salary Range Matcher ($120k+)"]:::action
        M["Uncheck Follow Company Checkbox"]:::action

        D --> H
        D --> I
        D --> J
        D --> K
        D --> L
        D --> M
    end

    subgraph DISPATCH ["5. Submission & Pacing"]
        N["Auto-Submit Form"]:::core
        O["SQLite DB State Store<br/>(applications.db)"]:::storage
        P["Pacing Delay (4s) & Next Card"]:::input

        H & I & J & K & L & M --> N
        N --> O
        N --> P
        P --> B
    end
```

---

## 🚀 Key Modules

* **`daemon.py`**: The central execution runtime managing the browser lifecycle, streaming search cards, applying pre-qualification rules, and executing the form state machine.
* **`config/settings.yaml`**: System-level operational parameters, including search keywords, location filters (`target_location`, `exclude_california`), pacing delays, and company size/type thresholds.
* **`config/truth_matrix.yaml`**: The single source of truth for candidate metadata, work authorization status, salary expectations, skills mapping, and canned essay answers.
* **`src/mcp/tools/browser.py`**: Playwright stealth browser driver with persistent context storage to maintain LinkedIn login sessions without repeated re-authentication.

---

## ⚙️ Setup & Execution

### 1. Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configuration

```bash
cp config/truth_matrix.example.yaml config/truth_matrix.yaml
cp .env.example .env
```

Ensure your master resume is placed at `data/ResumeSoftwareEngineer.pdf`.

### 3. Run

```bash
python daemon.py
```