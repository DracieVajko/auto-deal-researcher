from .models import AppConfig
import yaml
import os

def load_config(config_path="config.yaml"):
    """Load configuration from YAML file"""
    # Check if config file exists
    if not os.path.exists(config_path):
        # Return default configuration
        return AppConfig(search=SearchConfig(
            websites=[],
            llm=LLMConfig()
        ))
    
    with open(config_path, 'r') as f:
        config_data = yaml.safe_load(f)
    
    return AppConfig(**config_data)