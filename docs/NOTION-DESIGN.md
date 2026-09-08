# Notion Workspace Design — Mohammad J. Bakr

Real structured content for each page. Copy into Notion blocks exactly as shown.

---

## 1. Home / Dashboard

**Page name:** `Personal OS · Home`

```
┌─────────────────────────────────────────────────────────┐
│  HEADER                                                 │
│  👤 Mohammad J. Bakr   |   CE Student · 2026           │
│  Taif University  ·  GPA 3.22/4  ·  Saudi Arabia      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────┬───────────────────────────────────┐
│  QUICK STATS        │  ACTIVE GOALS                    │
│  ─────────────────  │  ─────────────────────────────── │
│  🎯 Applications: 0 │  □ Secure CE internship / entry  │
│  📄 CVs drafted: 0  │  □ Build Personal OS v1         │
│  ✉️ Emails sent: 0   │  □ Learn AI/ML tooling          │
│  🌐 Job sources: 3   │  □ Arabic + English fluency     │
└─────────────────────┴───────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  CURRENT FOCUS                                         │
│  ────────────────────────────────────────────────────  │
│  🎓 Education: CE, Taif University (2026 grad)         │
│  🏢 Target: Saudi Electricity Co. / Tech firms KSA      │
│  🛠 Skills: C++, React, SQL, AI, Cloud, Networking    │
│  📍 Location: Saudi Arabia (willing to relocate)       │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  AGENT STATUS                                          │
│  ──────────────────────────────────────────────────── │
│  ◉ CEO Agent         online    coordination            │
│  ◉ Job Agent         online    free-model policy        │
│  ◉ Dad's Email       online    correspondence           │
│  ◉ Tech News Agent   online    scripts                  │
└─────────────────────────────────────────────────────────┘
```

**Tags:** `#dashboard` `#home`

---

## 2. Job Tracker Database

**Database name:** `Job Applications`

| Property | Type | Notes |
|---|---|---|
| Company | Title | e.g. "Saudi Electricity Co." |
| Role | Title | e.g. "Junior CE Engineer" |
| Status | Select | `Research` · `Applied` · `Interview` · `Offer` · `Rejected` · `Declined` |
| Applied Date | Date | |
| Source | Select | `LinkedIn` · `Company Website` · `Referral` · `Recruiter` · `Other` |
| Link | URL | Job posting URL |
| Contact | Person | HR contact name |
| Follow-up | Date | Next follow-up date |
| Notes | Text | |
| Salary Range | Text | e.g. "8,000–12,000 SAR" |
| Location | Select | `Riyadh` · `Jeddah` · `Dammam` · `Remote` · `Other` |
| Agent | Select | `Job Agent` · `CEO Agent` · `Manual` |

**Default view:** Table, grouped by Status, sorted by Applied Date desc

---

## 3. CV & Cover Letter Templates

**Page name:** `Applications / CV & Letters`

### CV Template (Notion blocks)

```
EDUCATION
─────────
Taif University                          Expected June 2026
Bachelor of Science, Computer Engineering
GPA: 3.22 / 4.00

SKILLS
──────
Languages:    C++, Python, SQL, JavaScript, HTML/CSS, ARM Assembly
AI/ML:        Prompt engineering, LLM APIs, WebAssembly, AI toolchains
Cloud:        AWS EC2, Cloud networking, security fundamentals
Embedded:     ARM Cortex-M, interrupts, GPIO, real-time systems
Tools:        Git, Linux, React, SQLite, VS Code, Docker basics

EXPERIENCE
──────────
Saudi Electricity Co. — Practical Training          Jun–Aug 2024
• Operated grid monitoring systems and interpreted SCADA displays
• Logged outage events and communicated status to shift engineers
• Shadowed protection engineers on 110kV substation rounds

Tech Support & Sales — Retail                      2022–2023
• Diagnosed and resolved 30+ daily customer technical issues
• Translated complex product specs into clear Arabic/English explanations
• Maintained 95% customer satisfaction across 3-month peak season

PROJECTS
────────
Personal OS Agent (Python, SQLite, HTML/CSS/JS)    2026
• Built a local-first personal agent operating system with 4 specialist
  agents, approval-gated actions, and n8n automation hooks
• Designed warm editorial UI with per-agent browser isolation
• GitHub: github.com/mohammadjbakr/personal-os

AWARDS & ACTIVITIES
──────────────────
• Dean's List, Fall 2023
• IEEE Student Member
• Arabic: Native   English: Fluent (TOEFL-equivalent preparation)
```

**Tags:** `#cv` `#template` `#computer-engineering`

### Cover Letter Structure

```
[Your Name]
[Address]
[Phone] · [Email]
[Date]

[Hiring Manager Name]
[Company Name]
[Address]

Dear [Name / Hiring Manager],

I am writing to express my strong interest in the [Role Title] position
at [Company Name], as posted on [Source]. As a Computer Engineering
student at Taif University (GPA 3.22/4.00, graduating 2026) with
practical training at Saudi Electricity Co. and hands-on experience in
[relevant skill from job posting], I am confident I can contribute to
your [team/project/goal].

In my practical training, I [specific achievement — e.g. operated grid
monitoring systems, communicated outage status to engineers]. This
experience taught me [skill] which aligns directly with your requirement
for [requirement from posting].

[Paragraph 2: Second most relevant experience — tech support/customer
service if applying for anything involving communication, or project
work if technical role. Be specific: what did you do, what was the
result?]

I am particularly drawn to [Company Name] because [specific reason from
company website/LinkedIn/posting — not generic flattery].

I would welcome the opportunity to discuss how my background in
[skills] matches your needs. Thank you for your time and consideration.

Sincerely,
[Your Name]
```

---

## 4. Skills Inventory

**Database name:** `Skills`

| Property | Type | Values |
|---|---|---|
| Skill | Title | e.g. "C++" |
| Category | Select | `Languages` · `AI/ML` · `Cloud` · `Embedded` · `Tools` · `Soft` |
| Level | Select | `Beginner` · `Intermediate` · `Advanced` · `Expert` |
| Evidence | Text | Where you used/demonstrated this |
| Proof | URL | GitHub link, certificate, project |
| Updated | Date | |

**Knowledge items:**
- **C++** — Intermediate — university courses, personal OS project — [GitHub]
- **Python** — Intermediate — scripting, AI toolchains, data analysis
- **SQL / SQLite** — Intermediate — Personal OS backend, database design
- **React / JS** — Beginner — Personal OS frontend
- **AI / LLM APIs** — Beginner — prompt engineering, API integration
- **AWS / Cloud** — Beginner — networking, EC2 fundamentals
- **ARM Embedded** — Intermediate — Cortex-M, interrupts, GPIO
- **Git** — Intermediate — version control, branching workflows
- **Arabic** — Native — written and spoken
- **English** — Fluent — academic reading, professional writing

---

## 5. Company Research Database

**Database name:** `Target Companies`

| Property | Type | Notes |
|---|---|---|
| Company | Title | |
| Industry | Select | `Energy` · `Tech` · `Telecom` · `Government` · `Finance` · `Other` |
| Status | Select | `Researching` · `Contacted` · `Interviewing` · `Offer` · `Not interested` |
| Website | URL | |
| LinkedIn | URL | |
| Size | Select | `Startup` · `SME` · `Large` · `Enterprise` · `Government` |
| Location | Multi-select | Cities |
| Hiring? | Checkbox | Currently hiring CE grads? |
| Culture Notes | Text | |
| HR Contact | Person | |
| Notes | Text | |

---

## 6. Weekly Review Template

**Page name:** `Weekly Review / [Week of Date]`

```
GOALS REVIEW — Week of [Monday Date]
──────────────────────────────────────
Goal 1: [ ] Completed  /  [ ] Partial  /  [ ] Skipped
Goal 2: [ ] Completed  /  [ ] Partial  /  [ ] Skipped
Goal 3: [ ] Completed  /  [ ] Partial  /  [ ] Skipped

WHAT I ACCOMPLISHED THIS WEEK
─────────────────────────────
• [Achievement 1]
• [Achievement 2]
• [Achievement 3]

WHAT WENT WELL
──────────────
• [ ]

WHAT NEEDS IMPROVEMENT
──────────────────────
• [ ]

BLOCKERS / STUCK POINTS
───────────────────────
• [ ] [Action: ask CEO Agent / research / follow up]

NEXT WEEK'S PRIORITIES
──────────────────────
1. [ ]
2. [ ]
3. [ ]

JOB AGENT CHECK-IN
──────────────────
Applications submitted this week: [N]
Interviews scheduled: [N]
Follow-ups sent: [N]
New sources added: [N]

PERSONAL OS CHECK-IN
───────────────────
Agents behaving: [yes/no]
Pending approvals: [N]
New skills registered: [N]
n8n webhooks firing: [yes/no]
```

---

## 7. Learning Roadmap

**Page name:** `Learning Roadmap`

```
IMMEDIATE (0–3 months)
──────────────────────
□ Complete Personal OS v1 (GitHub, n8n, agents)
□ Build 3 strong job applications (tailored CV + cover)
□ Practice 10 LeetCode Easy/Medium SQL problems
□ AWS Cloud Practitioner certification prep

SHORT TERM (3–6 months)
───────────────────────
□ Secure internship or entry-level CE position
□ Complete 2 more portfolio projects
□ Attend 1 career fair or tech meetup in KSA
□ Build professional LinkedIn with 500+ connections

MEDIUM TERM (6–12 months)
──────────────────────────
□ Land first CE engineering role
□ Contribute to open-source project
□ Expand cloud skills (AWS Solutions Architect path)
□ Arabic technical writing portfolio

ACCELERATORS
────────────
• Use CEO Agent weekly to review progress
• Job Agent tracks every application automatically
• n8n notifies Telegram on every approval decision
• Weekly review every Sunday with this template
```

---

## 8. Reading List / Tech Watch

**Database name:** `Tech Watch`

| Property | Type | Notes |
|---|---|---|
| Title | Title | |
| Source | Select | `RSS` · `LinkedIn` · `Newsletter` · `Friend` · `Manual` |
| URL | URL | |
| Summary | Text | 1–2 sentence summary |
| Status | Select | `To Read` · `In Progress` · `Reviewed` · `Scripted` |
| Script? | Checkbox | Used for TikTok script? |
| Date Added | Date | |
| Notes | Text | |

---

## 9. n8n Automation Log

**Page name:** `n8n / Automation Log`

```
CONFIGURED WEBHOOKS
──────────────────
Name: Telegram Notify on Approval
URL: https://your-n8n-instance/webhook/...
Trigger: Action approved in Personal OS
Last fired: [timestamp]
Status: ● Active

WORKFLOW DESCRIPTION
────────────────────
When Mohammad approves an action in Personal OS:
1. n8n receives POST with agent_slug, action_type, payload, digest
2. Formats a Telegram message: "✅ [CEO] submitted_application — 3M Corp"
3. Sends to Mohammad's Telegram bot
4. Logs to this page (optional)

TEST RESULTS
───────────
Webhook ID | Result        | Timestamp
-----------|---------------|------------------
wh_xxx     | ✅ 200 OK     | 2026-09-06 10:30
wh_xxx     | ✅ 200 OK     | 2026-09-07 14:22
```

---

## 10. Personal OS Documentation

**Page name:** `Personal OS / Documentation`

```
PERSONAL OS — INSTALLATION & RUN
─────────────────────────────────
git clone https://github.com/mohammadjbakr/personal-os.git
cd personal-os
python3 server.py --host 127.0.0.1 --port 8765
→ Open http://127.0.0.1:8765

ENABLE HERMES (optional)
────────────────────────
PERSONAL_OS_ENABLE_HERMES=1 python3 server.py --enable-hermes

CONNECT N8N
───────────
1. Start n8n: n8n start
2. Import samples/n8n-workflow-telegram-notify.json
3. Activate the workflow (copy the webhook URL)
4. Paste URL into Personal OS → n8n page → Add webhook
5. Approve an action → Telegram ping

CONNECT GITHUB
──────────────
GitHub repo: github.com/mohammadjbakr/personal-os
Tokens stored in: Hermes credential store (NOT in .env or DB)
```

---

*Copy each section as a Notion page or database. Adjust to your actual company targets and contact info.*
