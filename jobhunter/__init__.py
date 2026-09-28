"""Job Hunter — an email-connected job-search agent for AgenticOS.

    python3 -m jobhunter setup     # one-time: profile + email
    python3 -m jobhunter run       # keep running (search, read inbox, email you)

See docs/JOB-HUNTER.md.
"""
from .agent import JobHunter

__all__ = ["JobHunter"]
