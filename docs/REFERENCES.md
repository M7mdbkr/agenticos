# References

Sourced findings from four user-supplied public repositories, reviewed read-only.
Not installed, not executed, no packages pulled.

---

## 1. bible-strong-avatar-lab · AGPL-3.0 · Procedural Avatar Studio

**Repo:** `smontlouis/bible-strong-avatar-lab` · `main` @ `79fe9ba` [3][4][5]
**License:** GNU Affero General Public License v3.0 — verified from `LICENSE` file and all three sub-packages [5][6][9][10][11][12][13]

### What it is
Browser-based authoring studio for procedural 2D avatars using React 19 + Vite 8. Avatar geometry is 3D-inspired but rendered as SVG. Projects are stored locally in the browser; no backend. Exports portable `.avatar.json` for React (`@bible-strong/avatar-react`) or vanilla JS (`@bible-strong/avatar-web`). Both packages are also AGPL-3.0-only [6][9][10][11][12][13].

### Relevant to Personal-OS
- **Avatar authoring concept:** Avatar Studio as a separate design tool, not embedded UI. Personal-OS uses vanilla HTML/JS; SVG avatar generation would be a separate concern.
- **Storage pattern:** Browser localStorage + JSON export/import mirrors how Personal-OS stores data in git-ignored SQLite/files. The copy-on-write behavior library model (shared defaults → avatar-specific copy on first edit) is an interesting pattern for per-agent config isolation.
- **UI separation:** Avatar rendering is framework-independent; the React layer owns the editor. Personal-OS's stdlib-only constraint means avatar rendering would need a separate output path if adopted.
- **Initials vs. full avatars:** Personal-OS uses initials-style display. Full procedural avatars are a separate feature decision; no avatar code from this repo should be embedded in the current build.

### License boundary
AGPL-3.0 requires that if you distribute this application or a modified version over a network, you must make the corresponding source code available. [5] This applies to *using* the library in a network-hosted product. It does not prohibit referencing the architecture as inspiration or writing original SVG avatar code from scratch. The `@bible-strong/avatar-web` LICENSE file (shorter form, no Section 13 verbatim) is a simplified notice variant but still AGPL — not MIT. [13]

**Safe adoption boundary:** Do not import `@bible-strong/avatar-core`, `@bible-strong/avatar-react`, or `@bible-strong/avatar-web` packages into Personal-OS without relicensing those components under a compatible license, or isolating them behind a network boundary where the AGPL source-distribution obligation does not apply.

---

## 2. mattpocock/skills · MIT · Agent Skills Framework

**Repo:** `mattpocock/skills` · `main` @ `3cca18b` [14][15][16]
**License:** MIT — verified from `LICENSE` file [15]

### What it is
Matt Pocock's skill library for Claude Code and compatible agents. Skills are structured Markdown files (YAML frontmatter + Markdown body) defining repeatable engineering and productivity disciplines. Published as a Claude plugin via `.claude-plugin/plugin.json` and `marketplace.json`. [16][17]

### Skill categories (all MIT)
- **User-invoked:** `/grill-me`, `/grill-with-docs`, `/triage`, `/improve-codebase-architecture`, `/to-spec`, `/to-tickets`, `/implement`, `/wayfinder` [18][19][20]
- **Model-invoked:** `/tdd`, `/diagnosing-bugs`, `/prototype`, `/codebase-design`, `/domain-modeling`, `/code-review`, `/resolving-merge-conflicts`, `/wizard`, `/research` [19][20]

### Relevant to Personal-OS

**Skill frontmatter format** is directly relevant — `mattpocock/skills` SKILL.md files use YAML frontmatter with `name`, `description`, and optionally `disable-model-invocation`. [18] This is the same pattern Hermes uses. A Personal-OS `docs/` directory could follow this format for agent-facing skill documents.

**TDD skill structure** (`/tdd`): Red-green-refactor loop, testing at pre-agreed seams, no implementation coupling, vertical slices not horizontal. Key rule: "Refactoring is not part of the loop." [19] — relevant as a discipline reference.

**`/improve-codebase-architecture`** skill: Scans for "deepening opportunities" — refactors that turn shallow modules into deep ones. Uses domain vocabulary from `CONTEXT.md` and a design vocabulary (module, interface, depth, seam, adapter, leverage, locality). Proposes candidates as a visual HTML report, then grills through the chosen candidate. [20] — the HTML report pattern is useful.

**`/to-spec` skill:** Turns a conversation into a spec published to the issue tracker. Template covers Problem Statement, Solution, User Stories (formatted "As an `<actor>`…"), Implementation Decisions, Testing Decisions, Out of Scope. [18] — directly usable as a spec template.

**`/grill-me` / `/grilling`:** Disciplined interview loop until every branch of the design tree is resolved. Core primitive behind `grill-with-docs`, `triage`, `wayfinder`, and `improve-codebase-architecture`. [18] — reusable conversation primitive.

**Two-axis code review** (`/code-review`): Standards (coding standards + Fowler smell baseline) and Spec (faithful to originating issue) run as parallel sub-agents so neither pollutes the other.

**"Free vs. paid" attribution:** The README explicitly states these are skills for "real engineering" not "vibe coding." The repo is MIT; attribute in any derivative.

### License boundary
MIT allows reuse with attribution. The skill structure, format, and discipline patterns can be used as **inspiration for data** (reading as reference material) without adopting the MIT license for Personal-OS's own skill files. If any text is copied verbatim, retain the MIT license notice from `LICENSE`. [15]

---

## 3. build-ai-agents-free · MIT · Free Agent Tutorial

**Repo:** `Moh4696/build-ai-agents-free` · `master` @ `1a4f300` [21][22]
**License:** MIT — verified from `LICENSE` file [23]

### What it is
Beginner's guide to building a LangChain/LangGraph agent on free provider tiers (Groq + Gemini), with tool use, memory, and provider fallback. Tutorial code in `src/`. [22]

### "Free" claims — what they actually mean

| Claim | Reality | Source |
|---|---|---|
| Groq free tier | ~14,400 requests/day, no card | [22] |
| Gemini free tier | 1,500 requests/day, 1M-token context | [22] |
| No credit card required | Both Groq and Gemini require account signup; Groq provides free key immediately | [22][25] |
| Free duckduckgo-search | Rate-limited; no key needed | [22] |
| "Everything here is free, forever" | Free *tiers change monthly* — the README itself says so | [22] |

**Important:** The README states: *"most [free tiers] train on your prompts."* Keep sensitive data off free providers. The fallback setup (Groq → Gemini → local Ollama) addresses provider instability. [22]

### Relevant to Personal-OS
- **Provider fallback pattern:** `try/except` around model initialization with sequential fallback, not LangChain's `with_fallbacks()` which the author found unreliable with agents. [22][29] — practical pattern for multi-provider resilience.
- **Tool definition via `@tool` decorator:** The docstring becomes the model's tool description. Type hints define I/O. [22] — same pattern Personal-OS skill frontmatter uses.
- **`InMemorySaver` + `thread_id`:** Checkpointer pattern for per-user conversation memory. `InMemorySaver` is RAM-only (loses state on restart). [22] — Personal-OS uses SQLite for durable state, which is a stronger approach.
- **`groq → gemini` fallback** in `src/04_agent_with_fallback.py`: Clean try/except pattern. [29] — directly usable reference for provider resilience.
- **Requirements:** `langchain`, `langchain-groq`, `langchain-google-genai`, `langchain-community`, `duckduckgo-search`, `python-dotenv`. [24] — external dependencies; Personal-OS stdlib-only constraint rules out LangChain directly, but the architecture patterns are reference material.

### License boundary
MIT. [23] The code patterns (fallback initialization, `@tool` usage, checkpointer setup) are techniques, not copyrightable expression. Attribute the repo if copying tutorial text verbatim.

---

## 4. auto-browser · MIT · MCP Browser Control Plane

**Repo:** `LvcidPsyche/auto-browser` · `main` @ `aa99c42` [30][31][32]
**License:** MIT — verified from `LICENSE` file [32]

### What it is
Playwright-backed browser control plane packaged as an MCP server. Gives LLMs a shared browser with screenshot, DOM observation, element interaction, human takeover (noVNC), reusable auth profiles, and approval-gated actions. [31]

### Architecture
Three planes: **visual** (screenshot, accessibility outline, OCR), **control** (Playwright protocol, session management), **action** (human approval, policy rails). [31][35]

Model-agnostic: adapters for OpenAI, Claude, Gemini, OpenRouter, DeepSeek, MiniMax, and any OpenAI-compatible endpoint. [31]

### Relevant to Personal-OS

**Approval gate pattern:** [39]
- `ApprovalStore` holds pending/approved/rejected/executed records
- `require_approved()` blocks the action until approval exists with matching `session_id`, `kind`, and `BrowserActionDecision`
- Actions must match the approved action *exactly* (excluding `reason` and `confidence` fields)
- Approved executions have a TTL (default 15 min); expired approvals throw `PermissionError`
- File uploads and account-change/destructive actions require approval before `require_approved()` returns
- Personal-OS's `create_action()` → `decide_action()` → `_notify_n8n_webhooks()` pattern is conceptually aligned

**Session isolation:** Two modes verified by code audit [37]
- `shared_browser_node` (default): one Chromium, one X display, one noVNC. Browser-level state (cookies, localStorage, IndexedDB) isolated per session via `new_context()`. Shared: DNS cache, process memory, takeover plane.
- `docker_ephemeral`: one container per session with isolated Chromium, X display, noVNC port, and optional reverse-SSH tunnel. Auth state files are *copied* into new contexts, not aliased — source is read-only relative to the session.
- **Relevance:** Personal-OS `personal-agent-os` skill uses per-agent Chrome profiles for session isolation. The `auto-browser` audit confirms `new_context()` is Playwright's correct isolation boundary, and that copy-on-write for auth state prevents cross-session contamination. [37]

**Auth state encryption:** `AUTH_STATE_ENCRYPTION_KEY` (Fernet) + `REQUIRE_AUTH_STATE_ENCRYPTION=true`. Named bearer tokens (`API_BEARER_TOKENS=alice:token-a,bob:token-b`) provide operator identity with audit attribution. [36][40]

**Production hardening requirements:** [36]
- `API_BEARER_TOKEN` ≥ 32 chars when API is reachable off-box
- `REQUIRE_OPERATOR_ID=true`
- `AUTH_STATE_ENCRYPTION_KEY` + `REQUIRE_AUTH_STATE_ENCRYPTION=true`
- `CONTROLLER_ALLOWED_HOSTS` for ingress hostnames
- `REQUEST_RATE_LIMIT_ENABLED=true`
- Compliance presets: `strict` (auth encryption required, operator ID required, PII scrub all layers, docker_ephemeral isolation, 4h max session) vs `balanced` (shared browser, network+text PII scrub, 24h session) [31]

**Security advisories published and fixed:** [38]
- GHSA-xmh3-cw7j-9gp5: `Runtime.evaluate` reached through "safe" CDP allowlist + unauthenticated Codespaces overlay (fixed 1.6.1)
- GHSA-32ph-8hp6-7qgj: Safety controls reporting success while not functioning (fixed 1.5.1/1.5.3) — documented in `docs/audits/2026-08-execution-audit.md`

**Python floor: 3.11** (CI tests 3.11 and 3.14, Dockerfile pins `python:3.11-slim`). [33]

### License boundary
MIT. [32] The approval store pattern, session isolation architecture, compliance preset design, and provider adapter pattern can inform Personal-OS design without license constraint. Browser automation permission concerns (CAPTCHA, auth farming) are explicitly out of scope per the repo's security policy. [31][38]

---

## Consolidated Findings

### Agent UI Patterns
- Skill frontmatter format (`name`, `description`, `disable-model-invocation`) from mattpocock/skills [18] — directly applicable to Personal-OS agent-facing docs
- Tabbed unified agent panel (CEO · Job · Dad · Tech News) from personal-agent-os skill — multi-agent UI pattern
- Avatar display vs. initials: Personal-OS uses initials; full procedural avatars are optional future decision

### Agent Skills Patterns
- Spec template (`/to-spec`): Problem Statement → Solution → User Stories → Implementation Decisions → Testing Decisions → Out of Scope [18]
- TDD loop: red-green-refactor, vertical slices, pre-agreed seams, refactoring excluded from loop [19]
- Architecture review as visual HTML report with before/after diagrams (`/improve-codebase-architecture`) [20]
- Two-axis code review (Standards + Spec) as parallel sub-agents [18]
- Grilling loop as reusable interview primitive [18]
- Provider fallback: try/except sequential, not framework helpers [22][29]

### Licenses
| Repo | License | Copyleft/Network | Compatible with Personal-OS? |
|---|---|---|---|
| bible-strong-avatar-lab | AGPL-3.0 | Yes (network use triggers source obligation) | No — AGPL packages cannot be imported without relicensing or isolation |
| mattpocock/skills | MIT | No | Yes — use as inspiration/data reference; retain MIT notice if text copied |
| build-ai-agents-free | MIT | No | Yes — architecture patterns usable; LangChain deps incompatible with stdlib constraint but patterns are reference material |
| auto-browser | MIT | No | Yes — approval pattern, session isolation architecture, compliance presets all informative |

### Safe Adoption Boundary
- **Do not** import any AGPL-3.0 code from bible-strong-avatar-lab into Personal-OS without isolating it behind a network boundary or relicensing
- **Do** use mattpocock/skills discipline patterns as data/inspiration; MIT requires attribution on verbatim text
- **Do not** promise AGPL source is MIT — confirmed all avatar packages are AGPL-3.0-only [6][9][10][11][12][13]
- **Do** use auto-browser's session isolation audit as evidence that `new_context()` + auth state copy is the correct Playwright boundary [37]
- **Do** use the approval store pattern (`require_approved()` with TTL and action matching) as reference for Personal-OS `decide_action()` gate [39]

---

## Sources

[1] smontlouis/bible-strong-avatar-lab `main` @ `79fe9ba` — GitHub commits API
[2] mattpocock/skills `main` @ `3cca18b` — GitHub commits API
[3] bible-strong-avatar-lab README.md
[4] bible-strong-avatar-lab `package.json`
[5] bible-strong-avatar-lab `LICENSE` (AGPL-3.0 full text)
[6] bible-strong-avatar-lab `packages/avatar-core/package.json`
[7] bible-strong-avatar-lab `packages/avatar-core/LICENSE`
[8] bible-strong-avatar-lab `packages/avatar-web/README.md`
[9] bible-strong-avatar-lab `packages/avatar-web/package.json`
[10] bible-strong-avatar-lab `packages/avatar-web/LICENSE`
[11] bible-strong-avatar-lab `packages/avatar-react/package.json`
[12] bible-strong-avatar-lab `packages/avatar-react/LICENSE`
[13] bible-strong-avatar-lab `packages/avatar-web/LICENSE` vs root `LICENSE` diff
[14] mattpocock/skills README.md
[15] mattpocock/skills `LICENSE` (MIT)
[16] mattpocock/skills `.claude-plugin/plugin.json`
[17] mattpocock/skills `.claude-plugin/marketplace.json`
[18] mattpocock/skills `skills/engineering/to-spec/SKILL.md`
[19] mattpocock/skills `skills/engineering/tdd/SKILL.md`
[20] mattpocock/skills `skills/engineering/improve-codebase-architecture/SKILL.md`
[21] Moh4696/build-ai-agents-free `master` @ `1a4f300` — GitHub commits API
[22] build-ai-agents-free README.md
[23] build-ai-agents-free `LICENSE` (MIT)
[24] build-ai-agents-free `requirements.txt`
[25] build-ai-agents-free `.env.example`
[26] build-ai-agents-free `src/agent.py`
[29] build-ai-agents-free `src/04_agent_with_fallback.py`
[30] LvcidPsyche/auto-browser `main` @ `aa99c42` — GitHub commits API
[31] auto-browser README.md
[32] auto-browser `LICENSE` (MIT)
[33] auto-browser `controller/pyproject.toml`
[34] auto-browser `browser-node/package.json`
[35] auto-browser `docs/architecture.md`
[36] auto-browser `docs/production-hardening.md`
[37] auto-browser `docs/session-isolation-audit.md`
[38] auto-browser `SECURITY.md`
[39] auto-browser `controller/app/approvals.py`
[40] auto-browser `controller/app/auth_policy.py`
[41] auto-browser `controller/app/session_isolation.py`
