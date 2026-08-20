import sys
import yaml
import asyncio
from src.agents.form_agent import FormAutomationAgent
from src.core.llm_client import GeminiFlashClient
from src.mcp.tools.browser import StealthBrowserTool


async def test_apply(target_url: str):
    print(f"\n[Testing Target URL]: {target_url}")
    with open("config/settings.yaml", "r") as f:
        settings = yaml.safe_load(f)

    browser_tool = StealthBrowserTool(
        headless=False,
        user_data_dir=settings["automation_safety"]["user_data_dir"]
    )
    await browser_tool.initialize()

    llm_client = GeminiFlashClient(model_name="gemini-2.5-flash")
    form_agent = FormAutomationAgent(browser_tool, llm_client)

    try:
        page = await browser_tool.get_page(target_url)
        res = await form_agent.process_linkedin_application(page, "single_test", "Staff Software Engineer", "TestCorp")
        print(f"\n[Result]: {res}")
        await asyncio.sleep(5)
    finally:
        await browser_tool.close()


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.linkedin.com/jobs/view/4429707612/"
    asyncio.run(test_apply(url))