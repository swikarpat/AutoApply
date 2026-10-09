import asyncio
import hashlib
import json
import random
import urllib.parse
from typing import Any, List, Optional, Tuple
from playwright.async_api import Page
from src.core.database import ApplicationStateStore
from src.core.llm_client import GeminiFlashClient
from src.core.schemas import ApplicationStatus, JobPosting
from src.mcp.tools.browser import StealthBrowserTool


class DiscoveryAgent:
    def __init__(
        self,
        state_store: ApplicationStateStore,
        browser_tool: StealthBrowserTool,
        llm_client: GeminiFlashClient,
        pacing: Optional[Any] = None,
    ):
        self.db = state_store
        self.browser = browser_tool
        self.llm = llm_client
        self.pacing = pacing

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

            # 1. California Exclusion Filter
            if search_cfg.get("exclude_california", False):
                ca_indicators = [
                    "california", ", ca", "ca,", "ca ", "(ca)", "san francisco", "bay area", 
                    "los angeles", "san jose", "san diego", "sunnyvale", 
                    "mountain view", "palo alto", "menlo park", "cupertino", 
                    "fremont", "oakland", "santa clara", "irvine"
                ]
                if any(ind in location_text for ind in ca_indicators) or any(ind in raw[:400] for ind in ca_indicators):
                    return False, "Excluded Region: California / Bay Area posting"

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