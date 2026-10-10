import asyncio
import hashlib
import json
import random
import re
import urllib.parse
from typing import Any, List, Optional, Tuple
from playwright.async_api import Page
from src.core.database import ApplicationStateStore
from src.core.llm_client import GeminiFlashClient
from src.core.schemas import ApplicationStatus, JobPosting
from src.mcp.tools.browser import StealthBrowserTool


DEFAULT_BAY_AREA_CITIES: List[str] = [
    "San Francisco",
    "Bay Area",
    "San Jose",
    "Sunnyvale",
    "Mountain View",
    "Palo Alto",
    "Santa Clara",
    "Redwood City",
    "Menlo Park",
    "Cupertino",
    "Foster City",
    "San Mateo",
    "Fremont",
    "Oakland",
    "Berkeley",
    "Pleasanton",
    "San Ramon",
]

KNOWN_CA_INDICATORS: List[str] = [
    "california",
    "bay area",
    "san francisco",
    "san jose",
    "sunnyvale",
    "mountain view",
    "palo alto",
    "santa clara",
    "redwood city",
    "menlo park",
    "cupertino",
    "foster city",
    "san mateo",
    "fremont",
    "oakland",
    "berkeley",
    "pleasanton",
    "san ramon",
    "los angeles",
    "san diego",
    "irvine",
    "sacramento",
    "orange county",
    "pasadena",
    "burbank",
    "santa monica",
    "long beach",
    "anaheim",
    "santa barbara",
    "fresno",
    "bakersfield",
    "riverside",
    "stockton",
    "chula vista",
    "newport beach",
    "carlsbad",
    "torrance",
    "el segundo",
    "ontario",
    "glendale",
    "santa ana",
]


class DiscoveryAgent:
    DEFAULT_BAY_AREA_CITIES = DEFAULT_BAY_AREA_CITIES
    KNOWN_CA_INDICATORS = KNOWN_CA_INDICATORS

    def __init__(
        self,
        state_store: Optional[ApplicationStateStore] = None,
        browser_tool: Optional[StealthBrowserTool] = None,
        llm_client: Optional[GeminiFlashClient] = None,
        pacing: Optional[Any] = None,
        settings: Optional[dict] = None,
    ):
        self.db = state_store
        self.browser = browser_tool
        self.llm = llm_client
        self.pacing = pacing
        self.settings = settings

    @staticmethod
    def get_location_policy(settings: Optional[dict] = None) -> Tuple[str, List[str]]:
        """
        Extracts the California location policy and bay area cities list from settings.
        Supports new structured `location` section as well as legacy `exclude_california`.

        Returns:
            Tuple[str, List[str]]: (california_policy, bay_area_cities)
        """
        if not settings:
            return "bay_area_only", list(DEFAULT_BAY_AREA_CITIES)

        loc_cfg = settings.get("location") or settings.get("job_search", {}).get("location") or {}

        policy = loc_cfg.get("california_policy")
        cities = loc_cfg.get("bay_area_cities") or DEFAULT_BAY_AREA_CITIES

        if not policy:
            legacy_exclude = None
            if "exclude_california" in settings:
                legacy_exclude = settings["exclude_california"]
            elif "exclude_california" in settings.get("job_search", {}):
                legacy_exclude = settings["job_search"]["exclude_california"]

            if legacy_exclude is True:
                policy = "exclude_ca"
            elif legacy_exclude is False:
                policy = "all_ca"
            else:
                policy = "bay_area_only"

        policy = str(policy).lower().strip()
        if policy not in ["exclude_ca", "bay_area_only", "all_ca"]:
            policy = "bay_area_only"

        return policy, list(cities)

    @staticmethod
    def is_california_location(location_str: Optional[str]) -> bool:
        """
        Identifies whether a location string represents California
        (mentions CA, California, Bay Area, or known CA cities/regions).
        """
        if not location_str or not isinstance(location_str, str):
            return False

        text = location_str.lower().strip()

        # Direct mentions of California or Bay Area
        if "california" in text or "bay area" in text:
            return True

        # State abbreviation with boundary check (avoids Cambridge, Canada, Chicago, etc.)
        if re.search(r'(?:\bca\b)', text, re.IGNORECASE):
            return True

        # Known California cities and regions
        for indicator in KNOWN_CA_INDICATORS:
            if indicator in text:
                return True

        return False

    @staticmethod
    def evaluate_location_policy(
        location_str: Optional[str],
        settings: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """
        Evaluates whether a location string is acceptable under the configured California policy.

        Policies:
        - "exclude_ca": Exclude all California locations completely
        - "bay_area_only": If California, ONLY accept San Francisco Bay Area locations
        - "all_ca": Accept all California locations

        Returns:
            Tuple[bool, str]: (is_accepted, reason)
        """
        if not location_str or not isinstance(location_str, str):
            return True, "No location text specified"

        policy, bay_area_cities = DiscoveryAgent.get_location_policy(settings)
        is_ca = DiscoveryAgent.is_california_location(location_str)

        # Non-California roles (e.g., Seattle, WA, New York, NY, Remote) remain accepted under all modes
        if not is_ca:
            return True, "Non-California location"

        # California location evaluation
        if policy == "exclude_ca":
            return False, "Excluded Region: California location"

        if policy == "bay_area_only":
            loc_lower = location_str.lower()
            for city in bay_area_cities:
                if city.lower() in loc_lower:
                    return True, f"Accepted: Bay Area location ({city})"
            return False, "Non-Bay Area California location"

        if policy == "all_ca":
            return True, "Accepted: California location"

        return True, "Location accepted"

    @staticmethod
    def is_location_allowed(
        location_str: Optional[str],
        settings: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Alias for evaluate_location_policy."""
        return DiscoveryAgent.evaluate_location_policy(location_str, settings)

    async def simulate_reading_delay(self, pacing: Optional[Any] = None) -> float:
        """Simulates human reading delay before opening Easy Apply modal (12 to 28 seconds)."""
        engine = pacing or self.pacing
        if engine and hasattr(engine, "get_reading_delay"):
            delay = engine.get_reading_delay()
        else:
            delay = round(random.uniform(12.0, 28.0), 2)
        print(f"  [Pacing] 📖 Simulating human reading pause ({delay:.1f}s)...")
        await asyncio.sleep(delay)
        return delay

    async def detect_security_checkpoint(self, page: Page) -> Tuple[bool, str]:
        """
        Emergency Circuit Breaker: Inspects the active page URL and DOM for LinkedIn
        security checkpoints, challenges, Arkose Labs verification, or CAPTCHA prompts.
        Returns (True, reason) if a checkpoint is detected, (False, "") otherwise.
        """
        current_url = (page.url or "").lower()

        # 1. URL pattern check
        checkpoint_url_patterns = [
            "/checkpoint/",
            "/challenge/",
            "/uas/consumer-captcha",
            "checkpoint/challenge",
            "linkedin.com/checkpoint",
        ]
        for pattern in checkpoint_url_patterns:
            if pattern in current_url:
                return True, f"Security challenge URL detected ({pattern})"

        # 2. DOM Selectors, Iframes, & Text
        try:
            dom_check = await page.evaluate("""() => {
                // Check for Arkose Labs / CAPTCHA iframes
                const iframes = Array.from(document.querySelectorAll('iframe'));
                for (const frame of iframes) {
                    const src = (frame.src || '').toLowerCase();
                    const name = (frame.name || '').toLowerCase();
                    const id = (frame.id || '').toLowerCase();
                    if (src.includes('arkoselabs') || src.includes('funcaptcha') || 
                        src.includes('checkpoint') || src.includes('challenge') ||
                        name.includes('captcha') || id.includes('captcha')) {
                        return { detected: true, reason: 'Arkose Labs / CAPTCHA iframe found in DOM' };
                    }
                }

                // Check for specific CAPTCHA containers
                const captchaContainers = document.querySelectorAll(
                    '#captcha-internal, .captcha-container, input#captcha-user-answer, div[data-testid="captcha"], #security-challenge'
                );
                if (captchaContainers.length > 0) {
                    return { detected: true, reason: 'CAPTCHA container element found in DOM' };
                }

                // Check page text for security verification keywords
                const bodyText = (document.body ? document.body.innerText : '').toLowerCase();
                const suspiciousPhrases = [
                    'quick security check',
                    "verify it's you",
                    "verify it’s you",
                    'security verification',
                    'please solve this puzzle',
                    "let's do a quick security check",
                    "let’s do a quick security check"
                ];
                for (const phrase of suspiciousPhrases) {
                    if (bodyText.includes(phrase)) {
                        return { detected: true, reason: `Security challenge phrase detected: "${phrase}"` };
                    }
                }

                return { detected: false, reason: '' };
            }""")

            if dom_check and dom_check.get("detected"):
                return True, dom_check.get("reason", "Security verification detected in DOM")
        except Exception:
            pass

        return False, ""

    def _generate_job_id(self, url: str) -> str:
        return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]

    def build_search_url(self, settings: dict) -> str:
        """Constructs a Boolean-targeted, recency-sorted LinkedIn Easy Apply search URL."""
        job_cfg = settings.get("job_search", {})
        titles = job_cfg.get("target_titles", ["Staff Software Engineer", "Senior Software Engineer"])
        location = job_cfg.get("target_location", "United States")
        recent_first = job_cfg.get("sort_by_recent_first", True)
        time_range = job_cfg.get("time_posted_range", "r86400")

        boolean_query = " OR ".join([f'"{t}"' for t in titles])
        params = {
            "keywords": boolean_query,
            "location": location,
            "f_AL": "true",  # Easy Apply only
            "sortBy": "DD" if recent_first else "R"
        }
        if time_range:
            params["f_TPR"] = time_range

        return f"https://www.linkedin.com/jobs/search/?{urllib.parse.urlencode(params)}"

    def check_company_size(self, raw_text: str, min_employees: int = 5000) -> Tuple[bool, str]:
        """
        Validates company employee count against min_employees threshold (default: >= 5000).
        Strictly enforces enterprise size requirement and rejects sub-5000 or unverified companies.
        """
        import re
        text = raw_text.lower()
        # Normalize hyphens and multiple spaces
        text = re.sub(r'\s*-\s*', '-', text)

        # 1. Immediate rejection for explicit sub-5000 size tiers
        small_size_signatures = [
            "1-10 employees", "2-10 employees", "11-50 employees", 
            "51-200 employees", "201-500 employees", 
            "501-1,000 employees", "501-1000 employees",
            "1,001-5,000 employees", "1001-5000 employees", "1,000-5,000 employees",
            "1k-5k employees", "<1,000 employees", "<500 employees"
        ]
        for sig in small_size_signatures:
            if sig in text:
                return False, f"Company size < 5,000 employees ({sig})"

        # 2. Acceptance for verified >= 5000 size tiers
        large_size_signatures = [
            "10,001+ employees", "10001+ employees", "10,000+ employees", "10000+ employees",
            "5,001-10,000 employees", "5001-10000 employees", "5,000-10,000 employees",
            "5,000+ employees", "5000+ employees", "10k+ employees", "5k-10k employees"
        ]
        for sig in large_size_signatures:
            if sig in text:
                return True, f"Verified enterprise company size ({sig})"

        # 3. Numeric employee count regex fallback (e.g. "7,500 employees", "25,000 employees")
        matches = re.findall(r'([\d,]+)(?:\+|-[\d,]+)?\s*employees', text)
        for m in matches:
            try:
                num = int(m.replace(",", ""))
                if num >= min_employees:
                    return True, f"Verified employee count >= {min_employees} ({num:,} employees)"
                else:
                    return False, f"Company size too small ({num:,} < {min_employees} employees)"
            except ValueError:
                pass

        # 4. Strict filter enforcement: if size cannot be verified >= 5000, reject
        return False, f"Unverified company size (requires >= {min_employees} employees)"

    async def evaluate_job_eligibility(self, page: Page, settings: dict) -> Tuple[bool, str]:
        """
        Evaluates active job posting against configured safety & boundary filters:
        - Exclude California / Bay Area if configured
        - Exclude Staffing, Agency & IT Consulting industries
        - Public Company requirement (if configured)
        - Strictly enforce company size >= 5000 employees
        """
        filters = settings.get("company_filters", {})
        search_cfg = settings.get("job_search", {})
        min_employees = filters.get("min_employees", 5000)

        try:
            job_meta = await page.evaluate(
                """() => {
                    const detailsContainer = document.querySelector(
                        '.jobs-search__job-details, .jobs-details, .jobs-details__main-content, .job-view-layout, div[data-view-name="job-details"]'
                    );
                    const detailsText = detailsContainer ? detailsContainer.innerText : (document.body ? document.body.innerText : '');
                    const locationHeader = document.querySelector(
                        '.job-details-jobs-unified-top-card__bullet, .jobs-unified-top-card__bullet, .job-details-jobs-unified-top-card__primary-description-container'
                    )?.innerText || '';
                    
                    return {
                        full_text: detailsText.toLowerCase(),
                        location: locationHeader.toLowerCase()
                    };
                }"""
            )
            raw = job_meta.get("full_text", "")
            location_text = job_meta.get("location", "")

            # 1. Granular California Location Policy Filter (exclude_ca vs bay_area_only vs all_ca)
            loc_to_check = location_text
            if not self.is_california_location(loc_to_check) and self.is_california_location(raw[:400]):
                loc_to_check = raw[:400]

            loc_allowed, loc_reason = self.evaluate_location_policy(loc_to_check or location_text or raw[:400], settings)
            if not loc_allowed:
                return False, loc_reason

            # 2. Excluded Industries / Staffing Agencies
            excluded_industries = filters.get("excluded_industries", [])
            for ind in excluded_industries:
                if ind.lower() in raw:
                    return False, f"Excluded Industry: '{ind}'"

            # 3. Public Company Only (if enabled)
            if filters.get("public_company_only", False):
                if "privately held" in raw or "private" in raw:
                    if "public company" not in raw:
                        return False, "Non-Public Company (Privately Held)"

            # 4. Strict Enterprise Company Size Filter (>= 5,000 employees)
            size_ok, size_reason = self.check_company_size(raw, min_employees=min_employees)
            if not size_ok:
                return False, size_reason

            return True, f"Eligible ({size_reason})"
        except Exception as e:
            return False, f"Eligibility check failed: {e}"

    async def ingest_from_url(self, job_url: str) -> Optional[JobPosting]:
        try:
            page: Page = await self.browser.get_page(job_url)

            meta = await page.evaluate(
                """
                () => {
                    const titleEl = document.querySelector('.job-details-jobs-unified-top-card__job-title, h1');
                    const companyEl = document.querySelector('.job-details-jobs-unified-top-card__company-name, .job-card-container__company-name');
                    const locationEl = document.querySelector('.job-details-jobs-unified-top-card__bullet, .job-card-container__metadata-item');
                    const descEl = document.querySelector('.jobs-description__content, #job-details');

                    return {
                        title: titleEl ? titleEl.innerText.trim() : document.title.replace(' | LinkedIn', ''),
                        company: companyEl ? companyEl.innerText.trim() : 'Company',
                        location: locationEl ? locationEl.innerText.trim() : 'San Francisco, CA',
                        description: descEl ? descEl.innerText.trim() : document.body.innerText.substring(0, 1500)
                    };
                }
                """
            )

            job_id = self._generate_job_id(job_url)
            job = JobPosting(
                job_id=job_id,
                platform="linkedin",
                company_name=meta.get("company") or "Company",
                job_title=meta.get("title") or "Staff Software Engineer",
                location=meta.get("location") or "United States",
                job_url=job_url,
                raw_description=meta.get("description") or "No description.",
                is_remote="remote" in meta.get("location", "").lower(),
                status=ApplicationStatus.DISCOVERED
            )

            self.db.upsert_job(job)
            return job
        except Exception as e:
            print(f"[Discovery Warning] {str(e)}")
            return None