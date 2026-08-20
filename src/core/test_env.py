import os
import yaml
from dotenv import load_dotenv
from google import genai
from rich.console import Console

console = Console()

def test_setup():
    load_dotenv()
    
    # 1. Test YAML Configuration Loading
    with open("config/settings.yaml", "r") as f:
        settings = yaml.safe_load(f)
    with open("config/truth_matrix.yaml", "r") as f:
        truth = yaml.safe_load(f)
        
    console.print(f"[green]✓[/green] Loaded configs for: [bold]{truth['candidate']['full_name']}[/bold]")
    console.print(f"[green]✓[/green] Target model: [bold]{settings['llm_routing']['fast_model']}[/bold]")
    
    # 2. Check API Key Presence
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or "your_actual" in api_key:
        console.print("[yellow]![/yellow] [bold yellow]GEMINI_API_KEY[/bold yellow] not set in .env. Add your real key.")
    else:
        client = genai.Client(api_key=api_key)
        console.print("[green]✓[/green] Gemini Client initialized successfully.")

if __name__ == "__main__":
    test_setup()