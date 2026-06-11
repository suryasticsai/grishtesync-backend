"""
Hugging Face Space Configuration Helper
Loads config from YAML file and provides helpers for Space creation
"""

import os
import yaml
from pathlib import Path

class HFConfig:
    """Manages Hugging Face Space configuration from external YAML file"""
    
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
    
    def get_sdk_version(self, sdk):
        """Get default version for an SDK"""
        return self.config['huggingface']['sdk_versions'].get(sdk, "4.0")
    
    def get_python_version(self):
        """Get default Python version"""
        return self.config['huggingface']['python_version']
    
    def get_readme_template(self, sdk):
        """Get README template for an SDK"""
        templates = self.config['huggingface']['readme_templates']
        
        # Map framework to SDK
        if sdk == "docker":
            return templates.get('docker', templates['gradio'])
        elif sdk == "gradio":
            return templates.get('gradio', templates['gradio'])
        elif sdk == "streamlit":
            return templates.get('streamlit', templates['gradio'])
        else:
            return templates['gradio']
    
    def generate_readme(self, space_name, sdk):
        """Generate README.md content with proper YAML frontmatter"""
        template = self.get_readme_template(sdk)
        return template.format(space_name=space_name)
    
    def get_required_files(self, sdk):
        """Get list of required files for an SDK"""
        required = self.config['huggingface']['required_files']
        if sdk == "docker":
            return required.get('docker', [])
        elif sdk == "gradio":
            return required.get('gradio', [])
        elif sdk == "streamlit":
            return required.get('streamlit', [])
        return []
    
    def get_app_port(self):
        """Get default app port"""
        return self.config['huggingface']['app_port']
    
    def get_pr_template(self, version, files_list):
        """Generate PR description from template"""
        template = self.config['github']['pr_template']
        return template.format(version=version, files_list=files_list)
    
    def get_app_version(self):
        """Get app version"""
        return self.config['app']['version']
    
    def is_feature_enabled(self, feature):
        """Check if a feature is enabled"""
        return self.config['app'].get(feature, False)


# Create a global instance for easy import
hf_config = HFConfig()
