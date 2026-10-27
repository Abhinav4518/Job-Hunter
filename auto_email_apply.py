import os
import re
import time
import smtplib
import dns.resolver
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from email.message import EmailMessage
from dotenv import load_dotenv
from jobspy import scrape_jobs

load_dotenv()

SMTP_EMAIL = os.getenv("SMTP_EMAIL", "abhinavjha542@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
RESUME_PATH = os.getenv("RESUME_PATH", "AbhinavJhaIIITManipurResume.pdf")
HISTORY_FILE = "emailed_addresses_history.txt"
CSV_LOG_FILE = "emailed_startups_log.csv"

# Fast 2-second DNS timeout so the script never hangs
dns_resolver = dns.resolver.Resolver()
dns_resolver.timeout = 2.0
dns_resolver.lifetime = 2.0
MX_CACHE = {}

# ==========================================================
# 1. STRICT FILTERS (NO PAKISTAN, NO LOCKED GROUPS, NO JUNK)
# ==========================================================
EXCLUDED_GEO_KEYWORDS = [
    "pakistan", "pakistani", "karachi", "lahore", "islamabad",
    "rawalpindi", "faisalabad", "peshawar", "multan", "sialkot"
]

INDIA_KEYWORDS = [
    "india", "bengaluru", "bangalore", "mumbai", "delhi", "gurgaon",
    "gurugram", "noida", "hyderabad", "pune", "chennai", "indian"
]

BLOCKED_EMAIL_PREFIXES = {
    "founders", "founder", "sales", "support", "billing", "cancel",
    "help", "info", "privacy", "legal", "security", "press", "media",
    "marketing", "noreply", "no-reply", "donotreply", "abuse", "admin",
    "webmaster", "compliance", "accommodation", "disability", "example",
    "you", "name", "user", "test", "yourname", "firstname", "email"
}

BAD_EMAIL_SUBSTRINGS = [
    "accommodation", "disability", "accessibility", "equalopportunity",
    "eeo", "ethics", "compliance", "privacy", "legal", "security",
    "support", "billing", "cancel", "noreply", "no-reply", "donotreply",
    "example.com", "email.com", "domain.com", "sentry.io", "wixpress.com"
]

ALLOWED_SITE_HIRING_PREFIXES = {
    "careers", "career", "jobs", "job", "hiring", "talent",
    "recruiting", "recruitment", "hr", "people", "join", "work",
    "engineering", "hello", "hi", "contact", "team"
}

VALID_ROLE_KEYWORDS = [
    "software", "sde", "backend", "back-end", "full stack", "fullstack",
    "full-stack", "node", "react", "next.js", "c++", "python", "ai",
    "genai", "agent", "platform", "systems", "developer", "engineer", "mern"
]

EXCLUDE_ROLE_KEYWORDS = [
    "aircraft", "mechanical", "civil", "electrical", "power greenfield",
    "sales", "marketing", "hr ", "human resource", "flutter", "ios", "android",
    "php", "wordpress", "shopify", "dotnet", ".net"
]

def is_excluded_geo(text="", domain_or_url=""):
    combined = f"{text} {domain_or_url}".lower()
    if any(k in combined for k in EXCLUDED_GEO_KEYWORDS):
        return True
    clean_dom = domain_or_url.lower().strip()
    if clean_dom.endswith((".pk", ".com.pk", ".org.pk", ".net.pk", ".edu.pk")):
        return True
    return False

def is_relevant_role(title):
    t = str(title).lower()
    if any(bad in t for bad in EXCLUDE_ROLE_KEYWORDS):
        return False
    return any(good in t for good in VALID_ROLE_KEYWORDS)

def is_valid_deliverable_email(email):
    if not email or "@" not in email:
        return False
    e = email.lower().strip().rstrip(".")
    if e.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".js", ".css", ".pdf")):
        return False
    if any(bad in e for bad in BAD_EMAIL_SUBSTRINGS):
        return False

    prefix, domain = e.split("@", 1)
    if prefix in BLOCKED_EMAIL_PREFIXES or len(prefix) < 2 or len(prefix) > 35:
        return False
    if "." not in domain or is_excluded_geo(e, domain):
        return False

    if domain in MX_CACHE:
        return MX_CACHE[domain]

    try:
        records = dns_resolver.resolve(domain, 'MX')
        valid = len(records) > 0
        MX_CACHE[domain] = valid
        return valid
    except Exception:
        MX_CACHE[domain] = False
        return False


# ==========================================================
# 2. WEBSITE DEEP EMAIL SCRAPER (USED FOR YC & STARTUPS)
# ==========================================================
def extract_clean_domain(website_url):
    if not website_url or pd.isna(website_url):
        return None
    if not website_url.startswith("http"):
        website_url = "https://" + website_url
    parsed = urlparse(website_url)
    domain = parsed.netloc.replace("www.", "").strip().lower()
    if is_excluded_geo(domain, domain):
        return None
    if any(bad in domain for bad in ["github.com", "notion.site", "linkedin.com", "ycombinator.com", "apple.com", "google.com"]):
        return None
    return domain if "." in domain else None

def resolve_company_to_domain(company_name):
    if not company_name or pd.isna(company_name):
        return None
    clean_name = re.sub(r"\b(Pvt|Ltd|Private|Limited|Inc|LLC|Corp|Technologies|Solutions|Labs|India)\b\.?", "", str(company_name), flags=re.IGNORECASE).strip()
    if len(clean_name) < 2:
        return None
    try:
        url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={clean_name}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200 and len(res.json()) > 0:
            dom = res.json()[0].get("domain", "").lower()
            if dom and not is_excluded_geo(dom, dom):
                return dom
    except Exception:
        pass
    return None

def scrape_emails_from_company_website(base_url, target_domain):
    """
    Visits /careers, /jobs, /, /about, /contact on a startup's website
    and extracts real published emails (both mailto: and text). Zero guessing.
    """
    found_emails = []
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    for path in ["/careers", "/jobs", "", "/contact", "/about"]:
        try:
            target_url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
            res = requests.get(target_url, headers=headers, timeout=3)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")

            # 1. Extract clickable mailto: links
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if href.lower().startswith("mailto:"):
                    raw_email = href[7:].split("?")[0].strip().lower().rstrip(".")
                    if "@" in raw_email:
                        prefix, dom = raw_email.split("@", 1)
                        if dom == target_domain and is_valid_deliverable_email(raw_email):
                            if raw_email not in found_emails:
                                found_emails.append(raw_email)

            # 2. Extract visible @target_domain emails written on the page
            page_text = soup.get_text(" ", strip=True)
            text_matches = re.findall(r"[a-zA-Z0-9._%+-]+@" + re.escape(target_domain), page_text, flags=re.IGNORECASE)
            for e in text_matches:
                e_low = e.lower().strip().rstrip(".")
                prefix = e_low.split("@")[0]
                if prefix in ALLOWED_SITE_HIRING_PREFIXES and is_valid_deliverable_email(e_low):
                    if e_low not in found_emails:
                        found_emails.append(e_low)

            if found_emails:
                break
        except Exception:
            continue

    def rank_email(addr):
        p = addr.split("@")[0]
        if p in {"careers", "career", "jobs", "job", "hiring", "talent", "recruiting", "hr"}:
            return 0
        if p not in ALLOWED_SITE_HIRING_PREFIXES:
            return 1  # Named founder/engineer email
        return 2

    found_emails.sort(key=rank_email)
    return found_emails


# ==========================================================
# 3. PRIORITY 1: NEWLY FUNDED YC STARTUPS (INDIAN + GLOBAL)
# ==========================================================
def gather_yc_directory_emails(max_indian=50, max_global=40):
    print("[*] Priority 1: Scanning YC Directory (Indian YC + Newly Funded Global YC) for emails...")
    url = "https://yc-oss.github.io/api/companies/all.json"
    email_leads = []

    try:
        res = requests.get(url, timeout=12)
        companies = res.json()

        indian_yc = []
        global_yc = []

        for comp in reversed(companies):
            status = str(comp.get("status", "Active"))
            website = str(comp.get("website", "")).strip()
            if status != "Active" or not website.startswith("http"):
                continue

            batch = str(comp.get("batch", "")).strip()
            is_hiring = comp.get("isHiring", False)
            team_size = comp.get("team_size") or 15

            loc_str = " ".join([
                str(comp.get("name", "")),
                str(comp.get("all_locations", "")),
                str(comp.get("regions", "")),
                str(comp.get("long_description", "")),
                str(comp.get("one_liner", "")),
                website
            ]).lower()

            if is_excluded_geo(loc_str, website):
                continue

            is_indian = any(k in loc_str for k in INDIA_KEYWORDS) or website.endswith(".in")
            is_recent = any(yr in batch for yr in ["24", "25", "26", "2024", "2025", "2026"])

            if is_indian and (is_hiring or is_recent) and team_size <= 150:
                indian_yc.append((comp, f"YC India ({batch})", 0))
            elif is_recent and is_hiring and team_size <= 60:
                global_yc.append((comp, f"YC Global ({batch})", 1))

        candidates = indian_yc[:max_indian] + global_yc[:max_global]
        print(f"  -> Deep-scanning {len(candidates)} YC startup websites for direct emails...")

        for comp, source_tag, prio in candidates:
            website = comp.get("website", "")
            domain = extract_clean_domain(website)
            if not domain:
                continue
            emails = scrape_emails_from_company_website(website, domain)
            if emails:
                email_leads.append({
                    "Company": comp.get("name"),
                    "Role": "Founding / Backend / Full-Stack Engineer (Intern / SDE-1)",
                    "One_Liner": comp.get("one_liner") or "AI & Software Systems",
                    "Source": source_tag,
                    "Priority": prio,
                    "Pitch_Type": "YC_STARTUP",
                    "Emails": emails
                })
        print(f"  [+] Found verified emails for {len(email_leads)} YC Directory startups!")
    except Exception as e:
        print(f"  [!] YC Directory error: {e}")

    return email_leads


# ==========================================================
# 4. PRIORITY 2: YC HACKER NEWS "WHO IS HIRING" STARTUPS
# ==========================================================
def gather_hn_startup_emails():
    print("[*] Priority 2: Scanning YC Hacker News 'Who is Hiring' for direct founder/CTO emails...")
    email_leads = []
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        search_url = "https://hn.algolia.com/api/v1/search_by_date?tags=story,ask_hn&query=%22Who%20is%20hiring%22&hitsPerPage=3"
        stories = requests.get(search_url, headers=headers, timeout=8).json().get("hits", [])

        for story in stories:
            story_id = story.get("objectID")
            title = story.get("title", "")
            if not story_id or "who is hiring" not in title.lower():
                continue

            queries = ["India", "YC", "Remote", "backend", "fullstack", "engineer", "AI"]
            seen_ids = set()

            for q in queries:
                c_url = f"https://hn.algolia.com/api/v1/search_by_date?tags=comment,story_{story_id}&query={q}&hitsPerPage=100"
                comments = requests.get(c_url, headers=headers, timeout=8).json().get("hits", [])

                for c in comments:
                    cid = c.get("objectID")
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)

                    raw_html = c.get("comment_text", "")
                    if not raw_html:
                        continue
                    soup = BeautifulSoup(raw_html, "html.parser")
                    text = soup.get_text(" ", strip=True)
                    text_lower = text.lower()

                    if is_excluded_geo(text_lower):
                        continue
                    if not any(k in text_lower for k in ["backend", "full stack", "full-stack", "fullstack", "typescript", "node", "react", "python", "c++", "ai", "intern", "new grad", "software"]):
                        continue

                    norm_text = re.sub(r"\s*\[at\]\s*|\s*\(at\)\s*", "@", text, flags=re.IGNORECASE)
                    norm_text = re.sub(r"\s*\[dot\]\s*|\s*\(dot\)\s*", ".", norm_text, flags=re.IGNORECASE)

                    raw_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", norm_text)
                    valid_emails = []
                    for e in raw_emails:
                        e_low = e.lower().strip().rstrip(".")
                        if is_valid_deliverable_email(e_low) and e_low not in valid_emails:
                            valid_emails.append(e_low)

                    if valid_emails:
                        is_yc = "yc " in text_lower or "y combinator" in text_lower or "(yc" in text_lower
                        is_india = any(ind in text_lower for ind in INDIA_KEYWORDS) or any(e.endswith(".in") for e in valid_emails)
                        prio = 0 if is_yc else (1 if is_india else 2)
                        source_tag = "YC Startup (HN)" if is_yc else ("India Startup (HN)" if is_india else "Global Startup (HN)")

                        first_line = text.split("|")[0].split("\n")[0].strip()[:45]
                        company_name = re.sub(r"https?://\S+", "", first_line).strip() or "Tech Startup"
                        if len(company_name) > 2:
                            email_leads.append({
                                "Company": company_name,
                                "Role": "Software / Backend / Full-Stack Engineer",
                                "One_Liner": "scaling modern software & AI systems",
                                "Source": source_tag,
                                "Priority": prio,
                                "Pitch_Type": "YC_STARTUP",
                                "Emails": valid_emails
                            })
        print(f"  [+] Found {len(email_leads)} startups with direct emails on Hacker News!")
    except Exception as e:
        print(f"  [!] HN API error: {e}")

    return email_leads


# ==========================================================
# 5. PRIORITY 3: OTHER HIRING STARTUPS (INDEED, NAUKRI, LINKEDIN)
# ==========================================================
def gather_job_board_startup_emails():
    print("[*] Priority 3: Scraping hiring startups on Indeed, Naukri & LinkedIn for HR emails...")
    # Targeted queries including email-intent keywords so posts actually contain HR emails
    search_configs = [
        ("Backend Developer Intern", "Bengaluru, Karnataka, India", "india"),
        ("Full Stack Developer Intern", "Bengaluru, Karnataka, India", "india"),
        ("Software Engineer Intern", "Gurugram, Haryana, India", "india"),
        ("Software Engineer Fresher Startup", "India", "india"),
        ("SDE Intern", "Hyderabad, Telangana, India", "india"),
        ("Full Stack Developer Intern", "Remote", "usa")
    ]

    all_jobs = []
    for query, loc, country_code in search_configs:
        try:
            sites = ["indeed", "naukri"] if country_code == "india" else ["indeed"]
            in_jobs = scrape_jobs(
                site_name=sites,
                search_term=query,
                location=loc,
                results_wanted=25,
                hours_old=96,
                country_indeed=country_code
            )
            if not in_jobs.empty:
                all_jobs.append(in_jobs)
        except Exception:
            pass

        time.sleep(2)

        try:
            li_jobs = scrape_jobs(
                site_name=["linkedin"],
                search_term=query,
                location=loc,
                results_wanted=15,
                hours_old=96,
                linkedin_fetch_description=True
            )
            if not li_jobs.empty:
                all_jobs.append(li_jobs)
        except Exception:
            pass

        time.sleep(5)

    if not all_jobs:
        return []

    df = pd.concat(all_jobs, ignore_index=True)
    df = df.drop_duplicates(subset=["company", "title"], keep="first")
    df = df[df["title"].apply(is_relevant_role)]

    email_leads = []
    print(f"  -> Extracting HR emails from {len(df)} scraped startup/tech roles...")

    for _, row in df.iterrows():
        company = str(row.get("company", "")).strip()
        title = str(row.get("title", "")).strip()
        location = str(row.get("location", "")).strip()
        description = str(row.get("description", ""))
        job_url = str(row.get("job_url", ""))

        if not company or company.lower() == "nan":
            continue
        if is_excluded_geo(f"{company} {location} {description}", job_url):
            continue

        found_emails = []
        # 1. Extract explicit email from job description
        if isinstance(description, str):
            matches = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", description)
            for m in matches:
                e_low = m.lower().strip().rstrip(".")
                if is_valid_deliverable_email(e_low) and e_low not in found_emails:
                    found_emails.append(e_low)

        # 2. If not in JD, resolve startup website and scrape /careers or /contact
        if not found_emails:
            dom = resolve_company_to_domain(company)
            if dom:
                found_emails = scrape_emails_from_company_website(f"https://{dom}", dom)

        if found_emails:
            email_leads.append({
                "Company": company,
                "Role": title,
                "One_Liner": "rapidly scaling software systems",
                "Source": f"Job Board ({location or 'India/Remote'})",
                "Priority": 2,
                "Pitch_Type": "HR_ROLE",
                "Emails": found_emails
            })

    print(f"  [+] Extracted verified HR/Career emails for {len(email_leads)} actively hiring companies!")
    return email_leads


# ==========================================================
# 6. EMAIL TEMPLATES & AUTOMATED SENDER
# ==========================================================
def build_email_content(lead):
    company = lead["Company"]
    role = lead["Role"]
    one_liner = lead["One_Liner"]

    if lead["Pitch_Type"] == "YC_STARTUP":
        subject = f"Engineering @ {company} — Shipping Agentic AI & Backends (IIIT Manipur)"
        body = f"""Hi {company} team,

Saw your engineering opening for {company} ({one_liner})—reaching out because I'd love to contribute as a {role}.

I'm a final-year CS undergrad at IIIT Manipur (8.89 CGPA) and spend most of my time shipping agentic AI architectures and high-concurrency backends:
- VoiceCode (TypeScript, Node.js, Gemini/Ollama): Built an autonomous coding agent running a bounded plan-execute-verify-repair loop with a deterministic safety/rollback layer and 40+ integration tests.
- Agent Ops (Next.js, Node.js, WebSockets, Groq): Architected a real-time ReAct workflow builder with custom tool execution and rate-limit backoff.
- C++17 Multithreaded Engine: Built a custom thread-pool and lock-optimized producer-consumer file processing engine.
- Production Internships: Shipped full-stack and Node.js/Express backend systems at Dairywala and IITian Craft (cut Tally sync latency by 40%).

I've attached my resume. Happy to build a quick prototype or tackle a backlog ticket this week to show how fast I ship.

Best,
Abhinav Kumar Jha
IIIT Manipur | +91-8287244296
GitHub: https://github.com/Abhinav4518/
LinkedIn: https://www.linkedin.com/in/abhinav-kumar-jha-912426330/
"""
    else:
        subject = f"Application for {role} | Abhinav Kumar Jha (IIIT Manipur, 8.89 CGPA)"
        body = f"""Hi {company} Hiring Team,

I noticed the opening for the {role} role at {company} and wanted to reach out directly.

I am a final-year Computer Science undergraduate at IIIT Manipur (CGPA: 8.89) with hands-on production experience across Backend and Full-Stack engineering:
- Backend Intern @ IITian Craft: Built a Node.js/Express automation architecture integrating web servers with Tally Prime, improving synchronization speed by 40%.
- Tech Intern @ Dairywala: Engineered full-stack supply chain workflows across procurement, operations, and analytics.
- Systems & AI Engineering: Built 'VoiceCode' (an autonomous TypeScript/Node.js AI IDE agent with 40+ automated tests), 'Agent Ops' (Next.js, WebSockets, React Flow), and a high-concurrency C++17 Multithreaded File Processing Engine.

I have attached my resume for your review. Given my foundation in C++, TypeScript/Node.js, React/Next.js, and distributed systems, I can start contributing to your engineering team from day one.

Would love to chat if my background aligns with what you are looking for.

Best regards,
Abhinav Kumar Jha
B.Tech CSE, IIIT Manipur
Phone: +91-8287244296
GitHub: https://github.com/Abhinav4518/
LinkedIn: https://www.linkedin.com/in/abhinav-kumar-jha-912426330/
"""
    return subject, body

def send_email_now(to_email, lead, dry_run=True):
    subject, body = build_email_content(lead)
    company = lead["Company"]
    source = lead["Source"]

    if dry_run:
        print(f"  [DRY RUN] -> {to_email} | {company} [{source}]")
        return True

    msg = EmailMessage()
    msg["From"] = f"Abhinav Kumar Jha <{SMTP_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    if os.path.exists(RESUME_PATH):
        with open(RESUME_PATH, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="application",
                subtype="pdf",
                filename=os.path.basename(RESUME_PATH)
            )
    else:
        print(f"  [!] Resume file not found at {RESUME_PATH}. Aborting.")
        return False

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"  [SENT] -> {to_email} | {company} [{source}]")
        return True
    except Exception as e:
        print(f"  [ERROR] Failed to email {to_email}: {e}")
        return False


# ==========================================================
# 7. MASTER EMAIL-ONLY ORCHESTRATOR
# ==========================================================
def load_sent_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r") as f:
        return set(line.strip().lower() for line in f if line.strip())

def mark_as_sent(email_addr):
    with open(HISTORY_FILE, "a") as f:
        f.write(email_addr.strip().lower() + "\n")

def run_master_email_bot(dry_run=True, max_emails_to_send=35):
    sent_history = load_sent_history()

    # Gather emails from all 3 pipelines (YC Directory -> YC/HN -> Job Boards)
    yc_leads = gather_yc_directory_emails(max_indian=50, max_global=40)
    hn_leads = gather_hn_startup_emails()
    jb_leads = gather_job_board_startup_emails()

    all_leads = yc_leads + hn_leads + jb_leads
    all_leads.sort(key=lambda x: x.get("Priority", 2))

    sent_count = 0
    logged_rows = []

    print(f"\n[*] Sending emails across {len(all_leads)} total verified startup leads (Max this run: {max_emails_to_send})...")
    for lead in all_leads:
        fresh_emails = [e for e in lead["Emails"] if e not in sent_history]
        if not fresh_emails:
            continue

        target_email = fresh_emails[0]
        if sent_count >= max_emails_to_send:
            break

        if send_email_now(target_email, lead, dry_run=dry_run):
            sent_count += 1
            sent_history.add(target_email)
            if not dry_run:
                mark_as_sent(target_email)
                time.sleep(15)  # 15-second pause between live emails to protect Gmail

            logged_rows.append({
                "Company": lead["Company"],
                "Role": lead["Role"],
                "Source": lead["Source"],
                "Emailed_Address": target_email,
                "Status": "Sent (Dry Run)" if dry_run else "Sent"
            })

    if logged_rows:
        out_df = pd.DataFrame(logged_rows)
        write_header = not os.path.exists(CSV_LOG_FILE)
        out_df.to_csv(CSV_LOG_FILE, mode="a", header=write_header, index=False)
        print(f"\n[+] Finished! Automatically emailed {sent_count} startups. Receipt log saved to '{CSV_LOG_FILE}'.")
    else:
        print("\n[-] No new un-emailed addresses found in this run.")

if __name__ == "__main__":
    # 1. Run once with dry_run=True to see the exact list of emails in your terminal.
    # 2. Change dry_run=False to send all 35 emails automatically!
    run_master_email_bot(dry_run=False, max_emails_to_send=35)