#!/usr/bin/env python3
"""
Job Finder Bot - Damilola Akinbobola
Fetches fresh AI/automation jobs every run, scores with Claude, sends email digest.
Run every 4-6 hours via Windows Task Scheduler.
"""

import os, json, time, hashlib, smtplib, re, feedparser, requests
from bs4 import BeautifulSoup
from anthropic import Anthropic
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from dotenv import load_dotenv
from email.utils import parsedate_to_datetime

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
GMAIL_USER         = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL    = os.getenv("RECIPIENT_EMAIL", "kelvinjr995@gmail.com")

BOT_DIR      = Path(__file__).parent
SEEN_FILE    = BOT_DIR / "seen_jobs.json"
LATEST_FILE  = BOT_DIR / "jobs_latest.json"
SOURCE_HEALTH_FILE = BOT_DIR / "source_health.json"

SEARCH_KEYWORDS = [
    # Core profile titles
    "AI Automation Engineer",
    "LLM Engineer",
    "AI Automation Consultant",
    "Agentic Systems Engineer",
    "Workflow Automation Engineer",
    "AI Automation Specialist",
    "AI Automation Builder",
    "AI Automation Expert",
    "Lead AI Automation & Operations",
    "AI Engineer n8n",
    "LangChain Engineer",
    "AI Agent Developer",
    # AI solutions / implementation angle
    "AI Solutions Engineer",
    "AI Integration Engineer",
    "AI Implementation Specialist",
    "AI Enablement Consultant",
    "AI Tools Specialist",
    "AI Platform Engineer",
    "AI Workflow Specialist",
    "Agentic AI Engineer",
    "AI Product Engineer",
    "Generative AI Engineer",
    "MCP Developer",
    # Business process / operations angle
    "Business Process Automation",
    "Intelligent Process Automation",
    "Intelligent Automation Engineer",
    "Hyperautomation Engineer",
    "Digital Process Automation",
    "Process Automation Consultant",
    "Automation Architect",
    # Low-code / no-code angle
    "Low Code AI Developer",
    "No Code Automation Developer",
    "n8n Developer",
    "GoHighLevel Automation",
    "GoHighLevel Developer",
    # Broader operational AI
    "AI Operations Engineer",
    "Conversational AI Engineer",
    "Prompt Engineer",
    "AI Tooling Engineer",
]

PROFILE_SUMMARY = """
Name: Damilola Akinbobola
Title: AI Automation Builder / Engineer
Experience: Nov 2023 - Present (independent, client work)
Core skills: Multi-agent system design, LLM orchestration, n8n, Claude API, OpenAI GPT-4,
LangChain, RAG pipelines, retrieval-augmented generation, agentic task orchestration,
hallucination detection, human-in-the-loop checkpoints, output validation, model evaluation.
Tools: n8n, Make, Zapier, JavaScript, Node.js, Python, REST APIs, webhooks, JSON transformation,
Airtable, PostgreSQL, Google Sheets, ElevenLabs, Vapi, WhatsApp Business API, HubSpot, GoHighLevel.
Projects shipped:
- Multi-agent sales intelligence system (Claude API, Fathom, Instagram/Facebook/Slack) - lead scoring 1-100 in real time
- 5-agent real estate lead management system - response time hours to seconds, 24/7
- LLM content generation + auto-publishing pipeline - eliminated 8hr/week manual work
- Event-driven payment automation - payment time hours to under 90 seconds
Client coaching: Live walkthroughs, non-technical stakeholder training, documentation.
Education: B.Sc. Mechanical Engineering, FUTO 2021.
Remote, UTC+1, open to full-time and contract.
"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

client = Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Seen Jobs (dedup) ──────────────────────────────────────────────────────────

def load_seen() -> set:
    if not SEEN_FILE.exists():
        return set()
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        # Support both old format (list) and new format (dict with timestamps)
        if isinstance(data, list):
            return set(data)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return set(k for k, v in data.items() if v > cutoff)
    except Exception:
        return set()

def save_seen(seen: set, seen_ts: dict):
    now = datetime.now(timezone.utc).isoformat()
    # Keep only entries still within 7 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    merged = {k: v for k, v in seen_ts.items() if v > cutoff}
    for jid in seen:
        if jid not in merged:
            merged[jid] = now
    SEEN_FILE.write_text(json.dumps(merged, indent=2))

def job_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


# ── Source: Remotive ──────────────────────────────────────────────────────────

def fetch_remotive() -> list[dict]:
    jobs = []
    try:
        r = requests.get("https://remotive.com/api/remote-jobs", timeout=15)
        data = r.json()
        for j in data.get("jobs", []):
            title = j.get("title", "")
            if not is_relevant(title):
                continue
            jobs.append({
                "title": title,
                "company": j.get("company_name", ""),
                "url": j.get("url", ""),
                "description": clean_html(j.get("description", "")),
                "location": j.get("candidate_required_location", "Remote"),
                "posted": j.get("publication_date", ""),
                "source": "Remotive",
            })
    except Exception as e:
        print(f"[Remotive] Error: {e}")
    print(f"[Remotive] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: We Work Remotely ──────────────────────────────────────────────────

def fetch_wwr() -> list[dict]:
    jobs = []
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "https://weworkremotely.com/remote-jobs.rss",
    ]
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = entry.get("title", "")
                if not is_relevant(title):
                    continue
                jobs.append({
                    "title": title,
                    "company": entry.get("author", ""),
                    "url": entry.get("link", ""),
                    "description": clean_html(entry.get("summary", "")),
                    "location": "Remote",
                    "posted": entry.get("published", ""),
                    "source": "WeWorkRemotely",
                })
        except Exception as e:
            print(f"[WWR] Error on {feed_url}: {e}")
    print(f"[WeWorkRemotely] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: Remote OK ────────────────────────────────────────────────────────

def fetch_remoteok() -> list[dict]:
    jobs = []
    try:
        # A bare "Mozilla/5.0" UA gets the connection reset by RemoteOK. The
        # full browser UA in HEADERS returns 200 with the complete feed.
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=15)
        data = r.json()
        for j in data:
            if not isinstance(j, dict) or "position" not in j:
                continue
            title = j.get("position", "")
            if not is_relevant(title):
                continue
            jobs.append({
                "title": title,
                "company": j.get("company", ""),
                "url": j.get("url", ""),
                "description": clean_html(j.get("description", "")),
                "location": j.get("location", "Remote") or "Remote",
                "posted": j.get("date", ""),
                "source": "RemoteOK",
            })
    except Exception as e:
        print(f"[RemoteOK] Error: {e}")
    print(f"[RemoteOK] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: Arbeitnow ─────────────────────────────────────────────────────────

def fetch_arbeitnow() -> list[dict]:
    jobs = []
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=15)
        data = r.json()
        for j in data.get("data", []):
            title = j.get("title", "")
            if not is_relevant(title):
                continue
            if not j.get("remote", False):
                continue
            desc = clean_html(j.get("description", ""))
            if not is_english(desc):
                continue
            if is_geo_restricted(desc):
                continue
            jobs.append({
                "title": title,
                "company": j.get("company_name", ""),
                "url": j.get("url", ""),
                "description": desc,
                "location": "Remote",
                "posted": j.get("created_at", ""),
                "source": "Arbeitnow",
            })
    except Exception as e:
        print(f"[Arbeitnow] Error: {e}")
    print(f"[Arbeitnow] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: Jobicy ────────────────────────────────────────────────────────────

def fetch_jobicy() -> list[dict]:
    jobs = []
    seen_urls: set = set()
    tags = ["developer", "ai", "machine-learning", "backend"]
    for tag in tags:
        try:
            r = requests.get(f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={tag}", timeout=15)
            data = r.json()
            for j in data.get("jobs", []):
                title = j.get("jobTitle", "")
                url = j.get("url", "")
                if not is_relevant(title) or url in seen_urls:
                    continue
                seen_urls.add(url)
                jobs.append({
                    "title": title,
                    "company": j.get("companyName", ""),
                    "url": url,
                    "description": clean_html(j.get("jobDescription", "")),
                    "location": j.get("jobGeo", "Remote") or "Remote",
                    "posted": j.get("pubDate", ""),
                    "source": "Jobicy",
                })
            time.sleep(1)
        except Exception as e:
            print(f"[Jobicy] Error for tag '{tag}': {e}")
    print(f"[Jobicy] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: Himalayas ─────────────────────────────────────────────────────────

def fetch_himalayas() -> list[dict]:
    """
    Himalayas job pages now return 403 to scrapers, so the previous approach of
    fetching each page for its description dropped every job as "no-description"
    and the source silently went to zero in Aug 2026.

    The RSS feed already carries what we need: the full description in the
    `content` field, plus structured locationRestriction and timezoneRestriction
    fields that are far more reliable than inferring geography from prose.
    """
    jobs = []
    try:
        feed = feedparser.parse("https://himalayas.app/jobs/rss")
        for entry in feed.entries:
            title = entry.get("title", "")
            if not is_relevant(title):
                continue

            # Full HTML description lives in content[0].value; summary is a stub
            body = ""
            content = entry.get("content") or []
            if content:
                body = clean_html(content[0].get("value", ""))
            if not body:
                body = clean_html(entry.get("summary", ""))

            # Structured restriction fields, appended so classify_remote sees them
            loc_r = (entry.get("himalayasjobs_locationrestriction") or "").strip()
            tz_r  = (entry.get("himalayasjobs_timezonerestriction") or "").strip()
            if loc_r:
                body += f"\nLocation restriction: {loc_r}"
            if tz_r:
                body += f"\nTimezone restriction: {tz_r}"

            jobs.append({
                "title": title,
                "company": entry.get("himalayasjobs_companyname", "") or entry.get("author", ""),
                "url": entry.get("link", ""),
                "description": body[:4000],
                "location": loc_r or "Remote",
                "posted": entry.get("published", ""),
                "source": "Himalayas",
            })
    except Exception as e:
        print(f"[Himalayas] RSS error: {e}")

    # Filter: drop if no description, geo-restricted, or hybrid/onsite
    clean = []
    for j in jobs:
        desc = j["description"]
        if not desc:
            print(f"  [DROP no-description] {j['title']}")
            continue
        if is_hybrid_or_onsite(desc):
            print(f"  [DROP hybrid/onsite] {j['title']}")
            continue
        if is_geo_restricted(desc):
            print(f"  [DROP geo-restricted] {j['title']}")
            continue
        clean.append(j)
    print(f"[Himalayas] {len(clean)} jobs after remote/geo filter")
    return clean


# ── Source: Working Nomads ────────────────────────────────────────────────────

def fetch_workingnomads() -> list[dict]:
    """
    The /feed?category=... RSS endpoints started returning 404 (checked Aug 2026).
    The JSON API still serves the full board and carries a real location field,
    which is more useful than the RSS ever was.
    """
    jobs = []
    try:
        r = requests.get("https://www.workingnomads.com/api/exposed_jobs/",
                         headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"[WorkingNomads] HTTP {r.status_code}")
            return jobs
        for j in r.json():
            title = j.get("title", "")
            if not is_relevant(title):
                continue
            jobs.append({
                "title": title,
                "company": j.get("company_name", ""),
                "url": j.get("url", ""),
                "description": clean_html(j.get("description", "")),
                "location": j.get("location", "Remote") or "Remote",
                "posted": j.get("pub_date", ""),
                "source": "WorkingNomads",
            })
    except Exception as e:
        print(f"[WorkingNomads] Error: {e}")
    print(f"[WorkingNomads] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: Remote.co ─────────────────────────────────────────────────────────

def fetch_remoteco() -> list[dict]:
    jobs = []
    feeds = [
        "https://remote.co/remote-jobs/developer/feed/",
        "https://remote.co/remote-jobs/all/feed/",
    ]
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = entry.get("title", "")
                if not is_relevant(title):
                    continue
                jobs.append({
                    "title": title,
                    "company": entry.get("author", ""),
                    "url": entry.get("link", ""),
                    "description": clean_html(entry.get("summary", "")),
                    "location": "Remote",
                    "posted": entry.get("published", ""),
                    "source": "RemoteCo",
                })
        except Exception as e:
            print(f"[RemoteCo] Error on {feed_url}: {e}")
    print(f"[RemoteCo] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: Jobspresso ────────────────────────────────────────────────────────

def fetch_jobspresso() -> list[dict]:
    jobs = []
    try:
        feed = feedparser.parse("https://jobspresso.co/feed/")
        for entry in feed.entries:
            title = entry.get("title", "")
            if not is_relevant(title):
                continue
            jobs.append({
                "title": title,
                "company": entry.get("author", ""),
                "url": entry.get("link", ""),
                "description": clean_html(entry.get("summary", "")),
                "location": "Remote",
                "posted": entry.get("published", ""),
                "source": "Jobspresso",
            })
    except Exception as e:
        print(f"[Jobspresso] Error: {e}")
    print(f"[Jobspresso] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: AIJobs.net ───────────────────────────────────────────────────────

def fetch_aijobs() -> list[dict]:
    jobs = []
    try:
        feed = feedparser.parse("https://aijobs.net/feed/")
        for entry in feed.entries:
            title = entry.get("title", "")
            if not is_relevant(title):
                continue
            jobs.append({
                "title": title,
                "company": entry.get("author", ""),
                "url": entry.get("link", ""),
                "description": clean_html(entry.get("summary", "")),
                "location": "Remote",
                "posted": entry.get("published", ""),
                "source": "AIJobs",
            })
    except Exception as e:
        print(f"[AIJobs] Error: {e}")
    print(f"[AIJobs] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: Wellfound ─────────────────────────────────────────────────────────

def fetch_wellfound() -> list[dict]:
    jobs = []
    try:
        r = requests.get(
            "https://wellfound.com/jobs.json?remote=true&role=engineer",
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            for j in (data if isinstance(data, list) else data.get("jobs", [])):
                title = j.get("title", "") or j.get("role", "")
                if not is_relevant(title):
                    continue
                jobs.append({
                    "title": title,
                    "company": j.get("startup", {}).get("name", "") if isinstance(j.get("startup"), dict) else j.get("company", ""),
                    "url": j.get("url", "") or j.get("job_url", ""),
                    "description": clean_html(j.get("description", "")),
                    "location": "Remote",
                    "posted": j.get("created_at", ""),
                    "source": "Wellfound",
                })
    except Exception as e:
        print(f"[Wellfound] Error: {e}")
    print(f"[Wellfound] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: Indeed RSS ────────────────────────────────────────────────────────

def fetch_indeed() -> list[dict]:
    jobs = []
    queries = [
        "AI+Automation+Engineer",
        "LLM+Engineer",
        "AI+Agent+Developer",
        "Agentic+AI+Engineer",
        "n8n+automation",
        "AI+Workflow+Automation",
        "AI+Solutions+Engineer",
        "Prompt+Engineer+AI",
        "Make+Integromat+automation",
        "AI+Implementation+Specialist",
    ]
    for q in queries:
        try:
            url = f"https://www.indeed.com/rss?q={q}&l=remote&sort=date&fromage=1"
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "")
                jobs.append({
                    "title": title,
                    "company": entry.get("author", ""),
                    "url": entry.get("link", ""),
                    "description": clean_html(entry.get("summary", "")),
                    "location": "Remote",
                    "posted": entry.get("published", ""),
                    "source": "Indeed",
                })
            time.sleep(1)
        except Exception as e:
            print(f"[Indeed] Error for query {q}: {e}")
    print(f"[Indeed] {len(jobs)} jobs found")
    return jobs


# ── Source: LinkedIn (guest search) ──────────────────────────────────────────

def fetch_linkedin() -> list[dict]:
    jobs = []
    keywords_to_try = [
        "AI Automation Engineer",
        "LLM Engineer",
        "AI Agent Developer",
        "Agentic AI Engineer",
        "n8n automation",
        "AI Automation Consultant",
        "AI Solutions Engineer",
        "AI Workflow Automation",
        "Make Zapier automation",
        "Prompt Engineer",
        "AI Implementation Specialist",
        "AI Product Engineer",
        "Generative AI Engineer",
        "GoHighLevel Automation",
        "AI Workflow Engineer",
    ]
    for keyword in keywords_to_try:
        try:
            encoded = keyword.replace(" ", "%20")
            url = (
                f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                f"?keywords={encoded}&location=Worldwide&f_TPR=r86400&f_WT=2&start=0"
            )
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                print(f"[LinkedIn] Status {r.status_code} for '{keyword}'")
                time.sleep(3)
                continue
            soup = BeautifulSoup(r.text, "lxml")
            cards = soup.find_all("li")
            for card in cards:
                title_el = card.find("h3", class_="base-search-card__title")
                company_el = card.find("h4", class_="base-search-card__subtitle")
                link_el = card.find("a", class_="base-card__full-link")
                if not title_el or not link_el:
                    continue
                title = title_el.get_text(strip=True)
                if not is_relevant(title):
                    continue
                company = company_el.get_text(strip=True) if company_el else ""
                link = link_el.get("href", "")
                # Normalize to canonical www.linkedin.com URL using just the numeric job ID
                clean_link = link.split("?")[0]
                id_match = re.search(r"-(\d{10,})$", clean_link)
                canonical = f"https://www.linkedin.com/jobs/view/{id_match.group(1)}" if id_match else clean_link
                jobs.append({
                    "title": title,
                    "company": company,
                    "url": canonical,
                    "description": "",
                    "location": "Remote",
                    "posted": "",
                    "source": "LinkedIn",
                })
            time.sleep(1.5)
        except Exception as e:
            print(f"[LinkedIn] Error for '{keyword}': {e}")
            time.sleep(3)
    # Fetch descriptions and external apply URLs for LinkedIn jobs (cap at 30)
    jobs = jobs[:30]
    print(f"[LinkedIn] Fetching descriptions for {len(jobs)} jobs...")
    for j in jobs:
        try:
            r = requests.get(j["url"], headers=HEADERS, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "lxml")

                # Extract work arrangement from JSON-LD (most reliable signal)
                # jobLocationType: "TELECOMMUTE" = remote, anything else = not remote
                work_type_confirmed = None
                for script in soup.find_all("script", type="application/ld+json"):
                    try:
                        data = json.loads(script.string or "")
                        jlt = data.get("jobLocationType", "")
                        if jlt:
                            work_type_confirmed = jlt.upper()
                            break
                        # Some postings use applicantLocationRequirements instead
                        alr = data.get("applicantLocationRequirements", "")
                        if alr:
                            work_type_confirmed = "TELECOMMUTE" if "remote" in str(alr).lower() else "ONSITE"
                    except Exception:
                        pass

                # Fallback: check LinkedIn's criteria pills ("On-site", "Hybrid", "Remote")
                if work_type_confirmed is None:
                    for el in soup.find_all(class_=lambda c: c and "workplace-type" in c):
                        text = el.get_text(strip=True).lower()
                        if "remote" in text:
                            work_type_confirmed = "TELECOMMUTE"
                        elif "hybrid" in text or "on-site" in text or "onsite" in text:
                            work_type_confirmed = "ONSITE"
                        break
                    # Also check criteria items which sometimes contain the work type
                    if work_type_confirmed is None:
                        for item in soup.find_all("li", class_=lambda c: c and "description__job-criteria-item" in c):
                            header = item.find("h3")
                            value = item.find("span", class_=lambda c: c and "description__job-criteria-text--criteria" in c)
                            if header and value:
                                h = header.get_text(strip=True).lower()
                                v = value.get_text(strip=True).lower()
                                if "workplace" in h or "work type" in h or "work arrangement" in h:
                                    if "remote" in v:
                                        work_type_confirmed = "TELECOMMUTE"
                                    elif "hybrid" in v or "on-site" in v or "onsite" in v:
                                        work_type_confirmed = "ONSITE"

                j["_linkedin_work_type"] = work_type_confirmed or "UNKNOWN"

                desc_el = soup.find("div", class_="description__text") or \
                          soup.find("div", {"class": lambda c: c and "description" in c}) or \
                          soup.find("div", class_="show-more-less-html__markup")
                if desc_el:
                    j["description"] = clean_html(desc_el.get_text())
                # Try to extract the external apply URL (company ATS / careers page)
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if href.startswith("http") and "linkedin.com" not in href:
                        cls = " ".join(a.get("class", []))
                        tracking = a.get("data-tracking-control-name", "")
                        if "apply" in cls.lower() or "apply" in tracking.lower():
                            j["apply_url"] = href
                            break
            time.sleep(1)
        except Exception:
            pass

    # Pre-filter: drop jobs that are not confirmed remote
    confirmed_remote = []
    for j in jobs:
        wt = j.get("_linkedin_work_type", "UNKNOWN")
        desc = j.get("description", "").lower()

        # Drop if LinkedIn's own metadata says on-site or hybrid
        if wt == "ONSITE":
            print(f"  [DROP linkedin=onsite] {j['title']} at {j['company']}")
            continue

        # Drop if no description fetched (can't verify)
        if not desc:
            print(f"  [DROP no-description] {j['title']} at {j['company']}")
            continue

        # Drop if description text reveals hybrid/onsite regardless of metadata
        if is_hybrid_or_onsite(desc):
            print(f"  [DROP hybrid/onsite in desc] {j['title']} at {j['company']}")
            continue

        # Keep if LinkedIn confirmed remote, or if UNKNOWN but description passes
        if wt == "TELECOMMUTE":
            print(f"  [KEEP linkedin=remote] {j['title']} at {j['company']}")
        else:
            print(f"  [KEEP unconfirmed, no disqualifiers] {j['title']} at {j['company']}")

        confirmed_remote.append(j)

    print(f"[LinkedIn] {len(confirmed_remote)} jobs after hybrid/onsite filter")
    return confirmed_remote


# ── Remote / language filters ─────────────────────────────────────────────────

HYBRID_ONSITE_PATTERNS = [
    r"\bhybrid\b", r"\bon[- ]?site\b", r"\bon[- ]?location\b",
    r"\bin[- ]?office\b", r"\boffice days\b", r"\bdays? (per|a|in the) week (in|at) (the )?office\b",
    r"\bwork from (our|the) office\b", r"\breport to (the )?(office|hq|headquarters)\b",
    r"\bcommut", r"\bpresence required\b",
]

# Geo-restriction signals: role is remote but only open to specific countries/regions
GEO_RESTRICTION_PATTERNS = [
    r"\bonly (open|available|accepting).{0,30}(us|uk|eu|canada|australia|india|latam|latin america|europe|asia)\b",
    r"\bmust be (based|located|residing).{0,20}(us|uk|eu|canada|australia|india|latam|europe|asia)\b",
    r"\bauthorized to work in\b",
    r"\bwork authorization.{0,20}(us|uk|canada|australia)\b",
    r"\b(us|uk) (citizens?|residents?|nationals?) only\b",
    r"\beligible to work in the (us|uk|eu|canada|australia)\b",
    r"\bapplicants? (must|should) (be|reside|live).{0,20}(us|uk|eu|canada|spain|uruguay|pakistan|india|latin america|latam)\b",
    r"\bthis role is (open|available) (only |exclusively )?(to|for) (candidates? in|residents? of)\b",
    r"\bno (visa )?sponsor(ship)?\b",
    r"\bcandidates? based in\b",
    r"\blocated in (the )?(us|usa|united states|uk|united kingdom|eu|europe|canada|australia|spain|uruguay|pakistan)\b",
]

def is_geo_restricted(text: str) -> bool:
    t = text.lower()
    for pat in GEO_RESTRICTION_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False

# City-name signals: "Location: [City, Country]" or "📍 City"
CITY_LOCATION_PATTERN = re.compile(
    r"(?:location\s*[:\-–]\s*|📍\s*)([A-Z][a-zA-Z\s]+,\s*[A-Z][a-zA-Z\s]+)"
)

GERMAN_MARKERS = [
    "minijob", "homeoffice", "stunden", "bewerb", "arbeit", "gehalt",
    "wir bieten", "aufgaben", "qualifikation", "umfragen", "telefonist",
]

def is_hybrid_or_onsite(description: str) -> bool:
    desc = description.lower()
    for pat in HYBRID_ONSITE_PATTERNS:
        if re.search(pat, desc, re.IGNORECASE):
            return True
    # City-pattern check: "Location: Bucharest, Romania" → likely not remote
    city_match = CITY_LOCATION_PATTERN.search(description)
    if city_match:
        return True
    return False

def is_english(description: str) -> bool:
    if not description:
        return True
    desc = description.lower()
    german_hits = sum(1 for m in GERMAN_MARKERS if m in desc)
    return german_hits < 3


# ── Relevance filter ──────────────────────────────────────────────────────────

# Terms requiring exact word-boundary match (short/ambiguous substrings that cause false positives)
RELEVANT_TERMS_WORD = [
    "ai", "ml", "nlp", "rag", "llm", "gpt", "rpa",
]
# Terms safe for substring match
RELEVANT_TERMS_SUBSTR = [
    "automation", "agentic", "agent", "n8n", "langchain",
    "openai", "claude", "workflow", "machine learning",
    "artificial intelligence", "chatbot", "retrieval", "generative",
    "prompt engineer", "integration specialist", "zapier", "make.com",
    "intelligent process", "hyperautomation", "digital process",
    "low-code", "no-code", "crewai", "autogen", "vapi",
    "ai solutions", "ai platform", "ai workflow", "ai tool",
    "ai engineer", "ai specialist", "ai consultant", "ai developer",
    "ai trainer", "ai evaluator", "ai implementation",
    "gohighlevel", "ghl", "mcp", "voice ai", "ai product",
]

# Job titles that pass the keyword check but are completely off-profile
EXCLUDE_TITLE_TERMS = [
    # Engineering disciplines unrelated to AI
    "civil engineer", "grid engineer", "mechanical engineer", "electrical engineer",
    "structural engineer", "environmental engineer", "water engineer", "drainage",
    "permit engineer", "work permit",
    # Compliance / legal / finance
    "aml officer", "compliance officer", "chief aml", "patent agent", "patent attorney",
    # Operations / logistics
    "supply chain", "clinical", "logistics", "fundraising", "coordinator",
    # Marketing / media
    "paid media", "paid search", "seo manager", "social media manager",
    "media strategist", "media manager", "media buyer",
    # Medical
    "surgeon", "physician", "nurse", "doctor",
    # German survey / irrelevant roles
    "telefonist", "interviewer", "umfragen", "homeoffice",
    # AI-adjacent but consistently off-profile
    "safety specialist", "adversarial specialist", "privacy compliance",
    "rpa developer",  # often on-prem, mainframe-heavy
]

def is_relevant(title: str) -> bool:
    t = title.lower()
    if any(excl in t for excl in EXCLUDE_TITLE_TERMS):
        return False
    # Word-boundary check for short terms (prevents "ai" matching "paid", "ml" matching "html")
    for term in RELEVANT_TERMS_WORD:
        if re.search(rf"\b{re.escape(term)}\b", t):
            return True
    # Substring check is fine for longer, unambiguous terms
    return any(term in t for term in RELEVANT_TERMS_SUBSTR)


# ── Score with Claude ─────────────────────────────────────────────────────────

def score_job(job: dict) -> dict:
    description = job["description"][:3000] if job["description"] else "No description available."
    prompt = f"""Evaluate this job for Damilola Akinbobola.

CANDIDATE PROFILE:
{PROFILE_SUMMARY}

JOB:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Description: {description}

Score this job 0-100 based on technical skill match, role fit, remote compatibility, seniority match.
Return ONLY a JSON object, no markdown, no explanation outside the JSON:
{{"score": 85, "reason": "Two sentence max."}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "{"},
            ]
        )
        text = "{" + response.content[0].text.strip()
        # Strip markdown code fences if present
        text = re.sub(r"```json|```", "", text).strip()
        # Extract first JSON object
        match = re.search(r'\{.*?\}', text, re.DOTALL)
        if match:
            result = json.loads(match.group())
            job["score"] = int(result.get("score", 0))
            job["reason"] = result.get("reason", "")
        else:
            job["score"] = 0
            job["reason"] = "Could not parse score."
    except Exception as e:
        print(f"[Scorer] Error scoring '{job['title']}': {e}")
        job["score"] = 0
        job["reason"] = "Could not score."
    return job


# ── Email digest ──────────────────────────────────────────────────────────────

def build_health_banner(health: dict) -> str:
    """Red banner in the digest when sources go silent, so decay is visible."""
    if not health:
        return ""
    dead = {s: v for s, v in health.items() if v["status"] != "ok"}
    if not dead:
        return ""

    live = len(health) - len(dead)
    rows = ", ".join(
        f"{s} ({v['status']})" if v["status"].startswith("error") else s
        for s, v in sorted(dead.items())
    )
    severity = "#dc2626" if live <= len(health) / 2 else "#f59e0b"
    return f"""
      <div style="border-left:4px solid {severity};background:#fef2f2;padding:12px 16px;
                  margin:16px 0;border-radius:4px;">
        <div style="font-weight:700;color:{severity};font-size:14px;">
          Source health: {live} of {len(health)} producing
        </div>
        <div style="color:#374151;font-size:13px;margin-top:4px;">
          Silent this run: {rows}
        </div>
        <div style="color:#6b7280;font-size:12px;margin-top:6px;">
          Fewer live sources means the feed leans harder on LinkedIn worldwide,
          which is noisier and surfaces more region-locked roles.
        </div>
      </div>"""


def send_digest(jobs: list[dict], health: dict | None = None):
    if not GMAIL_APP_PASSWORD or GMAIL_APP_PASSWORD == "your_gmail_app_password_here":
        print("[Email] Gmail app password not set. Skipping email. Check .env file.")
        return

    top = jobs[:10]
    now = datetime.now().strftime("%d %b %Y, %I:%M %p")
    health_banner = build_health_banner(health or {})

    rows = ""
    for i, j in enumerate(top, 1):
        score = j.get("score", 0)
        if score >= 80:
            color = "#22c55e"
        elif score >= 60:
            color = "#f59e0b"
        else:
            color = "#ef4444"
        verdict = j.get("remote_verdict", "unverified")
        if verdict == "global":
            badge = ('<span style="background:#dcfce7;color:#166534;padding:2px 8px;'
                     'border-radius:4px;font-size:11px;font-weight:600;">GLOBAL REMOTE</span>')
        else:
            badge = ('<span style="background:#fef3c7;color:#92400e;padding:2px 8px;'
                     'border-radius:4px;font-size:11px;font-weight:600;">GEOGRAPHY UNCONFIRMED</span>')

        rows += f"""
        <tr style="border-bottom:1px solid #e5e7eb;">
          <td style="padding:12px 8px;font-weight:bold;color:#6b7280;">{i}</td>
          <td style="padding:12px 8px;">
            <a href="{j['url']}" style="color:#1d4ed8;font-weight:600;text-decoration:none;">{j['title']}</a><br>
            <span style="color:#6b7280;font-size:13px;">{j['company']} &middot; {j['source']}</span><br>
            {badge}
          </td>
          <td style="padding:12px 8px;text-align:center;">
            <span style="background:{color};color:white;padding:4px 10px;border-radius:20px;font-weight:bold;font-size:14px;">{score}</span>
          </td>
          <td style="padding:12px 8px;color:#374151;font-size:13px;">{j.get('reason','')}</td>
          <td style="padding:12px 8px;">
            <a href="{j.get('apply_url', j['url'])}" style="background:#1d4ed8;color:white;padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;">Apply</a>
          </td>
        </tr>"""

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;">
      <h2 style="color:#111827;">Job Matches - {now}</h2>
      <p style="color:#6b7280;">{len(jobs)} new jobs found and scored. Top {len(top)} shown below.</p>
      {health_banner}
      <table style="width:100%;border-collapse:collapse;margin-top:16px;">
        <thead>
          <tr style="background:#f3f4f6;">
            <th style="padding:10px 8px;text-align:left;color:#6b7280;">#</th>
            <th style="padding:10px 8px;text-align:left;color:#6b7280;">Role</th>
            <th style="padding:10px 8px;text-align:center;color:#6b7280;">Score</th>
            <th style="padding:10px 8px;text-align:left;color:#6b7280;">Why it fits</th>
            <th style="padding:10px 8px;color:#6b7280;">Link</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="margin-top:24px;color:#6b7280;font-size:13px;">
        To apply: open Claude Code and run <code>/applyjob</code> with the job description.<br>
        Or run <code>/reviewjobs</code> to browse all {len(jobs)} matches interactively.
      </p>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Job Bot] {len(jobs)} new AI jobs found - {now}"
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
        print(f"[Email] Digest sent to {RECIPIENT_EMAIL}")
    except Exception as e:
        print(f"[Email] Failed to send: {e}")


# ── Clean HTML ────────────────────────────────────────────────────────────────

def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ── Freshness filter (24 hours max) ──────────────────────────────────────────

def parse_posted_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    # Try RFC 2822 (RSS feeds: "Tue, 07 Jul 2026 12:49:42 +0000")
    try:
        return parsedate_to_datetime(date_str).replace(tzinfo=timezone.utc)
    except Exception:
        pass
    # Try ISO 8601 (Remotive, LinkedIn)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(date_str[:26], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return None

def is_fresh(job: dict) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    # LinkedIn sets posted=now() at scrape time — not a real post date.
    # LinkedIn already uses f_TPR=r86400 to request only last-24h listings,
    # so all LinkedIn results from a live run are fresh. Trust the API filter.
    if job.get("source") == "LinkedIn":
        return True
    dt = parse_posted_date(job.get("posted", ""))
    if dt is None:
        return True
    fresh = dt >= cutoff
    if not fresh:
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        print(f"  [STALE {age_hours:.0f}h] Skipping: {job['title']} at {job['company']}")
    return fresh


# ── Remote-work hard filter ───────────────────────────────────────────────────

# Sources that use remote-only APIs/filters — all results are remote-confirmed
REMOTE_CONFIRMED_SOURCES = {
    "Remotive", "RemoteOK", "WeWorkRemotely", "WorkingNomads", "RemoteCo",
    "Jobspresso", "AIJobs", "Wellfound",
    # LinkedIn bot uses f_WT=2 (remote-only work type filter)
    "LinkedIn",
}

# Signals in title/description/location that hard-disqualify a job regardless of source
HYBRID_ONSITE_PATTERNS = [
    r"\bhybrid\b",
    r"\bon[- ]?site\b",
    r"\bon[- ]?location\b",
    r"\bin[- ]?office\b",
    r"\bdays? (per week |a week )?in (the )?office\b",
    r"\brequired (to be )?in (the )?office\b",
    r"\boffice[- ]based\b",
    r"\bpresence (in|at) (our )?(office|hq|headquarter)\b",
    # Physical-workplace perks. A company describing its canteen or its city is
    # describing a place it expects you to show up to, whatever the "Remote"
    # location tag says.
    r"\blive and work in\b",
    r"\bcanteens?\b",
    r"\bon every floor\b",
    r"\bgaming corners?\b",
    r"\brelocation (support|assistance|package|allowance)\b",
    r"\bwill relocate\b|\bwilling to relocate\b",
    r"\bfree (lunch|breakfast|meals|snacks)\b",
    r"\bour (office|studio) in\b",
    # Anchored so remote selling points ("no commute", "skip the daily commute")
    # are not mistaken for a commuting requirement.
    r"\bcommutable distance\b",
    r"\bable to commute\b",
    r"\bdaily commute to\b",
    r"\bfree parking\b",
    r"\bparking (?:is )?(?:available|provided|on-?site)\b",
]

# City/country names that, when used as a *work location* signal, disqualify the job.
# These are matched against location field and key phrases in the description.
LOCATION_DISQUALIFIERS = [
    # Germany
    r"\bFrankfurt\b", r"\bBerlin\b", r"\bMunich\b", r"\bMünchen\b",
    r"\bHamburg\b", r"\bCologne\b", r"\bDüsseldorf\b", r"\bStuttgart\b",
    # UK (office)
    r"\bLondon[- ]based\b", r"\bbased in London\b", r"\bLondon office\b",
    # Asia / APAC
    r"\bSingapore[- ]based\b", r"\bbased in Singapore\b",
    r"\bJapan[- ]based\b", r"\bbased in Japan\b", r"\bTokyo office\b",
    r"\bIndia[- ]based\b", r"\bbased in India\b",
    r"\bHyderabad\b", r"\bBangalore\b", r"\bBengaluru\b",
    r"\bPune\b", r"\bChennai\b", r"\bMumbai office\b",
    r"\bPhilippines[- ]based\b", r"\bbased in (?:the )?Philippines\b",
    r"\bPakistan[- ]based\b", r"\bbased in Pakistan\b",
    r"\bMalaysia[- ]based\b", r"\bbased in Malaysia\b",
    # Americas (non-remote)
    r"\bLATAM[- ]only\b", r"\bLatin America only\b",
]

# Timezone requirements that imply physical presence or exclude UTC+1
TIMEZONE_DISQUALIFIERS = [
    r"\bPKT\b",           # Pakistan
    r"\bIST\b.*\bhours?\b",  # India Standard Time
    r"\bJST\b",           # Japan
    r"\bSGT\b",           # Singapore
    r"\bPhilippine[s]? time\b",
    r"\bmust overlap with (?:PST|EST|CST|MST)\b",
    r"\bUS[- ]hours?\b", r"\bUS[- ]timezone\b",
]

# Non-English title signals (m/w/d, H/F are German/French gender markers in job titles)
NON_ENGLISH_TITLE_PATTERNS = [
    r"\bm/w/d\b", r"\bm/f/d\b", r"\bw/m/d\b",
    r"\(H/F\)", r"\bH/F\b",
    r"[^\x00-\x7F]{3,}",  # 3+ consecutive non-ASCII chars (CJK, Cyrillic)
]

# Words that appear in essentially every English job posting. If a description
# of reasonable length contains almost none of them, the posting is not English.
# This catches Romance-language posts (Portuguese/Spanish/French/Italian) that
# use mostly-ASCII text and therefore slip past the non-ASCII check above.
ENGLISH_STOPWORDS = [
    "the", "and", "with", "for", "you", "are", "will", "have", "your",
    "our", "this", "that", "from", "work", "team", "role",
]

# Function words specific to the languages we actually see in these feeds.
# Requiring positive evidence here prevents terse English bullet-list postings
# (which naturally contain few stopwords) from being misread as non-English.
FOREIGN_FUNCTION_WORDS = [
    # Portuguese / Spanish
    "de", "para", "que", "com", "uma", "dos", "das", "por", "una", "los",
    "las", "del", "como", "experiencia", "conhecimento", "vaga", "empresa",
    # French
    "les", "des", "vous", "nous", "votre", "pour", "dans", "avec",
    # German
    "und", "der", "die", "das", "mit", "wir", "sie", "für", "eine",
    # Italian
    "della", "delle", "nostro", "azienda",
]

# Employment-region markers. These signal the employer hires into a specific
# country's payroll/benefits system. LinkedIn's f_WT=2 filter only means the
# WORK is performed remotely — it does NOT mean the company hires globally.
# A US company hiring a US-based remote employee is still f_WT=2, so these
# markers are the only reliable way to catch region-locked "remote" roles.
EMPLOYMENT_REGION_MARKERS = [
    # US payroll / benefits / tax
    (r"\b401\s?\(?k\)?\b",                       "US 401(k)"),
    (r"\bW-?2\b",                                 "US W-2"),
    (r"\bmedical,?\s*dental,?\s*(and\s*)?vision\b", "US health benefits"),
    (r"\bdental (and|&) vision\b",                "US health benefits"),
    (r"\bH-?1B\b",                                "US visa sponsorship"),
    (r"\bgreen card\b",                           "US green card"),
    (r"\bFLSA\b|\bEEO\b|\bADA\b",                 "US employment law"),
    (r"\bin-person offsites?\b",                  "in-person offsites"),
    # Explicit national salary bands imply national payroll. Two shapes:
    # a currency-prefixed range ($120,000 - $190,000) and a currency-suffixed
    # one (123,200.00 - 193,600.00 USD), which Proofpoint used and the
    # prefix-only pattern missed.
    # Allow a currency code to sit between the figure and the separator, as in
    # "$127,000 USD - $145,000 USD" (Tebra), which a dash-adjacent pattern misses.
    (r"[$£€]\s?\d{2,3},\d{3}(?:\.\d{2})?\s*(?:USD|CAD|AUD|GBP|EUR)?\s*(?:to|-|–|—)\s*"
     r"[$£€]?\s?\d{2,3},\d{3}",                    "currency salary band"),
    (r"\d{2,3},\d{3}(?:\.\d{2})?\s*(?:USD|CAD|AUD|GBP|EUR)\s*(?:to|-|–|—)\s*"
     r"\d{2,3},\d{3}(?:\.\d{2})?\s*(?:USD|CAD|AUD|GBP|EUR)", "currency-suffixed salary band"),
    (r"\d{2,3},\d{3}(?:\.\d{2})?\s*(?:to|-|–|—)\s*\d{2,3},\d{3}(?:\.\d{2})?\s*(?:USD|CAD|AUD|GBP|EUR)",
                                                  "currency-suffixed salary band"),
    # US pay-transparency and geo-banding language
    (r"\bpay transparency\b",                     "US pay transparency law"),
    (r"\bCalifornia residents\b",                 "US state privacy notice"),
    (r"\bgeo[- ]?zones?\b",                       "US geo-zone pay banding"),
    (r"\bZone \d\b[^.]{0,40}\bNational Average\b", "US geo-zone pay banding"),
    (r"\bveteran (?:or disability )?status\b",    "US EEO language"),
    (r"£\s?\d{2,3},\d{3}",                        "GBP salary band"),
    (r"\bCAD\s?\$?\d{2,3},\d{3}",                 "CAD salary band"),
    # Pay banded by US metro or state is a US-payroll tell on its own
    (r"\bBase Pay Range\b",                       "US metro pay banding"),
    (r"\bSF Bay Area\b|\bBay Area\b",             "US metro pay banding"),
    (r"\b(?:New York City )?Metro Area\b",        "US metro pay banding"),
    # UK / EU payroll
    (r"\bNational Insurance\b",                   "UK payroll"),
    (r"\bpension scheme\b",                       "UK/EU pension"),
]

# "Remote, but really we want you near an office" patterns
SOFT_LOCATION_PREFERENCE = [
    r"remote[- ]first,?\s*(with\s*)?(a\s*)?preference for candidates in",
    r"preference (given )?to candidates (located |based )?in",
    r"remote\s*[-–—]\s*(India|Philippines|Pakistan|Brazil|Mexico|Poland|Ukraine|Vietnam)",
    r"headquarters:\s*remote\s*[-–—]\s*\w+",
    r"remote \(?(US|USA|United States|UK|EU|Canada|EMEA|APAC|LATAM)\)?[- ]only",
    r"\bopen to remote (?:candidates )?(?:within|in) (?:the )?(US|USA|United States|UK|EU|Canada)\b",
]

# Positive evidence that the employer genuinely hires without geographic limits.
#
# These must describe the HIRING POLICY, not the company's footprint. Phrases
# like "globally distributed teams" or "clients worldwide" describe what the
# company looks like, not where it can employ you, and matching them produced a
# false GLOBAL verdict on an on-site Shanghai role (Virtuos, Aug 2026). Keep
# every pattern here anchored to hiring, working, or applying.
GLOBAL_REMOTE_SIGNALS = [
    r"\bwork from anywhere\b",
    r"\banywhere in the world\b",
    r"\bfully (?:distributed|remote),? globally\b",
    r"\bhire (?:from )?(?:anywhere|globally|worldwide)\b",
    r"\bwe hire (?:in|from) (?:any|every) country\b",
    r"\bno location restrictions?\b",
    r"\bwork from any (?:country|timezone|time zone)\b",
    r"\bopen to (?:candidates|applicants) (?:from )?(?:anywhere|worldwide|any country)\b",
    r"\bapplicants? from (?:any country|anywhere|Africa|Nigeria)\b",
    r"\b(?:employ|hiring) (?:in|across) \d+\+? countries\b",
]


# "Work from anywhere" is also the name of a common PERK: a few weeks a year
# when staff may work abroad. That is the opposite of a global hiring policy,
# and Proofpoint's "three-week Work from Anywhere option" produced a false
# GLOBAL verdict on a role priced by US metro. Neutralise the perk phrasing
# before testing for genuine worldwide-hiring language.
# Location values that carry no geographic restriction. Anything else in a
# structured location field names a place and is treated as a restriction.
GENERIC_LOCATION = re.compile(
    r"\s*(?:remote|remote\s*/?\s*(?:global|worldwide|anywhere)|global(?:ly)?|"
    r"worldwide|anywhere|any\s*where|distributed|n/?a|unspecified|-|)\s*",
    re.IGNORECASE,
)

WFA_PERK_PATTERN = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|eight|twelve)[- ]weeks?\s+"
    r"(?:of\s+)?(?:paid\s+)?work[ -]from[ -]anywhere\b"
    r"|\bwork from anywhere\s+(?:option|policy|perk|benefit|program|programme|days?|weeks?)\b",
    re.IGNORECASE,
)


def _looks_non_english(text: str) -> bool:
    """
    True only when a description is both sparse in English stopwords AND rich in
    foreign function words. Requiring both avoids flagging terse English
    requirement lists, which legitimately contain very few stopwords.
    """
    if len(text) < 400:
        return False  # too short to judge reliably
    low = text.lower()
    english = sum(1 for w in ENGLISH_STOPWORDS if re.search(rf"\b{w}\b", low))
    foreign = sum(1 for w in FOREIGN_FUNCTION_WORDS if re.search(rf"\b{w}\b", low))
    return english < 6 and foreign >= 5


def classify_remote(job: dict) -> tuple[str, str]:
    """
    Classify how confidently a Nigeria-based candidate can take this job.

    Returns (verdict, note) where verdict is one of:
      "region_locked" - clear evidence the role is tied to a country. Drop it.
      "global"        - positive evidence of worldwide hiring. Safe to list.
      "unverified"    - remote work, but no statement either way on geography.
                        Keep, but surface the uncertainty rather than implying
                        it is confirmed remote-for-Nigeria.
    """
    title    = job.get("title", "") or ""
    location = job.get("location", "") or ""
    desc     = job.get("description", "") or ""
    combined = f"{title} {location} {desc}"

    # 1. Non-English posting — implies the role is served by a local market
    for pat in NON_ENGLISH_TITLE_PATTERNS:
        if re.search(pat, title, re.IGNORECASE):
            return "region_locked", "non-English title"
    if _looks_non_english(desc):
        return "region_locked", "non-English description"

    # 2. Structured location field. The curated boards (Himalayas, RemoteOK,
    #    WorkingNomads) return a real value here such as "Portugal", "South
    #    Korea" or "Europe, North America" rather than a blanket "Remote".
    #    When present it is the most reliable geography signal available, so
    #    trust it over anything inferred from the prose.
    loc = location.strip()
    if loc:
        # An explicit global tag from a curated board is positive evidence, not
        # merely an absence of restriction, so check it before the generic set.
        if re.search(r"\b(?:Africa|Nigeria|Worldwide|Global(?:ly)?|Anywhere)\b",
                     loc, re.IGNORECASE):
            return "global", f"location field open worldwide: {loc[:40]}"
        if not GENERIC_LOCATION.fullmatch(loc):
            return "region_locked", f"location field restricts to: {loc[:40]}"

    # 3. Hybrid / on-site
    for pat in HYBRID_ONSITE_PATTERNS:
        if re.search(pat, combined, re.IGNORECASE):
            return "region_locked", "hybrid/onsite requirement"

    # 3. Named work locations
    for pat in LOCATION_DISQUALIFIERS:
        if re.search(pat, combined, re.IGNORECASE):
            return "region_locked", "named work location"

    # 4. Timezone requirements
    for pat in TIMEZONE_DISQUALIFIERS:
        if re.search(pat, combined, re.IGNORECASE):
            return "region_locked", "timezone requirement"

    # 5. "Remote but prefer near an office" / country-scoped remote
    for pat in SOFT_LOCATION_PREFERENCE:
        if re.search(pat, combined, re.IGNORECASE):
            return "region_locked", "remote scoped to a region"

    # 6. Country payroll/benefits markers — the signal f_WT=2 cannot see
    for pat, label in EMPLOYMENT_REGION_MARKERS:
        if re.search(pat, combined, re.IGNORECASE):
            return "region_locked", f"employment-region marker ({label})"

    # 7. Positive global-hiring evidence, with perk phrasing stripped first
    global_text = WFA_PERK_PATTERN.sub(" ", combined)
    for pat in GLOBAL_REMOTE_SIGNALS:
        if re.search(pat, global_text, re.IGNORECASE):
            return "global", "explicit global hiring"

    # 8. Remote work confirmed by source, geography simply never stated
    if job.get("source") in REMOTE_CONFIRMED_SOURCES:
        return "unverified", "remote work confirmed, hiring geography not stated"

    explicit_remote = re.search(
        r"\b(fully remote|100%\s*remote|remote[- ]first|remote[- ]ok|"
        r"remote[- ]friendly|work from home|location[:\s]+remote)\b",
        combined, re.IGNORECASE
    )
    if explicit_remote:
        return "unverified", "remote stated, hiring geography not stated"

    return "region_locked", "no remote confirmation"


def is_remote_compatible(job: dict) -> bool:
    """
    Drop region-locked roles before they reach the scorer. Surviving jobs are
    tagged with `remote_verdict` / `remote_note` so the digest and /reviewjobs
    can distinguish confirmed-global roles from merely-unverified ones.
    """
    verdict, note = classify_remote(job)
    job["remote_verdict"] = verdict
    job["remote_note"] = note

    if verdict == "region_locked":
        print(f"  [REMOTE-SKIP {note}] {job.get('title','')}")
        return False
    return True


# ── Eligibility check (location restrictions) ─────────────────────────────────

# Patterns that signal the job is restricted to regions that exclude Nigeria
EXCLUDE_PATTERNS = [
    r"only welcome[s]? applications from\s+(?:Americas?|Europe|Israel|US|UK|Canada|Australia)",
    r"must be (?:located|based|residing|resident) in\s+(?:the\s+)?(?:US|USA|United States|UK|Europe|Canada|Australia)",
    r"must be (?:authorized|eligible) to work in the (?:US|USA|United States|UK)",
    r"(?:US|USA|United States)[- ](?:only|based|citizens? only|residents? only)",
    r"candidates? must (?:reside|live|be located) in",
    r"within \d+ (?:miles?|km) of",
    r"open (?:only )?to (?:US|UK|EU|European|American) (?:residents?|citizens?|applicants?)",
    r"not available (?:in|for) (?:Nigeria|Africa)",
    r"LATAM[- ]only|Latin America only",
    r"Oceania[- ]only",
]

# Patterns that explicitly include Nigeria or Africa or are truly global
INCLUDE_PATTERNS = [
    r"anywhere in the world",
    r"worldwide",
    r"all countries",
    r"no location restriction",
    r"open to all",
    r"Africa",
    r"Nigeria",
    r"global",
]

def is_eligible(job: dict) -> bool:
    description = (job.get("description", "") + " " + job.get("location", "")).lower()
    title = job.get("title", "")

    # Check explicit exclusions
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, description, re.IGNORECASE):
            print(f"  [INELIGIBLE - location restricted] Skipping: {title}")
            return False

    # Check explicit inclusions (override any ambiguity)
    for pattern in INCLUDE_PATTERNS:
        if re.search(pattern, description, re.IGNORECASE):
            return True

    # If location field contains only specific non-eligible regions, skip
    location = job.get("location", "").lower()
    ineligible_locations = [
        "united states only", "us only", "usa only", "uk only",
        "americas, europe, israel", "latam only", "oceania",
        "harrisburg", "sacramento",  # specific city requirements
    ]
    for loc in ineligible_locations:
        if loc in location:
            print(f"  [INELIGIBLE - location] Skipping: {title} ({job.get('location', '')})")
            return False

    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"Job Bot starting at {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"{'='*60}\n")

    seen = load_seen()
    try:
        seen_ts = json.loads(SEEN_FILE.read_text(encoding="utf-8")) if SEEN_FILE.exists() else {}
        if isinstance(seen_ts, list):
            seen_ts = {}
    except (json.JSONDecodeError, ValueError):
        seen_ts = {}
    all_jobs = []

    # Fetch from all sources — each wrapped so one failure never kills the run.
    # Health is recorded per source so a dead scraper shows up in the digest
    # instead of silently shrinking the feed. Eight of these produced nothing
    # for weeks in Aug 2026 and nobody noticed, because the only signal was a
    # print buried in the GitHub Actions log.
    # Retired Aug 2026 after each was verified dead at the endpoint, not merely
    # unlucky. They cost roughly 50s per run in connection timeouts for nothing:
    #   RemoteCo   - connection times out (WinError 10060)
    #   Jobspresso - RSS returns 200 but an empty channel, no items
    #   AIJobs     - feed URL 404s
    #   Wellfound  - jobs.json returns 403, needs authentication now
    #   Indeed     - returns nothing, blocks automated access
    # Re-enable any of them if the endpoint comes back.
    RETIRED = [fetch_remoteco, fetch_jobspresso, fetch_aijobs,
               fetch_wellfound, fetch_indeed]

    source_health = {}
    for fetcher in [
        fetch_remotive, fetch_wwr, fetch_remoteok, fetch_arbeitnow,
        fetch_jobicy, fetch_himalayas, fetch_workingnomads,
        fetch_linkedin,
    ]:
        label = fetcher.__name__.replace("fetch_", "")
        t0 = time.time()
        try:
            got = fetcher()
            all_jobs += got
            source_health[label] = {
                "count": len(got),
                "status": "ok" if got else "empty",
                "seconds": round(time.time() - t0, 1),
            }
        except Exception as e:
            print(f"[{fetcher.__name__}] Fatal error, skipping: {e}")
            source_health[label] = {
                "count": 0,
                "status": f"error: {type(e).__name__}",
                "seconds": round(time.time() - t0, 1),
            }

    healthy = [s for s, v in source_health.items() if v["status"] == "ok"]
    dead    = [s for s, v in source_health.items() if v["status"] != "ok"]
    print(f"\nSource health: {len(healthy)} producing, {len(dead)} silent")
    for s, v in sorted(source_health.items(), key=lambda kv: -kv[1]["count"]):
        print(f"  {s:<16} {v['count']:>4} jobs  {v['seconds']:>6}s  {v['status']}")
    SOURCE_HEALTH_FILE.write_text(json.dumps(source_health, indent=2), encoding="utf-8")

    print(f"\nTotal raw jobs: {len(all_jobs)}")

    # Filter 1: 24-hour freshness only
    fresh_jobs = [j for j in all_jobs if is_fresh(j)]
    print(f"Fresh jobs (within 24h): {len(fresh_jobs)}")

    # Filter 2: remote compatibility (hybrid/onsite/location/timezone signals)
    remote_jobs = [j for j in fresh_jobs if is_remote_compatible(j)]
    print(f"Remote-compatible jobs: {len(remote_jobs)}")

    # Filter 3: location eligibility (explicit country/region restrictions)
    eligible_jobs = [j for j in remote_jobs if is_eligible(j)]
    print(f"Eligible jobs (no location block): {len(eligible_jobs)}")

    # Deduplicate
    new_jobs = []
    for j in eligible_jobs:
        jid = job_id(j["url"])
        if jid not in seen and j["url"]:
            new_jobs.append(j)
            seen.add(jid)

    print(f"New (unseen) jobs: {len(new_jobs)}")

    if not new_jobs:
        print("No new jobs found this run.")
        return

    # Prioritise curated remote-only boards ahead of LinkedIn in the scoring
    # queue. LinkedIn is searched with location=Worldwide, which is correct for
    # finding globally-open roles but also the noisiest source by a distance.
    # When the scoring budget is the binding constraint, spend it on the boards
    # that only list remote work in the first place.
    CURATED_FIRST = ["Himalayas", "WeWorkRemotely", "RemoteOK", "Remotive",
                     "WorkingNomads", "Jobicy", "Arbeitnow"]
    def source_rank(j):
        src = j.get("source", "")
        return CURATED_FIRST.index(src) if src in CURATED_FIRST else len(CURATED_FIRST)
    new_jobs.sort(key=source_rank)

    # Score with Claude (cap at 50 to control API cost)
    to_score = new_jobs[:50]
    print(f"\nScoring {len(to_score)} jobs with Claude...")
    scored = []
    for i, job in enumerate(to_score, 1):
        print(f"  Scoring {i}/{len(to_score)}: {job['title']} at {job['company']}")
        scored.append(score_job(job))
        time.sleep(0.5)

    # Sort by score
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Stamp each job with the batch run time so reviewers can filter by age
    batch_ts = datetime.now(timezone.utc).isoformat()
    for j in scored:
        j["scraped_at"] = batch_ts

    # Save results
    LATEST_FILE.write_text(json.dumps(scored, indent=2, ensure_ascii=False), encoding="utf-8")
    save_seen(seen, seen_ts)

    print(f"\nTop 5 matches:")
    for j in scored[:5]:
        print(f"  [{j['score']}] {j['title']} at {j['company']} ({j['source']})")

    # Send email
    high_quality = [j for j in scored if j["score"] >= 70]
    if high_quality:
        send_digest(high_quality, source_health)
    else:
        print("[Email] No jobs scored 70+, skipping digest.")

    print(f"\nDone. {len(scored)} jobs scored, saved to jobs_latest.json")


if __name__ == "__main__":
    main()
