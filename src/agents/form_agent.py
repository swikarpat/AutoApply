import json
import os
import re
import yaml
import asyncio
from typing import Any, Dict, List
from playwright.async_api import Page
from src.core.llm_client import GeminiFlashClient
from src.mcp.tools.browser import StealthBrowserTool


class FormAutomationAgent:
    def __init__(self, browser_tool: StealthBrowserTool, llm_client: GeminiFlashClient, config_path: str = "config/settings.yaml"):
        self.browser = browser_tool
        self.llm = llm_client
        with open(config_path, "r") as f:
            self.settings = yaml.safe_load(f)
        with open("config/truth_matrix.yaml", "r") as f:
            self.truth = yaml.safe_load(f)
        with open("data/master_resume.json", "r") as f:
            self.master_resume = json.load(f)

        self.pdf_path = os.path.abspath("data/ResumeSoftwareEngineer.pdf")
        self.auto_submit = self.settings["automation_safety"].get("auto_submit", True)

    def _resolve_fast_answer(self, combined_text: str, is_textarea: bool = False) -> str:
        c = self.truth["candidate"]
        q = combined_text.lower()

        # 1. Experience Questions -> 6
        if any(k in q for k in ["how many years", "years of experience", "years of work", "years", "experience"]):
            return "6"

        # 2. Notice Period -> 2
        if "notice" in q:
            return "2"

        # 3. Target Salary
        if any(k in q for k in ["salary", "compensation", "pay", "rate", "remuneration", "expectation"]):
            return "220000"

        # 4. Standard Identity Fields
        if any(k in q for k in ["first name", "firstname"]):
            return c["full_name"].split()[0]
        if any(k in q for k in ["last name", "lastname"]):
            return c["full_name"].split()[-1]
        if "phone" in q or "mobile" in q:
            return c["phone"]
        if "email" in q:
            return c["email"]
        if "linkedin" in q:
            return c["linkedin"]
        if "github" in q:
            return c["github"]
        if "gpa" in q:
            return "3.8"

        if is_textarea:
            return "I bring over 6 years of enterprise experience designing high-throughput distributed systems and production AI architectures."

        return "6"

    async def _handle_location_typeahead(self, page: Page, input_locator, target_city: str = "San Francisco, California"):
        try:
            await input_locator.click()
            await input_locator.fill("")
            await page.keyboard.type(target_city, delay=25)
            await asyncio.sleep(0.8)

            suggestion = page.locator('.artdeco-typeahead__result, div[role="option"], .basic-typeahead__selectable-result').first
            if await suggestion.is_visible():
                await suggestion.click()
            else:
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.1)
                await page.keyboard.press("Enter")
            await asyncio.sleep(0.3)
        except Exception:
            pass

    async def _dismiss_modal(self, page: Page):
        try:
            dismiss_btn = page.locator('button[aria-label="Dismiss"], button[data-test-modal-close-btn]').first
            if await dismiss_btn.is_visible():
                await dismiss_btn.click()
                await asyncio.sleep(0.5)
                discard_btn = page.locator('button[data-control-name="discard_application_confirm_btn"], button:has-text("Discard")').first
                if await discard_btn.is_visible():
                    await discard_btn.click()
                    await asyncio.sleep(0.5)
        except Exception:
            pass

    async def process_linkedin_application(self, page: Page, job_id: str, job_title: str, company: str) -> Dict[str, Any]:
        results = {
            "job_id": job_id,
            "resume_uploaded": False,
            "fields_filled": [],
            "submitted": False,
            "status": "FAILED"
        }

        # 1. Ensure user is logged in
        if "login" in page.url or "signup" in page.url:
            print("  [Auth] LinkedIn login required. Please sign in on the browser window.")
            return results

        # 2. Scoped Top-Card Apply Button Selector (Excludes search filter pills)
        top_card_selectors = [
            '.jobs-apply-button--top-card button.jobs-apply-button',
            '.jobs-s-apply button.jobs-apply-button',
            '.jobs-details__main-content button.jobs-apply-button',
            '.job-details-jobs-unified-top-card button.jobs-apply-button',
            'button.jobs-apply-button[data-job-id]',
            'button.jobs-apply-button'
        ]

        apply_btn = None
        for sel in top_card_selectors:
            loc = page.locator(sel).first
            try:
                if await loc.is_visible():
                    btn_text = (await loc.inner_text()).strip()
                    if "Easy Apply" in btn_text:
                        apply_btn = loc
                        break
            except Exception:
                continue

        if not apply_btn:
            print("  [Notice] Not an 'Easy Apply' role (External Apply only). Skipping.")
            return results

        # 3. Click Easy Apply in Top Card
        print("  [Action] Found Top-Card 'Easy Apply' button. Clicking...")
        await apply_btn.scroll_into_view_if_needed()
        await apply_btn.click(force=True)

        # 4. Wait for Modal Container
        modal = page.locator('div[role="dialog"].jobs-easy-apply-modal, div.jobs-easy-apply-modal, #artdeco-modal-outlet .artdeco-modal').first
        try:
            await modal.wait_for(state="visible", timeout=7000)
            print("  [Modal] Easy Apply dialog opened successfully!")
        except Exception:
            print("  [Error] Easy Apply modal did not render within 7s.")
            return results

        # 5. Multi-Step Form Traversal
        for step in range(1, 10):
            await asyncio.sleep(0.6)

            if not await modal.is_visible():
                break

            # A. Upload / Select Resume
            file_input = modal.locator('input[type="file"]').first
            if await file_input.count() > 0 and not results["resume_uploaded"]:
                try:
                    await file_input.set_input_files(self.pdf_path)
                    results["resume_uploaded"] = True
                    print(f"  [Resume] Uploaded {os.path.basename(self.pdf_path)}")
                    await asyncio.sleep(0.8)
                except Exception:
                    pass

            # B. Fill Active Inputs
            filled_count = await self._fill_modal_fields(page, modal)
            print(f"  [Step {step}] Handled {filled_count} form inputs.")

            # C. Check for Final Submit Button
            submit_btn = modal.locator(
                'button[aria-label="Submit application"], '
                'button:has-text("Submit application")'
            ).first

            if await submit_btn.is_visible():
                if self.auto_submit:
                    follow_chk = modal.locator('label[for="follow-company-checkbox"], input#follow-company-checkbox').first
                    if await follow_chk.is_visible():
                        try:
                            await follow_chk.click()
                        except Exception:
                            pass

                    print("  [Submit] Clicking Final 'Submit application'...")
                    await submit_btn.click(force=True)
                    await asyncio.sleep(3.0)

                    results["submitted"] = True
                    results["status"] = "SUBMITTED"
                    print("  [Success] ✓ APPLICATION SUBMITTED SUCCESSFULLY!")
                    await self._dismiss_modal(page)
                break

            # D. Click Next / Review
            next_btn = modal.locator(
                'button[aria-label="Review your application"], '
                'button[aria-label="Continue to next step"], '
                'button:has-text("Review"), '
                'button:has-text("Next")'
            ).first

            if await next_btn.is_visible():
                btn_name = (await next_btn.inner_text()).strip()
                print(f"  [Navigation] Clicking '{btn_name}'...")
                await next_btn.click(force=True)
                await asyncio.sleep(1.2)

                # Retry on validation errors
                error_badge = modal.locator('.artdeco-inline-feedback--error, .fb-form-element--error').first
                if await error_badge.is_visible():
                    print("  [Validation] Required fields flagged. Retrying with fallback defaults...")
                    await self._fill_modal_fields(page, modal, force_all=True)
                    await next_btn.click(force=True)
                    await asyncio.sleep(1.0)
            else:
                print("  [Notice] End of form steps reached.")
                break

        if not results["submitted"]:
            await self._dismiss_modal(page)

        return results

    async def _fill_modal_fields(self, page: Page, modal, force_all: bool = False) -> int:
        count = 0

        # 1. Text, Number & Textarea Inputs
        input_locators = modal.locator('input:not([type="hidden"]):not([type="file"]):not([type="radio"]):not([type="checkbox"]), textarea')
        num_inputs = await input_locators.count()

        for i in range(num_inputs):
            inp = input_locators.nth(i)
            try:
                if not await inp.is_visible():
                    continue

                curr_val = await inp.input_value()
                if curr_val and len(curr_val.strip()) > 0 and not force_all:
                    continue

                label_text = await page.evaluate(
                    """
                    (el) => {
                        if (el.id) {
                            const lbl = document.querySelector(`label[for="${el.id}"]`);
                            if (lbl && lbl.innerText) return lbl.innerText;
                        }
                        const parent = el.closest('.jobs-easy-apply-form-section__grouping, .fb-dash-form-element, .artdeco-text-input, div');
                        if (parent) {
                            const header = parent.querySelector('label, span, p, h3, legend');
                            if (header && header.innerText) return header.innerText;
                        }
                        return el.getAttribute('aria-label') || el.name || el.placeholder || '';
                    }
                    """,
                    await inp.element_handle()
                )
                combined = label_text.lower().strip()

                if any(k in combined for k in ["city", "location"]):
                    if not curr_val or len(curr_val.strip()) < 2:
                        await self._handle_location_typeahead(page, inp, "San Francisco, California")
                        count += 1
                    continue

                is_textarea = (await inp.get_attribute("type")) == "textarea" or (await page.evaluate("el => el.tagName", await inp.element_handle())) == "TEXTAREA"
                val = self._resolve_fast_answer(combined, is_textarea=is_textarea)

                if val:
                    await inp.fill(str(val))
                    count += 1
            except Exception:
                continue

        # 2. Radio Buttons
        fieldsets = modal.locator('fieldset')
        num_fs = await fieldsets.count()
        for i in range(num_fs):
            fs = fieldsets.nth(i)
            try:
                legend_text = (await fs.inner_text()).lower()
                if "sponsorship" in legend_text or "visa" in legend_text:
                    no_radio = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_radio.is_visible():
                        await no_radio.click()
                        count += 1
                elif any(k in legend_text for k in ["authorized", "legally", "eligible", "citizen"]):
                    yes_radio = fs.locator('label:has-text("Yes"), input[value="Yes"]').first
                    if await yes_radio.is_visible():
                        await yes_radio.click()
                        count += 1
                else:
                    checked = fs.locator('input[type="radio"]:checked')
                    if await checked.count() == 0:
                        first_radio = fs.locator('label, input[type="radio"]').first
                        if await first_radio.is_visible():
                            await first_radio.click()
                            count += 1
            except Exception:
                continue

        # 3. Dropdowns
        selects = modal.locator('select')
        num_sel = await selects.count()
        for i in range(num_sel):
            sel = selects.nth(i)
            try:
                if not await sel.is_visible():
                    continue
                curr_sel = await sel.input_value()
                if not curr_sel or curr_sel in ["Select an option", ""]:
                    options = await sel.inner_text()
                    if "Yes" in options:
                        await sel.select_option(label="Yes")
                    elif "United States" in options:
                        await sel.select_option(label="United States")
                    else:
                        await sel.select_option(index=1)
                    count += 1
            except Exception:
                continue

        return count