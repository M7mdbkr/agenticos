"""Company-reply triage: deterministic classification and reply drafting.

Everything here runs offline with the standard library. A local model is only
ever used to *rewrite* a draft that was already produced deterministically, so
the Inbox keeps working when Ollama is not running (core requirement 1).

Nothing in this module sends mail. It produces a draft; delivery happens after
an explicit approval, through the automation configured in the n8n page.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Tuple

OWNER_NAME = os.environ.get("AGENTICOS_OWNER_NAME", "Mohammad J. Bakr")

# Each rule is (category, weight, pattern). Weights let a decisive phrase
# ("we regret to inform") outrank a generic one ("thank you for applying")
# when a single message contains both, which rejection emails usually do.
RULES: List[Tuple[str, int, str]] = [
    # ── Rejection ───────────────────────────────────────────────────────────
    ("rejection", 5, r"regret to inform|we regret|unfortunately[, ]"),
    ("rejection", 5, r"not (been )?(selected|shortlisted|successful)"),
    ("rejection", 4, r"decided to (move forward|proceed) with (other|another)"),
    ("rejection", 4, r"other candidates?|more closely (match|aligned)"),
    ("rejection", 3, r"keep your (cv|resume|profile) on file|future opportunities"),
    ("rejection", 5, r"نعتذر|للأسف|لم يتم اختيار|لم يقع الاختيار|غير مناسب"),
    # ── Interview invitation ────────────────────────────────────────────────
    ("interview_invite", 6, r"\binterview\b|interview invitation"),
    ("interview_invite", 5, r"(schedule|arrange|set up) a (call|meeting|chat|conversation)"),
    ("interview_invite", 4, r"would like to (meet|speak|talk) with you|invite you to"),
    ("interview_invite", 4, r"availability (for|next week)|are you available"),
    ("interview_invite", 3, r"(teams|zoom|google meet) (link|invite|call)"),
    ("interview_invite", 6, r"مقابلة|المقابلة|موعد مقابلة|نود مقابلتك"),
    # ── Assessment / test ───────────────────────────────────────────────────
    ("assessment", 6, r"(online |technical |coding )?assessment\b"),
    ("assessment", 5, r"coding (challenge|test)|technical (test|exercise)|take[- ]home"),
    ("assessment", 4, r"aptitude test|hackerrank|codility|testgorilla"),
    ("assessment", 6, r"اختبار|الاختبار|تقييم فني|امتحان"),
    # ── Offer ───────────────────────────────────────────────────────────────
    ("offer", 7, r"(job |employment )?offer letter|pleased to offer|happy to offer"),
    ("offer", 5, r"offer of employment|extend an offer"),
    ("offer", 4, r"contract (attached|enclosed)|start date"),
    ("offer", 7, r"عرض عمل|خطاب عرض|يسرنا أن نقدم"),
    # ── Documents requested ─────────────────────────────────────────────────
    ("document_request", 5, r"(please )?(send|provide|share|upload) (us )?(your )?(the )?"
                            r"(documents?|transcript|certificate|diploma|passport|id copy)"),
    ("document_request", 4, r"required documents|supporting documents|complete your (profile|file)"),
    ("document_request", 5, r"المستندات|الوثائق|إرفاق|السجل الأكاديمي|كشف الدرجات"),
    # ── Acknowledgement ─────────────────────────────────────────────────────
    ("acknowledgement", 3, r"(we have |we've )?received your (application|cv|resume)"),
    ("acknowledgement", 3, r"thank you for (applying|your (application|interest))"),
    ("acknowledgement", 3, r"under review|being reviewed|reviewing your"),
    ("acknowledgement", 3, r"application (has been )?submitted|do not reply"),
    ("acknowledgement", 3, r"شكرا لتقديمك|تم استلام طلبك|قيد المراجعة|قيد الدراسة"),
    # ── Recruiter outreach ──────────────────────────────────────────────────
    ("recruiter_outreach", 3, r"came across your (profile|cv|resume)|your profile (stood out|caught)"),
    ("recruiter_outreach", 3, r"(exciting |new )?opportunity (at|with|for)"),
    ("recruiter_outreach", 3, r"would you be (open|interested) (to|in)"),
    ("recruiter_outreach", 3, r"فرصة وظيفية|اطلعنا على ملفك|هل أنت مهتم"),
]

CATEGORY_LABELS = {
    "interview_invite": "Interview invitation",
    "assessment": "Assessment / test",
    "offer": "Offer",
    "rejection": "Rejection",
    "document_request": "Documents requested",
    "acknowledgement": "Application acknowledged",
    "recruiter_outreach": "Recruiter outreach",
    "other": "Uncategorised",
}

# Categories where a reply is genuinely expected. Everything else is filed
# without a draft so the review desk is not padded with pointless replies.
REPLY_EXPECTED = {"interview_invite", "assessment", "offer", "document_request", "recruiter_outreach"}

_ARABIC = re.compile(r"[؀-ۿ]")
_NOREPLY = re.compile(r"no[-_.]?reply|donotreply|do[-_.]?not[-_.]?reply", re.I)
_FREE_MAIL = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "live.com"}


def detect_language(text: str) -> str:
    """'ar' when the message is mostly Arabic script, otherwise 'en'."""
    arabic = len(_ARABIC.findall(text))
    letters = len(re.findall(r"[^\W\d_]", text, flags=re.UNICODE))
    return "ar" if letters and arabic / letters > 0.3 else "en"


def company_from_address(from_address: str, from_name: str = "") -> str:
    """Best-effort company label from the sender domain.

    Returns "" rather than a guess for free mail providers — an empty company
    is honest; an invented one is not.
    """
    domain = from_address.split("@")[-1].strip().lower() if "@" in from_address else ""
    if not domain or domain in _FREE_MAIL:
        return from_name.strip()
    base = domain.split(".")[0]
    if base in {"mail", "email", "careers", "jobs", "recruiting", "hr", "notifications"}:
        parts = domain.split(".")
        base = parts[1] if len(parts) > 2 else base
    base = base.replace("-", " ")
    # Short domains are nearly always acronyms (stc, ibm, sap); title case mangles them.
    return base.upper() if len(base) <= 4 else base.title()


def classify(subject: str, body: str) -> Dict[str, Any]:
    """Score an email against the rule table.

    Returns the winning category, a 0–1 confidence, and the exact phrases that
    triggered it so the UI can show *why* — the classification is auditable
    rather than a black box.
    """
    text = f"{subject}\n{body}".lower()
    scores: Dict[str, int] = {}
    signals: Dict[str, List[str]] = {}
    for category, weight, pattern in RULES:
        match = re.search(pattern, text, flags=re.I)
        if match:
            scores[category] = scores.get(category, 0) + weight
            signals.setdefault(category, []).append(match.group(0).strip()[:60])
    if not scores:
        return {"category": "other", "confidence": 0.0, "signals": [],
                "language": detect_language(f"{subject} {body}")}
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    category, top = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    # Confidence rises with the winning score and falls when a second category
    # scored almost as high (a genuinely ambiguous message).
    confidence = min(0.95, top / (top + 4)) * (1 - 0.4 * (runner_up / top if top else 0))
    return {"category": category, "confidence": round(max(confidence, 0.05), 2),
            "signals": signals[category][:6],
            "language": detect_language(f"{subject} {body}")}


def is_automated(from_address: str) -> bool:
    """True for no-reply senders — a draft to those addresses goes nowhere."""
    return bool(_NOREPLY.search(from_address or ""))


def _reply_subject(subject: str) -> str:
    subject = (subject or "").strip() or "Your message"
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def _greeting(from_name: str, language: str) -> str:
    name = (from_name or "").strip()
    if language == "ar":
        return f"مرحباً {name}،" if name else "مرحباً،"
    return f"Dear {name}," if name else "Hello,"


# Bracketed placeholders mark the only facts the template cannot know. They are
# left visible on purpose: the reply is not sendable until a human fills them.
_TEMPLATES = {
    "interview_invite": {
        "en": ("Thank you for the invitation to interview for the {role} position"
               "{company_clause}. I am very interested and glad to move forward.\n\n"
               "I am available [add two or three concrete dates and times, with your time zone]. "
               "If another slot suits your team better, I am happy to accommodate it.\n\n"
               "Please let me know the format and anything you would like me to prepare in advance."),
        "ar": ("شكراً لدعوتكم لإجراء مقابلة لوظيفة {role}{company_clause}. "
               "أنا مهتم بالفرصة ويسعدني المضي قدماً.\n\n"
               "أوقاتي المتاحة: [أضف موعدين أو ثلاثة محددة مع المنطقة الزمنية]. "
               "وإذا كان هناك وقت آخر أنسب لفريقكم فلا مانع لدي.\n\n"
               "أرجو إفادتي بصيغة المقابلة وأي شيء تودون مني تجهيزه مسبقاً."),
    },
    "assessment": {
        "en": ("Thank you for sending the assessment for the {role} position{company_clause}. "
               "I confirm receipt and I will complete it within the stated deadline.\n\n"
               "Could you confirm [the deadline / the expected duration / whether any specific "
               "tools or languages are required]?"),
        "ar": ("شكراً لإرسال الاختبار الخاص بوظيفة {role}{company_clause}. "
               "أؤكد استلامه وسأنجزه ضمن المهلة المحددة.\n\n"
               "أرجو تأكيد [الموعد النهائي / المدة المتوقعة / الأدوات أو اللغات المطلوبة]."),
    },
    "offer": {
        "en": ("Thank you for the offer for the {role} position{company_clause}. "
               "I appreciate the confidence your team has placed in me.\n\n"
               "I would like to review the full terms before confirming. Could you share "
               "[the written offer / start date / and any details still outstanding]? "
               "I will come back to you by [state a date you can genuinely meet]."),
        "ar": ("شكراً لعرضكم الوظيفي لوظيفة {role}{company_clause}، وأقدّر ثقة فريقكم.\n\n"
               "أود مراجعة الشروط كاملة قبل التأكيد. هل يمكنكم مشاركة "
               "[العرض المكتوب / تاريخ المباشرة / وأي تفاصيل متبقية]؟ "
               "وسأوافيكم بالرد بحلول [حدد تاريخاً تستطيع الالتزام به]."),
    },
    "document_request": {
        "en": ("Thank you for your message regarding the {role} position{company_clause}.\n\n"
               "I am preparing the requested documents and will send them by "
               "[state a date you can genuinely meet]. Please confirm "
               "[the exact list and the preferred format] so I send everything correctly the first time."),
        "ar": ("شكراً لرسالتكم بخصوص وظيفة {role}{company_clause}.\n\n"
               "أقوم بتجهيز المستندات المطلوبة وسأرسلها بحلول [حدد تاريخاً تستطيع الالتزام به]. "
               "أرجو تأكيد [القائمة الدقيقة والصيغة المفضلة] لأرسلها بشكل صحيح من المرة الأولى."),
    },
    "recruiter_outreach": {
        "en": ("Thank you for reaching out about the {role} opportunity{company_clause}. "
               "I am interested in learning more.\n\n"
               "Could you share [the job description, location and working model]? "
               "I am a Computer Engineering graduate focused on [name the one or two areas that "
               "actually match this role], and I would like to see how that lines up with what you need."),
        "ar": ("شكراً لتواصلكم بخصوص فرصة {role}{company_clause}، وأنا مهتم بمعرفة المزيد.\n\n"
               "هل يمكنكم مشاركة [الوصف الوظيفي والموقع ونمط العمل]؟ "
               "أنا خريج هندسة حاسب أركّز على [اذكر المجالين الأقرب فعلاً لهذه الوظيفة]، "
               "وأود معرفة مدى توافق ذلك مع متطلباتكم."),
    },
    "rejection": {
        "en": ("Thank you for letting me know, and for the time your team spent reviewing my "
               "application for the {role} position{company_clause}.\n\n"
               "I would be glad to be considered for future openings that match my background. "
               "If you can share any feedback on my application, it would genuinely help me improve."),
        "ar": ("شكراً لإفادتي، وللوقت الذي خصصه فريقكم لمراجعة طلبي لوظيفة {role}{company_clause}.\n\n"
               "يسعدني أن يتم النظر في ملفي لأي فرص مستقبلية تناسب خلفيتي. "
               "وإن أمكن مشاركة أي ملاحظات على طلبي فسأستفيد منها فعلاً."),
    },
}


def draft_reply(email: Dict[str, Any], role: str = "") -> Dict[str, str]:
    """Build a deterministic reply draft. Never invents dates, salaries or facts.

    Returns an empty body for categories where no reply is expected, and for
    no-reply senders, so the approval queue only ever holds real work.
    """
    category = email.get("category", "other")
    language = email.get("language") or detect_language(email.get("body", ""))
    if is_automated(email.get("from_address", "")) or category not in _TEMPLATES:
        return {"subject": "", "body": "", "source": "",
                "note": "No reply drafted: automated sender or no reply expected."}
    if category not in REPLY_EXPECTED and category != "rejection":
        return {"subject": "", "body": "", "source": "", "note": "No reply expected for this category."}

    company = (email.get("company") or "").strip()
    template = _TEMPLATES[category][language if language in ("en", "ar") else "en"]
    if language == "ar":
        company_clause = f" لدى {company}" if company else ""
        role_text = role or "[اسم الوظيفة كما ورد في رسالتهم]"
        closing = f"\n\nمع خالص التقدير،\n{OWNER_NAME}"
    else:
        company_clause = f" at {company}" if company else ""
        role_text = role or "[role named in their email]"
        closing = f"\n\nKind regards,\n{OWNER_NAME}"
    body = template.format(role=role_text, company_clause=company_clause)
    greeting = _greeting(email.get("from_name", ""), language)
    return {"subject": _reply_subject(email.get("subject", "")),
            "body": f"{greeting}\n\n{body}{closing}",
            "source": "offline-template", "note": ""}


_REFINE_PROMPT = """You are editing a reply email that a human will review before it is sent.

Rewrite the draft below so it reads naturally and professionally. Hard rules:
- Keep every [bracketed placeholder] exactly as it is. They mark facts you do not know.
- Do not add any fact that is not already in the draft or the original message:
  no dates, no salary figures, no company names, no qualifications, no promises.
- Keep it under 150 words and keep the same language as the draft.
- Output the email body only. No subject line, no commentary, no markdown.

Original message received:
{original}

Draft to rewrite:
{draft}
"""


def refine_with_model(draft_body: str, original_body: str, model: str) -> Dict[str, str]:
    """Ask a local model to polish an existing draft.

    The deterministic draft is the fallback: any failure, empty reply, or a
    rewrite that dropped the placeholders returns the original untouched.
    """
    from brains import _ollama_reply  # local import: Ollama is optional

    prompt = _REFINE_PROMPT.format(original=original_body[:2000], draft=draft_body[:2000])
    try:
        rewritten = (_ollama_reply(prompt, model=model) or "").strip()
    except Exception as error:  # unreachable server, unknown model, timeout
        return {"body": draft_body, "source": "offline-template",
                "note": f"Local model unavailable, kept the offline draft ({type(error).__name__})."}
    if not rewritten:
        return {"body": draft_body, "source": "offline-template",
                "note": "Local model returned nothing, kept the offline draft."}
    kept = set(re.findall(r"\[[^\]]{3,}\]", draft_body))
    if kept and not any(placeholder in rewritten for placeholder in kept):
        return {"body": draft_body, "source": "offline-template",
                "note": "Model dropped the placeholders, kept the offline draft."}
    return {"body": rewritten, "source": f"ollama:{model}", "note": ""}
