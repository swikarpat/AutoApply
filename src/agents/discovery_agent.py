import hashlib
import json
import urllib.parse
from typing import List, Optional, Tuple
from playwright.async_api import Page
from src.core.database import ApplicationStateStore
from src.core.llm_client import GeminiFlashClient
from src.core.schemas import ApplicationStatus, JobPosting
from src.mcp.tools.browser import StealthBrowserTool


class DiscoveryAgent:
    def __init__(self, state_store: ApplicationStateStore, browser_tool: StealthBrowserTool, llm_client: GeminiFlashClient):
        self.db = state_store
        self.browser = browser_tool
        self.llm = llm_client

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

    async def evaluate_job_eligibility(self, page: Page, settings: dict) -> Tuple[bool, str]:
        """
        Evaluates active job posting against configured safety & boundary filters:
        - Exclude California / Bay Area if configured
        - Exclude Staffing, Agency & IT Consulting industries
        - Public Company requirement
        - Minimum employee count (> 200)
        """
        filters = settings.get("company_filters", {})
        search_cfg = settings.get("job_search", {})

        try:
            job_meta = await page.evaluate(
                """() => {
                    const topCard = document.querySelector('.jobs-details__main-content, .job-view-layout, .job-details-jobs-unified-top-card')?.innerText || '';
                    const aboutCompany = document.querySelector('.jobs-company, .artdeco-card')?.innerText || '';
                    const locationHeader = document.querySelector('.job-details-jobs-unified-top-card__bullet, .jobs-unified-top-card__bullet')?.innerText || '';
                    
                    return {
                        full_text: (topCard + ' ' + aboutCompany).toLowerCase(),
                        location: locationHeader.toLowerCase()
                    };
                }"""
            )
            raw = job_meta.get("full_text", "")
            location_text = job_meta.get("location", "")

            # 1. California Exclusion Filter
            if search_cfg.get("exclude_california", False):
                ca_indicators = [
                    "california", ", ca", "ca,", "san francisco", "bay area", 
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

            # 3. Public Company Only
            if filters.get("public_company_only", False):
                if "privately held" in raw or "private" in raw:
                    if "public company" not in raw:
                        return False, "Non-Public Company (Privately Held)"

            # 4. Minimum Employee Count (> 200)
            small_sizes = ["1-10 employees", "11-50 employees", "51-200 employees", "2-10 employees"]
            for sig in small_sizes:
                if sig in raw:
                    return False, f"Company size too small ({sig})"

            return True, "Eligible"
        except Exception as e:
            return True, f"Eligibility check bypassed: {e}"

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