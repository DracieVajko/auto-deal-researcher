import json
import os
from datetime import datetime
import markdown

class ResultProcessor:
    def __init__(self, config):
        self.config = config
        
    def save_results(self, results, output_dir="results"):
        """Save results in both JSON and Markdown formats"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Save as JSON
        json_path = os.path.join(output_dir, f"results_{timestamp}.json")
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2)
            
        # Convert to Markdown
        md_content = self._convert_to_markdown(results, timestamp)
        md_path = os.path.join(output_dir, f"results_{timestamp}.md")
        with open(md_path, 'w') as f:
            f.write(md_content)
            
        return json_path, md_path
        
    def _convert_to_markdown(self, results, timestamp):
        """Convert search results to Markdown format"""
        md = f"# Deal Search Results - {timestamp}\n\n"
        md += "| Website | Product | Price | Link |\n"
        md += "|---------|---------|-----|------|\n"
        
        for result in results:
            for item in result.get('results', []):
                md += f"| {result['website']} | {item.get('title', 'N/A')} | {item.get('price', 'N/A')} | [{item.get('link', '#')}]({item.get('link', '#')} ) |\n"
                
        return md