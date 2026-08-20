import os
import re
import yaml
import asyncio
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

    def _resolve_answer(self, text: str, is_textarea: bool = False) -> str:
        q = text.lower()
        c = self.truth["candidate"]
        comp = self.truth.get("compensation", {})

        # Experience -> Configured Years
        if any(k in q for k in ["how many years", "years of experience", "years", "experience"]):
            return str(c.get("years_of_experience", 6))
        
        # Notice Period -> Configured Weeks
        if "notice" in q:
            return str(comp.get("notice_period_weeks", 2))
        
        # Compensation
        if any(k in q for k in ["salary", "compensation", "pay", "expectation", "remuneration"]):
            return str(comp.get("target_base_salary_min_usd", 220000))
        
        # Identity Details from truth_matrix
        if "first name" in q:
            return c["first_name"]
        if "last name" in q:
            return c["last_name"]
        if "phone" in q or "mobile" in q:
            return c["phone"]
        if "email" in q:
            return c["email"]
        if "linkedin" in q:
            return c["linkedin"]
        if "github" in q:
            return c["github"]
        if "postal" in q or "zip" in q:
            return c.get("postal_code", "94105")
        
        if is_textarea:
            return "I bring over 6 years of enterprise experience architecting distributed systems and production AI."
        
        return str(c.get("years_of_experience", 6))

    async def _handle_location(self, input_loc: Locator):
        target_location = self.truth["candidate"].get("location_query", "San Francisco, California")
        try:
            await input_loc.click()
            await input_loc.fill("")
            await self.page.keyboard.type(target_location, delay=35)
            await asyncio.sleep(0.8)
            sugg = self.page.locator('.artdeco-typeahead__result, div[role="option"]').first
            if await sugg.is_visible():
                await sugg.click()
            else:
                await self.page.keyboard.press("ArrowDown")
                await self.page.keyboard.press("Enter")
            console.print(f"    [dim]↳ Location Autocomplete:[/dim] [cyan]{target_location}[/cyan]")
            await asyncio.sleep(0.3)
        except Exception:
            pass

    async def fill_modal_step(self, modal: Locator, step_num: int):
        table = Table(title=f"Step {step_num} - Form Fields Inspected", show_header=True, header_style="bold magenta")
        table.add_column("Field / Question", style="dim", width=45)
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

                # Location handling
                if any(k in combined for k in ["city", "location"]):
                    if not curr or len(curr.strip()) < 2:
                        await self._handle_location(inp)
                        table.add_row("Location (City)", self.truth["candidate"].get("location_query", "San Francisco, CA"))
                        has_entries = True
                    continue

                # Phone Number Override Check
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

                if "sponsorship" in txt or "visa" in txt:
                    no_r = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_r.is_visible():
                        await no_r.click(force=True)
                        table.add_row("Requires Visa Sponsorship", "No")
                        has_entries = True
                elif any(k in txt for k in ["authorized", "legally", "eligible"]):
                    yes_r = fs.locator('label:has-text("Yes"), input[value="Yes"]').first
                    if await yes_r.is_visible():
                        await yes_r.click(force=True)
                        table.add_row("Legally Authorized to Work", "Yes")
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
                        table.add_row("Demographic / EEO Survey", "I don't wish to answer / No")
                        has_entries = True
                    else:
                        first_r = fs.locator('label, input[type="radio"]').first
                        if await first_r.is_visible():
                            await first_r.click(force=True)
                else:
                    first_r = fs.locator('label:has-text("Yes"), label:has-text("No"), label').first
                    if await first_r.is_visible():
                        await first_r.click(force=True)
                        table.add_row("General Radio Question", "Selected Option")
                        has_entries = True
            except Exception:
                continue

        # 3. Dropdown Options Match
        await self.page.evaluate(
            """() => {
                const selects = Array.from(document.querySelectorAll('select'));
                for (const sel of selects) {
                    if (sel.offsetParent === null) continue;
                    
                    const parentText = (sel.closest('.jobs-easy-apply-form-section__grouping, .fb-dash-form-element, div')?.innerText || '').toLowerCase();
                    const options = Array.from(sel.options);
                    const selectedIdx = sel.selectedIndex;
                    const currentText = selectedIdx >= 0 ? options[selectedIdx].text.toLowerCase() : '';

                    if (currentText.includes('select an option') || currentText === '' || sel.value === '') {
                        let targetIdx = -1;

                        if (parentText.includes('authorized') || parentText.includes('hybrid') || parentText.includes('commute') || parentText.includes('willing')) {
                            targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('yes'));
                        } else if (parentText.includes('sponsorship') || parentText.includes('visa')) {
                            targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('no'));
                        } else if (parentText.includes('disability') || parentText.includes('veteran') || parentText.includes('gender')) {
                            targetIdx = options.findIndex(o => o.text.toLowerCase().includes('wish to answer') || o.text.toLowerCase().includes('decline'));
                        }

                        if (targetIdx === -1) {
                            targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('yes'));
                        }
                        if (targetIdx === -1 && options.length > 1) {
                            targetIdx = 1;
                        }

                        if (targetIdx !== -1) {
                            sel.selectedIndex = targetIdx;
                            sel.dispatchEvent(new Event('change', { bubbles: true }));
                            sel.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                    }
                }
            }"""
        )

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

        console.print("  [green]Found Easy Apply button. Clicking...[/green]")
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

                # Scroll down modal
                try:
                    await self.page.evaluate("""() => {
                        const content = document.querySelector('.jobs-easy-apply-modal__content, .artdeco-modal__content');
                        if (content) content.scrollTop = content.scrollHeight;
                    }""")
                except Exception:
                    pass

                # Inspection Pause: Allows you to see what was filled
                console.print(f"  [dim]Inspecting step {step}... Pausing {self.step_delay}s...[/dim]")
                await asyncio.sleep(self.step_delay)

                # Check Submit Button
                submit_btn = modal.locator('button[aria-label="Submit application"], button:has-text("Submit application")').first
                if await submit_btn.is_visible():
                    if self.auto_submit:
                        follow_chk = modal.locator('label[for="follow-company-checkbox"]').first
                        if await follow_chk.is_visible():
                            try:
                                await follow_chk.click()
                            except Exception:
                                pass
                        console.print("  [bold green]Clicking Final 'Submit application'![/bold green]")
                        await submit_btn.click(force=True)
                        await asyncio.sleep(3.0)
                        submitted = True
                    else:
                        console.print("[bold yellow]Review complete. Ready for manual submit in browser.[/bold yellow]")
                    break

                # Click Next / Review Button
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

                    # Error Recovery
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
    console.print(Panel("[bold green]STARTING IN-SEARCH LINKEDIN STREAM APPLIER (INSPECTION MODE)[/bold green]"))

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

        search_url = "https://www.linkedin.com/jobs/search/?keywords=Staff%20Software%20Engineer&location=San%20Francisco%20Bay%20Area&f_AL=true&sortBy=R"
        console.print(f"[cyan]Navigating to LinkedIn Search Stream:[/cyan] {search_url}")
        
        await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2.5)

        applier = LinkedInStreamApplier(page, settings, truth)

        applied_total = 0
        max_apps = 30

        card_locators = page.locator(
            'li[data-occludable-job-id], '
            'li.jobs-search-results__list-item, '
            'div.job-card-container, '
            'div[data-job-id]'
        )

        total_cards = await card_locators.count()
        console.print(f"[bold cyan]Found {total_cards} job cards in active search stream.[/bold cyan]\n")

        for idx in range(total_cards):
            if applied_total >= max_apps:
                console.print(f"[yellow]Reached limit of {max_apps} applications.[/yellow]")
                break

            card = card_locators.nth(idx)
            try:
                if not await card.is_visible():
                    await card.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)

                card_title = (await card.inner_text()).split('\n')[0].strip()
                console.print(f"[bold]─────────────────────────────────────────────────────────────────────────────[/bold]")
                console.print(f"[bold yellow][{idx+1}/{total_cards}] Selecting:[/bold yellow] {card_title[:45]}")

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