"""Command line for the job hunter: python3 -m jobhunter <command>."""
from __future__ import annotations

import argparse
import getpass
import os
import platform
import subprocess
import sys
from pathlib import Path

from .config import ENV_FILE, ROOT, load_env_file, mail_settings, save_env_values


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def _hunter():
    load_env_file()
    from .agent import JobHunter
    return JobHunter()


def cmd_setup(args) -> int:
    load_env_file()
    from .agent import JobHunter
    hunter = JobHunter()
    profile = hunter.profile()
    print("Job Hunter setup — press Enter to keep the value in [brackets].\n")
    name = _ask("Your full name", profile["name"])
    phone = _ask("Phone (optional, used in cover letters)", profile["phone"])
    headline = _ask("One-line headline (e.g. 'Computer Engineering graduate, Taif University')", profile["headline"])
    summary = _ask("2–3 sentence truthful summary of your experience", profile["summary"])
    roles = _ask("Job titles to search (comma separated)", ", ".join(profile["roles"]) or "software engineer, IT support")
    skills = _ask("Your skills (comma separated)", ", ".join(profile["skills"]))
    locations = _ask("Locations (comma separated; include 'Remote' if you want remote)",
                     ", ".join(profile["locations"]) or "Saudi Arabia, Remote")
    level = _ask("Level: entry / mid / senior / any", profile["level"])
    cv = _ask("Path to your CV (PDF/DOCX) to attach to email applications", profile["cv_path"])
    hunter.update_profile({"name": name, "phone": phone, "headline": headline, "summary": summary, "roles": roles,
                           "skills": skills, "locations": locations, "level": level, "cv_path": os.path.expanduser(cv)})

    print("\nEmail connection (IMAP/SMTP). For Gmail: turn on 2-Step Verification, then create an App Password at")
    print("https://myaccount.google.com/apppasswords and paste the 16 letters below. Your normal password won't work.\n")
    settings = mail_settings()
    address = _ask("Mailbox the agent reads and sends from", settings.address)
    if address:
        password = getpass.getpass("App password (hidden; Enter to keep current): ").replace(" ", "") or settings.password
        values = {"JOBHUNTER_EMAIL": address, "JOBHUNTER_EMAIL_PASSWORD": password}
        domain = address.rsplit("@", 1)[-1].lower()
        from .config import MAIL_PRESETS
        if domain not in MAIL_PRESETS:
            values["JOBHUNTER_IMAP_HOST"] = _ask("IMAP server", settings.imap_host or f"imap.{domain}")
            values["JOBHUNTER_SMTP_HOST"] = _ask("SMTP server", settings.smtp_host or f"smtp.{domain}")
            values["JOBHUNTER_SMTP_PORT"] = _ask("SMTP port (465 or 587)", str(settings.smtp_port))
        save_env_values(values)
        owner = _ask("Where should I send your updates / accept commands from?", ", ".join(hunter.owner_emails()) or address)
        hunter.update_profile({"owner_emails": owner})
        from .mailbox import Mailbox, MailError
        try:
            Mailbox(mail_settings()).test()
            print("✅ Email connected.")
        except MailError as exc:
            print(f"⚠️  {exc}")
    print(f"\nSaved profile to {hunter.profile_path} and secrets to {ENV_FILE} (git-ignored).")
    print("Next: python3 -m jobhunter once   (try it)   then   python3 -m jobhunter install-service   (keep it running)")
    return 0


def cmd_run(args) -> int:
    hunter = _hunter()
    print("Job Hunter running — Ctrl+C to stop.", flush=True)
    try:
        hunter.run_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_once(args) -> int:
    hunter = _hunter()
    if hunter.mailbox.configured:
        print("Inbox:", hunter.check_inbox())
    report = hunter.search(reason="cli once")
    print(f"Checked {report['fetched']} postings · {report['new']} new · {len(report['matches'])} new matches")
    for name, error in report["errors"].items():
        print(f"  ⚠️ {name}: {error}")
    return 0


def cmd_search(args) -> int:
    hunter = _hunter()
    report = hunter.search(query=args.query, location=args.location, reason="cli search", notify=False)
    from .writer import job_line
    for index, job in enumerate(report["results"][: args.limit], 1):
        print(job_line(job, index), end="\n\n")
    if not report["results"]:
        print("No matches.")
    for name, error in report["errors"].items():
        print(f"⚠️ {name}: {error}")
    return 0


def cmd_inbox(args) -> int:
    print(_hunter().check_inbox())
    return 0


def cmd_status(args) -> int:
    print(_hunter().status_text())
    return 0


def cmd_ask(args) -> int:
    print(_hunter().handle_text(" ".join(args.text), channel="cli"))
    return 0


def cmd_test_email(args) -> int:
    hunter = _hunter()
    used = hunter.notify_owner("✅ Job Hunter is connected",
                               "This is a test from your Job Hunter agent.\n\nReply to this email with \"status\" or \"help\" "
                               "and I'll answer within a few minutes while I'm running.", kind="notice")
    print(used)
    return 0 if used.get("email") else 1


def cmd_install_service(args) -> int:
    python = sys.executable
    log_dir = ROOT / "data" / "jobhunter"
    log_dir.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / "com.agenticos.jobhunter.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.agenticos.jobhunter</string>
  <key>ProgramArguments</key><array><string>{python}</string><string>-m</string><string>jobhunter</string><string>run</string></array>
  <key>WorkingDirectory</key><string>{ROOT}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log_dir / 'service.log'}</string>
  <key>StandardErrorPath</key><string>{log_dir / 'service.log'}</string>
</dict></plist>
""", encoding="utf-8")
        commands = [["launchctl", "unload", str(path)], ["launchctl", "load", "-w", str(path)]]
        stop = f"launchctl unload -w {path}"
    elif system == "Linux":
        path = Path.home() / ".config" / "systemd" / "user" / "jobhunter.service"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"""[Unit]
Description=AgenticOS Job Hunter
After=network-online.target

[Service]
WorkingDirectory={ROOT}
ExecStart={python} -m jobhunter run
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
""", encoding="utf-8")
        commands = [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", "jobhunter.service"]]
        stop = "systemctl --user disable --now jobhunter.service"
    else:
        print("On Windows, create a Task Scheduler task that runs at log-on:")
        print(f'  schtasks /Create /SC ONLOGON /TN JobHunter /TR "\\"{python}\\" -m jobhunter run" /F')
        print(f"  (working directory: {ROOT})")
        return 0
    print(f"Wrote {path}")
    if args.dry_run:
        print("Activate with:", " && ".join(" ".join(c) for c in commands))
        return 0
    for command in commands:
        subprocess.run(command, check=False)
    print(f"Job Hunter now starts with your laptop and keeps running. Stop it with: {stop}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m jobhunter", description="Email-connected job-search agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="interactive profile + email setup").set_defaults(func=cmd_setup)
    sub.add_parser("run", help="run forever: search, read inbox, email you").set_defaults(func=cmd_run)
    sub.add_parser("once", help="one inbox check + one search, then exit (for cron)").set_defaults(func=cmd_once)
    search = sub.add_parser("search", help="search every source now and print results")
    search.add_argument("query")
    search.add_argument("--location", "-l", default=None)
    search.add_argument("--limit", type=int, default=15)
    search.set_defaults(func=cmd_search)
    sub.add_parser("inbox", help="read new email now").set_defaults(func=cmd_inbox)
    sub.add_parser("status", help="pipeline summary").set_defaults(func=cmd_status)
    ask = sub.add_parser("ask", help='run a command or question, e.g. ask "apply 7K2QX"')
    ask.add_argument("text", nargs="+")
    ask.set_defaults(func=cmd_ask)
    sub.add_parser("test-email", help="send yourself a test email").set_defaults(func=cmd_test_email)
    service = sub.add_parser("install-service", help="start automatically with your laptop (macOS/Linux)")
    service.add_argument("--dry-run", action="store_true", help="write the file but don't activate it")
    service.set_defaults(func=cmd_install_service)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
