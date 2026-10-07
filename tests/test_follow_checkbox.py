import os
import pytest
from playwright.async_api import Page
from src.agents.form_agent import FormAutomationAgent
from src.core.llm_client import GeminiFlashClient
from src.mcp.tools.browser import StealthBrowserTool


@pytest.mark.asyncio
async def test_uncheck_follow_company_guarantee(tmp_path):
    # 1. Create a mock LinkedIn final review page with multiple checked follow checkboxes
    mock_html = """
    <!DOCTYPE html>
    <html>
    <head><title>LinkedIn Easy Apply Review</title></head>
    <body>
        <div role="dialog" class="jobs-easy-apply-modal">
            <h3>Review your application</h3>

            <!-- Checkbox 1: Standard LinkedIn ID -->
            <div>
                <input type="checkbox" id="follow-company-checkbox" checked>
                <label for="follow-company-checkbox">Follow Netflix to stay up to date with their page.</label>
            </div>

            <!-- Checkbox 2: Wrapped in container with follow text -->
            <div class="follow-wrapper">
                <label>
                    <input type="checkbox" name="follow-company" checked>
                    Follow Stripe to get updates about new jobs
                </label>
            </div>

            <!-- Checkbox 3: Unrelated checkbox that SHOULD remain checked (e.g. Terms) -->
            <div>
                <input type="checkbox" id="terms-agree" checked>
                <label for="terms-agree">I agree to the terms and conditions</label>
            </div>

            <button type="button" aria-label="Submit application">Submit application</button>
        </div>
    </body>
    </html>
    """
    mock_file = os.path.join(tmp_path, "mock_review.html")
    with open(mock_file, "w", encoding="utf-8") as f:
        f.write(mock_html)

    browser_tool = StealthBrowserTool(headless=True)
    await browser_tool.initialize()
    llm = GeminiFlashClient(model_name="gemini-2.5-flash")
    agent = FormAutomationAgent(browser_tool, llm)

    try:
        page: Page = await browser_tool.get_page(f"file://{mock_file}")
        modal = page.locator('div[role="dialog"]').first

        # Verify initial state: both follow checkboxes are checked
        assert await page.locator("#follow-company-checkbox").is_checked() is True
        assert await page.locator('input[name="follow-company"]').is_checked() is True
        assert await page.locator("#terms-agree").is_checked() is True

        # Run safety uncheck method
        did_uncheck = await agent.uncheck_follow_company(page, modal)
        assert did_uncheck is True

        # STRICT ASSERTIONS:
        # 1. Follow company checkboxes MUST be unchecked
        assert await page.locator("#follow-company-checkbox").is_checked() is False
        assert await page.locator('input[name="follow-company"]').is_checked() is False

        # 2. Terms checkbox was not a follow checkbox, should not be disturbed
        assert await page.locator("#terms-agree").is_checked() is True

        # 3. Calling it a SECOND time must NOT toggle them back to checked!
        await agent.uncheck_follow_company(page, modal)
        assert await page.locator("#follow-company-checkbox").is_checked() is False
        assert await page.locator('input[name="follow-company"]').is_checked() is False
    finally:
        await browser_tool.close()
