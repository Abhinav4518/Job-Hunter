import os
import re
import time
import smtplib
import dns.resolver
import pandas as pd
from email.message import EmailMessage
from dotenv import load_dotenv
from jobspy import scrape_jobs

load_dotenv()

SMTP_EMAIL = os.getenv("SMTP_EMAIL", "abhinavjha542@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
RESUME_PATH = os.getenv("RESUME_PATH", "AbhinavJhaIIITManipurResume.pdf")
HISTORY_FILE = "jobs_emailed_history.txt"

# Fast 2-second timeout on DNS lookups so the script never hangs
dns_resolver = dns.resolver.Resolver()
dns_resolver.timeout = 2.0
dns_resolver.lifetime = 2.0
MX_CACHE = {}

# ==========================================================
# 1. ROLE & INDIAN LOCATION FILTERS
# ==========================================================
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

BAD_EMAIL_SUBSTRINGS = [
    "accommodation", "disability", "accessibility", "equalopportunity",
    "eeo", "ethics", "compliance", "privacy", "legal", "security",
    "support", "help", "sales", "billing", "cancel", "marketing", "press",
    "media", "info@", "noreply", "no-reply", "donotreply", "example.com",
    "founders@", "founder@"
]

def is_relevant_role(title):
    t = str(title).lower()
    if any(bad in t for bad in EXCLUDE_ROLE_KEYWORDS):
        return False
    return any(good in t for good in VALID_ROLE_KEYWORDS)


# ==========================================================
# 2. FAST CACHED DNS MX VERIFIER (NO PORT 25 HANGING)
# ==========================================================
def is_clean_and_deliverable_email(email):
    e = email.lower().strip().rstrip(".")
    if "@" not in e or e.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf")):
        return False
    if any(bad in e for bad in BAD_EMAIL_SUBSTRINGS):
        return False

    prefix, domain = e.split("@", 1)
    if len(prefix) < 3:
        return False

    if domain in MX_CACHE:
        return MX_CACHE[domain]

    try:
        mx_records = dns_resolver.resolve(domain, 'MX')
        valid = len(mx_records) > 0
        MX_CACHE[domain] = valid
        return valid
    except Exception:
        MX_CACHE[domain] = False
        return False


def extract_explicit_hr_emails(job_description=""):
    """
    ONLY extracts HR/recruiter emails that were explicitly typed inside the job post
    (e.g., 'Send your resume to hiring@startup.in').
    Zero domain guessing = Zero bounces.
    """
    found_emails = []
    if isinstance(job_description, str):
        desc_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", job_description)
        for email in desc_emails:
            e_low = email.lower().strip().rstrip(".")
            if e_low not in found_emails and is_clean_and_deliverable_email(e_low):
                found_emails.append(e_low)
    return found_emails


# ==========================================================
# 3. INDIAN STARTUP HUB SCRAPER (INDEED INDIA + NAUKRI + LINKEDIN)
# ==========================================================
def fetch_targeted_jobs():
    # Targeted queries & Indian startup hubs (Bengaluru, NCR, Hyderabad, Pune, Remote India)
    search_configs = [
        ("Backend Developer Intern", "Bengaluru, Karnataka, India"),
        ("Full Stack Developer Intern", "Bengaluru, Karnataka, India"),
        ("Software Engineer Intern", "Gurugram, Haryana, India"),
        ("SDE Intern", "Hyderabad, Telangana, India"),
        ("Full Stack Developer Fresher", "Pune, Maharashtra, India"),
        ("Node.js Backend Developer Intern", "India")
    ]
    
    all_jobs = []
    print("[*] Scraping Indian startup hubs across Indeed India, Naukri, and LinkedIn...")
    
    for query, loc in search_configs:
        # 1. Scrape Indeed India + Naukri
        try:
            in_jobs = scrape_jobs(
                site_name=["indeed", "naukri"],
                search_term=query,
                location=loc,
                results_wanted=25,
                hours_old=96,
                country_indeed='india'
            )
            if not in_jobs.empty:
                all_jobs.append(in_jobs)
                print(f"  [+] Indeed/Naukri ({loc}): Found {len(in_jobs)} jobs for '{query}'")
        except Exception as e:
            print(f"  [!] Indeed/Naukri error on '{query}': {e}")

        time.sleep(3)

        # 2. Scrape LinkedIn India with full JD text enabled to catch Indian HR emails
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
                print(f"  [+] LinkedIn ({loc}): Found {len(li_jobs)} jobs for '{query}'")
        except Exception:
            pass

        time.sleep(7)

    if not all_jobs:
        return pd.DataFrame()

    df = pd.concat(all_jobs, ignore_index=True)
    df = df.drop_duplicates(subset=["company", "title"], keep="first")
    df = df[df["title"].apply(is_relevant_role)]
    return df


# ==========================================================
# 4. COLD EMAIL SENDER & ORCHESTRATOR
# ==========================================================
def build_email_body(company_name, role_title):
    return f"""Hi {company_name} Hiring Team,

I noticed the opening for the {role_title} role at {company_name} and wanted to reach out directly.

I am a final-year Computer Science undergraduate at IIIT Manipur (CGPA: 8.89)[cite: 1] with hands-on production experience across Backend and Full-Stack engineering:
- Backend Intern @ IITian Craft: Built a Node.js/Express automation architecture integrating web servers with Tally Prime, improving synchronization speed by 40%[cite: 1].
- Tech Intern @ Dairywala: Engineered full-stack supply chain workflows across procurement, operations, and analytics[cite: 1].
- Systems & AI Engineering: Built 'VoiceCode' (an autonomous TypeScript/Node.js AI IDE agent with 40+ automated tests), 'Agent Ops' (Next.js, WebSockets, React Flow), and a high-concurrency C++17 Multithreaded File Processing Engine[cite: 1].

I have attached my resume for your review. Given my foundation in C++, TypeScript/Node.js, React/Next.js, and distributed systems[cite: 1], I can start contributing to your engineering team from day one.

Would love to chat if my background aligns with what you are looking for.

Best regards,
Abhinav Kumar Jha
B.Tech CSE, IIIT Manipur
Phone: +91-8287244296[cite: 1]
GitHub: https://github.com/Abhinav4518/
LinkedIn: https://www.linkedin.com/in/abhinav-kumar-jha-912426330/
"""

def send_application_email(to_email, company_name, role_title, dry_run=True):
    subject = f"Application for {role_title} | Abhinav Kumar Jha (IIIT Manipur, 8.89 CGPA)"
    body = build_email_body(company_name, role_title)

    if dry_run:
        print(f"  [DRY RUN - EXPLICIT INDIAN JD EMAIL] -> {to_email} | {company_name} ({role_title})")
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
        print(f"  [!] Resume file not found at {RESUME_PATH}. Aborting email send.")
        return False

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"  [SENT] Emailed {to_email} for {company_name}")
        return True
    except Exception as e:
        print(f"  [ERROR] Failed to send to {to_email}: {e}")
        return False

def load_sent_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r") as f:
        return set(line.strip().lower() for line in f if line.strip())

def mark_as_sent(email_addr):
    with open(HISTORY_FILE, "a") as f:
        f.write(email_addr.strip().lower() + "\n")

def run_pipeline(dry_run=True, max_emails_per_run=20):
    df = fetch_targeted_jobs()
    if df.empty:
        print("[-] No jobs found.")
        return

    sent_history = load_sent_history()

    print(f"\n[*] Scanning {len(df)} Indian software job descriptions for explicit HR emails...")
    results = []
    emails_sent = 0

    for _, row in df.iterrows():
        company = str(row.get("company", "")).strip()
        title = str(row.get("title", "")).strip()
        job_url = row.get("job_url", "")
        description = str(row.get("description", ""))

        if not company or company.lower() == "nan":
            continue

        hr_emails = [e for e in extract_explicit_hr_emails(description) if e not in sent_history]
        status = "Apply via Direct_Apply_URL"

        if hr_emails and emails_sent < max_emails_per_run:
            target_email = hr_emails[0]
            if send_application_email(target_email, company, title, dry_run=dry_run):
                status = "Cold Email Sent (Dry Run)" if dry_run else "Cold Email Sent"
                emails_sent += 1
                sent_history.add(target_email)
                if not dry_run:
                    mark_as_sent(target_email)
                    time.sleep(15)

        results.append({
            "Company": company,
            "Role": title,
            "Location": row.get("location", "India"),
            "Explicit_JD_HR_Emails": ", ".join(hr_emails),
            "Direct_Apply_URL": job_url,
            "Outreach_Status": status
        })

    out_df = pd.DataFrame(results)
    write_header = not os.path.exists("targeted_jobs_and_hr_mails.csv")
    out_df.to_csv("targeted_jobs_and_hr_mails.csv", mode="a", header=write_header, index=False)
    print(f"\n[+] Pipeline complete! Saved {len(out_df)} Indian startup/tech jobs ({emails_sent} explicit HR emails triggered) to 'targeted_jobs_and_hr_mails.csv'.")

if __name__ == "__main__":
    # Test with dry_run=True first, then set dry_run=False to send live emails!
    run_pipeline(dry_run=False, max_emails_per_run=20)