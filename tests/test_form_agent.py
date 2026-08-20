import os
import pytest
from src.core.llm_client import GeminiFlashClient
from src.mcp.tools.browser import StealthBrowserTool
from src.agents.form_agent import FormAutomationAgent


@pytest.mark.asyncio
async def test_form_agent_pdf_upload(tmp_path):
    # 1. Create a mock HTML application form
    mock_form_html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Mock Job Application</title></head>
    <body style="padding: 20px;">
        <h2>Apply for Staff AI Software Engineer</h2>
        <form id="app-form">
            <label for="name">Full Name</label><br>
            <input type="text" id="name" name="name"><br><br>

            <label for="email">Email Address</label><br>
            <input type="email" id="email" name="email"><br><br>

            <label for="linkedin">LinkedIn Profile</label><br>
            <input type="text" id="linkedin" name="linkedin"><br><br>

            <label for="resume">Upload Resume (PDF)</label><br>
            <input type="file" id="resume" name="resume" accept=".pdf"><br><br>

            <button type="button" id="submit-btn">Submit Application</button>
        </form>
    </body>
    </html>
    """
    mock_form_path = os.path.join(tmp_path, "mock_job_portal.html")
    with open(mock_form_path, "w") as f:
        f.write(mock_form_html)

    # 2. Ensure test PDF exists
    os.makedirs("data", exist_ok=True)
    pdf_test_path = "data/Resume_Swikar_Patel.pdf"
    if not os.path.exists(pdf_test_path):
        with open(pdf_test_path, "wb") as f:
            f.write(b"%PDF-1.4 Mock PDF Content")

    # 3. Execute Browser & Form Agent
    browser_tool = StealthBrowserTool(headless=True)
    await browser_tool.initialize()
    llm_client = GeminiFlashClient(model_name="gemini-2.5-flash")
    agent = FormAutomationAgent(browser_tool, llm_client)

    page = await browser_tool.get_page(f"file://{mock_form_path}")
    result = await agent.process_application_form(page, "test_job_01", "Staff AI Engineer", "MockCorp")

    await browser_tool.close()

    # 4. Assertions
    assert result["resume_uploaded"] is True
    assert len(result["fields_filled"]) >= 3
    assert os.path.exists(result["screenshot_path"])
    print(f"\n[SUCCESS] Uploaded {pdf_test_path} and filled fields: {result['fields_filled']}")