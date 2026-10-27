import os
import re
import io
import time
import smtplib
import dns.resolver
import requests
import pandas as pd
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

SMTP_EMAIL = os.getenv("SMTP_EMAIL", "abhinavjha542@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
RESUME_PATH = os.getenv("RESUME_PATH", "AbhinavJhaIIITManipurResume.pdf")
HISTORY_FILE = "delhi_sheet_emailed_history.txt"
CSV_LOG_FILE = "delhi_sheet_outreach_log.csv"
LOCAL_CACHE_CSV = "delhi_startups_cache.csv"

# Direct CSV export URL for your Google Sheet
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/17R8EVYX1AGr7qX-nLHZhqJQfA4hFW-avxe4gjrZyGKQ/export?format=csv"

# Use Google & Cloudflare public DNS directly so local router DNS hiccups don't fail
dns_resolver = dns.resolver.Resolver(configure=False)
dns_resolver.nameservers = ["8.8.8.8", "1.1.1.1", "8.8.4.4"]
dns_resolver.timeout = 3.0
dns_resolver.lifetime = 3.0
MX_CACHE = {}

# Skip media/news outlets and coworking spaces in the sheet
SKIP_COMPANY_KEYWORDS = [
    "inc42", "tice news", "techobserver", "coworks", "coworking",
    "entrepreneurs association", "fitt, iit delhi"
]

# Avoid sending job applications to pure sales/regional support/editorial inboxes
BLOCKED_PREFIXES = {
    "sales", "salest", "editor", "editorial", "ir", "bd",
    "canberra.support", "sg-enquiry", "vietnam", "thailand",
    "indonesia", "uk.info", "sg.info", "partner.app"
}


# ==========================================================
# 1. DNS MX CHECK & SMART EMAIL RANKER (COLUMN C + D)
# ==========================================================
def has_valid_mx(email):
    if not email or "@" not in email:
        return False
    _, domain = email.split("@", 1)
    if domain in MX_CACHE:
        return MX_CACHE[domain]
    try:
        records = dns_resolver.resolve(domain, "MX")
        valid = len(records) > 0
        MX_CACHE[domain] = valid
        return valid
    except Exception:
        MX_CACHE[domain] = False
        return False

def pick_best_email_for_company(primary_str, secondary_str):
    """
    Combines Primary Working Email (Col C) and Secondary/Alternate Emails (Col D),
    cleans truncated/invalid addresses, and picks the best HR/Founder/Contact inbox.
    """
    combined_raw = f"{primary_str or ''}, {secondary_str or ''}"
    candidates = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", combined_raw)

    valid_emails = []
    for e in candidates:
        e_low = e.lower().strip().rstrip(".")
        if e_low.endswith("..."):
            continue
        prefix = e_low.split("@")[0]
        if prefix in BLOCKED_PREFIXES:
            continue
        if has_valid_mx(e_low) and e_low not in valid_emails:
            valid_emails.append(e_low)

    if not valid_emails:
        return None, []

    def score_email(addr):
        p = addr.split("@")[0]
        if p in {"hr", "careers", "career", "people", "jobs", "hiring", "talent"}:
            return 0
        if p in {"hello", "hi", "connect", "contact", "ai"}:
            return 2
        if p in {"info", "mail", "admin", "enquiry", "care", "help", "support"}:
            return 3
        return 1  # Named person (founder/CTO)

    valid_emails.sort(key=score_email)
    return valid_emails[0], valid_emails


# ==========================================================
# 2. LOAD & PARSE GOOGLE SHEET (WITH RETRY + LOCAL CACHE)
# ==========================================================
def load_delhi_startups_from_sheet():
    df = None

    # If we already cached the sheet locally, use it or refresh it
    if os.path.exists(LOCAL_CACHE_CSV):
        print(f"[*] Loading Delhi startups from local cache '{LOCAL_CACHE_CSV}'...")
        df = pd.read_csv(LOCAL_CACHE_CSV)
    else:
        print("[*] Downloading '100+ Delhi Tech Startups Contacts' from Google Sheets...")
        for attempt in range(1, 5):
            try:
                res = requests.get(SHEET_CSV_URL, timeout=15)
                res.raise_for_status()
                with open(LOCAL_CACHE_CSV, "w", encoding="utf-8") as f:
                    f.write(res.text)
                df = pd.read_csv(io.StringIO(res.text))
                print(f"  [+] Downloaded and cached sheet to '{LOCAL_CACHE_CSV}'.")
                break
            except Exception as e:
                print(f"  [!] Network/DNS hiccup on attempt {attempt}/4: {e}")
                if attempt < 4:
                    print("      Retrying in 5 seconds...")
                    time.sleep(5)
                else:
                    raise RuntimeError(
                        "Could not reach docs.google.com. Check your Wi-Fi connection, "
                        "or download the Google Sheet as CSV (File -> Download -> CSV) "
                        f"and save it in this folder as '{LOCAL_CACHE_CSV}'."
                    )

    leads = []
    for _, row in df.iterrows():
        company = str(row.get("Company Name", "")).strip()
        if not company or company.lower() == "nan" or "get startup bundle" in company.lower():
            continue

        if any(skip in company.lower() for skip in SKIP_COMPANY_KEYWORDS):
            continue

        primary_em = str(row.get("Primary Working Email", "")) if pd.notna(row.get("Primary Working Email")) else ""
        secondary_em = str(row.get("Secondary / Alternate Emails", "")) if pd.notna(row.get("Secondary / Alternate Emails")) else ""
        address = str(row.get("Office Location / Address", "Delhi NCR")).strip()

        best_email, all_emails = pick_best_email_for_company(primary_em, secondary_em)
        if best_email:
            leads.append({
                "Company": company,
                "Best_Email": best_email,
                "All_Valid_Emails": all_emails,
                "Address": address
            })

    print(f"  [+] Loaded {len(leads)} Delhi NCR tech startups with verified working emails!")
    return leads


# ==========================================================
# 3. DELHI-TAILORED COLD EMAIL PITCH & SENDER (WITH RETRY)
# ==========================================================
def build_delhi_email(company_name):
    clean_company = company_name.split("|")[0].split(" - ")[0].strip()

    subject = "Software / Full-Stack & Backend Engineer (Delhi NCR) | Abhinav Kumar Jha (IIIT Manipur, 8.89 CGPA)"
    body = f"""Hi {clean_company} Hiring Team,

I am a Software Engineer from Delhi (currently in my final year of B.Tech CSE at IIIT Manipur with an 8.89 CGPA) reaching out regarding Full-Stack, Backend, or Software Engineering roles (Intern or Full-Time) at {clean_company} in Delhi NCR.

I have hands-on production experience shipping full-stack web applications, Node.js/Python backends, and autonomous AI systems:
- Backend Developer Intern @ IITian Craft: Spearheaded backend architecture using Node.js and Express.js for Tally Prime server synchronization, reducing processing time by 40%.
- Tech Intern @ Dairywala: Built and optimized full-stack software workflows across procurement, operations, and analytics.
- VoiceCode (TypeScript, Node.js, Gemini API): Engineered an autonomous AI coding assistant running a bounded plan-execute-verify-repair loop with 40+ unit/integration tests.
- Agent Ops & C++17 Multithreaded Engine: Architected a real-time agentic workflow platform (Next.js, React Flow, WebSockets) and a high-concurrency C++17 file processing engine.

Being from Delhi, I am readily available for in-office, hybrid (Delhi / Noida / Gurugram), or remote roles. I have attached my resume for your review and would love to discuss how I can contribute to your engineering team.

Best regards,
Abhinav Kumar Jha
Delhi, India | B.Tech CSE, IIIT Manipur (CGPA: 8.89)
Phone: +91-8287244296
GitHub: https://github.com/Abhinav4518/
LinkedIn: https://www.linkedin.com/in/abhinav-kumar-jha-912426330/
"""
    return subject, body

def send_delhi_email(to_email, company_name, dry_run=True):
    subject, body = build_delhi_email(company_name)

    if dry_run:
        print(f"  [DRY RUN] -> {to_email:<35} | {company_name}")
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

    for attempt in range(1, 4):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.send_message(msg)
            print(f"  [SENT] -> {to_email:<35} | {company_name}")
            return True
        except Exception as e:
            print(f"  [!] SMTP attempt {attempt}/3 failed for {to_email}: {e}")
            if attempt < 3:
                time.sleep(5)

    return False


# ==========================================================
# 4. ORCHESTRATOR WITH HISTORY TRACKING
# ==========================================================
def load_sent_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r") as f:
        return set(line.strip().lower() for line in f if line.strip())

def mark_as_sent(email_addr):
    with open(HISTORY_FILE, "a") as f:
        f.write(email_addr.strip().lower() + "\n")

def run_delhi_sheet_mailer(dry_run=True, max_emails_per_run=35):
    leads = load_delhi_startups_from_sheet()
    sent_history = load_sent_history()

    sent_count = 0
    logged_rows = []

    print(f"\n[*] Processing Delhi startups (Max emails this run: {max_emails_per_run})...")
    for item in leads:
        company = item["Company"]
        target_email = item["Best_Email"]

        if target_email in sent_history:
            continue

        if sent_count >= max_emails_per_run:
            break

        if send_delhi_email(target_email, company, dry_run=dry_run):
            sent_count += 1
            sent_history.add(target_email)
            if not dry_run:
                mark_as_sent(target_email)
                time.sleep(15)

            logged_rows.append({
                "Company": company,
                "Emailed_Address": target_email,
                "Alternate_Emails_In_Sheet": ", ".join(item["All_Valid_Emails"]),
                "Location": item["Address"],
                "Status": "Sent (Dry Run)" if dry_run else "Sent"
            })

    if logged_rows:
        out_df = pd.DataFrame(logged_rows)
        write_header = not os.path.exists(CSV_LOG_FILE)
        out_df.to_csv(CSV_LOG_FILE, mode="a", header=write_header, index=False)
        print(f"\n[+] Done! Processed {sent_count} Delhi startup emails. Log saved to '{CSV_LOG_FILE}'.")
    else:
        print("\n[-] All valid emails in this sheet have already been emailed!")

if __name__ == "__main__":
    # Set dry_run=False when ready to send live emails
    run_delhi_sheet_mailer(dry_run=False, max_emails_per_run=35)