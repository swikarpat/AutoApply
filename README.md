# Multi Agentic AI Job ⚡

An autonomous, agentic LinkedIn job application engine designed to stream, evaluate, and submit LinkedIn "Easy Apply" applications end-to-end. Built with Playwright Async API, Google Gemini Flash, and deterministic heuristic fallback pipelines.

flowchart TD
    subgraph ConfigLayer ["1. Configuration & Truth Matrix"]
        A1["config/settings.yaml<br/>(Target Roles, Exclude CA, Public Only, >200 Emp)"]
        A2["config/truth_matrix.yaml<br/>(Profile, Skills Map, Comp, EEO, Work Auth)"]
        A3["data/ResumeSoftwareEngineer.pdf<br/>(Locked Master Resume)"]
    end

    subgraph SearchEngine ["2. Search Stream & Discovery"]
        B1["Query Generator<br/>Boolean Keyword Builder + sortBy=DD + f_TPR=r86400"]
        B2["Stealth Browser (Playwright)<br/>Persistent Session / Login Auth Check"]
        B3["Card Stream Consumer<br/>Zero-Reload In-Search Card Iterator"]
    end

    subgraph FilterPipeline ["3. Eligibility & Policy Gate"]
        C1{"Location Filter<br/>Exclude CA / Bay Area?"}
        C2{"Company Industry Filter<br/>Exclude Staffing / Agency / Consulting?"}
        C3{"Size & Structure Filter<br/>Public Company & >200 Employees?"}
        C4["Skip Card & Advance Stream"]
    end

    subgraph FormEngine ["4. Autonomous Modal Execution Engine"]
        D1["Top-Card Easy Apply Trigger<br/>Hardware Click & Modal Outlet Mount"]
        D2["Resume Uploader<br/>Direct PDF File Descriptor Injection"]
        D3["Deterministic Field Matcher<br/>Skill Years Map, Notice, Comp, Location"]
        D4["Radio Matrix & EEO Handler<br/>Work Auth: Yes | Visa: No | Hispanic: No | Ref: No"]
        D5["Dynamic Dropdown Substring Matcher<br/>Salary Bracket Match & Native Event Dispatch"]
        D6["Uncheck 'Follow Company' Interceptor"]
        D7["Error Detection & Retry Loop"]
    end

    subgraph FinalizeLayer ["5. Review & State Store"]
        E1["Final Submit / Manual Inspection Pause"]
        E2[("data/applications.db<br/>Application SQLite State Store")]
    end

    %% Wiring
    ConfigLayer --> SearchEngine
    B1 --> B2 --> B3
    B3 --> FilterPipeline
    C1 -- Rejected --> C4
    C2 -- Rejected --> C4
    C3 -- Rejected --> C4
    C1 -- Approved --> FormEngine
    C2 -- Approved --> FormEngine
    C3 -- Approved --> FormEngine
    C4 --> B3
    D1 --> D2 --> D3 --> D4 --> D5 --> D6 --> D7
    D7 --> FinalizeLayer
    E1 --> E2
    E1 --> B3

---

## Key Features

* **In-Search Stream Processing:** Applies directly across active LinkedIn search streams without repetitive page refreshes or context resets.
* **Deterministic Rule Engine + LLM Fallback:** Resolves common recruiter prompts (notice periods, compensation, years of experience, US work authorization) instantaneously with zero latency, utilizing Gemini Flash for complex essay questions.
* **Dynamic Form Traversal:** Autonomously handles multi-step modals, typeaheads (locations), radio groups, and custom dropdowns with substring matching.
* **EEO & Compliance Handling:** Gracefully navigates voluntary demographic, disability, and veteran surveys (auto-selecting neutral/decline options).
* **Resume Attachment Pipeline:** Locks directly to your master PDF resume without dynamic alteration or unexpected regeneration.
* **Inspection Mode:** Configurable step pacing and visual Rich CLI logging to inspect every field injection live in real time.

---

## Project Structure

```text
├── config/
│   ├── settings.yaml              # App configuration, search filters, and delays
│   ├── truth_matrix.example.yaml  # Candidate profile, compensation, and work auth template
├── data/
│   └── ResumeSoftwareEngineer.pdf # Master resume attachment (gitignored)
├── src/
│   ├── agents/
│   │   ├── discovery_agent.py     # LinkedIn job search harvester
│   │   ├── form_agent.py          # Playwright form automation engine
│   │   └── match_agent.py         # Job evaluation & scoring engine
│   ├── core/
│   │   ├── database.py            # SQLite application state store
│   │   ├── llm_client.py          # Gemini Flash API client
│   │   └── schemas.py             # Pydantic models & enums
│   └── mcp/
│       └── tools/
│           └── browser.py         # Playwright stealth browser wrapper
├── daemon.py                      # Main stream application runner
├── requirements.txt               # Project dependencies
└── README.md
