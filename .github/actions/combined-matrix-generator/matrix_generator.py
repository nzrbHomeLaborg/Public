#!/usr/bin/env python3
import os
import re
import json
import tempfile
import subprocess
import argparse
from pathlib import Path

def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description='Generate deployment matrices with secret processing')
    parser.add_argument('--resource-paths', required=True, help='Comma-separated paths to resources')
    parser.add_argument('--specific-environment', default='CD-EM-CRS-DEV', help='Specific environment to deploy (leave empty for all)')
    parser.add_argument('--process-secrets', action='store_true', default=True, help='Process secrets in parameters')
    parser.add_argument('--no-process-secrets', action='store_false', dest='process_secrets', help='Disable secret processing')
    return parser.parse_args()

def process_parameter_file(file_path, temp_dir):
    """Process a parameter file and return the path to the processed file."""
    if not file_path or not os.path.isfile(file_path):
        return file_path
        
    print(f"Processing parameter file: {file_path}")
    
    # Read the file content
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Check if the file might contain secrets (quick check before regex)
    if not ('${{' in content and '}}' in content):
        print("No potential secrets found in parameter file")
        return file_path
        
    # Replace secrets in the content
    modified_content = content
    
    # Find all secret references using regex
    pattern = r'\$\{\{\s*secrets\.([A-Za-z0-9_-]+)\s*\}\}'
    for match in re.finditer(pattern, content):
        full_match = match.group(0)  # The entire match ${{ secrets.X }}
        secret_name = match.group(1)  # Just the secret name X
        
        if secret_name in os.environ:
            print(f"Replacing secret: {secret_name}")
            modified_content = modified_content.replace(full_match, os.environ[secret_name])
        else:
            print(f"Warning: Secret {secret_name} not found in environment")
    
    # Only create a new file if content changed
    if modified_content != content:
        proc_file = temp_dir / f"processed_{os.path.basename(file_path)}"
        with open(proc_file, 'w') as f:
            f.write(modified_content)
        print(f"Created processed parameter file: {proc_file}")
        return str(proc_file)
    
    return file_path

def process_inline_parameters(params):
    """Process inline parameters in either array or object format."""
    if not params:
        return params
        
    # Check if we have inline parameters
    if 'inline-parameters' not in params:
        return params
        
    inline_params = params['inline-parameters']
    
    # Skip if no inline parameters
    if not inline_params:
        return params
    
    print("Processing inline parameters")
    pattern = r'\$\{\{\s*secrets\.([A-Za-z0-9_-]+)\s*\}\}'
    
    # Handle array format (list of dicts with ParameterKey/ParameterValue)
    if isinstance(inline_params, list):
        for item in inline_params:
            if isinstance(item, dict) and 'ParameterValue' in item:
                value = item['ParameterValue']
                if isinstance(value, str) and '${{' in value and '}}' in value:
                    modified_value = value
                    
                    for match in re.finditer(pattern, value):
                        full_match = match.group(0)
                        secret_name = match.group(1)
                        
                        if secret_name in os.environ:
                            print(f"Replacing secret in array parameter: {secret_name}")
                            modified_value = modified_value.replace(full_match, os.environ[secret_name])
                        else:
                            print(f"Warning: Secret {secret_name} not found in environment")
                    
                    item['ParameterValue'] = modified_value
    
    # Handle object format (simple key/value pairs)
    elif isinstance(inline_params, dict):
        for key, value in list(inline_params.items()):
            if isinstance(value, str) and '${{' in value and '}}' in value:
                modified_value = value
                
                for match in re.finditer(pattern, value):
                    full_match = match.group(0)
                    secret_name = match.group(1)
                    
                    if secret_name in os.environ:
                        print(f"Replacing secret in object parameter: {secret_name}")
                        modified_value = modified_value.replace(full_match, os.environ[secret_name])
                    else:
                        print(f"Warning: Secret {secret_name} not found in environment")
                
                inline_params[key] = modified_value
    
    # Update the parameters with processed inline params
    params['inline-parameters'] = inline_params
    return params

def process_parameters(params, temp_dir, process_secrets):
    """Process both parameter file and inline parameters."""
    if not process_secrets or not params:
        return params
        
    # Convert to dict if it's a string (JSON)
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            print(f"Error parsing parameters JSON: {params}")
            return params
    
    # Process parameter file if present
    if 'parameter-file' in params and params['parameter-file']:
        processed_file = process_parameter_file(params['parameter-file'], temp_dir)
        params['parameter-file'] = processed_file
    
    # Process inline parameters
    params = process_inline_parameters(params)
    
    return params

def main():
    """Main function to generate deployment matrices."""
    args = parse_args()
    
    # Parse inputs
    resource_paths = [path.strip() for path in args.resource_paths.split(",") if path.strip()]
    specific_environment = args.specific_environment
    process_secrets = args.process_secrets
    
    print(f"Processing resource paths: {resource_paths}")
    print(f"Specific environment: {specific_environment or 'None'}")
    print(f"Processing secrets: {process_secrets}")
    
    # Initialize matrices
    dev_matrix_items = []
    int_matrix_items = []
    prod_matrix_items = []
    
    # Create temp directory for processed parameter files
    temp_dir = Path(tempfile.mkdtemp(prefix="matrix-params-"))
    print(f"Created temporary directory: {temp_dir}")
    
    # Process each resource path
    for resource_path in resource_paths:
        print(f"Processing resource path: {resource_path}")
        
        # Try both YAML and YML extensions
        config_path = os.path.join(resource_path, "deployment-config.yaml")
        if not os.path.isfile(config_path):
            config_path = os.path.join(resource_path, "deployment-config.yml")
            if not os.path.isfile(config_path):
                print(f"Warning: Configuration file not found for {resource_path}")
                continue
        
        # Read YAML config file and convert to JSON
        print(f"Reading YAML configuration from {config_path}")
        try:
            result = subprocess.run(['yq', '-o=json', 'eval', '.', config_path], 
                                  capture_output=True, text=True, check=True)
            config_content = result.stdout
            config_json = json.loads(config_content)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            print(f"Error processing config file {config_path}: {e}")
            continue
        
        # Extract app and resource from path
        app = os.path.dirname(resource_path)
        resource = os.path.basename(resource_path)
        
        print(f"Using APP={app} and RESOURCE={resource}")
        
        # Get environments list
        environments = []
        try:
            environments = config_json['deployments'][0]['environments']
        except (KeyError, IndexError):
            print(f"Warning: No environments found in {config_path}")
            continue
        
        print(f"Found environments: {environments}")
        
        # Filter by specific environment if provided
        if specific_environment:
            if specific_environment in environments:
                environments = [specific_environment]
            else:
                print(f"Warning: Specified environment {specific_environment} not found in {config_path}")
                continue
        
        # Process each environment for this resource
        for env in environments:
            print(f"Processing environment: {env} for {resource_path}")
            
            try:
                # Extract parameters
                params = config_json['deployments'][0]['parameters'].get(env, {})
                runner = config_json['deployments'][0]['runners'].get(env)
                gh_env = config_json['deployments'][0]['github_environments'].get(env)
                aws_region = config_json['deployments'][0]['aws_regions'].get(env)
                aws_role_secret = config_json['deployments'][0]['aws_role_secrets'].get(env, "AWS_ROLE_TO_ASSUME")
                cfn_role_secret = config_json['deployments'][0]['cfn_role_secrets'].get(env, "CFN_ROLE_ARN")
                iam_role_secret = config_json['deployments'][0]['iam_execution_role_secrets'].get(env, "IAM_EXECUTION_ROLE_ARN")
                vars_config = config_json['deployments'][0]['github_vars'].get(env, {})
                
                # Skip if any required field is empty
                if not params or not runner or not gh_env or not aws_region:
                    print(f"Warning: Missing required configuration for {resource_path} in {env} environment")
                    continue
                
                # Process secrets in parameters
                processed_params = process_parameters(params, temp_dir, process_secrets)
                
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
                    "parameters": processed_params
                }
                
                # Add to appropriate matrix based on environment
                if env == "dev":
                    dev_matrix_items.append(matrix_item)
                elif env == "int":
                    int_matrix_items.append(matrix_item)
                elif env == "prod":
                    prod_matrix_items.append(matrix_item)
            
            except Exception as e:
                print(f"Error processing environment {env}: {e}")
                continue
    
    # Construct environment-specific matrices
    dev_matrix = {"include": dev_matrix_items}
    int_matrix = {"include": int_matrix_items}
    prod_matrix = {"include": prod_matrix_items}
    
    # Verify JSON is valid
    try:
        dev_matrix_json = json.dumps(dev_matrix)
        int_matrix_json = json.dumps(int_matrix)
        prod_matrix_json = json.dumps(prod_matrix)
    except Exception as e:
        print(f"Error serializing matrices to JSON: {e}")
        exit(1)
    
    # Write matrices to outputs
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a') as f:
            f.write("dev_matrix<<EOF\n")
            f.write(dev_matrix_json + "\n")
            f.write("EOF\n")
            
            f.write("int_matrix<<EOF\n")
            f.write(int_matrix_json + "\n")
            f.write("EOF\n")
            
            f.write("prod_matrix<<EOF\n")
            f.write(prod_matrix_json + "\n")
            f.write("EOF\n")
    else:
        # If running outside of GitHub Actions, print to stdout
        print("\nDEV_MATRIX:")
        print(dev_matrix_json)
        print("\nINT_MATRIX:")
        print(int_matrix_json)
        print("\nPROD_MATRIX:")
        print(prod_matrix_json)
            
    print(f"Generated matrices: DEV({len(dev_matrix_items)}), INT({len(int_matrix_items)}), PROD({len(prod_matrix_items)})")

if __name__ == "__main__":
    main()