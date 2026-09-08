# Engineering Report: Mohammad's Personal OS

## Overview
This document describes the architecture, safety model, data flow, and implementation details of the Personal OS—a local-first, approval-gated operations system for macOS (and Windows/Linux) that provides separate workspaces for a Job Application agent, a Dad's Email agent, a Tech News agent, and a CEO agent that can coordinate them and modify the system's source code.

## Core Principles
- **Local-first**: All operational state lives in SQLite on the machine; no data is sent to external services without explicit, revocable approval.
- **Approval-gated**: Every protected action (sending email, submitting an application, uploading a file, modifying source code, changing account settings) requires an explicit approval of the exact action payload.
- **Agent isolation**: Each agent has its own conversation history, model configuration, allowed tools, skills, and a dedicated persistent Chrome browser profile (so manual sign-ins are retained and never synchronized into notes or SQLite).
- **Transparent evidence**: An append-only, SHA-256 hash-chained audit log records every state-changing event; corrections create new events rather than altering history.
- **Deterministic offline mode**: By default, all agents run with an offline deterministic provider so that no external model call occurs unless the user explicitly configures a subscription or API key.
- **Extensible via skills and tools**: New capabilities are added as reusable skills (policy metadata) or as tools (executable actions) that the admin can enable/disable per agent.

## Architecture Diagram
```mermaid
flowchart TD
    subgraph Browser[Browser (User)]
        UI[HTML/CSS/JS SPA]
        JS[[JavaScript frontend]]
    end
    subgraph Server[Python Backend]
        API[REST/JSON API]
        Store[(SQLite Store)]
        Ops[OperationsStore class]
        Auth[Credential Pools (via Hermes auth)]
    end
    subgraph Hermes[Hermes Agent (optional)]
        Model[[LLM Provider]]
        Tools[[Safe Toolset]]
    end
    Browser -->|REST/JSON| Server
    Server -->|hermes chat -q ... --toolsets safe| Hermes
    Hermes -->|tool results| Server
    Server --> Store
    Store -.->|read/write| API
```

### Components
1. **Frontend**: A single-page application (`index.html`, `static/styles.css`, `static/app.js`) that runs in the browser, providing:
   - A persistent sidebar for navigation between workspaces (Overview, CEO, Job, Dad, Tech News, Approvals, Files, Browsers, Models, Tools, Skills, Email accounts, Connectors, Job sources, Schedules, Projects, Audit log, Engineering report).
   - Agent-specific chat windows with model selectors.
   - Approvals panel showing pending actions with exact payloads and Approve/Deny buttons.
   - File upload dialog (max 25 MB per file) that stores uploads locally under `./uploads`.
   - Tech News page for adding stories and generating TikTok scripts.
   - Agent browser launcher that opens a dedicated Chrome profile per agent.
   - Settings pages for tools, skills, connectors, email accounts, job sources, and schedules (these are policy records only; no credentials are stored here).
   - Command palette (⌘K) for quick navigation.

2. **Backend**: A minimal, dependency-free Python HTTP server (`server.py`) plus the core operations library (`personal_os.py`):
   - Uses only the Python standard library (`http.server`, `sqlite3`, `uuid`, `hashlib`, `json`, `cgi`, `urllib`, `xml.etree`).
   - Implements a REST/JSON API under `/api/` that the frontend consumes.
   - The `OperationsStore` class manages all operational state in a single SQLite file (`data/personal-os.db`).
   - Uploads are saved as files in `./uploads` with SHA-256 verification and safe filenames.
   - The server can be run in two modes:
     - **Offline-safe mode** (default): All agent chats are answered by a local rule‑based responder that records the user's intent but does not perform any external action.
     - **Hermes-enabled mode** (opt‑in via `--enable-hermes` or env var `PERSONAL_OS_ENABLE_HERMES=1`): The backend calls `hermes chat -q ... --toolsets safe --provider <agent.provider> -m <agent.model>` to get a response from a Hermes agent running with a restricted safe toolset (no network, no file writes outside the uploads directory, no shell commands). This provides a real LLM capable of drafting emails, summarizing job descriptions, etc., while still being unable to perform external side‑effects without approval.

3. **Security & Safety Boundaries**
   - **No automatic external actions**: The backend never sends an email, submits a form, or modifies a source file on its own. It only records the user's requested action in the `actions` table with status `pending`.
   - **Approval binding**: When the user presses the Approve button in the Approvals panel, the backend marks the action as `approved` and records the decision in the audit log. The frontend then shows a message that the action was recorded locally (no external side‑effect occurs until the user integrates a real sender—see the "Next steps" section).
   - **Edit invalidates approval**: If the user edits an approved action's payload, its status reverts to `pending` and a new approval is required.
   - **Data minimization**: The SQLite store never contains passwords, API keys, or OAuth tokens. Those are managed exclusively by the Hermes credential store (if Hermes is enabled) or by the user's manual sign‑in in the isolated Chrome profiles.
   - **Browser isolation**: Each agent's "Open browser" button launches Google Chrome with a dedicated `--user-data-dir` pointing to a folder under `./browser-profiles/<agent-slug>`. Cookies, localStorage, and signed‑in sessions are retained in that folder and are never copied into the SQLite store or notes.
   - **Audit log**: Every state change (agent created/updated, message added, action created/decided/edited, resource created/updated/deleted, file uploaded, news item added, script generated) is appended to the `audit` table with a SHA-256 hash that chains to the previous row, forming an append‑only log that cannot be silently rewritten.

4. **Model Routing & Agent Configuration**
   - Each agent record includes:
     - `model_provider` (e.g., `offline`, `ollama`, `openai-codex`, `openrouter`, `anthropic`, `nous`)
     - `model_id` (e.g., `deterministic`, `qwen3:8b`)
     - `free_only` flag (when true, the UI encourages the user to pick a free/local model; the backend does not enforce it—policy is enforced by the user or by Hermes configuration).
   - The CEO can update any agent's model via the Models page or by talking to the CEO agent (`@ceo set Job Agent model to ollama/qwen3:8b`).
   - Tools and skills are stored as JSON arrays in the agents table; they are currently used only for display and future Hermes tool‑set selection.

5. **Workflows (Planned)**
   - **Job Application** (guided by the Job Agent workspace):
     1. User tells the Job Agent: "Find graduate roles at Saudi Electricity Company."
     2. Job Agent records the request. (In Hermes‑enabled mode, it could draft a LinkedIn search query.)
     3. User opens the Job Agent's dedicated Chrome profile, logs into LinkedIn manually, and finds a posting.
     4. User uploads the job description (PDF or text) and their current CV to the Job Agent's file library.
     5. User asks the Job Agent: "Prepare a truthful, tailored CV for this role."
     6. Job Agent records the request; in Hermes‑enabled mode it could call a local skill to rewrite the CV (still requiring approval).
     7. User reviews the drafted CV in the chat, possibly edits it via file upload, then tells the Job Agent: "Show me the exact application before I approve."
     8. Job Agent creates a pending `submit_application` action with the CV, cover letter, and target URL in the payload.
     9. User opens the Approvals panel, sees the exact action, and presses Approve.
     10. The backend marks the action approved; the user then manually submits the application via their browser (or a future integrated sender could be added after approval).
     11. User tells the Job Agent: "Track replies." The agent creates a scheduled task note (or a real cron job when Hermes is enabled) to check for replies.
   - **Dad's Email** (guided by the Dad's Email Agent workspace):
     1. User tells Dad's Agent: "Check the inbox for website‑support messages."
     2. Agent records the request; user opens Dad's Agent's Chrome profile and logs into the email provider manually.
     3. User describes a problem or drafts a reply.
     4. User asks Dad's Agent: "Show me the exact email before I send."
     5. Agent creates a pending `send_email` action with recipient, subject, and body.
     6. User approves in the Approvals panel; then sends the email manually (or via a future approved sender).
   - **Tech News & TikTok Script** (guided by the Tech News Agent workspace):
     1. User adds a verified story via the Tech News page (title, summary, source URL).
     2. User presses the Generate TikTok script button.
     3. Backend creates a deterministic script: Hook → Story → Why it matters → Call to action → Source citation.
     4. User edits the script in place, then copies it to record a TikTok video.

## Safety Limitations & Trust Boundaries
- **The offline responder does not perform any external action**; it is purely a conversational placeholder. To get real language‑model assistance, the user must enable Hermes (`--enable-hermes`) and configure at least one model provider (Ollama for free local models, or an API key for a cloud provider).
- **Even with Hermes enabled, the agent is limited to the `safe` toolset**: no network requests, no filesystem writes outside the `./uploads` directory, no shell execution. This guarantees that the LLM cannot, for example, read `~/.ssh/id_rsa` or send a POST to an arbitrary endpoint.
- **All external side‑effects (email, application submission, source‑code deploy, account changes) require an explicit approval of the exact action**. The system does not attempt to perform those side‑effects on its own; it merely records the user's intent.
- **The audit log prevents repudiation**: If an action is later disputed, the hash‑chained log shows whether it was approved and what the exact payload was.
- **Browser profiles are not a hardened sandbox**: They retain manual sign‑ins and cookies, but they do not protect against malicious websites exploiting browser vulnerabilities. The user should still exercise caution when visiting unfamiliar sites.

## Next Steps for Production Use
1. **Enable Hermes** for real language‑model assistance:
   ```bash
   # Install Hermes Agent (see https://hermes-agent.nousresearch.com/docs/)
   pip install hermes-agent
   # Then start the backend with:
   PERSONAL_OS_ENABLE_HERMES=1 python3 server.py --host 127.0.0.1 --port 8765
   ```
   Configure at least one model via `hermes model` or `hermes setup`.

2. **Add approved external senders** (after thorough review):
   - An email‑sending tool that only sends to pre‑approved addresses and only when the corresponding `send_email` action is marked approved.
   - A LinkedIn‑application tool that reads the approved `submit_application` payload and submits via the LinkedIn API (requires OAuth credentials stored in Hermes credential store).
   - A source‑code deployment tool that only applies changes when a `deploy_source_change` action is approved.

3. **Integrate with Hermes skills** for recurring workflows:
   - Create a skill `job-application-workflow` that encapsulates the steps above and can be invoked by the Job Agent.
   - Create a skill `dad-support-workflow` for the Dad's Email agent.

4. **Hardening** (optional, for multi‑user or high‑security settings):
   - Run the backend behind a reverse proxy with authentication.
   - Store the SQLite file on an encrypted volume.
   - Restrict Chrome profiles to a read‑only overlay after sign‑in, using Chrome policies.

## Testing
The repository includes a basic test suite under `tests/test_core.py` that validates:
- Independent model configuration per agent.
- Message routing and CEO addressing.
- Approval binding and edit‑invalidation.
- Persistence of tools, skills, connectors, email accounts, job sources, and schedules.
- Safe file upload sanitization.
- Deterministic TikTok script generation.
- Browser profile isolation.

Run the tests with:
```bash
python3 -m unittest discover -s tests -v
```

## Licensing
The source code of this Personal OS is available under the MIT License. See the LICENSE file in the repository root.

---
*Built with Hermes Agent as a reviewed dependency. The system respects the user's intention to keep agents approval‑gated and model‑configurable, while providing a warm, extensible HTML workspace.*