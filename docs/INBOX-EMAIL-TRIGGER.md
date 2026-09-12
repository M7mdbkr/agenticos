# Inbox — the company-reply trigger

When a company answers one of your applications, n8n catches the mail and posts it
into AgenticOS. AgenticOS classifies it locally, drafts a reply, and holds that
draft until you approve it. The send itself happens back in n8n, and the reply is
only marked **sent** once n8n reports the provider's own message id.

```
Gmail ──▶ n8n (watch + filter) ──▶ POST /api/inbox/ingest
                                        │
                                        ▼
                             classify locally (regex, no model)
                             draft a reply from a template
                                        │
                                        ▼
                        Inbox page  ──▶ you edit and approve
                                        │
                                        ▼
              approval webhook ──▶ n8n sends via Gmail ──▶ POST /api/inbox/<id>/sent
                                                              (provider message id)
```

**AgenticOS never sends mail itself.** It has no SMTP client and no mail credentials.
The only thing it can do is show you a draft.

---

## 1. Arm the trigger (once)

The ingest endpoint is closed until you give it a shared secret. Generate one and
put it in your environment — never in a file that gets committed:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

```bash
# ~/.zshrc or the local .env (which is git-ignored)
export AGENTICOS_INGEST_TOKEN="the-value-you-just-generated"
export AGENTICOS_OWNER_NAME="Mohammad J. Bakr"   # optional, used to sign drafts
```

Restart the server. The Inbox page stops showing the "not armed yet" notice once
the token is set.

Set the same value in n8n's environment as `AGENTICOS_INGEST_TOKEN` (Settings →
Variables, or the `.env` of your n8n install). The sample workflows read it from
there, so the secret never lives inside a workflow file.

---

## 2. Import the two workflows

| File | What it does |
|---|---|
| `samples/n8n-inbox-watch-gmail.json` | Polls Gmail every minute, keeps job-related mail, POSTs it to AgenticOS |
| `samples/n8n-inbox-send-approved-reply.json` | Receives approved replies, sends them, confirms back |

1. n8n → **Import from file** for each.
2. In the watch workflow, connect your Gmail credential on the **Gmail Trigger** node.
3. In the send workflow, connect the same credential on **Gmail — send reply**, then
   copy the webhook URL from **Approval webhook**.
4. AgenticOS → **⇔ n8n automation** → **＋ Add webhook** → paste that URL → Save → **Test**.
5. Activate both workflows.

### If n8n runs in Docker

The container cannot reach `127.0.0.1:8765` — that is the container's own loopback.
Use `http://host.docker.internal:8765` in both HTTP Request nodes, and tell AgenticOS
to accept that name **on the ingest path only**:

```bash
export AGENTICOS_EXTRA_HOSTS="host.docker.internal:8765"
```

The token is still required, so widening the hostname on its own grants nothing.

---

## 3. What the classification actually does

`inbox.py` scores each message against a weighted rule table (English and Arabic)
and returns the winning category plus **the exact phrases that matched**. Those
phrases show on the card, so you can always see why something was filed as it was.

| Category | Reply drafted? |
|---|---|
| Interview invitation | yes |
| Assessment / test | yes |
| Offer | yes |
| Documents requested | yes |
| Recruiter outreach | yes |
| Rejection | yes — a short, gracious thank-you |
| Application acknowledged | no (nothing to answer) |
| Uncategorised | no |

No draft is produced for a `no-reply@` sender either. That keeps the review desk
holding only real work.

This runs on plain regular expressions: **no model, no network, no GPU.** It works
with Ollama switched off, which is the point — the Inbox is useful on a laptop on
a plane.

---

## 4. Drafts never invent facts

Templates leave every unknown fact as a visible placeholder:

> I am available **[add two or three concrete dates and times, with your time zone]**.

Approval is **blocked** while a `[bracketed placeholder]` is still in the body. You
cannot accidentally send a template.

**Improve with local model** is optional. It asks Ollama to rewrite the wording only,
and the rewrite is thrown away if the model dropped the placeholders (which is how a
model invents a meeting time). The deterministic draft is always the fallback.

---

## 5. Status meanings

| Status | Meaning |
|---|---|
| `new` | Arrived, classified, no draft (none was expected) |
| `drafted` | A draft is ready for you to edit |
| `awaiting_approval` | On the review desk; nothing has been sent |
| `approved` | Handed to n8n. **Not sent as far as this OS knows** |
| `sent` | n8n reported the provider's message id — confirmed delivery |
| `denied` | You rejected it; nothing was sent |

The gap between `approved` and `sent` is deliberate. If the Gmail node fails, the
card stays at `approved` rather than lying to you.

---

## 6. API reference

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/inbox/ingest` | `X-AgenticOS-Token` | Deliver one email. Idempotent on `message_id` |
| GET | `/api/inbox?status=` | loopback | List records |
| GET | `/api/inbox/summary` | loopback | Counts + whether the trigger is armed |
| POST | `/api/inbox/<id>/draft` | loopback | Rebuild the draft (`use_model: true` to polish) |
| POST | `/api/inbox/<id>/queue` | loopback | Raise the approval card |
| POST | `/api/inbox/<id>/sent` | `X-AgenticOS-Token` | Confirm delivery with `provider_message_id` |
| POST | `/api/inbox/<id>/archive` | loopback | File it away |
| PATCH | `/api/inbox/<id>` | loopback | Edit a field |
| DELETE | `/api/inbox/<id>` | loopback | Remove the record |

Test the trigger by hand:

```bash
curl -s -X POST http://127.0.0.1:8765/api/inbox/ingest \
  -H "Content-Type: application/json" \
  -H "X-AgenticOS-Token: $AGENTICOS_INGEST_TOKEN" \
  -d '{"message_id":"manual-1","subject":"Interview invitation",
       "from_address":"careers@example.com","from_name":"Sara",
       "body":"We would like to invite you to an interview. Please share your availability."}'
```

Then open the Inbox page — the card is there.

---

## 7. What is stored, and what is not

Stored in SQLite: sender, subject, body text, the classification and its matched
phrases, your draft, and the approval link.

Never stored: OAuth tokens, mail passwords, the ingest token, raw provider headers.
The audit trail records that a message arrived and how it was classified — it does
not copy the body.

---

## 8. Hardware: running the local models

The trigger, classification and templates need no GPU at all. A GPU only speeds up
the optional **Improve with local model** step and normal agent chat.

On an **RTX 4070 Ti Super (16 GB VRAM)**, with Ollama's default Q4 quantisation:

| Model | VRAM | Fits fully on the card? | Use it for |
|---|---|---|---|
| `qwen2.5:7b`, `llama3.1:8b`, `hermes3:8b` | ~5–6 GB | yes, comfortably | Everything in this Inbox. Fast |
| `qwen2.5:14b` | ~9–10 GB | yes | Better wording, still quick |
| `qwen3:30b` (MoE) | ~18–20 GB | no — spills to system RAM | Works, noticeably slower |
| `deepseek-coder:33b` | ~20 GB | no | Not worth it on 16 GB |
| 70B models | ~40 GB+ | no | Do not try |

Practical answer: **yes, your PC runs all of this comfortably** — the whole OS plus
n8n plus a 7B–14B model, with headroom. Stay at 14B and under to keep everything on
the card; the moment a model spills into system RAM, tokens per second collapse.

The rest of the stack barely registers: the Python server is a single stdlib process
(tens of MB), SQLite is a file, and n8n is a Node process (~200–400 MB). The GPU is
the only component under real load, and only while a model is actually generating.

One caveat: `PERSONAL_OS_ENABLE_HERMES` and the subscription CLIs (Claude Code, Codex)
are cloud calls — those depend on your account, not your graphics card.
