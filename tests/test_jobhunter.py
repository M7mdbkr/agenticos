"""Job Hunter tests. No network, no real mailbox: sources and mail are faked."""
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jobhunter import sources
from jobhunter.agent import JobHunter
from jobhunter.commands import command_lines
from jobhunter.config import MailSettings, mail_settings, save_env_values
from jobhunter.mailbox import parse_message
from jobhunter.profile import load_profile, validate
from jobhunter.scoring import required_years, score_job
from jobhunter.sources import Query, Source, parse_feed, parse_linkedin
from jobhunter.store import ID_ALPHABET, JobStore, fingerprint
from jobhunter.writer import Brain

NOW = datetime.now(timezone.utc)
RECENT = (NOW - timedelta(days=1)).isoformat()

PROFILE = {
    "name": "Mohammad Bakr", "headline": "Computer Engineering graduate", "summary": "I built web apps in Python.",
    "roles": ["software engineer", "IT support"], "skills": ["python", "sql", "networking"],
    "locations": ["Saudi Arabia", "Remote"], "level": "entry", "min_score": 50, "daily_summary_hour": -1,
    "notify_desktop": False, "notify_telegram": False, "open_browser_on_apply": True,
}

LINKEDIN_HTML = """
<li>
  <div class="base-card relative w-full base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:4012345678">
    <a class="base-card__full-link absolute top-0" href="https://sa.linkedin.com/jobs/view/junior-software-engineer-at-acme-4012345678?position=1&amp;pageNum=0" data-tracking="x">
      <span class="sr-only">Junior Software Engineer</span></a>
    <div class="base-search-card__info">
      <h3 class="base-search-card__title">
            Junior Software Engineer
      </h3>
      <h4 class="base-search-card__subtitle"><a class="hidden-nested-link" href="https://sa.linkedin.com/company/acme">Acme Tech</a></h4>
      <div class="base-search-card__metadata">
        <span class="job-search-card__location">Riyadh, Riyadh, Saudi Arabia</span>
        <time class="job-search-card__listdate--new" datetime="2026-09-27">1 day ago</time>
      </div>
    </div>
  </div>
</li>
<li>
  <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:4099999999">
    <a class="base-card__full-link" href="https://sa.linkedin.com/jobs/view/senior-staff-engineer-4099999999?trk=1"></a>
    <h3 class="base-search-card__title">Senior Staff Engineer</h3>
    <h4 class="base-search-card__subtitle"><a href="#">BigCo</a></h4>
    <span class="job-search-card__location">Jeddah, Saudi Arabia</span>
  </div>
</li>
"""


def raw_mail(sender, subject, body, message_id, in_reply_to=None, auth=None, html=None, headers=None, to="me@gmail.com"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    if auth:
        msg["Authentication-Results"] = auth
    for key, value in (headers or {}).items():
        msg[key] = value
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    return parse_message(msg.as_bytes(), uid=1)


class FakeMailbox:
    def __init__(self, address="me@gmail.com"):
        self.address = address
        self.configured = True
        self.settings = MailSettings(address=address, password="x", imap_host="imap", smtp_host="smtp")
        self.inbox = []
        self.sent = []

    def test(self):
        return {"imap": True, "smtp": True}

    def fetch_new(self, state=None, first_run_days=2, limit=60):
        messages, self.inbox = self.inbox, []
        return messages, {"uidvalidity": "1", "last_uid": 10}

    def send(self, to, subject, text, html=None, attachments=(), in_reply_to=None, references=None, bcc=(), agent_kind=None):
        message_id = f"<out{len(self.sent)}@test>"
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html, "attachments": list(attachments),
                          "in_reply_to": in_reply_to, "bcc": list(bcc), "kind": agent_kind, "message_id": message_id})
        return message_id


def fake_source(items, mode="once", name="fake"):
    return Source(name, name.title(), lambda query, ctx: [dict(i) for i in items], mode)


JOBS = [
    sources.job("fake", "Junior Software Engineer", "Acme Tech", "Riyadh, Saudi Arabia", "https://acme.example/jobs/1",
                "Python and SQL. Send your CV to careers@acme-tech.com", "1", RECENT),
    sources.job("fake", "IT Support Specialist", "Gulf Net", "Jeddah, Saudi Arabia", "https://gulf.example/jobs/2",
                "Networking, help desk.", "2", RECENT),
    sources.job("fake", "Senior Principal Architect", "BigCo", "Riyadh, Saudi Arabia", "https://bigco.example/3",
                "10+ years of experience", "3", RECENT),
    sources.job("fake", "Pastry Chef", "Bakery", "Paris, France", "https://bakery.example/4", "", "4", RECENT),
]


class AgentCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mailbox = FakeMailbox()
        self.opened = []
        self.hunter = JobHunter(data_dir=self.root / "jh", env={}, mailbox=self.mailbox,
                                sources={"fake": fake_source(JOBS)}, brain=Brain("none"),
                                opener=lambda url, profile_dir=None: self.opened.append(url) or True,
                                desktop=lambda *a: False, telegram=lambda *a: False, request_delay=0)
        cv = self.root / "Mohammad_CV.pdf"
        cv.write_bytes(b"%PDF-1.4 test")
        self.hunter.update_profile({**PROFILE, "cv_path": str(cv)})

    def tearDown(self):
        self.hunter.stop()
        self.hunter.store.close()
        self.tmp.cleanup()

    def deliver(self, *messages):
        self.mailbox.inbox.extend(messages)
        return self.hunter.check_inbox()


class ScoringTests(unittest.TestCase):
    def test_entry_level_match_in_saudi_arabia_scores_high_and_explains_why(self):
        score, reasons, blocked = score_job(JOBS[0], validate(PROFILE))
        self.assertFalse(blocked)
        self.assertGreaterEqual(score, 80)
        self.assertTrue(any("software engineer" in r for r in reasons))
        self.assertTrue(any("apply by email" in r for r in reasons))

    def test_senior_roles_and_other_countries_fall_below_threshold(self):
        profile = validate(PROFILE)
        self.assertLess(score_job(JOBS[2], profile)[0], 50)
        self.assertLess(score_job(JOBS[3], profile)[0], 20)

    def test_excluded_title_is_blocked_and_strict_location_blocks(self):
        profile = validate({**PROFILE, "exclude": ["sales"]})
        self.assertTrue(score_job(sources.job("x", "Sales Engineer", "Co", "Riyadh"), profile)[2])
        strict = validate({**PROFILE, "strict_location": True, "remote_ok": False, "locations": ["Saudi Arabia"]})
        self.assertTrue(score_job(sources.job("x", "Software Engineer", "Co", "Berlin, Germany"), strict)[2])

    def test_remote_restricted_to_another_region_scores_lower_than_worldwide(self):
        profile = validate(PROFILE)
        worldwide = score_job(sources.job("x", "Software Engineer", "Co", "Worldwide", remote=True), profile)[0]
        usa_only = score_job(sources.job("x", "Software Engineer", "Co", "USA only", remote=True), profile)[0]
        self.assertGreater(worldwide, usa_only)

    def test_required_years(self):
        self.assertEqual(5, required_years("we need 5+ years of experience with python"))
        self.assertEqual(3, required_years("3-5 years experience"))
        self.assertEqual(0, required_years("founded 10 years ago"))


class SourceParserTests(unittest.TestCase):
    def test_linkedin_guest_html(self):
        jobs = parse_linkedin(LINKEDIN_HTML)
        self.assertEqual(2, len(jobs))
        first = jobs[0]
        self.assertEqual("Junior Software Engineer", first["title"])
        self.assertEqual("Acme Tech", first["company"])
        self.assertEqual("Riyadh, Riyadh, Saudi Arabia", first["location"])
        self.assertEqual("4012345678", first["external_id"])
        self.assertNotIn("?", first["url"])
        self.assertTrue(first["posted_at"].startswith("2026-09-27"))

    def test_linkedin_enrichment_reads_description_and_apply_email(self):
        page = '<div class="show-more-less-html__markup relative">We use Python.<br>Email hr@acme-tech.com</div>'
        with mock.patch.object(sources, "http_get", return_value=page.encode()):
            item = sources.enrich_linkedin({"external_id": "1", "title": "x", "apply_email": ""})
        self.assertIn("Python", item["description"])
        self.assertEqual("hr@acme-tech.com", item["apply_email"])

    def test_json_boards(self):
        payloads = {
            "remotive": {"jobs": [{"id": 1, "url": "https://r/1", "title": "Python Dev", "company_name": "R",
                                   "candidate_required_location": "Worldwide", "publication_date": "2026-09-20T10:00:00",
                                   "description": "<p>Python</p>"}]},
            "remoteok": [{"legal": "notice"}, {"id": 2, "position": "Backend", "company": "OK", "url": "https://ok/2",
                                               "salary_min": 50000, "salary_max": 70000, "epoch": 1790000000}],
            "jobicy": {"jobs": [{"id": 3, "jobTitle": "SRE", "companyName": "J", "jobGeo": "EMEA", "url": "https://j/3",
                                 "jobDescription": "<b>Linux</b>", "pubDate": "2026-09-20 10:00:00"}]},
            "himalayas": {"jobs": [{"title": "Data", "companyName": "H", "locationRestrictions": ["Saudi Arabia"],
                                    "applicationLink": "https://h/4", "guid": "g4", "pubDate": 1790000000}]},
            "arbeitnow": {"data": [{"slug": "s5", "title": "Dev", "company_name": "A", "location": "Berlin",
                                    "url": "https://a/5", "remote": True, "created_at": 1790000000}]},
            "greenhouse": {"jobs": [{"id": 6, "title": "Engineer", "absolute_url": "https://gh/6",
                                     "location": {"name": "Riyadh"}, "content": "&lt;p&gt;Python&lt;/p&gt;"}]},
            "lever": [{"id": "7", "text": "Analyst", "hostedUrl": "https://lever/7", "categories": {"location": "Dubai"},
                       "descriptionPlain": "SQL", "createdAt": 1790000000000, "workplaceType": "remote"}],
            "jsearch": {"data": [{"job_id": "8", "job_title": "IT Support", "employer_name": "Bayt Co",
                                  "job_publisher": "Bayt.com", "job_city": "Riyadh", "job_country": "SA",
                                  "job_apply_link": "https://bayt/8", "job_description": "Networking"}]},
            "serpapi": {"jobs_results": [{"title": "Network Engineer", "company_name": "G", "location": "Riyadh",
                                          "via": "via LinkedIn", "apply_options": [{"link": "https://g/9"}],
                                          "detected_extensions": {"work_from_home": False}}]},
            "adzuna": {"results": [{"id": 10, "title": "Dev", "company": {"display_name": "Z"},
                                    "location": {"display_name": "London"}, "redirect_url": "https://z/10"}]},
        }
        ctx = {"env": {"RAPIDAPI_KEY": "k", "SERPAPI_KEY": "k", "ADZUNA_APP_ID": "a", "ADZUNA_APP_KEY": "b"},
               "profile": {"greenhouse_boards": ["acme"], "lever_boards": ["acme"]}}
        for name, payload in payloads.items():
            with self.subTest(source=name), mock.patch.object(sources, "get_json", return_value=payload):
                jobs = sources.SOURCES[name].fetch(Query("python", "Riyadh", "entry"), ctx)
                self.assertEqual(1, len(jobs), name)
                self.assertTrue(jobs[0]["title"] and jobs[0]["url"].startswith("https://"), jobs[0])
        with mock.patch.object(sources, "get_json", return_value=payloads["jsearch"]):
            self.assertEqual("jsearch:bayt.com", sources.fetch_jsearch(Query("x"), ctx)[0]["source"])
        with mock.patch.object(sources, "get_json", return_value=payloads["remoteok"]):
            self.assertEqual("USD 50,000–70,000", sources.fetch_remoteok(Query(), ctx)[0]["salary"])

    def test_bayt_search_page(self):
        page = """<ul><li class="has-pointer-d" data-js-job="" data-job-id="5123456">
            <h2 class="jb-title m0 t-large"><a data-js-aid="jobID" href="/en/saudi-arabia/jobs/it-support-engineer-5123456/?utm=1">IT Support Engineer</a></h2>
            <div class="t-nowrap p10l"><span>Riyadh Tech Co.</span></div>
            <div class="t-mute t-small">Riyadh &middot; Saudi Arabia</div></li>
            <li class="other"><a href="/x">not a job</a></li></ul>"""
        with mock.patch.object(sources, "http_get", return_value=page.encode()) as get:
            jobs = sources.fetch_bayt(Query("IT support", "Riyadh"), {})
        self.assertIn("/en/saudi-arabia/jobs/it-support-jobs/", get.call_args[0][0])
        self.assertEqual([("IT Support Engineer", "Riyadh Tech Co.", "https://www.bayt.com/en/saudi-arabia/jobs/it-support-engineer-5123456/")],
                         [(j["title"], j["company"], j["url"]) for j in jobs])
        self.assertIn("Saudi Arabia", jobs[0]["location"])

    def test_rss_feed_and_keyed_sources_need_keys(self):
        rss = b"""<rss><channel><item><title>Acme: Backend Developer</title><link>https://wwr/1</link>
                  <region>Anywhere in the World</region><description>&lt;p&gt;Go&lt;/p&gt;</description>
                  <pubDate>Mon, 21 Sep 2026 10:00:00 +0000</pubDate></item></channel></rss>"""
        job = parse_feed(rss, "weworkremotely")[0]
        self.assertEqual(("Backend Developer", "Acme"), (job["title"], job["company"]))
        self.assertTrue(job["remote"])
        self.assertFalse(sources.SOURCES["jsearch"].configured({}))
        self.assertTrue(sources.SOURCES["linkedin"].configured({}))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / "db.sqlite")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_same_job_on_two_sites_is_stored_once_with_both_sources(self):
        first, created = self.store.upsert_job(JOBS[0], 80, ["a"])
        again, created_again = self.store.upsert_job({**JOBS[0], "source": "linkedin", "company": "Acme Tech LLC"}, 85, ["b"])
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(["fake", "linkedin"], again["sources"])
        self.assertEqual(85, again["score"])
        self.assertEqual(5, len(first["id"]))
        self.assertTrue(all(c in ID_ALPHABET for c in first["id"]))

    def test_invalid_status_is_rejected(self):
        job, _ = self.store.upsert_job(JOBS[0], 80, [])
        with self.assertRaises(ValueError):
            self.store.update_job(job["id"], status="hacked")

    def test_fingerprint_ignores_legal_suffixes(self):
        self.assertEqual(fingerprint("Dev", "Acme Inc."), fingerprint("dev", "ACME"))


class SearchAndCommandTests(AgentCase):
    def test_search_emails_a_digest_once_and_marks_jobs_notified(self):
        report = self.hunter.search()
        self.assertEqual(4, report["fetched"])
        titles = [j["title"] for j in report["matches"]]
        self.assertEqual(["Junior Software Engineer", "IT Support Specialist"], titles)
        self.assertEqual(1, len(self.mailbox.sent))
        digest = self.mailbox.sent[0]
        self.assertEqual("me@gmail.com", digest["to"])
        self.assertEqual("digest", digest["kind"])
        self.assertIn("1. [", digest["text"])
        self.assertIn("apply 1", digest["html"])
        self.assertEqual("notified", self.hunter.store.get_job(report["matches"][0]["id"])["status"])
        self.hunter.search()
        self.assertEqual(1, len(self.mailbox.sent), "no duplicate digest for already-seen jobs")

    def test_apply_by_email_needs_explicit_send_and_attaches_cv(self):
        self.hunter.search()
        answer = self.hunter.handle_text("apply 1")
        job_id = self.hunter.store.get_state("last_list")[0]
        self.assertIn("careers@acme-tech.com", answer)
        self.assertIn(f"send {job_id}", answer)
        self.assertEqual(1, len(self.mailbox.sent), "nothing is sent to an employer before 'send'")
        self.assertEqual("drafted", self.hunter.store.get_job(job_id)["status"])
        answer = self.hunter.handle_text(f"send {job_id}")
        self.assertIn("✅", answer)
        sent = self.mailbox.sent[-1]
        self.assertEqual("careers@acme-tech.com", sent["to"])
        self.assertEqual("Mohammad_CV.pdf", sent["attachments"][0].name)
        self.assertIn("Dear Hiring Team at Acme Tech", sent["text"])
        job = self.hunter.store.get_job(job_id)
        self.assertEqual("applied", job["status"])
        self.assertTrue(job["applied_at"])
        self.assertIn("Nothing is waiting", self.hunter.handle_text(f"send {job_id}"))

    def test_apply_on_website_opens_the_browser_and_gives_a_letter(self):
        self.hunter.search()
        answer = self.hunter.handle_text("apply 2")
        self.assertIn("https://gulf.example/jobs/2", answer)
        self.assertIn("applied", answer)
        self.assertEqual(["https://gulf.example/jobs/2"], self.opened)

    def test_status_skip_profile_edits_and_unknown_questions(self):
        self.hunter.search()
        second = self.hunter.store.get_state("last_list")[1]
        self.assertIn("skipped", self.hunter.handle_text("skip 2"))
        self.assertEqual("skipped", self.hunter.store.get_job(second)["status"])
        self.assertIn("Pipeline", self.hunter.handle_text("status"))
        self.hunter.handle_text("add role data analyst\nremove skill sql")
        profile = self.hunter.profile()
        self.assertIn("data analyst", profile["roles"])
        self.assertNotIn("sql", profile["skills"])
        self.assertIn("didn't recognise", self.hunter.handle_text("what is the meaning of life"))
        self.assertIn("no #9", self.hunter.handle_text("apply 9"))

    def test_brain_answers_free_form_questions(self):
        class StubBrain(Brain):
            def __init__(self):
                super().__init__("ollama")
                self.prompts = []

            def ask(self, prompt):
                self.prompts.append(prompt)
                return "Apply to the Acme role first."
        self.hunter._brain = StubBrain()
        self.hunter.search()
        self.assertEqual("Apply to the Acme role first.", self.hunter.handle_text("which job should I pick?"))
        self.assertIn("Junior Software Engineer", self.hunter._brain.prompts[0])

    def test_explicit_search_scores_against_the_query(self):
        chef = self.hunter.search(query="pastry chef", location="Paris", notify=False)
        self.assertEqual(["Pastry Chef"], [j["title"] for j in chef["results"]])
        self.assertIn("Pastry Chef", self.hunter.handle_text("search pastry chef in Paris"))

    def test_tick_runs_due_work_and_respects_pause(self):
        self.assertEqual(["inbox", "search"], self.hunter.tick())
        self.assertEqual([], self.hunter.tick())
        self.hunter.update_profile({"paused": True})
        later = datetime.now(timezone.utc) + timedelta(days=1)
        self.assertEqual(["inbox"], self.hunter.tick(later))

    def test_daily_summary_is_sent_once_per_day(self):
        self.hunter.update_profile({"daily_summary_hour": 0})
        self.assertIn("summary", self.hunter.tick())
        self.assertNotIn("summary", self.hunter.tick())
        self.assertTrue(any("Daily job report" in m["subject"] for m in self.mailbox.sent))

    def test_follow_up_is_suggested_and_threaded(self):
        self.hunter.search()
        self.hunter.handle_text("apply 1")
        job_id = self.hunter.store.get_state("last_list")[0]
        self.hunter.handle_text(f"send {job_id}")
        application_id = self.mailbox.sent[-1]["message_id"]
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        self.hunter.store.update_job(job_id, applied_at=old)
        self.assertIn(f"followup {job_id}", self.hunter.status_text())
        self.assertIn("Follow-up ready", self.hunter.handle_text(f"followup {job_id}"))
        self.hunter.handle_text(f"send {job_id}")
        self.assertEqual(application_id, self.mailbox.sent[-1]["in_reply_to"])
        self.assertEqual(1, self.hunter.store.get_job(job_id)["followups"])

    def test_cancel_and_track_url(self):
        self.hunter.search()
        self.hunter.handle_text("apply 1")
        job_id = self.hunter.store.get_state("last_list")[0]
        self.assertIn("Cancelled", self.hunter.handle_text(f"cancel {job_id}"))
        with mock.patch("jobhunter.agent.http_get", return_value=b"<title>Cloud Intern | Neom</title>"):
            answer = self.hunter.handle_text("https://careers.neom.example/job/77")
        self.assertIn("Cloud Intern", answer)


class InboxTests(AgentCase):
    def test_emailed_command_gets_a_threaded_answer(self):
        msg = raw_mail("Me <me@gmail.com>", "Jobs", "status\n\nSent from my iPhone", "<cmd1@gmail.com>")
        self.assertEqual({"command": 1}, self.deliver(msg)["kinds"])
        reply = self.mailbox.sent[-1]
        self.assertEqual("me@gmail.com", reply["to"])
        self.assertEqual("<cmd1@gmail.com>", reply["in_reply_to"])
        self.assertEqual("Re: Jobs", reply["subject"])
        self.assertIn("Pipeline", reply["text"])
        self.assertEqual({"duplicate": 1}, self.deliver(msg)["kinds"])

    def test_reply_to_a_digest_uses_that_digests_numbering(self):
        self.hunter.search()
        digest = self.mailbox.sent[0]
        first_id = self.hunter.store.get_state("last_list")[0]
        self.hunter.handle_text("jobs 1")  # a newer list must not change the meaning of the old email
        reply = raw_mail("me@gmail.com", "Re: " + digest["subject"], f"apply 1\n\nOn Mon, Job Hunter wrote:\n> 1. [{first_id}]",
                         "<cmd2@gmail.com>", in_reply_to=digest["message_id"])
        self.deliver(reply)
        self.assertIn(first_id, self.mailbox.sent[-1]["text"])
        self.assertEqual("drafted", self.hunter.store.get_job(first_id)["status"])

    def test_spoofed_owner_address_is_not_obeyed(self):
        spoof = raw_mail("me@gmail.com", "Jobs", "send ABCDE", "<evil@x>",
                         auth="mx.google.com; dkim=fail; spf=fail; dmarc=fail header.from=gmail.com")
        self.assertEqual({"unverified": 1}, self.deliver(spoof)["kinds"])
        self.assertEqual([], self.mailbox.sent)

    def test_agent_ignores_its_own_mail(self):
        own = raw_mail("me@gmail.com", "🔎 3 new job matches", "…", "<own@x>", headers={"X-JobHunter": "digest"})
        self.assertEqual({"own": 1}, self.deliver(own)["kinds"])

    def test_employer_reply_in_thread_updates_status_and_notifies(self):
        self.hunter.search()
        self.hunter.handle_text("apply 1")
        job_id = self.hunter.store.get_state("last_list")[0]
        self.hunter.handle_text(f"send {job_id}")
        application = self.mailbox.sent[-1]["message_id"]
        reply = raw_mail("Sara <sara@acme-tech.com>", "Re: Application", "We would like to invite you to an interview. "
                         "Please share your availability.", "<emp1@acme-tech.com>", in_reply_to=application)
        self.assertEqual({"reply": 1}, self.deliver(reply)["kinds"])
        job = self.hunter.store.get_job(job_id)
        self.assertEqual("interview", job["status"])
        self.assertIn("Interview invitation", self.mailbox.sent[-1]["subject"])
        answer = self.hunter.handle_text(f"reply {job_id} I'm free on Tuesday at 10am.")
        self.assertIn("sara@acme-tech.com", answer)
        self.hunter.handle_text(f"send {job_id}")
        self.assertEqual("<emp1@acme-tech.com>", self.mailbox.sent[-1]["in_reply_to"])
        self.assertEqual("sara@acme-tech.com", self.mailbox.sent[-1]["to"])

    def test_ats_rejection_is_matched_by_company_name(self):
        self.hunter.search()
        job_id = self.hunter.store.get_state("last_list")[1]
        self.hunter.handle_text(f"applied {job_id}")
        rejection = raw_mail("no-reply@greenhouse.io", "Your application to Gulf Net",
                             "Unfortunately we have decided to move forward with other candidates.", "<ats1@gh>")
        self.assertEqual({"reply": 1}, self.deliver(rejection)["kinds"])
        self.assertEqual("rejected", self.hunter.store.get_job(job_id)["status"])

    def test_job_alert_emails_become_leads(self):
        html = ('<a href="https://www.linkedin.com/comm/jobs/view/4055555555/?trk=eml">Graduate Software Engineer</a>'
                '<p>Neom Tech · Riyadh, Saudi Arabia</p>'
                '<a href="https://www.linkedin.com/comm/jobs/search">See all jobs</a>')
        alert = raw_mail("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "Software engineer: new jobs",
                         "Graduate Software Engineer\nNeom Tech · Riyadh, Saudi Arabia", "<alert1@linkedin.com>", html=html)
        self.assertEqual({"alert": 1}, self.deliver(alert)["kinds"])
        jobs = self.hunter.store.list_jobs(query="Graduate Software Engineer")
        self.assertEqual(1, len(jobs))
        self.assertEqual("https://www.linkedin.com/jobs/view/4055555555", jobs[0]["url"])
        self.assertEqual("Neom Tech", jobs[0]["company"])
        self.assertIn("job-alert emails", self.mailbox.sent[-1]["text"])

    def test_recruiter_outreach_is_flagged_and_newsletters_ignored(self):
        recruiter = raw_mail("Ali <ali@talentfirm.sa>", "Job opportunity", "Hi, I'm a recruiter hiring for a position "
                             "that fits your resume.", "<rec1@x>")
        news = raw_mail("news@shop.example", "Big sale", "50% off", "<news1@x>", headers={"List-Unsubscribe": "<mailto:x>"})
        kinds = self.deliver(recruiter, news)["kinds"]
        self.assertEqual({"recruiter": 1, "ignored": 1}, kinds)
        ignored = [m for m in self.hunter.store.mail_log() if m["kind"] == "ignored"][0]
        self.assertEqual("", ignored["subject"], "nothing about unrelated mail is stored")

    def test_dedicated_mailbox_accepts_commands_without_subject_tag(self):
        self.hunter.update_profile({"owner_emails": ["mohammad@icloud.com"]})
        msg = raw_mail("mohammad@icloud.com", "hello", "status", "<d1@icloud.com>",
                       auth="mx.google.com; dkim=pass header.i=@icloud.com; spf=pass; dmarc=pass")
        self.assertEqual({"command": 1}, self.deliver(msg)["kinds"])
        self.assertEqual("mohammad@icloud.com", self.mailbox.sent[-1]["to"])


class DoctorTests(AgentCase):
    def test_offline_report_names_what_to_fix(self):
        from jobhunter.doctor import format_report, run
        checks = {c["name"]: c for c in run(self.hunter, live=False)}
        self.assertEqual("ok", checks["Profile"]["status"])
        self.assertEqual("fail", checks["Always on"]["status"])
        self.assertIn("install-service", checks["Always on"]["fix"])
        self.assertIn("thing(s) to fix", format_report(list(checks.values())))

    def test_live_source_check_reports_errors_without_crashing(self):
        from jobhunter.doctor import run
        broken = Source("broken", "Broken", lambda q, c: (_ for _ in ()).throw(sources.SourceError("HTTP 429")), "query")
        self.hunter.sources = {"fake": fake_source(JOBS), "broken": broken}
        checks = {c["name"]: c for c in run(self.hunter, live=True)}
        self.assertIn("4 postings", checks["Source · Fake"]["detail"])
        self.assertEqual("warn", checks["Source · Broken"]["status"])


class HelperTests(unittest.TestCase):
    def test_command_lines_drop_quotes_and_signatures(self):
        text = "job: apply 1\nskip 2\n\nOn Mon, 28 Sep 2026 Job Hunter wrote:\n> apply 5"
        self.assertEqual(["apply 1", "skip 2"], command_lines(text))

    def test_parse_message_prefers_text_and_keeps_links_and_first_auth_header(self):
        msg = EmailMessage()
        msg["From"] = "A <a@b.com>"
        msg["Subject"] = "Hi"
        msg["Authentication-Results"] = "mx.google.com; dkim=pass"
        msg["Authentication-Results"] = "attacker; dkim=pass"
        msg.set_content("plain body")
        msg.add_alternative('<p>html <a href="https://x.example/job/1">Dev role</a></p>', subtype="html")
        parsed = parse_message(msg.as_bytes())
        self.assertEqual("plain body", parsed.text.strip())
        self.assertEqual([("https://x.example/job/1", "Dev role")], parsed.links)
        self.assertTrue(parsed.auth_results.startswith("mx.google.com"))

    def test_profile_validation(self):
        profile = validate({"roles": "a, b, a", "min_score": 500, "level": "boss", "unknown": 1, "owner_emails": "X@Y.com, bad"})
        self.assertEqual(["a", "b"], profile["roles"])
        self.assertEqual(100, profile["min_score"])
        self.assertEqual("entry", profile["level"])
        self.assertNotIn("unknown", profile)
        self.assertEqual(["x@y.com"], profile["owner_emails"])

    def test_env_file_updates_and_mail_presets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("TELEGRAM_BOT_TOKEN=abc\nJOBHUNTER_EMAIL=old@gmail.com\n")
            with mock.patch.dict("os.environ", {}, clear=False):
                save_env_values({"JOBHUNTER_EMAIL": "new@gmail.com", "JOBHUNTER_EMAIL_PASSWORD": "pw"}, path)
            self.assertEqual("TELEGRAM_BOT_TOKEN=abc\nJOBHUNTER_EMAIL=new@gmail.com\nJOBHUNTER_EMAIL_PASSWORD=pw\n", path.read_text())
            with self.assertRaises(ValueError):
                save_env_values({"X": "a\nB=c"}, path)
        settings = mail_settings({"JOBHUNTER_EMAIL": "me@outlook.com", "JOBHUNTER_EMAIL_PASSWORD": "ab cd"})
        self.assertEqual(("outlook.office365.com", "smtp.office365.com", 587, "abcd"),
                         (settings.imap_host, settings.smtp_host, settings.smtp_port, settings.password))
        self.assertFalse(mail_settings({"JOBHUNTER_EMAIL": "me@custom.org", "JOBHUNTER_EMAIL_PASSWORD": "x"}).configured)


class FakeIMAP:
    def __init__(self, messages, validity=b"7"):
        self.messages, self.validity = messages, validity
        self.readonly = None

    def select(self, box, readonly=False):
        self.readonly = readonly
        return "OK", [b"3"]

    def response(self, code):
        return code, [self.validity]

    def uid(self, command, *args):
        if command == "SEARCH":
            criteria = args[1:]
            if criteria[0].startswith("UID "):
                low = int(criteria[0].split()[1].split(":")[0])
                uids = [u for u in self.messages if u >= low] or [max(self.messages)]  # IMAP returns the last message for n:*
            else:
                uids = list(self.messages)
            return "OK", [" ".join(str(u) for u in uids).encode()]
        if command == "FETCH":
            assert "PEEK" in args[1], "must never mark mail as read"
            return "OK", [(b"1 (UID 1 BODY[] {10}", self.messages[int(args[0])]), b")"]
        raise AssertionError(command)

    def logout(self):
        pass


class MailboxProtocolTests(unittest.TestCase):
    def setUp(self):
        from jobhunter.mailbox import Mailbox
        self.settings = MailSettings(address="me@gmail.com", password="pw", imap_host="imap.gmail.com", smtp_host="smtp.gmail.com")
        self.mailbox = Mailbox(self.settings)

    def _raw(self, n):
        msg = EmailMessage()
        msg["From"], msg["Subject"], msg["Message-ID"] = "a@b.com", f"m{n}", f"<m{n}@b>"
        msg.set_content("hi")
        return msg.as_bytes()

    def test_fetch_new_reads_read_only_and_tracks_uids(self):
        fake = FakeIMAP({5: self._raw(5), 6: self._raw(6)})
        with mock.patch.object(self.mailbox, "_imap", return_value=fake):
            messages, state = self.mailbox.fetch_new({})
            self.assertEqual(["m5", "m6"], [m.subject for m in messages])
            self.assertEqual({"uidvalidity": "7", "last_uid": 6}, state)
            self.assertTrue(fake.readonly)
            again, state2 = self.mailbox.fetch_new(state)
            self.assertEqual([], again, "UID n:* echoing the last message must not re-deliver it")
            self.assertEqual(6, state2["last_uid"])
            fake.validity = b"8"
            reset, state3 = self.mailbox.fetch_new(state2)
            self.assertEqual(2, len(reset), "a new UIDVALIDITY restarts from a date search")

    def test_send_sets_threading_headers_attachment_and_bcc(self):
        sent = {}

        class FakeSMTP:
            def __init__(self, *a, **k):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def login(self, user, password):
                sent["login"] = (user, password)
            def send_message(self, msg, to_addrs=None):
                sent["msg"], sent["to"] = msg, to_addrs

        with tempfile.TemporaryDirectory() as tmp:
            cv = Path(tmp) / "cv.pdf"
            cv.write_bytes(b"%PDF")
            with mock.patch("jobhunter.mailbox.smtplib.SMTP_SSL", FakeSMTP):
                message_id = self.mailbox.send("hr@acme.com", "Re: Interview", "Thanks", attachments=[cv],
                                               in_reply_to="<emp@acme>", references=["<a@acme>"], bcc=["me@icloud.com"],
                                               agent_kind="reply")
        msg = sent["msg"]
        self.assertEqual(("me@gmail.com", "pw"), sent["login"])
        self.assertEqual(["hr@acme.com", "me@icloud.com"], sent["to"])
        self.assertNotIn("Bcc", msg)
        self.assertEqual("<emp@acme>", msg["In-Reply-To"])
        self.assertEqual("<a@acme> <emp@acme>", msg["References"])
        self.assertEqual(message_id, msg["Message-ID"])
        self.assertEqual("reply", msg["X-JobHunter"])
        self.assertEqual(["cv.pdf"], [p.get_filename() for p in msg.iter_attachments()])


class ServerApiTests(unittest.TestCase):
    def setUp(self):
        import server
        from personal_os import OperationsStore
        self.server = server
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = OperationsStore(root / "db.sqlite", root / "uploads", root / "profiles")
        self.mailbox = FakeMailbox()
        self.hunter = JobHunter(data_dir=root / "jh", env={}, mailbox=self.mailbox, sources={"fake": fake_source(JOBS)},
                                brain=Brain("none"), opener=lambda *a: True, desktop=lambda *a: False,
                                telegram=lambda *a: False, request_delay=0)
        self.hunter.update_profile(PROFILE)
        self.patches = [mock.patch.object(server, "STORE", self.store), mock.patch.object(server, "JOBHUNTER", self.hunter)]
        for p in self.patches:
            p.start()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}/api/jobhunter"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        for p in self.patches:
            p.stop()
        self.hunter.store.close()
        self.store.close()
        self.tmp.cleanup()

    def call(self, path, data=None, headers=None, raw=None):
        body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
        req = Request(self.url + path, data=body, headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read() or b"null")

    def test_status_profile_ask_and_job_actions(self):
        code, status = self.call("/status")
        self.assertEqual(200, code)
        self.assertTrue(status["ready"])
        self.assertEqual(["fake"], [s["name"] for s in status["sources"]])
        code, profile = self.call("/profile", {"min_score": 60})
        self.assertEqual((200, 60), (code, profile["min_score"]))
        code, result = self.call("/search", {"query": "software engineer", "location": "Riyadh"})
        self.assertEqual(200, code)
        job_id = result["results"][0]["id"]
        code, jobs = self.call("/jobs")
        self.assertEqual(200, code)
        self.assertTrue(any(j["id"] == job_id for j in jobs))
        code, answer = self.call(f"/jobs/{job_id}/apply", {})
        self.assertEqual(200, code)
        self.assertIn("careers@acme-tech.com", answer["message"])
        draft = self.hunter.store.pending_draft(job_id)
        code, edited = self.call(f"/drafts/{draft['id']}", {"subject": "Edited subject"})
        self.assertEqual((200, "Edited subject"), (code, edited["subject"]))
        code, answer = self.call("/ask", {"text": "status"})
        self.assertIn("Pipeline", answer["reply"])
        code, _ = self.call(f"/jobs/{job_id}/bogus", {})
        self.assertEqual(404, code)
        code, _ = self.call("/jobs/ZZZZZ/skip", {})
        self.assertEqual(404, code)

    def test_telegram_jobs_commands_only_from_the_configured_chat(self):
        replies = []
        done = threading.Event()

        def fake_send(token, chat_id, text):
            replies.append((chat_id, text))
            done.set()
            return True

        self.hunter.update_profile({"telegram_chat_id": "123"})
        with mock.patch("jobhunter.notify.telegram_send", fake_send):
            self.assertFalse(self.server._jobhunter_telegram("999", "/jobs status"))
            self.assertFalse(self.server._jobhunter_telegram("123", "hello there"))
            self.assertTrue(self.server._jobhunter_telegram("123", "/jobs status"))
            self.assertTrue(done.wait(5))
        self.assertEqual("123", replies[0][0])
        self.assertIn("Pipeline", replies[0][1])

    def test_cards_master_cv_and_tailored_download(self):
        with mock.patch("jobhunter.cards.read_card", return_value={"name": "Omar", "title": "", "company": "Tamara",
                                                                   "email": "omar@tamara.example", "phone": "", "website": "",
                                                                   "method": "tesseract"}):
            code, result = self.call("/cards", raw=b"\xff\xd8" + b"0" * 2000, headers={"X-Filename": "card.jpg"})
        self.assertEqual(201, code)
        self.assertIn("Omar", result["message"])
        code, contacts = self.call("/contacts")
        self.assertEqual(["Omar"], [c["name"] for c in contacts])
        code, _ = self.call("/cv/master", {"text": MASTER_CV})
        self.assertEqual(200, code)
        self.assertEqual(MASTER_CV, self.call("/cv/master")[1]["text"])
        job_id = contacts[0]["job_id"]
        with urlopen(self.url + f"/jobs/{job_id}/cv", timeout=10) as response:
            self.assertEqual(200, response.status)
            self.assertTrue(response.read().startswith(b"PK"))

    def test_multipart_upload_without_cgi(self):
        boundary = "XyZ"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"agent_slug\"\r\n\r\njob\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"notes.txt\"\r\n"
                f"Content-Type: text/plain\r\n\r\nhello\r\n--{boundary}--\r\n").encode()
        req = Request(self.url.replace("/api/jobhunter", "/api/upload"), data=body,
                      headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urlopen(req, timeout=10) as response:
            item = json.loads(response.read())
        self.assertEqual(("job", "notes.txt", 5), (item["agent_slug"], item["original_name"], item["size"]))

    def test_cv_upload_and_cross_origin_block(self):
        code, result = self.call("/cv", raw=b"%PDF-1.4", headers={"X-Filename": "../My CV.pdf", "Content-Type": "application/pdf"})
        self.assertEqual((201, "My_CV.pdf"), (code, result["cv"]))
        self.assertTrue(load_profile(self.hunter.profile_path)["cv_path"].endswith("My_CV.pdf"))
        code, _ = self.call("/cv", raw=b"MZ", headers={"X-Filename": "evil.exe"})
        self.assertEqual(400, code)
        code, _ = self.call("/profile", {"paused": True}, headers={"Origin": "https://evil.example"})
        self.assertEqual(403, code)
        self.assertFalse(self.hunter.profile()["paused"])


if __name__ == "__main__":
    unittest.main()


MASTER_CV = """# Mohammed Bakr
Computer Engineer · Riyadh · +966 50 000 0000 · m@example.com

## Summary
Computer Engineering graduate who builds practical systems.

## Projects
### Recipe Blog — Personal
- Wrote articles about cooking
### Smart Black Box — Graduation Project (Team Leader)
- Led a team of four engineers
- Built network telemetry with Python and Linux

## Skills
Technical: Photoshop, Excel, Python, Networking

## Certifications
- Fundamentals of Artificial Intelligence — SDAIA (2025)
"""


class MasterCvTests(AgentCase):
    def test_tailoring_reorders_but_never_invents(self):
        from jobhunter import cv as cvlib
        job = {"title": "Network Engineer", "company": "Gulf Net", "description": "Python, Linux and networking."}
        tailored = cvlib.tailor(cvlib.parse(MASTER_CV), job, validate(PROFILE))
        text = cvlib.to_text(tailored)
        projects = next(s for s in tailored.sections if s.title == "Projects")
        self.assertTrue(projects.entries[0].heading.startswith("Smart Black Box"))
        self.assertEqual("Built network telemetry with Python and Linux", projects.entries[0].bullets[0])
        self.assertIn("Technical: Python, Networking", text)
        self.assertIn("Target role: Network Engineer at Gulf Net", text)
        master_lines = set(MASTER_CV.splitlines())
        for line in text.splitlines():
            if line.strip() and not line.startswith("Target role") and not line.startswith("Technical:") and not line.startswith("## "):
                self.assertIn(line, master_lines | {f"- {l[2:]}" for l in master_lines if l.startswith("- ")}, line)

    def test_docx_is_valid_and_imports_back(self):
        import zipfile
        from jobhunter import cv as cvlib
        path = cvlib.to_docx(cvlib.parse(MASTER_CV), self.root / "out.docx")
        with zipfile.ZipFile(path) as archive:
            self.assertIn("word/document.xml", archive.namelist())
            self.assertIn("Smart Black Box", archive.read("word/document.xml").decode())
        imported = cvlib.docx_to_master(path)
        self.assertTrue(imported.startswith("# Mohammed Bakr"))
        self.assertIn("## Projects", imported)
        self.assertIn("- Led a team of four engineers", imported)

    def test_application_attaches_a_cv_tailored_to_the_job(self):
        self.hunter.save_master_cv(MASTER_CV)
        with self.assertRaises(ValueError):
            self.hunter.save_master_cv("just some words")
        self.hunter.search()
        answer = self.hunter.handle_text("apply 1")
        job_id = self.hunter.store.get_state("last_list")[0]
        self.assertIn("tailored from your master CV", answer)
        self.hunter.handle_text(f"send {job_id}")
        attachment = self.mailbox.sent[-1]["attachments"][0]
        self.assertTrue(attachment.name.endswith(f"{job_id}.docx"))
        self.assertIn("Acme_Tech", attachment.name)
        self.assertIn("Master CV", self.hunter.handle_text("cv"))


class CardAndCompanyTests(AgentCase):
    def test_typed_card_saves_contact_and_prepares_application(self):
        answer = self.hunter.handle_text("card Ahmed Ali, HR Manager, Acme Company, ahmed@acme.sa, +966 55 123 4567, www.acme.sa")
        contact = self.hunter.store.list_contacts()[0]
        self.assertEqual(("Ahmed Ali", "HR Manager", "Acme Company", "ahmed@acme.sa"),
                         (contact["name"], contact["title"], contact["company"], contact["email"]))
        self.assertEqual("+966 55 123 4567", contact["phone"])
        self.assertIn("https://www.acme.sa", self.hunter.profile()["company_sites"])
        self.assertIn("Application ready", answer)
        draft = self.hunter.store.pending_draft(contact["job_id"])
        self.assertEqual("ahmed@acme.sa", draft["to_addr"])
        self.assertIn(contact["id"], self.hunter.handle_text("contacts"))

    def test_card_photo_by_email_is_read_and_answered(self):
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = "me@gmail.com", "me@gmail.com", "", "<card1@gmail.com>"
        msg.set_content("")
        msg.add_attachment(b"\xff\xd8" + b"0" * 5000, maintype="image", subtype="jpeg", filename="IMG_1.jpg")
        fields = {"name": "Sara", "title": "Talent Lead", "company": "Neom", "email": "sara@neom.example",
                  "phone": "", "website": "", "method": "ollama"}
        with mock.patch("jobhunter.cards.read_card", return_value=dict(fields)):
            self.assertEqual({"command": 1}, self.deliver(parse_message(msg.as_bytes()))["kinds"])
        reply = self.mailbox.sent[-1]
        self.assertIn("Saved contact", reply["text"])
        self.assertIn("sara@neom.example", reply["text"])
        self.assertEqual(1, len(list((self.hunter.data_dir / "cards").iterdir())))

    def test_unreadable_card_asks_for_details(self):
        with mock.patch("jobhunter.cards.read_card", return_value={"name": "", "title": "", "company": "", "email": "",
                                                                   "phone": "", "website": "", "method": "none"}):
            self.assertIn("couldn't read", self.hunter.add_card_image("x.jpg", b"123"))

    def test_company_sites_detect_ats_and_plain_pages(self):
        from jobhunter import companies
        self.assertEqual(("greenhouse", "careem"), companies.detect_ats("https://boards.greenhouse.io/careem"))
        home = ('<html><title>Acme Tech | Home</title><a href="/about">About</a>'
                '<a href="https://acme.example/careers">Careers</a></html>')
        careers = ('<a href="/careers/jobs/123-junior-software-engineer">Junior Software Engineer</a>'
                   '<a href="/careers/jobs/124">Apply now</a><a href="https://other.example/jobs/1">Elsewhere</a>')
        pages = {"https://acme.example": home.encode(), "https://acme.example/careers": careers.encode()}
        with mock.patch("jobhunter.companies.http_get", side_effect=lambda url, *a, **k: pages[url]):
            jobs, note = companies.scan_site("https://acme.example")
        self.assertEqual(["Junior Software Engineer"], [j["title"] for j in jobs])
        self.assertEqual("Acme Tech", jobs[0]["company"])
        embed = b'<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'
        with mock.patch("jobhunter.companies.http_get", return_value=b'<iframe src="https://job-boards.greenhouse.io/acme"></iframe>'), \
             mock.patch("jobhunter.companies.get_json", return_value={"jobs": [{"id": 1, "title": "IT Support",
                                                                                "absolute_url": "https://gh/1"}]}):
            jobs, note = companies.scan_site("https://acme.example/join")
        self.assertIn("Greenhouse", note)
        self.assertEqual("IT Support", jobs[0]["title"])
        self.assertTrue(embed)

    def test_remote_off_and_eastern_province(self):
        self.assertIn("off", self.hunter.handle_text("set remote off"))
        self.hunter.handle_text("set strict on")
        profile = self.hunter.profile()
        self.assertEqual((False, True), (profile["remote_ok"], profile["strict_location"]))
        profile = validate({**PROFILE, "locations": ["Riyadh", "Jeddah", "Eastern Province"], "remote_ok": False,
                            "strict_location": True})
        self.assertFalse(score_job(sources.job("x", "IT Support", "Co", "Al Khobar, Saudi Arabia"), profile)[2])
        self.assertTrue(score_job(sources.job("x", "IT Support", "Co", "Remote", remote=True), profile)[2])

    def test_add_company_command_and_arabic_commands(self):
        self.assertIn("company", self.hunter.handle_text("add company https://careers.stc.com.sa").lower())
        self.assertIn("https://careers.stc.com.sa", self.hunter.profile()["company_sites"])
        self.assertIn("Pipeline", self.hunter.handle_text("الحالة"))
        self.hunter.search()
        self.assertIn("careers@acme-tech.com", self.hunter.handle_text("قدم 1"))
