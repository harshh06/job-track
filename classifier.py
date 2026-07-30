# classifier.py — Job classification: US filter, experience filter, new grad 2027 detection
import requests, re, time, logging
from datetime import datetime, timezone
from collections import defaultdict
from bs4 import BeautifulSoup

try:
    import lxml  # noqa: F401
    HTML_PARSER = 'lxml'
except ImportError:
    HTML_PARSER = 'html.parser'

log = logging.getLogger(__name__)

# ── US Location Detection ────────────────────────────────────────────────────

US_STATES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'DC',
}

US_STATE_NAMES = [
    'alabama', 'alaska', 'arizona', 'arkansas', 'california', 'colorado',
    'connecticut', 'delaware', 'florida', 'georgia', 'hawaii', 'idaho',
    'illinois', 'indiana', 'iowa', 'kansas', 'kentucky', 'louisiana',
    'maine', 'maryland', 'massachusetts', 'michigan', 'minnesota',
    'mississippi', 'missouri', 'montana', 'nebraska', 'nevada',
    'new hampshire', 'new jersey', 'new mexico', 'new york',
    'north carolina', 'north dakota', 'ohio', 'oklahoma', 'oregon',
    'pennsylvania', 'rhode island', 'south carolina', 'south dakota',
    'tennessee', 'texas', 'utah', 'vermont', 'virginia', 'washington',
    'west virginia', 'wisconsin', 'wyoming', 'district of columbia',
]

US_CITIES = [
    'new york', 'nyc', 'los angeles', 'chicago', 'houston', 'phoenix',
    'philadelphia', 'san antonio', 'san diego', 'dallas', 'san jose',
    'austin', 'san francisco', 'seattle', 'denver', 'boston',
    'nashville', 'portland', 'las vegas', 'memphis', 'louisville',
    'baltimore', 'milwaukee', 'albuquerque', 'tucson', 'fresno',
    'sacramento', 'mesa', 'atlanta', 'pittsburgh', 'raleigh',
    'miami', 'minneapolis', 'tampa', 'orlando', 'st. louis',
    'cleveland', 'charlotte', 'detroit', 'indianapolis',
    'columbus', 'fort worth', 'jacksonville', 'sf', 'la', 'dc',
    'silicon valley', 'bay area', 'palo alto', 'mountain view',
    'sunnyvale', 'cupertino', 'menlo park', 'redwood city',
    'santa clara', 'irvine', 'bellevue', 'redmond', 'kirkland',
    'cambridge', 'somerville', 'brooklyn', 'manhattan',
    'san mateo', 'burlingame', 'south san francisco',
    'plano', 'irving', 'frisco', 'richardson',
    'durham', 'chapel hill', 'research triangle',
    'herndon', 'arlington', 'mclean', 'tysons',
    'alpharetta', 'sandy springs', 'scottsdale', 'tempe',
    'ann arbor', 'boulder', 'salt lake city', 'provo',
    'hoboken', 'jersey city', 'stamford', 'greenwich',
    'culver city', 'santa monica', 'pasadena', 'burbank',
    'san bruno', 'foster city', 'fremont', 'milpitas',
    'reston', 'fairfax', 'leesburg', 'ashburn',
    'des moines', 'omaha', 'kansas city', 'st louis',
    'rochester', 'ithaca', 'troy', 'albany',
    'madison', 'champaign', 'urbana',
    'hopewell junction', 'poughkeepsie',
]

NON_US_KEYWORDS = [
    # Canada
    'canada', 'canadian', 'toronto', 'vancouver', 'montreal', 'ottawa',
    'ontario', 'british columbia', 'alberta', 'manitoba', 'quebec',
    'nova scotia', 'saskatchewan', 'new brunswick', 'calgary', 'edmonton',
    'winnipeg', 'kitchener', 'waterloo, on', ', bc, ca', ', on, ca',
    ', ab, ca', ', mb, ca', ', qc, ca', ', ns, ca',
    # UK & Ireland
    'united kingdom', ', uk', 'london, uk', 'edinburgh', 'manchester, uk',
    'cambridge, uk', 'oxford, uk', 'bristol, uk', 'glasgow', 'ireland', 'dublin',
    # India
    'india', 'bangalore', 'bengaluru', 'hyderabad', 'mumbai', 'pune',
    'chennai', 'delhi', 'noida', 'gurgaon', 'gurugram', 'kolkata',
    # Europe
    'germany', 'berlin', 'munich', 'münchen', 'frankfurt', 'hamburg',
    'france', 'paris', 'netherlands', 'amsterdam', 'poland', 'warsaw',
    'krakow', 'kraków', 'czech', 'prague', 'spain', 'madrid', 'barcelona',
    'italy', 'milan', 'rome', 'sweden', 'stockholm', 'denmark', 'copenhagen',
    'finland', 'helsinki', 'norway', 'oslo', 'switzerland', 'zurich', 'zürich',
    'belgium', 'brussels', 'austria', 'vienna', 'portugal', 'lisbon',
    'romania', 'bucharest', 'ukraine', 'kyiv',
    # Asia-Pacific
    'israel', 'tel aviv', 'singapore', 'japan', 'tokyo',
    'australia', 'sydney', 'melbourne', 'brisbane',
    'china', 'beijing', 'shanghai', 'shenzhen',
    'korea', 'seoul', 'taiwan', 'taipei',
    'philippines', 'manila', 'vietnam', 'ho chi minh',
    'thailand', 'bangkok', 'indonesia', 'jakarta',
    # Latin America
    'brazil', 'são paulo', 'mexico city', 'argentina', 'buenos aires',
    'chile', 'santiago', 'colombia', 'bogotá', 'costa rica',
]

# Domains known to be non-US indeed variants
NON_US_DOMAINS = {'in.indeed.com', 'ca.indeed.com', 'uk.indeed.com',
                  'au.indeed.com', 'de.indeed.com', 'fr.indeed.com'}

# Build a compiled regex for US state codes, matching ", ST" patterns
_STATE_CODE_RE = re.compile(
    r'(?:,\s*|(?:^|\s))(' + '|'.join(US_STATES) + r')(?:\s|$|,|\)|;)',
)
# Detect Canadian province + country code pattern (e.g., "BC, CA" or "ON, CA")
_CANADA_CA_RE = re.compile(r'(?:BC|ON|AB|MB|QC|NS|SK|NB|PE|NL),?\s*CA\b')


def is_us_based(location_text, page_text=None):
    """
    Determine if a job is US-based from its location string.
    Returns True (US), False (non-US), or None (ambiguous).
    Ambiguous is treated as US downstream (permissive — won't miss real ones).
    """
    if not location_text:
        return None

    loc_lower = location_text.lower()

    # ── Non-US indicators ──
    has_non_us = any(kw in loc_lower for kw in NON_US_KEYWORDS)

    # ── US indicators ──
    has_us = False

    # Explicit US mentions
    if re.search(r'\b(?:united\s+states|usa|u\.s\.a?)\b', loc_lower):
        has_us = True

    # "Remote" without non-US context → US (these repos are US-focused)
    if re.search(r'\bremote\b', loc_lower) and not has_non_us:
        has_us = True

    # US state names (full)
    if any(f' {state}' in f' {loc_lower}' or loc_lower.startswith(state)
           for state in US_STATE_NAMES):
        has_us = True

    # US city names
    if any(city in loc_lower for city in US_CITIES):
        has_us = True

    # US state codes — but exclude Canadian "Province, CA" pattern
    if _STATE_CODE_RE.search(location_text):
        # If the match is "CA" and there's a Canadian province pattern, skip it
        if 'CA' in location_text and _CANADA_CA_RE.search(location_text):
            # There's a Canadian pattern, but check if there's ALSO a real US state
            non_ca_states = US_STATES - {'CA', 'IN'}  # IN is also ambiguous
            if any(re.search(r'(?:,\s*|(?:^|\s))' + s + r'(?:\s|$|,|\)|;)',
                             location_text) for s in non_ca_states):
                has_us = True
        else:
            has_us = True

    # Also check page text if available and still ambiguous
    if page_text and not has_us and not has_non_us:
        page_lower = page_text[:3000].lower()  # Only check first 3K chars
        if re.search(r'\bunited\s+states\b', page_lower):
            has_us = True
        elif any(kw in page_lower for kw in NON_US_KEYWORDS[:30]):
            has_non_us = True

    # ── Decision (permissive: if any US location, keep it) ──
    if has_us:
        return True
    elif has_non_us:
        return False
    return None  # Ambiguous → treated as US downstream


# ── Experience Detection ─────────────────────────────────────────────────────

_EXP_PATTERNS = [
    # "5+ years of experience", "7 years experience"
    re.compile(r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:professional\s+)?'
               r'(?:relevant\s+)?(?:related\s+)?(?:work\s+)?(?:industry\s+)?'
               r'(?:hands[- ]on\s+)?experience', re.I),
    # "minimum 5 years", "at least 3 years"
    re.compile(r'(?:minimum|at\s+least|over|more\s+than)\s+(\d+)\s*'
               r'(?:\+\s*)?(?:years?|yrs?)', re.I),
    # "3-5 years of experience", "3 to 5 years"
    re.compile(r'(\d+)\s*[-–to]+\s*(\d+)\s*(?:years?|yrs?)\s*'
               r'(?:of\s+)?(?:professional\s+)?(?:relevant\s+)?'
               r'(?:work\s+)?experience', re.I),
]


def extract_max_experience(text):
    """
    Extract the maximum years of experience required from job page text.
    Returns int or None if indeterminate.
    """
    if not text:
        return None

    max_years = None
    for pattern in _EXP_PATTERNS:
        for match in pattern.finditer(text):
            for g in match.groups():
                if g is not None:
                    try:
                        y = int(g)
                        if 0 <= y <= 30:  # Sanity check
                            if max_years is None or y > max_years:
                                max_years = y
                    except ValueError:
                        pass
    return max_years


# ── New Grad 2027 Detection ──────────────────────────────────────────────────

# --- Strong signals ---
_STRONG_PATTERNS = [
    # Explicit "2027"
    re.compile(r'\b2027\b'),
    # "Class of 2027"
    re.compile(r'class\s+of\s+2027', re.I),
    # "New grad" / "new graduate" / "recent graduate" / "university graduate"
    re.compile(r'\bnew\s*grad(?:uate)?\b', re.I),
    re.compile(r'\brecent\s*grad(?:uate)?\b', re.I),
    re.compile(r'\buniversity\s*grad(?:uate)?\b', re.I),
    re.compile(r'\bcollege\s*grad(?:uate)?\b', re.I),
    # Start date referencing 2027
    re.compile(r'start(?:ing)?\s+(?:date\s*[:.]?\s*)?(?:in\s+)?'
               r'(?:early|late)?\s*(?:summer|fall|winter|spring|'
               r'january|february|march|april|may|june|july|august|'
               r'september|october|november|december)\s*'
               r'(?:of\s+)?2027', re.I),
]

# --- Medium signals ---
_MEDIUM_PATTERNS = [
    # Entry-level markers
    re.compile(r'\bentry[\s-]*level\b', re.I),
    re.compile(r'\bjunior\b(?!\s+(?:partner|vp|director))', re.I),
    re.compile(r'\bassociate\b(?!\s+(?:director|vp|partner|manager|principal))', re.I),
    re.compile(r'\b(?:level|lvl)\s*(?:1|i|one)\b', re.I),
    re.compile(r'\bengineer\s*(?:1|i(?:\b|,))\b', re.I),
    re.compile(r'\b(?:swe|sde|se)\s*(?:1|i(?:\b|,))\b', re.I),
    # Graduation references (on page text)
    re.compile(r'\bgraduat(?:ing|ion)\b', re.I),
    re.compile(r'\brecent(?:ly)?\s+(?:earned|completed|received)\s+'
               r'(?:a\s+)?(?:bachelor|master|degree|b\.?s\.?|b\.?a\.?)', re.I),
    re.compile(r'\bcompleting\s+(?:a\s+)?(?:bachelor|master|degree)', re.I),
    # Relative time (current date is mid-2026, so "next summer/spring" = 2027)
    re.compile(r'\bnext\s+(?:spring|summer|fall|winter)\b', re.I),
    re.compile(r'\b(?:starting|beginning|commencing)\s+(?:next|this)\s+'
               r'(?:year|spring|summer|fall)\b', re.I),
    re.compile(r'\bgraduat(?:ing|e)\s+(?:in\s+)?(?:next|this)\s+'
               r'(?:year|spring|summer|fall)\b', re.I),
    # Low experience requirement
    re.compile(r'\b0\s*[-–to]+\s*[12]\s*(?:years?|yrs?)\b', re.I),
    re.compile(r'\bno\s+(?:prior\s+)?(?:professional\s+)?experience\s+'
               r'(?:required|necessary|needed)\b', re.I),
]


def classify_new_grad(role_text, page_text):
    """
    Classify whether a job is a new grad 2027 position.
    Returns: 'new_grad_2027', 'likely_new_grad', or 'general'.

    Uses a score-based system: multiple signals → higher confidence.
    """
    role_lower = (role_text or '').lower()
    page_lower = (page_text or '').lower()
    combined = f"{role_lower} {page_lower}"

    strong = sum(1 for p in _STRONG_PATTERNS if p.search(combined))
    medium = sum(1 for p in _MEDIUM_PATTERNS if p.search(combined))

    # ── Classification thresholds ──
    # 2+ strong, or 1 strong + 1 medium  →  new_grad_2027
    # 1 strong, or 2+ medium             →  likely_new_grad
    # Otherwise                           →  general
    if strong >= 2 or (strong >= 1 and medium >= 1):
        return 'new_grad_2027'
    elif strong >= 1 or medium >= 1:
        return 'likely_new_grad'
    return 'general'


# ── Page Scraper ─────────────────────────────────────────────────────────────

_domain_last_request = defaultdict(float)
_RATE_LIMIT_SEC = 1.0

SKIP_DOMAINS = {'simplify.jobs', 'github.com', 'shields.io', 'img.shields.io'}

_HTTP_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/126.0.0.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}


def _get_domain(url):
    m = re.search(r'https?://([^/]+)', url)
    return m.group(1) if m else ''


def _rate_limit(domain):
    now = time.time()
    wait = _RATE_LIMIT_SEC - (now - _domain_last_request[domain])
    if wait > 0:
        time.sleep(wait)
    _domain_last_request[domain] = time.time()


def scrape_job_page(url, retries=2):
    """
    Fetch a job posting page and return its text content.
    Returns None on failure or if the domain should be skipped.
    """
    domain = _get_domain(url)
    if any(skip in domain for skip in SKIP_DOMAINS):
        return None
    if domain in NON_US_DOMAINS:
        return None  # Known non-US Indeed variant

    _rate_limit(domain)

    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=_HTTP_HEADERS, timeout=10,
                             allow_redirects=True)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, HTML_PARSER)
            for tag in soup(['script', 'style', 'nav', 'footer', 'noscript',
                             'svg', 'img', 'link', 'meta']):
                tag.decompose()

            text = soup.get_text(separator=' ', strip=True)

            # Also grab meta description for extra context
            soup2 = BeautifulSoup(r.text, HTML_PARSER)
            meta = soup2.find('meta', attrs={'name': 'description'})
            meta_desc = meta.get('content', '') if meta else ''

            return f"{meta_desc} {text}"

        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                log.debug(f"Failed to scrape {url}: {e}")
    return None


# ── URL-level non-US check ───────────────────────────────────────────────────

def _url_is_non_us(url):
    """Quick check: is this URL on a known non-US domain?"""
    domain = _get_domain(url)
    return domain in NON_US_DOMAINS


# ── Main Classification Entry Point ──────────────────────────────────────────

def classify_job(url, meta):
    """
    Classify a single job.  Returns a dict of classification fields:
        us_based (bool), experience_max (int|None),
        grad_class (str), scraped_at (str)
    """
    location = meta.get('location', '')
    role = meta.get('role', '')

    # Quick non-US check from URL domain
    if _url_is_non_us(url):
        return {
            'us_based': False,
            'experience_max': None,
            'grad_class': 'general',
            'scraped_at': datetime.now(timezone.utc).isoformat(),
        }

    # Step 1: Location check (fast, no HTTP)
    us_check = is_us_based(location)

    # Step 2: Scrape the page
    page_text = scrape_job_page(url)

    # If location was ambiguous, try page text
    if page_text and us_check is None:
        us_check = is_us_based(location, page_text)

    # Step 3: Experience
    exp_max = extract_max_experience(page_text) if page_text else None

    # Step 4: New grad classification
    grad_class = classify_new_grad(role, page_text)

    return {
        'us_based': us_check if us_check is not None else True,  # permissive default
        'experience_max': exp_max,
        'grad_class': grad_class,
        'scraped_at': datetime.now(timezone.utc).isoformat(),
    }


def classify_jobs(state):
    """
    Classify all unscraped jobs in the state dict (modifies in-place).
    Returns the count of newly classified jobs.
    """
    total_unscraped = sum(
        1 for jobs in state.values()
        for meta in jobs.values()
        if 'scraped_at' not in meta
    )
    if total_unscraped == 0:
        log.info("All jobs already classified.")
        return 0

    log.info(f"Classifying {total_unscraped} unscraped jobs...")
    count = 0

    for repo, jobs in state.items():
        for url, meta in jobs.items():
            if 'scraped_at' in meta:
                continue

            count += 1
            if count % 100 == 0:
                log.info(f"  Progress: {count}/{total_unscraped} classified...")

            result = classify_job(url, meta)
            meta.update(result)

    # Summary stats
    all_meta = [m for jobs in state.values() for m in jobs.values()]
    us_count = sum(1 for m in all_meta if m.get('us_based', True))
    non_us = sum(1 for m in all_meta if not m.get('us_based', True))
    ng27 = sum(1 for m in all_meta if m.get('grad_class') == 'new_grad_2027')
    likely = sum(1 for m in all_meta if m.get('grad_class') == 'likely_new_grad')
    high_exp = sum(1 for m in all_meta
                   if (m.get('experience_max') or 0) > 5)

    log.info(f"Classification complete: {count} jobs classified.")
    log.info(f"  US-based: {us_count} | Non-US: {non_us}")
    log.info(f"  New Grad 2027: {ng27} | Likely New Grad: {likely}")
    log.info(f"  High experience (>5yr): {high_exp}")

    return count
