# 🤖 Autonomous Job & Startup Outreach Bot

An automated Python-based pipeline that scrapes software engineering and backend job listings, discovers verified recruiter/founder emails, filters out irrelevant positions, and sends personalized cold emails with resume attachments via Gmail SMTP.

## 🚀 Features

- **Multi-Platform Job Scraper**: Scrapes relevant software roles across Indeed and LinkedIn using `jobspy`.
- **YC Startup & Hacker News Outreach**: Fetches newly funded YC cohorts and parses Hacker News "Who is Hiring" threads to extract direct founder/CTO emails.
- **Strict Domain & Mailbox Verification**: Uses cached DNS MX checks and strict whitelisting to eliminate bounced emails and avoid locked Google Groups.
- **Anti-Rate-Limit Delays**: Built-in cooldowns and anti-429 rotation to keep scraper IPs safe from blocks.
- **Duplicate Prevention**: Tracks emailed companies/addresses locally (`emailed_addresses_history.txt`) to ensure you never email the same company twice on future runs.
- **Email-Only Execution**: Focuses on direct inbox delivery with automated PDF resume attachments (`AbhinavJhaIIITManipurResume.pdf`).

---

## 🛠️ Tech Stack

- **Language**: Python 3.10+
- **Libraries**: `pandas`, `requests`, `beautifulsoup4`, `dnspython`, `python-dotenv`, `jobspy`
- **Mailing Protocol**: Gmail SMTP (SSL via App Password)

---

## ⚙️ Setup & Installation

### 1. Clone the Repository
```bash
git clone [https://github.com/Abhinav4518/Job-hunter.git](https://github.com/Abhinav4518/Job-hunter.git)
cd Job-hunter
