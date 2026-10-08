import asyncio
import json
import os
import re
import yaml
from typing import Any, Dict, List, Optional
from playwright.async_api import Page, Locator
from src.core.llm_client import GeminiFlashClient
from src.mcp.tools.browser import StealthBrowserTool


class FormAutomationAgent:
    def __init__(
        self,
        browser_tool: StealthBrowserTool,
        llm_client: GeminiFlashClient,
        config_path: str = "config/settings.yaml",
        truth_path: str = "config/truth_matrix.yaml",
        auto_submit: Optional[bool] = None
    ):
        self.browser = browser_tool
        self.llm = llm_client
        
        with open(config_path, "r", encoding="utf-8") as f:
            self.settings = yaml.safe_load(f)
        with open(truth_path, "r", encoding="utf-8") as f:
            self.truth = yaml.safe_load(f)
            
        resume_json = "data/master_resume.json"
        if os.path.exists(resume_json):
            with open(resume_json, "r", encoding="utf-8") as f:
                self.master_resume = json.load(f)
        else:
            self.master_resume = {}

        configured_pdf = self.settings.get("resume_attachment", {}).get("master_pdf_path", "data/ResumeSoftwareEngineer.pdf")
        self.pdf_path = os.path.abspath(configured_pdf)
        # 100% Autonomous: HITL is permanently disabled; always auto-submit
        self.auto_submit = True
        self.step_delay = self.settings.get("automation_safety", {}).get("step_inspection_delay_seconds", 0.4)

    async def uncheck_follow_company(self, page: Page, modal: Locator) -> bool:
        """
        STRICT GUARANTEE: Never follow any company.
        Finds and forces ANY 'Follow company / stay up to date' checkbox to UNCHECKED.
        Only modifies checkboxes if currently checked, preventing accidental toggle on.
        """
        did_uncheck = False
        try:
            # 1. Direct in-browser JavaScript DOM scan
            unchecked_count = await page.evaluate("""() => {
                let count = 0;
                const checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"]'));
                for (const chk of checkboxes) {
                    const id = (chk.id || '').toLowerCase();
                    const name = (chk.name || '').toLowerCase();
                    const aria = (chk.getAttribute('aria-label') || '').toLowerCase();
                    const parent = chk.closest('label, div, li, fieldset') || chk.parentElement;
                    const text = parent ? (parent.innerText || '').toLowerCase() : '';
                    
                    const isFollow = id.includes('follow') || 
                                     name.includes('follow') || 
                                     aria.includes('follow') || 
                                     text.includes('follow') || 
                                     text.includes('stay up to date') ||
                                     text.includes('company updates');
                    
                    if (isFollow && chk.checked) {
                        chk.click();
                        chk.checked = false;
                        chk.dispatchEvent(new Event('change', { bubbles: true }));
                        chk.dispatchEvent(new Event('input', { bubbles: true }));
                        count++;
                    }
                }
                return count;
            }""")

            if unchecked_count and unchecked_count > 0:
                print(f"  [Safety Policy] ✓ UNCHECKED {unchecked_count} 'Follow Company' checkbox(es) via DOM.")
                did_uncheck = True

            # 2. Playwright locators verification
            selectors = [
                'input#follow-company-checkbox',
                'input[name*="follow"]',
                'label[for*="follow-company"]',
                'div:has-text("stay up to date") input[type="checkbox"]',
                'div:has-text("Follow") input[type="checkbox"]'
            ]
            for sel in selectors:
                locs = modal.locator(sel)
                count = await locs.count()
                for i in range(count):
                    el = locs.nth(i)
                    try:
                        tag = await el.evaluate("el => el.tagName.toLowerCase()")
                        if tag == "input" and await el.is_checked():
                            await el.uncheck(force=True)
                            print("  [Safety Policy] ✓ Explicitly unchecked follow company checkbox via Playwright.")
                            did_uncheck = True
                        elif tag == "label":
                            for_id = await el.get_attribute("for")
                            if for_id:
                                inp = modal.locator(f"#{for_id}").first
                                if await inp.count() > 0 and await inp.is_checked():
                                    await el.click(force=True)
                                    print("  [Safety Policy] ✓ Unchecked follow company via label click.")
                                    did_uncheck = True
                    except Exception:
                        pass
        except Exception as e:
            print(f"  [Safety Warning] Checkbox inspector: {e}")

        return did_uncheck

    def _resolve_fast_answer(self, combined_text: str, is_textarea: bool = False) -> str:
        """High-speed deterministic resolution using candidate truth matrix."""
        q = combined_text.lower()
        c = self.truth.get("candidate", {})
        comp = self.truth.get("compensation", {})
        skills = self.truth.get("skills_experience_years", {})
        edu = self.truth.get("education", {})
        canned = self.truth.get("canned_essays", {})

        # Block Referrer fields
        if any(k in q for k in ["referred by", "employee name", "referrer", "who referred"]):
            return ""

        # Specific skill experience years
        if any(k in q for k in ["how many years", "years of experience", "years of work", "years"]):
            for skill_key, years in skills.items():
                clean_key = skill_key.replace("_", " ")
                if clean_key in q:
                    return str(years)
            return str(skills.get("default_years", 6))

        # Notice period & availability
        if "notice" in q or "availability" in q:
            if "day" in q:
                return str(comp.get("notice_period_days", 5))
            return str(comp.get("notice_period_weeks", 1))

        # Compensation
        if any(k in q for k in ["salary", "compensation", "pay", "rate", "remuneration", "expectation"]):
            if "hour" in q:
                return str(comp.get("target_hourly_rate_usd", 65))
            return str(comp.get("target_base_salary_min_usd", 120000))

        # Education
        if "gpa" in q:
            return str(edu.get("gpa", "3.8"))
        if "school" in q or "university" in q or "college" in q:
            return edu.get("school", "James Cook University")
        if "degree" in q:
            return edu.get("degree", "Bachelor of Science")
        if "major" in q or "field of study" in q:
            return edu.get("field_of_study", "Computer Science")

        # Identity & Contact
        if any(k in q for k in ["full name", "your name"]) or q == "name":
            return c.get("full_name", f"{c.get('first_name', 'Swikar')} {c.get('last_name', 'Patel')}").strip()
        if any(k in q for k in ["first name", "given name", "first_name"]):
            return c.get("first_name", "Swikar")
        if any(k in q for k in ["last name", "family name", "surname", "last_name"]):
            return c.get("last_name", "Patel")
        if "phone" in q or "mobile" in q:
            return c.get("phone", "9514631792")
        if "email" in q:
            return c.get("email", "swikar.aus@gmail.com")
        if "linkedin" in q:
            return c.get("linkedin", "https://linkedin.com/in/swikar")
        if "github" in q:
            return c.get("github", "https://github.com/swikarpat?tab=repositories")
        if any(k in q for k in ["postal", "zip"]):
            return c.get("postal_code", "94105")

        # Textarea Essays
        if is_textarea:
            if any(k in q for k in ["why", "interest", "cover"]):
                return canned.get("why_interested", "I bring extensive experience architecting distributed systems and production AI.")
            return canned.get("summary", "Staff AI & Distributed Systems Engineer with 6+ years building high-throughput microservices.")

        # Default fallback years for unlabeled numeric boxes
        return str(skills.get("default_years", 6))

    async def _handle_location_typeahead(self, page: Page, input_locator: Locator, target_city: str = "San Francisco, California"):
        try:
            await input_locator.click()
            await input_locator.fill("")
            await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
            await input_locator.press_sequentially(target_city, delay=25)
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
                await asyncio.sleep(0.4)
                discard_btn = page.locator('button[data-control-name="discard_application_confirm_btn"], button:has-text("Discard")').first
                if await discard_btn.is_visible():
                    await discard_btn.click()
                    await asyncio.sleep(0.4)
        except Exception:
            pass

    async def _fill_modal_fields(self, page: Page, modal: Locator, force_all: bool = False) -> int:
        count = 0
        target_location = self.truth.get("candidate", {}).get("location_query", "San Francisco, California")

        # 1. Text Inputs & Textareas
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
                    """(el) => {
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
                    }""",
                    await inp.element_handle()
                )
                combined = label_text.lower().strip()

                # Location Typeahead
                if any(k in combined for k in ["city", "location"]):
                    if not curr_val or len(curr_val.strip()) < 2:
                        await self._handle_location_typeahead(page, inp, target_location)
                        count += 1
                    continue

                # Referrals
                if any(k in combined for k in ["referred by", "employee name", "referrer"]):
                    await inp.fill("")
                    continue

                # Phone number
                if any(k in combined for k in ["phone", "mobile"]):
                    phone = self.truth.get("candidate", {}).get("phone", "9514631792")
                    await inp.fill(phone)
                    count += 1
                    continue

                is_ta = (await inp.get_attribute("type")) == "textarea" or (await page.evaluate("el => el.tagName", await inp.element_handle())) == "TEXTAREA"
                val = self._resolve_fast_answer(combined, is_textarea=is_ta)

                # AI Fallback for unmapped question
                if not val and self.llm and self.llm.is_active:
                    val = self.llm.resolve_form_question(label_text, None, self.truth)

                if val:
                    await inp.fill(str(val))
                    count += 1
            except Exception:
                continue

        # 2. Radio Buttons
        fieldsets = modal.locator('fieldset, .fb-form-element__fieldset, div[role="radiogroup"]')
        num_fs = await fieldsets.count()
        for i in range(num_fs):
            fs = fieldsets.nth(i)
            try:
                checked = fs.locator('input[type="radio"]:checked')
                if await checked.count() > 0 and not force_all:
                    continue

                txt = (await fs.inner_text()).lower()

                # Sponsorship -> NO
                if "sponsorship" in txt or "visa" in txt:
                    no_r = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_r.is_visible():
                        await no_r.click(force=True)
                        count += 1
                # Authorized -> YES
                elif any(k in txt for k in ["authorized", "legally", "eligible", "citizen"]):
                    yes_r = fs.locator('label:has-text("Yes"), input[value="Yes"]').first
                    if await yes_r.is_visible():
                        await yes_r.click(force=True)
                        count += 1
                # Commute / Hybrid / Relocate -> YES
                elif any(k in txt for k in ["commute", "relocate", "hybrid", "onsite", "in-person", "willing"]):
                    yes_r = fs.locator('label:has-text("Yes"), input[value="Yes"]').first
                    if await yes_r.is_visible():
                        await yes_r.click(force=True)
                        count += 1
                # Drug test / Background check -> YES
                elif any(k in txt for k in ["background check", "drug test", "drug screen"]):
                    yes_r = fs.locator('label:has-text("Yes"), input[value="Yes"]').first
                    if await yes_r.is_visible():
                        await yes_r.click(force=True)
                        count += 1
                # Felony / Conviction -> NO
                elif any(k in txt for k in ["felony", "convict", "criminal"]):
                    no_r = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_r.is_visible():
                        await no_r.click(force=True)
                        count += 1
                # Hispanic / Latino -> NO
                elif "hispanic" in txt or "latino" in txt:
                    no_r = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_r.is_visible():
                        await no_r.click(force=True)
                        count += 1
                # Internal Referral -> NO
                elif any(k in txt for k in ["referred by", "internal employee", "referral"]):
                    no_r = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_r.is_visible():
                        await no_r.click(force=True)
                        count += 1
                # Demographic / EEO -> Decline
                elif any(k in txt for k in ["disability", "veteran", "gender", "race", "ethnic", "equal opportunity", "armed forces"]):
                    decline_r = fs.locator(
                        'label:has-text("I don\'t wish to answer"), '
                        'label:has-text("Decline"), '
                        'label:has-text("No, I am not"), '
                        'label:has-text("No")'
                    ).first
                    if await decline_r.is_visible():
                        await decline_r.click(force=True)
                        count += 1
                    else:
                        first_r = fs.locator('label, input[type="radio"]').first
                        if await first_r.is_visible():
                            await first_r.click(force=True)
                            count += 1
                else:
                    # Generic fallback: default to No for unknown inquiries
                    no_fallback = fs.locator('label:has-text("No"), input[value="No"]').first
                    if await no_fallback.is_visible():
                        await no_fallback.click(force=True)
                        count += 1
                    else:
                        first_r = fs.locator('label, input[type="radio"]').first
                        if await first_r.is_visible():
                            await first_r.click(force=True)
                            count += 1
            except Exception:
                continue

        # 3. Dynamic Dropdowns
        target_salary = self.truth.get("compensation", {}).get("target_base_salary_min_usd", 120000)
        try:
            await page.evaluate(
                f"""() => {{
                    const targetSalary = {target_salary};
                    const selects = Array.from(document.querySelectorAll('select'));
                    for (const sel of selects) {{
                        if (sel.offsetParent === null) continue;
                        
                        const parentText = (sel.closest('.jobs-easy-apply-form-section__grouping, .fb-dash-form-element, div')?.innerText || '').toLowerCase();
                        const options = Array.from(sel.options);
                        const selectedIdx = sel.selectedIndex;
                        const currentText = selectedIdx >= 0 ? options[selectedIdx].text.toLowerCase() : '';

                        if (currentText.includes('select an option') || currentText === '' || sel.value === '') {{
                            let targetIdx = -1;

                            if (parentText.includes('hispanic') || parentText.includes('latino') || parentText.includes('referred') || parentText.includes('sponsorship') || parentText.includes('visa')) {{
                                targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('no'));
                            }} else if (parentText.includes('authorized') || parentText.includes('hybrid') || parentText.includes('commute') || parentText.includes('relocate') || parentText.includes('clearance')) {{
                                targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('yes'));
                            }} else if (parentText.includes('salary') || parentText.includes('compensation') || parentText.includes('expectation')) {{
                                for (let i = 0; i < options.length; i++) {{
                                    const optText = options[i].text.replace(/,/g, '');
                                    const nums = optText.match(/\\d+/g);
                                    if (nums && nums.length > 0) {{
                                        const maxVal = Math.max(...nums.map(Number));
                                        const realVal = maxVal < 1000 ? maxVal * 1000 : maxVal;
                                        if (realVal >= targetSalary) {{
                                            targetIdx = i;
                                            break;
                                        }}
                                    }}
                                }}
                                if (targetIdx === -1) targetIdx = options.length - 1;
                            }} else if (parentText.includes('disability') || parentText.includes('veteran') || parentText.includes('gender')) {{
                                targetIdx = options.findIndex(o => o.text.toLowerCase().includes('wish to answer') || o.text.toLowerCase().includes('decline') || o.text.toLowerCase().startsWith('no'));
                            }}

                            if (targetIdx === -1) {{
                                targetIdx = options.findIndex(o => o.text.toLowerCase().startsWith('yes'));
                            }}
                            if (targetIdx === -1 && options.length > 1) {{
                                targetIdx = 1;
                            }}

                            if (targetIdx !== -1) {{
                                sel.selectedIndex = targetIdx;
                                sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                sel.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            }}
                        }}
                    }}
                }}"""
            )
        except Exception:
            pass

        # CRITICAL: Always uncheck follow company after filling fields
        await self.uncheck_follow_company(page, modal)
        return count

    async def process_linkedin_application(
        self,
        page: Page,
        job_id: str,
        job_title: str,
        company: str
    ) -> Dict[str, Any]:
        """
        Executes end-to-end 100% autonomous LinkedIn Easy Apply traversal:
        - Detects & clicks Easy Apply
        - Traverses multi-step forms
        - Automatically uploads master PDF resume
        - Fills contact, screening questions, radios, dropdowns
        - GUARANTEES 'Follow company' is explicitly UNCHECKED
        - Submits application automatically
        - Closes completion confirmation card
        """
        results = {
            "job_id": job_id,
            "company": company,
            "job_title": job_title,
            "resume_uploaded": False,
            "fields_filled": [],
            "submitted": False,
            "status": "FAILED",
            "screenshot_path": ""
        }

        # 1. Login Gatekeeper
        if any(k in page.url for k in ["login", "signup", "checkpoint", "authwall"]):
            print("  [Auth Warning] LinkedIn login wall encountered. Please authenticate.")
            return results

        # 2. Scoped Top-Card Easy Apply Button
        top_card_selectors = [
            '.jobs-details__main-content button:has-text("Easy Apply")',
            '.jobs-apply-button--top-card button:has-text("Easy Apply")',
            '.jobs-s-apply button:has-text("Easy Apply")',
            'button.jobs-apply-button:has-text("Easy Apply")',
            'button:has-text("Easy Apply")'
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
            print(f"  [Notice] '{job_title}' does not have Easy Apply badge (External Apply only). Skipping.")
            results["status"] = "SKIPPED"
            return results

        print(f"  [Action] Found 'Easy Apply' for '{job_title}' @ '{company}'. Opening dialog...")
        await apply_btn.scroll_into_view_if_needed()
        await apply_btn.click(force=True)

        # 3. Wait for Modal Dialog
        modal = page.locator('div[role="dialog"].jobs-easy-apply-modal, div.jobs-easy-apply-modal, #artdeco-modal-outlet .artdeco-modal, div[role="dialog"]').first
        try:
            await modal.wait_for(state="visible", timeout=7000)
            print("  [Modal] Easy Apply dialog active.")
        except Exception:
            print("  [Error] Easy Apply modal failed to render.")
            await self._dismiss_modal(page)
            return results

        submitted = False
        try:
            for step in range(1, 12):
                await asyncio.sleep(0.4)
                if not await modal.is_visible():
                    break

                # A. Resume Upload / Selection
                file_input = modal.locator('input[type="file"]').first
                if await file_input.count() > 0 and os.path.exists(self.pdf_path):
                    try:
                        await file_input.set_input_files(self.pdf_path)
                        results["resume_uploaded"] = True
                        print(f"  [Resume] ✓ Attached {os.path.basename(self.pdf_path)}")
                        await asyncio.sleep(0.6)
                    except Exception:
                        pass

                # B. Fill Active Form Fields
                filled = await self._fill_modal_fields(page, modal)
                print(f"  [Step {step}] Handled {filled} inputs.")

                # C. Scroll content down
                try:
                    await page.evaluate("""() => {
                        const content = document.querySelector('.jobs-easy-apply-modal__content, .artdeco-modal__content');
                        if (content) content.scrollTop = content.scrollHeight;
                    }""")
                except Exception:
                    pass

                # D. STRICT GUARANTEE: Uncheck Follow Company
                await self.uncheck_follow_company(page, modal)

                await asyncio.sleep(self.step_delay)

                submit_btn = modal.locator(
                    'button[aria-label="Submit application"], '
                    'button:has-text("Submit application")'
                ).first

                if await submit_btn.is_visible():
                    # Uncheck follow company right before submitting!
                    await self.uncheck_follow_company(page, modal)

                    print("  [Submit] 🚀 Auto-submitting application...")
                    await submit_btn.click(force=True)
                    await asyncio.sleep(2.0)

                    # Capture confirmation screenshot
                    screenshot_path = await self.browser.take_review_screenshot(page, job_id)
                    results["screenshot_path"] = screenshot_path
                    results["submitted"] = True
                    results["status"] = "SUBMITTED"
                    submitted = True
                    print(f"  [Success] ✓ APPLICATION SUBMITTED FOR '{company}'!")

                    # Close post-apply completion dialog
                    await asyncio.sleep(0.8)
                    try:
                        done_btn = page.locator(
                            'button:has-text("Done"), '
                            'button[aria-label="Done"], '
                            'button[aria-label="Dismiss"], '
                            'button:has-text("Dismiss")'
                        ).first
                        if await done_btn.is_visible():
                            await done_btn.click(force=True)
                            await asyncio.sleep(0.5)
                    except Exception:
                        pass
                    break

                # F. Click Next / Review Navigation
                next_btn = modal.locator(
                    'button[aria-label="Review your application"], '
                    'button[aria-label="Continue to next step"], '
                    'button:has-text("Review"), '
                    'button:has-text("Next")'
                ).first

                if await next_btn.is_visible():
                    btn_text = (await next_btn.inner_text()).strip()
                    print(f"  [Navigation] Clicking '{btn_text}'...")
                    await next_btn.click(force=True)
                    await asyncio.sleep(0.6)

                    # Validation error recovery
                    error_badge = modal.locator('.artdeco-inline-feedback--error, .fb-form-element--error').first
                    if await error_badge.is_visible():
                        print("  [Validation Recovery] Retrying required fields with fallback defaults...")
                        await self._fill_modal_fields(page, modal, force_all=True)
                        await next_btn.click(force=True)
                        await asyncio.sleep(0.8)
                else:
                    break
        finally:
            if not submitted:
                await self._dismiss_modal(page)

        return results

    async def process_application_form(
        self,
        page: Page,
        job_id: str,
        job_title: str,
        company: str
    ) -> Dict[str, Any]:
        """Generic adapter method for test suites and supervisor FSM."""
        if "linkedin.com" in page.url:
            return await self.process_linkedin_application(page, job_id, job_title, company)

        # Mock / generic form handling
        results = {
            "job_id": job_id,
            "resume_uploaded": False,
            "fields_filled": [],
            "submitted": False,
            "status": "COMPLETED",
            "screenshot_path": ""
        }

        test_pdf = os.path.abspath("data/Resume_Swikar_Patel.pdf")
        pdf_to_use = test_pdf if os.path.exists(test_pdf) else self.pdf_path
        if os.path.exists(pdf_to_use):
            uploaded = await self.browser.upload_master_pdf(page, pdf_to_use)
            results["resume_uploaded"] = uploaded

        count = await self._fill_modal_fields(page, page, force_all=True)
        results["fields_filled"] = [f"field_{i+1}" for i in range(count)]

        screenshot_path = await self.browser.take_review_screenshot(page, job_id)
        results["screenshot_path"] = screenshot_path
        return results