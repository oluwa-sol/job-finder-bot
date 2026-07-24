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
    # Broader operational AI
    "AI Operations Engineer",
    "Conversational AI Engineer",
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
        r = requests.get("https://remoteok.com/api", headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
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
    try:
        r = requests.get("https://jobicy.com/api/v2/remote-jobs?count=50&tag=developer", timeout=15)
        data = r.json()
        for j in data.get("jobs", []):
            title = j.get("jobTitle", "")
            if not is_relevant(title):
                continue
            jobs.append({
                "title": title,
                "company": j.get("companyName", ""),
                "url": j.get("url", ""),
                "description": clean_html(j.get("jobDescription", "")),
                "location": j.get("jobGeo", "Remote") or "Remote",
                "posted": j.get("pubDate", ""),
                "source": "Jobicy",
            })
    except Exception as e:
        print(f"[Jobicy] Error: {e}")
    print(f"[Jobicy] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: Himalayas ─────────────────────────────────────────────────────────

def fetch_himalayas() -> list[dict]:
    jobs = []
    feeds = [
        "https://himalayas.app/jobs/rss",
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
                    "source": "Himalayas",
                })
        except Exception as e:
            print(f"[Himalayas] Error: {e}")
    print(f"[Himalayas] {len(jobs)} relevant jobs found")
    return jobs


# ── Source: Working Nomads ────────────────────────────────────────────────────

def fetch_workingnomads() -> list[dict]:
    jobs = []
    feeds = [
        "https://www.workingnomads.com/feed?category=development",
        "https://www.workingnomads.com/feed?category=data",
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
                    "source": "WorkingNomads",
                })
        except Exception as e:
            print(f"[WorkingNomads] Error on {feed_url}: {e}")
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


# ── Source: Indeed RSS ────────────────────────────────────────────────────────

def fetch_indeed() -> list[dict]:
    jobs = []
    queries = [
        "AI+Automation+Engineer",
        "LLM+Engineer",
        "AI+Agent+Developer",
        "Agentic+AI+Engineer",
        "n8n+automation",
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
        "Agentic AI",
        "n8n automation",
        "AI Automation Consultant",
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
                    "posted": datetime.now(timezone.utc).isoformat(),
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

    # Pre-filter: drop jobs whose description reveals hybrid or on-site work
    confirmed_remote = []
    for j in jobs:
        desc = j.get("description", "").lower()
        if not desc:
            # No description fetched — keep and let scorer decide
            confirmed_remote.append(j)
            continue
        if is_hybrid_or_onsite(desc):
            print(f"  [DROP hybrid/onsite] {j['title']} at {j['company']}")
            continue
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

RELEVANT_TERMS = [
    "ai", "llm", "automation", "agentic", "agent", "n8n", "langchain",
    "openai", "claude", "gpt", "workflow", "machine learning", "ml",
    "artificial intelligence", "chatbot", "rag", "retrieval", "nlp",
    "generative", "prompt", "integration", "zapier", "make.com",
    "intelligent process", "hyperautomation", "digital process", "low-code", "no-code",
]

# Job titles that pass the keyword check but are completely off-profile
EXCLUDE_TITLE_TERMS = [
    "civil engineer", "grid engineer", "mechanical engineer", "electrical engineer",
    "structural engineer", "environmental engineer", "water engineer", "drainage",
    "aml officer", "compliance officer", "chief aml",
    "supply chain", "clinical", "logistics",
    "telefonist", "interviewer", "umfragen", "homeoffice",  # German survey roles
    "rpa developer",  # often on-prem, mainframe-heavy; filter unless clearly AI-adjacent
    "work permit", "permit engineer",
    "surgeon", "physician", "nurse", "doctor",
]

def is_relevant(title: str) -> bool:
    t = title.lower()
    if any(excl in t for excl in EXCLUDE_TITLE_TERMS):
        return False
    return any(term in t for term in RELEVANT_TERMS)


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

def send_digest(jobs: list[dict]):
    if not GMAIL_APP_PASSWORD or GMAIL_APP_PASSWORD == "your_gmail_app_password_here":
        print("[Email] Gmail app password not set. Skipping email. Check .env file.")
        return

    top = jobs[:10]
    now = datetime.now().strftime("%d %b %Y, %I:%M %p")

    rows = ""
    for i, j in enumerate(top, 1):
        score = j.get("score", 0)
        if score >= 80:
            color = "#22c55e"
        elif score >= 60:
            color = "#f59e0b"
        else:
            color = "#ef4444"
        rows += f"""
        <tr style="border-bottom:1px solid #e5e7eb;">
          <td style="padding:12px 8px;font-weight:bold;color:#6b7280;">{i}</td>
          <td style="padding:12px 8px;">
            <a href="{j['url']}" style="color:#1d4ed8;font-weight:600;text-decoration:none;">{j['title']}</a><br>
            <span style="color:#6b7280;font-size:13px;">{j['company']} &middot; {j['source']}</span>
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
    dt = parse_posted_date(job.get("posted", ""))
    if dt is None:
        # LinkedIn jobs we set to now(), always fresh
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    fresh = dt >= cutoff
    if not fresh:
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        print(f"  [STALE {age_hours:.0f}h] Skipping: {job['title']} at {job['company']}")
    return fresh


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

    # Fetch from all sources — each wrapped so one failure never kills the run
    for fetcher in [
        fetch_remotive, fetch_wwr, fetch_remoteok, fetch_arbeitnow,
        fetch_jobicy, fetch_himalayas, fetch_workingnomads, fetch_remoteco,
        fetch_jobspresso, fetch_indeed, fetch_linkedin,
    ]:
        try:
            all_jobs += fetcher()
        except Exception as e:
            print(f"[{fetcher.__name__}] Fatal error, skipping: {e}")

    print(f"\nTotal raw jobs: {len(all_jobs)}")

    # Filter 1: 24-hour freshness only
    fresh_jobs = [j for j in all_jobs if is_fresh(j)]
    print(f"Fresh jobs (within 24h): {len(fresh_jobs)}")

    # Filter 2: location eligibility
    eligible_jobs = [j for j in fresh_jobs if is_eligible(j)]
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

    # Save results
    LATEST_FILE.write_text(json.dumps(scored, indent=2, ensure_ascii=False), encoding="utf-8")
    save_seen(seen, seen_ts)

    print(f"\nTop 5 matches:")
    for j in scored[:5]:
        print(f"  [{j['score']}] {j['title']} at {j['company']} ({j['source']})")

    # Send email
    high_quality = [j for j in scored if j["score"] >= 70]
    if high_quality:
        send_digest(high_quality)
    else:
        print("[Email] No jobs scored 70+, skipping digest.")

    print(f"\nDone. {len(scored)} jobs scored, saved to jobs_latest.json")


if __name__ == "__main__":
    main()
