# Multi Agentic AI Job ⚡

An autonomous, agentic LinkedIn job application engine designed to stream, evaluate, and submit LinkedIn "Easy Apply" applications end-to-end. Built with Playwright Async API, Google Gemini Flash, and deterministic heuristic fallback pipelines.

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
