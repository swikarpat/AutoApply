import hashlib
import json
import urllib.parse
from typing import List, Optional
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
                location=meta.get("location") or "San Francisco, CA",
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

    async def discover_linkedin_jobs(self, titles: List[str], locations: List[str], easy_apply_only: bool = True) -> List[str]:
        """Harvests ONLY job postings verified to have the Easy Apply badge."""
        discovered_urls = []

        for title in titles:
            for loc in locations:
                params = {
                    "keywords": title,
                    "location": loc,
                    "sortBy": "R",
                }
                if easy_apply_only:
                    params["f_AL"] = "true"  # Easy Apply parameter

                search_url = f"https://www.linkedin.com/jobs/search/?{urllib.parse.urlencode(params)}"
                print(f"[LinkedIn Crawler] Searching: {title} in {loc} (Easy Apply Only)...")

                try:
                    page = await self.browser.get_page(search_url)
                    await page.wait_for_selector('.jobs-search-results-list, main', timeout=8000)

                    # Extract ONLY links from cards that explicitly show the "Easy Apply" badge
                    verified_links = await page.evaluate(
                        """
                        () => {
                            const cards = Array.from(document.querySelectorAll(
                                '.jobs-search-results__list-item, .job-card-container, li.jobs-search-results-list__list-item'
                            ));
                            
                            const validUrls = [];
                            for (const card of cards) {
                                const cardText = card.innerText || '';
                                // Strict filter: card must have Easy Apply badge text
                                if (cardText.includes('Easy Apply')) {
                                    const linkEl = card.querySelector('a.job-card-container__link, a.job-card-list__title, a[href*="/jobs/view/"]');
                                    if (linkEl && linkEl.href) {
                                        const cleanUrl = linkEl.href.split('?')[0];
                                        if (cleanUrl.includes('/jobs/view/')) {
                                            validUrls.push(cleanUrl);
                                        }
                                    }
                                }
                            }
                            return validUrls;
                        }
                        """
                    )

                    for link in verified_links:
                        if link not in discovered_urls:
                            discovered_urls.append(link)

                    if len(discovered_urls) >= 20:
                        break
                except Exception as e:
                    print(f"[LinkedIn Search Error] {str(e)}")
                    continue

        return list(set(discovered_urls))