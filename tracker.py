# tracker.py
import requests, json, re, os, smtplib, logging
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("tracker.log"),
        logging.StreamHandler()          # also prints to Actions console
    ]
)
log = logging.getLogger(__name__)

# ── config ───────────────────────────────────────────────────────────────────
REPOS = [
    ("SimplifyJobs", "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"),
    ("vanshb03",     "https://raw.githubusercontent.com/vanshb03/New-Grad-2027/main/README.md"),
    ("zapplyjobs",   "https://raw.githubusercontent.com/zapplyjobs/New-Grad-Software-Engineering-Jobs-2027/main/README.md"),
    ("ambicuity",    "https://raw.githubusercontent.com/ambicuity/New-Grad-Jobs/main/README.md"),
]
STATE_FILE  = "state.json"
LOG_FILE    = "tracker.log"
CLOSED_RE   = re.compile(r'🔒|no longer|closed|expired', re.IGNORECASE)

# ── helpers ──────────────────────────────────────────────────────────────────
def should_include_job(company, role):
    """
    Filters jobs based on role titles and company type.
    """
    company_lower = company.lower()
    role_lower = role.lower()

    # 1. Exclude defense contractors
    defense_keywords = [
        'lockheed', 'northrop', 'grumman', 'raytheon', 'rtx', 'bae systems', 
        'boeing', 'general dynamics', 'l3harris', 'anduril', 'leidos', 
        'caci', 'saic', 'booz allen'
    ]
    if any(dk in company_lower for dk in defense_keywords):
        return False

    # 2. Exclude roles with specific keywords
    exclude_keywords = [
        'clearance', 'security research', 'sre', 'site reliability', 
        'pre-sales', 'pre sales', 'broadcast'
    ]
    if any(ek in role_lower for ek in exclude_keywords):
        return False

    # 3. Include only target roles (Software, Full Stack, Frontend, ML/AI)
    include_patterns = [
        r'software\s*engineer', r'software\s*developer', r'swe',
        r'full\s*stack', r'frontend', r'front-end',
        r'ml\s*engineer', r'machine\s*learning', r'ai\s*engineer', r'artificial\s*intelligence'
    ]
    if not any(re.search(pat, role_lower) for pat in include_patterns):
        return False

    return True


def extract_urls_with_context(md):
    """
    Extracts job listings from both Markdown and HTML tables in the markdown content.
    Returns a dict of { url: {"company": ..., "role": ..., "location": ...} }
    """
    jobs = {}
    
    # 1. Parse HTML Tables (e.g. SimplifyJobs)
    soup = BeautifulSoup(md, "html.parser")
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not headers:
            first_row = table.find("tr")
            if first_row:
                headers = [cell.get_text(strip=True).lower() for cell in first_row.find_all(["th", "td"])]
        
        is_job_table = any("company" in h for h in headers) and \
                       any("role" in h or "position" in h or "title" in h or "job" in h for h in headers) and \
                       any("link" in h or "apply" in h or "application" in h or "url" in h for h in headers)
        
        if not is_job_table:
            continue
            
        last_company = ""
        for tr in table.find_all("tr"):
            if tr.find("th"):
                continue
            
            row_text = tr.get_text(" ", strip=True)
            if CLOSED_RE.search(row_text):
                continue
                
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
                
            company = tds[0].get_text(strip=True)
            company = re.sub(r'<[^>]+>', '', company)
            company = company.strip('*_ ↳\n\r\t')
            
            if not company or company == "":
                company = last_company
            else:
                last_company = company
                
            if not company or len(company) < 2:
                continue
                
            role = tds[1].get_text(strip=True)
            role = re.sub(r'<[^>]+>', '', role).strip('*_ \n\r\t')
            
            location = tds[2].get_text(strip=True)
            location = re.sub(r'<[^>]+>', '', location).strip('*_ \n\r\t')
            location = " / ".join([l.strip() for l in location.split("\n") if l.strip()])
            
            urls = []
            for a in tr.find_all("a"):
                href = a.get("href")
                if href:
                    urls.append(href)
                    
            for url in urls:
                if 'github.com' in url or 'shields.io' in url or 'img.shields' in url:
                    continue
                if not should_include_job(company, role):
                    continue
                jobs[url] = {
                    "company": company,
                    "role": role,
                    "location": location,
                    "found_at": datetime.now(timezone.utc).isoformat()
                }

    # 2. Parse Markdown Tables (e.g. vanshb03, zapplyjobs, ambicuity)
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
                
            if len(table_lines) < 3:
                continue
                
            headers = [c.strip().lower() for c in table_lines[0].split('|') if c.strip()]
            separator = [c.strip() for c in table_lines[1].split('|') if c.strip()]
            
            if not all(re.match(r'^[-:]+$', c) for c in separator):
                continue
                
            is_job_table = any("company" in h for h in headers) and \
                           any("role" in h or "position" in h or "title" in h or "job" in h for h in headers) and \
                           any("link" in h or "apply" in h or "application" in h or "url" in h for h in headers)
            
            if not is_job_table:
                continue
                
            last_company = ""
            for row_line in table_lines[2:]:
                if CLOSED_RE.search(row_line):
                    continue
                    
                cells = [c.strip() for c in row_line.split('|')]
                if len(cells) >= 2:
                    if cells[0] == "":
                        cells = cells[1:]
                    if cells[-1] == "":
                        cells = cells[:-1]
                        
                if len(cells) < 3:
                    continue
                    
                company = cells[0]
                company = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', company)
                company = re.sub(r'<[^>]+>', '', company)
                company = company.strip('*_ ↳\n\r\t')
                
                if not company or company == "":
                    company = last_company
                else:
                    last_company = company
                    
                if not company or len(company) < 2:
                    continue
                    
                role = cells[1]
                role = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', role)
                role = re.sub(r'<[^>]+>', '', role).strip('*_ \n\r\t')
                
                location = cells[2]
                location = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', location)
                location = re.sub(r'<[^>]+>', '', location).strip('*_ \n\r\t')
                
                urls = re.findall(r'https?://[^\s\)\]"\']+', row_line)
                for url in urls:
                    if 'github.com' in url or 'shields.io' in url or 'img.shields' in url:
                        continue
                    if not should_include_job(company, role):
                        continue
                    jobs[url] = {
                        "company": company,
                        "role": role,
                        "location": location,
                        "found_at": datetime.now(timezone.utc).isoformat()
                    }
        else:
            i += 1
            
    return jobs


def fetch_md(url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            return r.text
        except Exception as e:
            log.warning(f"Attempt {attempt} failed for {url}: {e}")
    return None


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        log.info("No state file found — first run, seeding baseline.")
        return {}
    except Exception as e:
        log.error(f"Failed to load state: {e}")
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        log.info("State saved.")
    except Exception as e:
        log.error(f"Failed to load state: {e}")


# ── notifications ─────────────────────────────────────────────────────────────
def send_email(new_jobs_by_repo):
    email_from = os.environ.get("EMAIL_FROM")
    email_to   = os.environ.get("EMAIL_TO")
    email_pass = os.environ.get("EMAIL_PASS")
    if not email_from or not email_to or not email_pass:
        log.info("Email notification skipped: EMAIL_FROM, EMAIL_TO, or EMAIL_PASS not set.")
        return

    total = sum(len(v) for v in new_jobs_by_repo.values())
    log.info(f"Sending email with {total} new jobs.")

    html_parts = []
    for repo, jobs in new_jobs_by_repo.items():
        html_parts.append(f"<h3 style='margin-bottom:6px'>{repo} — {len(jobs)} new</h3><ul>")
        for url, meta in jobs.items():
            html_parts.append(
                f"<li><b>{meta['company']}</b> — {meta['role']}"
                f"{'  📍 ' + meta['location'] if meta['location'] else ''}"
                f"<br><a href='{url}'>{url}</a></li>"
            )
        html_parts.append("</ul>")

    html_body = f"""
    <html><body>
      <p style='color:#555'>Checked at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
      {''.join(html_parts)}
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Job Alert] {total} new listing{'s' if total != 1 else ''}"
    msg["From"]    = email_from
    msg["To"]      = email_to
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(email_from, email_pass)
            s.send_message(msg)
        log.info("Email sent successfully.")
    except Exception as e:
        log.error(f"Email failed: {e}")


def send_telegram(new_jobs_by_repo):
    token   = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    total = sum(len(v) for v in new_jobs_by_repo.values())
    lines = [f"🎯 *{total} new job listing{'s' if total != 1 else ''}*\n"]

    for repo, jobs in new_jobs_by_repo.items():
        lines.append(f"*{repo}* ({len(jobs)} new)")
        for url, meta in jobs.items():
            loc = f" — {meta['location']}" if meta['location'] else ""
            lines.append(f"• {meta['company']} | {meta['role']}{loc}\n  {url}")
        lines.append("")

    # Telegram has a 4096 char limit per message — chunk if needed
    text = "\n".join(lines)
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]

    for chunk in chunks:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                timeout=10
            )
            log.info("Telegram message sent.")
        except Exception as e:
            log.error(f"Telegram failed: {e}")


def send_ntfy(new_jobs_by_repo):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return

    total = sum(len(v) for v in new_jobs_by_repo.values())
    
    # Create a rich markdown body listing the new jobs
    lines = [f"🎯 **{total} new job listing{'s' if total != 1 else ''} found!**\n"]
    
    count = 0
    for repo, jobs in new_jobs_by_repo.items():
        lines.append(f"**{repo}** ({len(jobs)} new):")
        for url, meta in jobs.items():
            count += 1
            if count <= 15:  # limit to first 15 to avoid massive notification body
                loc = f" — {meta['location']}" if meta['location'] else ""
                lines.append(f"• [{meta['company']}]({url}) | {meta['role']}{loc}")
        lines.append("")
        
    if total > 15:
        lines.append(f"*...and {total - 15} more jobs. Check your GitHub repository for the full list.*")
        
    body = "\n".join(lines)
    
    # Set the click URL to the GitHub repository page if running in Actions, or fallback to the first job
    repo_slug = os.environ.get("GITHUB_REPOSITORY")
    click_url = f"https://github.com/{repo_slug}" if repo_slug else ""
    if not click_url and new_jobs_by_repo:
        first_repo = next(iter(new_jobs_by_repo))
        click_url = next(iter(new_jobs_by_repo[first_repo]))

    try:
        headers = {
            "Title": f"{total} New Job Listing{'s' if total != 1 else ''}",
            "Priority": "high",
            "Tags": "briefcase",
            "X-Markdown": "yes"
        }
        if click_url:
            headers["Click"] = click_url
            
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=body.encode("utf-8"),
            headers=headers,
            timeout=10
        )
        log.info("ntfy notification sent.")
    except Exception as e:
        log.error(f"ntfy failed: {e}")


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("=== Job tracker run started ===")
    state = load_state()
    is_first_run = len(state) == 0
    new_jobs_by_repo = {}

    for name, url in REPOS:
        log.info(f"Fetching {name}...")
        md = fetch_md(url)
        if md is None:
            log.error(f"Skipping {name} — all fetch attempts failed.")
            continue

        current_jobs = extract_urls_with_context(md)
        log.info(f"{name}: found {len(current_jobs)} open URLs total.")

        previous_urls = set(state.get(name, {}).keys())
        current_urls  = set(current_jobs.keys())
        new_urls      = current_urls - previous_urls

        log.info(f"{name}: {len(new_urls)} new URL(s) since last run.")

        if new_urls and not is_first_run:
            new_jobs_by_repo[name] = {url: current_jobs[url] for url in new_urls}

        state[name] = current_jobs   # always update to current

    if is_first_run:
        log.info("First run — baseline seeded, no notifications sent.")
    elif new_jobs_by_repo:
        send_email(new_jobs_by_repo)
        send_telegram(new_jobs_by_repo)   # no-ops if env vars not set
        send_ntfy(new_jobs_by_repo)       # no-ops if env vars not set
    else:
        log.info("No new jobs found this run.")

    save_state(state)
    log.info("=== Run complete ===\n")


if __name__ == "__main__":
    main()
