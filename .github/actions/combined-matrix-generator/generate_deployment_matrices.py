#!/usr/bin/env python3
import os
import sys
import json
import yaml
import re
import subprocess
from typing import List, Dict, Any, Optional


def log(message: str) -> None:
    """Print a log message."""
    print(message)


def warning(message: str) -> None:
    """Print a GitHub Actions warning message."""
    print(f"::warning::{message}")


def load_yaml_config(file_path: str) -> Dict[str, Any]:
    """Load YAML configuration file and convert to dict."""
    try:
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        warning(f"Error loading YAML file {file_path}: {str(e)}")
        return {}


def main():
    """Main function to generate deployment matrices."""
    # Initialize empty lists for matrix items
    dev_matrix_items = []
    int_matrix_items = []
    prod_matrix_items = []
    custom_matrix_items = []
    
    # Get inputs from environment variables
    resource_paths = os.environ.get("INPUT_RESOURCE_PATHS", "")
    specific_environment = os.environ.get("INPUT_SPECIFIC_ENVIRONMENT", "")
    
    # Get GitHub output file path
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if not github_output:
        log("GITHUB_OUTPUT environment variable not set")
        sys.exit(1)
    
    # Split input resource paths by comma
    if not resource_paths:
        resource_paths_list = []
    else:
        resource_paths_list = [path.strip() for path in resource_paths.split(',') if path.strip()]
    
    # Process each resource path
    for resource_path in resource_paths_list:
        log(f"Processing resource path: {resource_path}")
        
        # Try both YAML and YML extensions
        config_path = f"{resource_path}/deployment-config.yaml"
        if not os.path.isfile(config_path):
            config_path = f"{resource_path}/deployment-config.yml"
            if not os.path.isfile(config_path):
                warning(f"Configuration file not found for {resource_path}")
                continue
        
        # Read YAML config file
        log(f"Reading YAML configuration from {config_path}")
        config_content = load_yaml_config(config_path)
        
        # Validate config structure
        if not config_content or not isinstance(config_content, dict):
            warning(f"Invalid YAML structure in {config_path}")
            continue
        
        # Extract app and resource from path
        app = os.path.dirname(resource_path)
        resource = os.path.basename(resource_path)
        
        log(f"Using APP={app} and RESOURCE={resource}")
        
        # Get deployments and validate
        deployments = config_content.get('deployments', [])
        if not deployments or not isinstance(deployments, list) or not deployments[0]:
            warning(f"No deployments found in {config_path}")
            continue
        
        # Get environments list
        environments = deployments[0].get('environments', [])
        if not environments:
            warning(f"No environments found in {config_path}")
            continue
        
        log(f"Found environments: {' '.join(environments)}")
        
        # Filter by specific environment if provided
        if specific_environment:
            if ',' in specific_environment:
                # Multiple environments specified
                selected_envs = [env.strip() for env in specific_environment.split(',') if env.strip()]
                log(f"Multiple environments selected: {selected_envs}")
                
                # Create regex pattern for matching
                selected_envs_pattern = f"^({'|'.join(selected_envs)})$"
                log(f"Environment regex pattern: {selected_envs_pattern}")
                
                # Filter environments
                filtered_environments = []
                for env_candidate in environments:
                    if re.match(selected_envs_pattern, env_candidate):
                        filtered_environments.append(env_candidate)
                        log(f"Selected environment: {env_candidate}")
                
                if not filtered_environments:
                    warning(f"None of the specified environments found in {config_path}")
                    continue
                
                environments = filtered_environments
                log(f"Filtered environments: {' '.join(environments)}")
            else:
                # Single environment specified
                if specific_environment in environments:
                    environments = [specific_environment]
                else:
                    warning(f"Specified environment not found in {config_path}")
                    continue
        
        # Process each environment for this resource
        for env in environments:
            log(f"Processing environment: {env} for {resource_path}")
            
            # Extract deployment configuration
            deployment = deployments[0]
            
            # Extract parameters
            params = deployment.get('parameters', {}).get(env, {})
            runner = deployment.get('runners', {}).get(env)
            gh_env = deployment.get('github_environments', {}).get(env)
            aws_region = deployment.get('aws_regions', {}).get(env)
            aws_role_secret = deployment.get('aws_role_secrets', {}).get(env, "AWS_ROLE_TO_ASSUME")
            cfn_role_secret = deployment.get('cfn_role_secrets', {}).get(env, "CFN_ROLE_ARN")
            iam_role_secret = deployment.get('iam_execution_role_secrets', {}).get(env, "IAM_EXECUTION_ROLE_ARN")
            vars_config = deployment.get('github_vars', {}).get(env, {})
            secret_pass = params.get('secret_pass', False)
            
            # Check if custom deployment is enabled for this environment
            custom_deployment = str(params.get('custom_deployment', "false")).lower()
            log(f"Custom deployment for {env}: {custom_deployment}")
            
            # Skip if any required field is empty
            if (not params or params is None or 
                not runner or runner is None or 
                not gh_env or gh_env is None or 
                not aws_region or aws_region is None):
                warning(f"Missing required configuration for {resource_path} in {env} environment")
                continue
            
            # Create matrix item
            matrix_item = {
                "application": app,
                "resource": resource,
                "environment": env,
                "runner": runner,
                "github_environment": gh_env,
                "aws_region": aws_region,
                "aws_role_secret": aws_role_secret,
                "cfn_role_secret": cfn_role_secret,
                "iam_role_secret": iam_role_secret,
                "github_vars": vars_config,
                "secret_pass": secret_pass,
                "parameters": params
            }
            
            # Add to appropriate matrix based on environment
            if env == "dev":
                dev_matrix_items.append(matrix_item)
            elif env == "int":
                int_matrix_items.append(matrix_item)
            elif env == "prod":
                prod_matrix_items.append(matrix_item)
            
            # Add to custom deployment matrix if enabled
            if custom_deployment == "true":
                custom_matrix_items.append(matrix_item)
    
    # Construct environment-specific matrices
    dev_matrix_json = {"include": dev_matrix_items}
    int_matrix_json = {"include": int_matrix_items}
    prod_matrix_json = {"include": prod_matrix_items}
    custom_matrix_json = {"include": custom_matrix_items}
    
    # Convert to JSON strings
    dev_matrix_str = json.dumps(dev_matrix_json, ensure_ascii=False)
    int_matrix_str = json.dumps(int_matrix_json, ensure_ascii=False)
    prod_matrix_str = json.dumps(prod_matrix_json, ensure_ascii=False)
    custom_matrix_str = json.dumps(custom_matrix_json, ensure_ascii=False)
    
    # Write matrices to GITHUB_OUTPUT
    with open(github_output, 'a') as f:
        f.write(f"dev_matrix<<EOF\n{dev_matrix_str}\nEOF\n")
        f.write(f"int_matrix<<EOF\n{int_matrix_str}\nEOF\n")
        f.write(f"prod_matrix<<EOF\n{prod_matrix_str}\nEOF\n")
        f.write(f"custom_matrix<<EOF\n{custom_matrix_str}\nEOF\n")


if __name__ == "__main__":
    main()