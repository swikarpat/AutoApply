import os
import re
import yaml
import asyncio
import urllib.parse
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from playwright.async_api import Page, Locator
from src.mcp.tools.browser import StealthBrowserTool

console = Console()


class LinkedInStreamApplier:
    def __init__(self, page: Page, settings: dict, truth: dict):
        self.page = page
        self.settings = settings
        self.truth = truth
        self.pdf_path = os.path.abspath(settings["resume_attachment"]["master_pdf_path"])
        self.auto_submit = settings["automation_safety"].get("auto_submit", True)
        self.step_delay = settings["automation_safety"].get("step_inspection_delay_seconds", 3.0)
        self.filters = settings.get("company_filters", {})
        self.search_cfg = settings.get("job_search", {})

    def _resolve_answer(self, text: str, is_textarea: bool = False) -> str:
        q = text.lower()
        c = self.truth.get("candidate", {})
        comp = self.truth.get("compensation", {})
        skills = self.truth.get("skills_experience_years", {})
        edu = self.truth.get("education", {})

        # Block Referrer Name Field
        if any(k in q for k in ["referred by", "employee name", "referrer", "who referred"]):
            return ""

        # Specific Skill Years Mapping
        if any(k in q for k in ["how many years", "years of experience", "years of work", "years"]):
            for skill_key, years in skills.items():
                clean_key = skill_key.replace("_", " ")
                if clean_key in q:
                    return str(years)
            return str(skills.get("default_years", 6))

        # Work Logistics & Notice
        if "notice" in q:
            if "day" in q:
                return str(comp.get("notice_period_days", 5))
            return str(comp.get("notice_period_weeks", 1))

        # Compensation
        if any(k in q for k in ["salary", "compensation", "pay", "expectation", "remuneration"]):
            if "hour" in q:
                return str(comp.get("target_hourly_rate_usd", 65))
            return str(comp.get("target_base_salary_min_usd", 120000))

        # Education
        if "gpa" in q:
            return str(edu.get("gpa", "3.8"))
        if "school" in q or "university" in q:
            return edu.get("school", "James Cook University")
        if "degree" in q:
            return edu.get("degree", "Bachelor of Science")
        if "major" in q or "field of study" in q:
            return edu.get("field_of_study", "Computer Science")

        # Identity Details
        if "first name" in q:
            return c.get("first_name", "Swikar")
        if "last name" in q:
            return c.get("last_name", "Patel")
        if "phone" in q or "mobile" in q:
            return c.get("phone", "9514631792")
        if "email" in q:
            return c.get("email", "swikar.aus@gmail.com")
        if "linkedin" in q:
            return c.get("linkedin", "")
        if "github" in q:
            return c.get("github", "")
        if "postal" in q or "zip" in q:
            return c.get("postal_code", "94105")

        # Textarea Essays
        if is_textarea:
            essays = self.truth.get("canned_essays", {})
            if any(k in q for k in ["why", "interest", "cover"]):
                return essays.get("why_interested", "I bring extensive experience architecting distributed systems and production AI.")
            return essays.get("summary", "Staff AI & Distributed Systems Engineer with 6+ years building high-throughput microservices.")

        return str(skills.get("default_years", 6))

    async def evaluate_job_eligibility(self) -> tuple[bool, str]:
        try:
            job_meta = await self.page.evaluate(
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
            if self.search_cfg.get("exclude_california", False):
                ca_indicators = [
                    "california", ", ca", "ca,", "san francisco", "bay area", 
                    "los angeles", "san jose", "san diego", "sunnyvale", 
                    "mountain view", "palo alto", "menlo park", "cupertino", 
                    "fremont", "oakland", "santa clara", "irvine"
                ]
                if any(ind in location_text for ind in ca_indicators) or any(ind in raw[:400] for ind in ca_indicators):
                    return False, "Excluded Region: California / Bay Area job posting"

            # 2. Excluded Industries / Agencies
            excluded = self.filters.get("excluded_industries", [])
            for ind in excluded:
                if ind.lower() in raw:
                    return False, f"Excluded Industry Match: '{ind}'"

            # 3. Public Company Only
            if self.filters.get("public_company_only", True):
                if "privately held" in raw or "private" in raw:
                    if "public company" not in raw:
                        return False, "Non-Public Company (Privately Held)"

            # 4. Employee Count > 200
            small_company_signatures = ["1-10 employees", "11-50 employees", "51-200 employees", "2-10 employees"]
            for sig in small_company_signatures:
                if sig in raw:
                    return False, f"Company size too small ({sig})"

            return True, "Eligible (Public, >200 Employees)"
        except Exception as e:
            return True, f"Inspection pass ({str(e)})"

    async def _handle_location(self, input_loc: Locator):
        target_location = self.truth["candidate"].get("location_query", "San Francisco, California")
        try:
            await input_loc.click()
            await input_loc.fill("")
            await self.page.keyboard.press("Meta+A")
            await self.page.keyboard.press("Backspace")
            await input_loc.press_sequentially(target_location, delay=35)
            await asyncio.sleep(0.8)
            
            sugg = self.page.locator('.artdeco-typeahead__result, div[role="option"], .basic-typeahead__selectable-result').first
            if await sugg.is_visible():
                await sugg.click()
            else:
                await self.page.keyboard.press("ArrowDown")
                await self.page.keyboard.press("Enter")
            await asyncio.sleep(0.3)
        except Exception:
            pass

    async def _uncheck_follow_company(self, modal: Locator):
        try:
            await self.page.evaluate("""() => {
                const checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"]'));
                for (const chk of checkboxes) {
                    const labelText = (chk.closest('label')?.innerText || chk.parentElement?.innerText || chk.id || '').toLowerCase();
                    if (labelText.includes('follow') || chk.id.includes('follow')) {
                        if (chk.checked) {
                            chk.click();
                            chk.checked = false;
                            chk.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    }
                }
            }""")
        except Exception:
            pass

    async def fill_modal_step(self, modal: Locator, step_num: int):
        table = Table(title=f"Step {step_num} - Form Fields Filled", show_header=True, header_style="bold magenta")
        table.add_column("Question / Field", style="dim", width=45)
        table.add_column("Value Injected", style="green", width=35)
        has_entries = False

        # 1. Inputs & Textareas
        inputs = modal.locator('input:not([type="hidden"]):not([type="file"]):not([type="radio"]):not([type="checkbox"]), textarea')
        count = await inputs.count()
        for i in range(count):
            inp = inputs.nth(i)
            try:
                if not await inp.is_visible():
                    continue
                curr = await inp.input_value()

                label_text = await self.page.evaluate(
                    """(el) => {
                        const parent = el.closest('.jobs-easy-apply-form-section__grouping, .fb-dash-form-element, .artdeco-text-input, div');
                        return parent ? parent.innerText : (el.name || el.placeholder || '');
                    }""",
                    await inp.element_handle()
                )
                combined = label_text.lower()

                # Location Correction
                if any(k in combined for k in ["city", "location"]):
                    target_loc = self.truth["candidate"].get("location_query", "San Francisco, California")
                    if not curr or "philippines" in curr.lower() or "manila" in curr.lower() or target_loc.split(',')[0].lower() not in curr.lower():
                        await self._handle_location(inp)
                        table.add_row("City / Location", target_loc)
                        has_entries = True
                    continue

                if any(k in combined for k in ["referred by", "employee name", "referrer", "who referred"]):
                    await inp.fill("")
                    continue

                if ("phone" in combined or "mobile" in combined) and (not curr or "0000" in curr):
                    real_phone = self.truth["candidate"]["phone"]
                    await inp.fill(real_phone)
                    table.add_row("Phone Number", real_phone)
                    has_entries = True
                    continue

                is_ta = (await inp.get_attribute("type")) == "textarea" or (await self.page.evaluate("el => el.tagName", await inp.element_handle())) == "TEXTAREA"
                val = self._resolve_answer(combined, is_textarea=is_ta)

                if val and (not curr or curr.strip() == ""):
                    await inp.fill(str(val))
                    table.add_row(label_text.split('\n')[0][:40], str(val))
                    has_entries = True
            except Exception:
                continue

        # 2. Radio Buttons
        fieldsets = modal.locator('fieldset, .fb-form-element__fieldset, div[role="radiogroup"]')
        fs_count = await fieldsets.count()
        for i in range(fs_count):
            fs = fieldsets.nth(i)
            try:
                checked = fs.locator('input[type="radio"]:checked')
                if await checked.count() > 0:
                    continue

                txt = (await fs.inner_text()).lower()

                if "hispanic" in txt or "latino" in txt:
                    no_r = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_r.is_visible():
                        await no_r.click(force=True)
                        table.add_row("Hispanic or Latino", "No")
                        has_entries = True
                elif any(k in txt for k in ["referred by", "internal employee", "referral"]):
                    no_r = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_r.is_visible():
                        await no_r.click(force=True)
                        table.add_row("Employee Referral", "No")
                        has_entries = True
                elif "sponsorship" in txt or "visa" in txt:
                    no_r = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_r.is_visible():
                        await no_r.click(force=True)
                        table.add_row("Requires Visa Sponsorship", "No")
                        has_entries = True
                elif any(k in txt for k in ["authorized", "legally", "eligible"]):
                    yes_r = fs.locator('label:has-text("Yes"), input[value="Yes"]').first
                    if await yes_r.is_visible():
                        await yes_r.click(force=True)
                        table.add_row("Authorized to Work", "Yes")
                        has_entries = True
                elif any(k in txt for k in ["disability", "veteran", "gender", "race", "ethnic", "equal opportunity", "armed forces"]):
                    decline_r = fs.locator(
                        'label:has-text("I don\'t wish to answer"), '
                        'label:has-text("Decline"), '
                        'label:has-text("No, I am not"), '
                        'label:has-text("No")'
                    ).first
                    if await decline_r.is_visible():
                        await decline_r.click(force=True)
                        table.add_row("Demographic / EEO", "Decline / No")
                        has_entries = True
                    else:
                        first_r = fs.locator('label, input[type="radio"]').first
                        if await first_r.is_visible():
                            await first_r.click(force=True)
                else:
                    no_fallback = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_fallback.is_visible():
                        await no_fallback.click(force=True)
                        table.add_row("Question Option", "No")
                        has_entries = True
                    else:
                        first_r = fs.locator('label, input[type="radio"]').first
                        if await first_r.is_visible():
                            await first_r.click(force=True)
            except Exception:
                continue

        # 3. Dynamic Dropdowns
        target_salary = self.truth.get("compensation", {}).get("target_base_salary_min_usd", 120000)
        await self.page.evaluate(
            f"""() => {{
                const targetSalary = {target_salary};
                const selects = Array.from(document.querySelectorAll('select'));
                for (const sel of selects) {{{{
                    if (sel.offsetParent === null) continue;
                    
                    const parentText = (sel.closest('.jobs-easy-apply-form-section__grouping, .fb-dash-form-element, div')?.innerText || '').toLowerCase();
                    const options = Array.from(sel.options);
                    const selectedIdx = sel.selectedIndex;
                    const currentText = selectedIdx >= 0 ? options[selectedIdx].text.toLowerCase() : '';

                    if (currentText.includes('select an option') || currentText === '' || sel.value === '') {{{{
                        let targetIdx = -1;

                        if (parentText.includes('hispanic') || parentText.includes('latino')) {{{{
                            targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('no'));
                        }}}} else if (parentText.includes('referred') || parentText.includes('internal employee')) {{{{
                            targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('no'));
                        }}}} else if (parentText.includes('authorized') || parentText.includes('hybrid') || parentText.includes('commute') || parentText.includes('willing') || parentText.includes('relocate')) {{{{
                            targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('yes'));
                        }}}} else if (parentText.includes('sponsorship') || parentText.includes('visa')) {{{{
                            targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('no'));
                        }}}} else if (parentText.includes('salary') || parentText.includes('compensation') || parentText.includes('expectation')) {{{{
                            for (let i = 0; i < options.length; i++) {{{{
                                const optText = options[i].text.replace(/,/g, '');
                                const nums = optText.match(/\\d+/g);
                                if (nums && nums.length > 0) {{{{
                                    const maxVal = Math.max(...nums.map(Number));
                                    const realVal = maxVal < 1000 ? maxVal * 1000 : maxVal;
                                    if (realVal >= targetSalary) {{{{
                                        targetIdx = i;
                                        break;
                                    }}}}
                                }}}}
                            }}}}
                            if (targetIdx === -1) targetIdx = options.length - 1;
                        }}}} else if (parentText.includes('disability') || parentText.includes('veteran') || parentText.includes('gender')) {{{{
                            targetIdx = options.findIndex(o => o.text.toLowerCase().includes('wish to answer') || o.text.toLowerCase().includes('decline') || o.text.toLowerCase().startsWith('no'));
                        }}}}

                        if (targetIdx === -1) {{{{
                            targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('yes'));
                        }}}}
                        if (targetIdx === -1 && options.length > 1) {{{{
                            targetIdx = 1;
                        }}}}

                        if (targetIdx !== -1) {{{{
                            sel.selectedIndex = targetIdx;
                            sel.dispatchEvent(new Event('change', {{{{ bubbles: true }}}}));
                            sel.dispatchEvent(new Event('input', {{{{ bubbles: true }}}}));
                        }}}}
                    }}}}
                }}}}
            }}"""
        )

        await self._uncheck_follow_company(modal)

        if has_entries:
            console.print(table)

    async def _dismiss_modal(self):
        try:
            dismiss = self.page.locator('button[aria-label="Dismiss"], button[data-test-modal-close-btn]').first
            if await dismiss.is_visible():
                await dismiss.click()
                await asyncio.sleep(0.4)
                discard = self.page.locator('button[data-control-name="discard_application_confirm_btn"], button:has-text("Discard")').first
                if await discard.is_visible():
                    await discard.click()
                    await asyncio.sleep(0.4)
        except Exception:
            pass

    async def apply_to_active_job(self) -> bool:
        easy_apply_btn = self.page.locator(
            '.jobs-details__main-content button:has-text("Easy Apply"), '
            '.jobs-apply-button--top-card button:has-text("Easy Apply"), '
            '.jobs-s-apply button:has-text("Easy Apply"), '
            'button.jobs-apply-button:has-text("Easy Apply")'
        ).first

        try:
            await easy_apply_btn.wait_for(state="visible", timeout=2500)
        except Exception:
            console.print("  [yellow]Not an Easy Apply role (External). Skipping.[/yellow]")
            return False

        eligible, reason = await self.evaluate_job_eligibility()
        if not eligible:
            console.print(f"  [red]Filtered Out:[/red] {reason}")
            return False

        console.print(f"  [green]Job Verified ({reason}). Clicking Easy Apply...[/green]")
        await easy_apply_btn.click()

        modal = self.page.locator('div[role="dialog"].jobs-easy-apply-modal, div.jobs-easy-apply-modal, #artdeco-modal-outlet .artdeco-modal, div[role="dialog"]').first
        try:
            await modal.wait_for(state="visible", timeout=5000)
        except Exception:
            console.print("  [red]Modal failed to render.[/red]")
            await self._dismiss_modal()
            return False

        submitted = False
        try:
            for step in range(1, 10):
                await asyncio.sleep(0.4)
                if not await modal.is_visible():
                    break

                # Upload Resume
                file_inp = modal.locator('input[type="file"]').first
                if await file_inp.count() > 0:
                    try:
                        await file_inp.set_input_files(self.pdf_path)
                        console.print(f"  [cyan]Attached {os.path.basename(self.pdf_path)}[/cyan]")
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass

                await self.fill_modal_step(modal, step)

                try:
                    await self.page.evaluate("""() => {
                        const content = document.querySelector('.jobs-easy-apply-modal__content, .artdeco-modal__content');
                        if (content) content.scrollTop = content.scrollHeight;
                    }""")
                except Exception:
                    pass

                await self._uncheck_follow_company(modal)

                console.print(f"  [dim]Inspecting step {step}... Pausing {self.step_delay}s...[/dim]")
                await asyncio.sleep(self.step_delay)

                # Check Final Submit
                submit_btn = modal.locator('button[aria-label="Submit application"], button:has-text("Submit application")').first
                if await submit_btn.is_visible():
                    await self._uncheck_follow_company(modal)
                    if self.auto_submit:
                        console.print("  [bold green]Clicking Final 'Submit application'![/bold green]")
                        await submit_btn.click(force=True)
                        await asyncio.sleep(3.0)
                        submitted = True
                    break

                # Click Next / Review
                next_btn = modal.locator(
                    'button[aria-label="Review your application"], '
                    'button[aria-label="Continue to next step"], '
                    'button:has-text("Review"), '
                    'button:has-text("Next")'
                ).first

                if await next_btn.is_visible():
                    btn_text = (await next_btn.inner_text()).strip()
                    console.print(f"  [cyan]Clicking {btn_text}...[/cyan]")
                    await next_btn.click(force=True)
                    await asyncio.sleep(0.8)

                    err = modal.locator('.artdeco-inline-feedback--error, .fb-form-element--error').first
                    if await err.is_visible():
                        await self.fill_modal_step(modal, step)
                        await next_btn.click(force=True)
                        await asyncio.sleep(0.8)
                else:
                    break
        finally:
            if not submitted:
                await self._dismiss_modal()

        return submitted


async def ensure_linkedin_login(page: Page):
    await page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(2.0)

    if any(k in page.url for k in ["login", "signup", "checkpoint", "authwall"]):
        console.print(Panel("[bold yellow]ACTION REQUIRED: Please log in to LinkedIn on the open browser window.[/bold yellow]"))
        while any(k in page.url for k in ["login", "signup", "checkpoint", "authwall"]):
            await asyncio.sleep(1.5)
        console.print("[bold green]Login verified! Resuming automation...[/bold green]\n")


async def main():
    console.print(Panel("[bold green]STARTING RECENT-FIRST MULTI-ROLE LINKEDIN APPLIER[/bold green]"))

    with open("config/settings.yaml", "r") as f:
        settings = yaml.safe_load(f)
    with open("config/truth_matrix.yaml", "r") as f:
        truth = yaml.safe_load(f)

    browser = StealthBrowserTool(
        headless=False,
        user_data_dir=settings["automation_safety"]["user_data_dir"]
    )
    await browser.initialize()

    try:
        page = await browser.get_page("https://www.linkedin.com/jobs/")
        await ensure_linkedin_login(page)

        # 1. Build Multi-Role Boolean Query
        titles = settings["job_search"].get("target_titles", ["Staff Software Engineer"])
        boolean_query = " OR ".join([f'"{t}"' for t in titles])
        loc = settings["job_search"].get("target_location", "United States")
        
        # 2. Build URL with Recency Sorting (sortBy=DD) & Time Range (f_TPR)
        params = {
            "keywords": boolean_query,
            "location": loc,
            "f_AL": "true",
            "sortBy": "DD" if settings["job_search"].get("sort_by_recent_first", True) else "R"
        }
        
        # Add Time Posted Filter (e.g. Past 24 Hours)
        time_range = settings["job_search"].get("time_posted_range")
        if time_range:
            params["f_TPR"] = time_range

        search_url = f"https://www.linkedin.com/jobs/search/?{urllib.parse.urlencode(params)}"
        console.print(f"[cyan]Target Roles:[/cyan] [bold magenta]{', '.join(titles)}[/bold magenta]")
        console.print(f"[cyan]Recency Sort:[/cyan] [bold green]Newest First (Past 24h / DD)[/bold green] | [cyan]Location:[/cyan] [bold green]{loc}[/bold green]")
        console.print(f"[cyan]Navigating to LinkedIn Stream:[/cyan] {search_url}\n")

        await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2.5)

        applier = LinkedInStreamApplier(page, settings, truth)

        applied_total = 0
        max_apps = settings["automation_safety"].get("max_applications_per_run", 30)

        card_locators = page.locator(
            'li[data-occludable-job-id], '
            'li.jobs-search-results__list-item, '
            'div.job-card-container, '
            'div[data-job-id]'
        )

        total_cards = await card_locators.count()
        console.print(f"[bold cyan]Found {total_cards} fresh job cards in active stream.[/bold cyan]\n")

        for idx in range(total_cards):
            if applied_total >= max_apps:
                console.print(f"[yellow]Reached application limit ({max_apps}).[/yellow]")
                break

            card = card_locators.nth(idx)
            try:
                if not await card.is_visible():
                    await card.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)

                card_title = (await card.inner_text()).split('\n')[0].strip()
                console.print(f"[bold]─────────────────────────────────────────────────────────────────────────────[/bold]")
                console.print(f"[bold yellow][{idx+1}/{total_cards}] Inspecting Fresh Posting:[/bold yellow] {card_title[:50]}")

                await card.click()
                await asyncio.sleep(1.2)

                success = await applier.apply_to_active_job()
                if success:
                    applied_total += 1
                    console.print(f"[bold green]✓ SUBMITTED SUCCESSFULLY! (Total Applied: {applied_total})[/bold green]")

                await asyncio.sleep(settings["automation_safety"]["delay_between_jobs_seconds"])
            except Exception as e:
                console.print(f"  [red]Card error:[/red] {str(e)}")
                await applier._dismiss_modal()
                continue

        console.print(f"\n[bold green]Run complete. Total applications submitted: {applied_total}[/bold green]")
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())