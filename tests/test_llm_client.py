import json
import yaml
import pytest
from src.core.llm_client import GeminiFlashClient


from google.genai.errors import ClientError


def test_gemini_flash_evaluation_and_tailoring():
    # 1. Load Configurations & Master Resume
    with open("config/truth_matrix.yaml", "r") as f:
        truth_matrix = yaml.safe_load(f)
    with open("data/master_resume.json", "r") as f:
        master_resume = json.load(f)

    try:
        client = GeminiFlashClient(model_name="gemini-2.5-flash")
    except Exception as e:
        pytest.skip(f"Gemini client setup skipped: {e}")

    job_description = """
    Palo Alto Networks is hiring a Sr Staff Software Engineer (AI) for Prisma Access.
    Key responsibilities:
    - Build scalable backend services in Python / Go.
    - LLM orchestration pipelines and structured output generation.
    - Design guardrails, zero-trust token vaults, and RAG pipelines using vector search.
    - Optimize latency for sub-50ms p99 performance.
    """

    # 2. Test Match Evaluation (Flash)
    try:
        evaluation = client.evaluate_job_match(
            job_id="test_panw_001",
            job_title="Sr Staff Software Engineer (AI)",
            company="Palo Alto Networks",
            description=job_description,
            candidate_summary=master_resume["basics"]["summary"],
            truth_matrix=truth_matrix
        )
    except ClientError as e:
        if "UNAUTHENTICATED" in str(e) or "401" in str(e):
            pytest.skip("Google Gemini API Key in .env is not yet authenticated or invalid. Skipping live API test.")
        raise


    assert evaluation.fit_score >= 75
    assert evaluation.matches_hard_criteria is True
    assert len(evaluation.key_matching_skills) > 0
    print(f"\n[Gemini Flash] Fit Score: {evaluation.fit_score}% | Reasoning: {evaluation.strategic_reasoning}")

    # 3. Test Resume Tailoring (Flash)
    tailored = client.tailor_resume_content(
        job_id="test_panw_001",
        job_title="Sr Staff Software Engineer (AI)",
        company="Palo Alto Networks",
        description=job_description,
        master_resume=master_resume
    )

    assert len(tailored.selected_experiences) > 0
    assert "Palo Alto Networks" in tailored.executive_summary or "Prisma Access" in tailored.executive_summary or "Staff" in tailored.executive_summary
    print(f"\n[Gemini Flash] Tailored Summary: {tailored.executive_summary[:150]}...")