"""
Generate Deployment Matrices

This script processes CloudFormation deployment configuration files and generates
deployment matrices for different environments (dev, int, prod) and custom deployments.
It is designed to be used in GitHub Actions.

The script:
1. Reads deployment configuration files (deployment-config.yml or deployment-config.yaml)
2. Extracts environment-specific configurations
3. Filters by specific environment(s) if provided
4. Creates deployment matrices for dev, int, prod, and custom deployments
5. Outputs JSON matrices that can be used in GitHub workflow jobs
"""

import os
import sys
import json
import yaml
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Set


def log(message: str, level: str = "INFO") -> None:
    """
    Log a message with timestamp and log level.
    
    Args:
        message: The message to log
        level: Log level (INFO, WARNING, ERROR, DEBUG)
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [{level}] - {message}")


def warning(message: str) -> None:
    """
    Print a GitHub Actions warning message.
    
    Args:
        message: The warning message
    """
    print(f"::warning::{message}")
    log(message, "WARNING")


def error(message: str) -> None:
    """
    Print a GitHub Actions error message.
    
    Args:
        message: The error message
    """
    print(f"::error::{message}")
    log(message, "ERROR")


def load_yaml_config(file_path: str) -> Dict[str, Any]:
    """
    Load YAML configuration file and convert to dict.
    
    Args:
        file_path: Path to the YAML configuration file
        
    Returns:
        Dictionary containing the configuration or an empty dict if loading fails
    """
    log(f"Attempting to load YAML file: {file_path}")
    try:
        with open(file_path, 'r') as file:
            config = yaml.safe_load(file)
            log(f"Successfully loaded YAML file: {file_path}")
            return config
    except FileNotFoundError:
        error(f"File not found: {file_path}")
        return {}
    except yaml.YAMLError as e:
        error(f"Error parsing YAML file {file_path}: {str(e)}")
        return {}
    except Exception as e:
        error(f"Unexpected error loading YAML file {file_path}: {str(e)}")
        return {}


def process_resource_path(resource_path: str, specific_environment: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Process a resource path to extract deployment configurations.
    
    Args:
        resource_path: Path to the CloudFormation resource
        specific_environment: Optional specific environment to filter
        
    Returns:
        Dictionary with matrix items for each environment type
    """
    log(f"Processing resource path: {resource_path}")
    
    # Initialize empty lists for matrix items
    matrix_items: Dict[str, List[Dict[str, Any]]] = {
        "dev": [],
        "int": [],
        "prod": [],
        "custom": []
    }
    
    # Try both YAML and YML extensions
    config_path = f"{resource_path}/deployment-config.yaml"
    if not os.path.isfile(config_path):
        config_path = f"{resource_path}/deployment-config.yml"
        if not os.path.isfile(config_path):
            warning(f"Configuration file not found for {resource_path}")
            return matrix_items
    
    # Read YAML config file
    log(f"Reading YAML configuration from {config_path}")
    config_content = load_yaml_config(config_path)
    
    # Validate config structure
    if not config_content or not isinstance(config_content, dict):
        warning(f"Invalid YAML structure in {config_path}")
        return matrix_items
    
    # Extract app and resource from path
    app = os.path.dirname(resource_path)
    resource = os.path.basename(resource_path)
    
    log(f"Using APP={app} and RESOURCE={resource}")
    
    # Get deployments and validate
    deployments = config_content.get('deployments', [])
    if not deployments or not isinstance(deployments, list) or len(deployments) == 0:
        warning(f"No deployments found in {config_path}")
        return matrix_items
    
    # Get environments list
    environments = deployments[0].get('environments', [])
    if not environments:
        warning(f"No environments found in {config_path}")
        return matrix_items
    
    log(f"Found environments: {' '.join(environments)}")
    
    # Filter by specific environment if provided
    if specific_environment:
        environments = filter_environments(environments, specific_environment, config_path)
        if not environments:
            return matrix_items
    
    # Process each environment for this resource
    for env in environments:
        matrix_item = process_environment(env, resource_path, app, resource, deployments[0], config_path)
        if matrix_item:
            # Add to appropriate matrix based on environment
            if env == "dev":
                matrix_items["dev"].append(matrix_item)
                log(f"Added to dev matrix: {app}/{resource}")
            elif env == "int":
                matrix_items["int"].append(matrix_item)
                log(f"Added to int matrix: {app}/{resource}")
            elif env == "prod":
                matrix_items["prod"].append(matrix_item)
                log(f"Added to prod matrix: {app}/{resource}")
            
            # Add to custom deployment matrix if enabled
            custom_deployment = str(matrix_item.get("parameters", {}).get("custom_deployment", "false")).lower()
            if custom_deployment == "true":
                matrix_items["custom"].append(matrix_item)
                log(f"Added to custom matrix: {app}/{resource}")
    
    return matrix_items


def filter_environments(environments: List[str], specific_environment: str, config_path: str) -> List[str]:
    """
    Filter environments based on specific_environment input.
    
    Args:
        environments: List of available environments
        specific_environment: Environment(s) to filter by (comma-separated)
        config_path: Path to the config file (for warning messages)
        
    Returns:
        Filtered list of environments
    """
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
            return []
        
        log(f"Filtered environments: {' '.join(filtered_environments)}")
        return filtered_environments
    else:
        # Single environment specified
        if specific_environment in environments:
            log(f"Selected single environment: {specific_environment}")
            return [specific_environment]
        else:
            warning(f"Specified environment not found in {config_path}")
            return []


def process_environment(env: str, resource_path: str, app: str, resource: str, 
                        deployment: Dict[str, Any], config_path: str) -> Optional[Dict[str, Any]]:
    """
    Process a single environment for a resource.
    
    Args:
        env: Environment name (dev, int, prod)
        resource_path: Path to the CloudFormation resource
        app: Application name
        resource: Resource name
        deployment: Deployment configuration
        config_path: Path to the config file
        
    Returns:
        Matrix item dictionary or None if required fields are missing
    """
    log(f"Processing environment: {env} for {resource_path}")
    
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
        log(f"Params: {params is not None}, Runner: {runner is not None}, " +
            f"GitHub Env: {gh_env is not None}, AWS Region: {aws_region is not None}")
        return None
    
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
    
    log(f"Created matrix item for {resource_path} in {env} environment")
    return matrix_item


def main():
    """
    Main function to generate deployment matrices.
    
    Reads input parameters from environment variables,
    processes resource paths, and outputs matrices for different environments.
    """
    log("Starting Generate Deployment Matrices script")
    
    # Initialize empty lists for matrix items
    dev_matrix_items = []
    int_matrix_items = []
    prod_matrix_items = []
    custom_matrix_items = []
    
    # Get inputs from environment variables
    resource_paths = os.environ.get("INPUT_RESOURCE_PATHS", "")
    specific_environment = os.environ.get("INPUT_SPECIFIC_ENVIRONMENT", "")
    
    log(f"Input resource_paths: {resource_paths}")
    log(f"Input specific_environment: {specific_environment}")
    
    # Get GitHub output file path
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if not github_output:
        error("GITHUB_OUTPUT environment variable not set")
        sys.exit(1)
    
    # Split input resource paths by comma
    if not resource_paths:
        log("No resource paths provided")
        resource_paths_list = []
    else:
        resource_paths_list = [path.strip() for path in resource_paths.split(',') if path.strip()]
        log(f"Processing {len(resource_paths_list)} resource paths")
    
    # Process each resource path
    for resource_path in resource_paths_list:
        matrix_items = process_resource_path(resource_path, specific_environment)
        
        # Add items to the appropriate matrices
        dev_matrix_items.extend(matrix_items["dev"])
        int_matrix_items.extend(matrix_items["int"])
        prod_matrix_items.extend(matrix_items["prod"])
        custom_matrix_items.extend(matrix_items["custom"])
    
    # Construct environment-specific matrices
    dev_matrix_json = {"include": dev_matrix_items}
    int_matrix_json = {"include": int_matrix_items}
    prod_matrix_json = {"include": prod_matrix_items}
    custom_matrix_json = {"include": custom_matrix_items}
    
    # Log summary of matrices
    log(f"Generated matrices summary:")
    log(f"  - dev matrix: {len(dev_matrix_items)} items")
    log(f"  - int matrix: {len(int_matrix_items)} items")
    log(f"  - prod matrix: {len(prod_matrix_items)} items")
    log(f"  - custom matrix: {len(custom_matrix_items)} items")
    
    # Convert to JSON strings
    try:
        dev_matrix_str = json.dumps(dev_matrix_json, ensure_ascii=False)
        int_matrix_str = json.dumps(int_matrix_json, ensure_ascii=False)
        prod_matrix_str = json.dumps(prod_matrix_json, ensure_ascii=False)
        custom_matrix_str = json.dumps(custom_matrix_json, ensure_ascii=False)
        log("Successfully converted matrices to JSON")
    except Exception as e:
        error(f"Error converting matrices to JSON: {str(e)}")
        sys.exit(1)
    
    # Write matrices to GITHUB_OUTPUT
    try:
        with open(github_output, 'a') as f:
            f.write(f"dev_matrix<<EOF\n{dev_matrix_str}\nEOF\n")
            f.write(f"int_matrix<<EOF\n{int_matrix_str}\nEOF\n")
            f.write(f"prod_matrix<<EOF\n{prod_matrix_str}\nEOF\n")
            f.write(f"custom_matrix<<EOF\n{custom_matrix_str}\nEOF\n")
        log("Successfully wrote matrices to GITHUB_OUTPUT")
    except Exception as e:
        error(f"Error writing to GITHUB_OUTPUT: {str(e)}")
        sys.exit(1)
    
    log("Generate Deployment Matrices script completed successfully")


if __name__ == "__main__":
    main()
