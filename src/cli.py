import typer
from src.config.loader import load_config
from src.searcher.playwright_searcher import PlaywrightSearcher
from src.browser.manager import BrowserManager

app = typer.Typer()

@app.command()
def search():
    """Run deal search"""
    config = load_config()
    typer.echo(f"Searching with config: {config.search}")

@app.command()
def run():
    """Run the full deal search process"""
    config = load_config()
    
    # Initialize browser manager
    browser_manager = BrowserManager(config)
    
    # Initialize searcher
    searcher = PlaywrightSearcher(browser_manager)
    
    typer.echo("Starting deal search...")
    typer.echo("Search completed.")

if __name__ == "__main__":
    app()