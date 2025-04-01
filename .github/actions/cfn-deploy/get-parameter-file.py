#!/usr/bin/env python3
import os
import json
import sys
import boto3
from botocore.exceptions import ClientError
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

BLUE = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

def main():
    """
    Process parameter files and inline parameters, combining them with
    inline parameters taking precedence over file parameters.
    """
    github_run_id = os.environ.get('GITHUB_RUN_ID', '')
    github_run_number = os.environ.get('GITHUB_RUN_NUMBER', '')
    parameter_file_path = os.environ.get('INPUT_PARAMETER_OVERRIDES', '')
    inline_parameters = os.environ.get('INPUT_INLINE_JSON_PARAMETERS', '').strip()
    
    # Отримуємо секрети з змінних середовища
    github_secrets = load_github_secrets()
    
    tmp_path = f"/tmp/{github_run_id}{github_run_number}"
    param_file = f"{tmp_path}/cfn-parameter-{github_run_id}-{github_run_number}.json"
    
    combined_parameters = []
    if parameter_file_path:
        logger.info(f"{BLUE}parameter-overrides are available: {parameter_file_path}{RESET}")
        if parameter_file_path.startswith('s3://'):
            file_parameters = read_from_s3(parameter_file_path)
        else:
            local_path = parameter_file_path.replace('file:///', '')
            file_parameters = read_from_local(local_path)
        
        if file_parameters:
            # Обробляємо секрети в параметрах з файлу
            if isinstance(file_parameters, list):
                # Для формату списку об'єктів з ParameterKey/ParameterValue
                for param in file_parameters:
                    if isinstance(param.get("ParameterValue"), str) and (
                        param["ParameterValue"].startswith("SECRET:") or 
                        param["ParameterValue"].startswith("SECRET.")
                    ):
                        secret_name = param["ParameterValue"].replace("SECRET:", "").replace("SECRET.", "")
                        if secret_name in github_secrets:
                            logger.info(f"{GREEN}Replacing SECRET:{secret_name} in parameter file with actual secret value{RESET}")
                            param["ParameterValue"] = github_secrets[secret_name]
                        else:
                            logger.warning(f"{YELLOW}Secret {secret_name} not found in available secrets{RESET}")
                combined_parameters = file_parameters
            else:
                # Для формату словника key:value
                parameter_dict = {}
                for key, value in file_parameters.items():
                    if isinstance(value, str) and (
                        value.startswith("SECRET:") or 
                        value.startswith("SECRET.")
                    ):
                        secret_name = value.replace("SECRET:", "").replace("SECRET.", "")
                        if secret_name in github_secrets:
                            logger.info(f"{GREEN}Replacing SECRET:{secret_name} in parameter file with actual secret value{RESET}")
                            parameter_dict[key] = github_secrets[secret_name]
                        else:
                            logger.warning(f"{YELLOW}Secret {secret_name} not found in available secrets{RESET}")
                            parameter_dict[key] = value
                    else:
                        parameter_dict[key] = value
                        
                # Конвертуємо у формат списку для CloudFormation
                for key, value in parameter_dict.items():
                    combined_parameters.append({
                        "ParameterKey": key,
                        "ParameterValue": value
                    })
        else:
            logger.warning(f"Could not read parameters from file: {parameter_file_path}")
    
    # Process inline parameters if provided
    if inline_parameters and inline_parameters != 'null':
        logger.info(f"{BLUE}inline-json-parameters are available.{RESET}")
        
        try:
            # Attempt to parse the inline parameters
            inline_params = json.loads(inline_parameters)
            
            # If it's not a list, convert to list of parameter dictionaries
            if not isinstance(inline_params, list):
                inline_params_list = []
                for key, value in inline_params.items():
                    inline_params_list.append({
                        "ParameterKey": key,
                        "ParameterValue": value
                    })
                inline_params = inline_params_list
            
            # Create a mapping of existing parameter keys
            existing_params = {param["ParameterKey"]: i for i, param in enumerate(combined_parameters)}
            
            # Process each inline parameter
            for param in inline_params:
                key = param["ParameterKey"]

                # Обробка секретів в інлайн-параметрах
                if isinstance(param["ParameterValue"], str) and (
                    param["ParameterValue"].startswith("SECRET:") or 
                    param["ParameterValue"].startswith("SECRET.")
                ):
                    secret_name = param["ParameterValue"].replace("SECRET:", "").replace("SECRET.", "")
                    if secret_name in github_secrets:
                        logger.info(f"{GREEN}Replacing SECRET:{secret_name} with actual secret value{RESET}")
                        param["ParameterValue"] = github_secrets[secret_name]
                    else:
                        logger.warning(f"{YELLOW}Secret {secret_name} not found in available secrets{RESET}")
                
                if key in existing_params:
                    # Override existing parameter
                    combined_parameters[existing_params[key]] = param
                else:
                    # Add new parameter
                    combined_parameters.append(param)
                
        except json.JSONDecodeError as e:
            logger.error(f"{RED}Error parsing inline JSON parameters: {e}{RESET}")
            logger.error(f"Raw value: {inline_parameters}")
            # Log the error but don't exit if file parameters exist
            if not combined_parameters:
                sys.exit(1)
    
    # Write the combined parameters to a file if we have any
    if combined_parameters:
        try:
            Path(tmp_path).mkdir(parents=True, exist_ok=True)
            logger.info(f"{BLUE}{tmp_path} created..{RESET}")
            with open(param_file, 'w') as f:
                json.dump(combined_parameters, f, indent=2)
            logger.info(f"{BLUE}{param_file} created with {len(combined_parameters)} parameters{RESET}")
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f"PARAM_FILE=file:///{param_file}\n")
        except Exception as e:
            logger.error(f"{RED}Error writing parameter file: {e}{RESET}")
            sys.exit(1)
    else:
        logger.info(f"{BLUE}No CFN parameters are available.{RESET}")
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write("PARAM_FILE=\n")

def load_github_secrets():
    """
    Load GitHub secrets from environment variables or file
    
    Returns:
        dict: Dictionary with secret names as keys and their values
    """
    secrets = {}
    
    secrets_path = os.environ.get('GITHUB_SECRETS_PATH', '')
    if secrets_path and os.path.exists(secrets_path):
        try:
            with open(secrets_path, 'r') as f:
                secrets = json.load(f)
            logger.info(f"{BLUE}Loaded secrets from file: {secrets_path}{RESET}")
            logger.info(f"{BLUE}Number of secrets loaded: {len(secrets)}{RESET}")
            try:
                os.remove(secrets_path)
                logger.info(f"{BLUE}Removed secrets file after reading{RESET}")
            except:
                pass
            return secrets
        except Exception as e:
            logger.error(f"{RED}Error reading secrets from file: {e}{RESET}")
    
    # Якщо не вдалося завантажити з файлу, спробуємо з змінних середовища
    for key, value in os.environ.items():
        # Include only variables that could be GitHub secrets
        if not key.startswith('GITHUB_') and not key.startswith('INPUT_'):
            secrets[key] = value
    
    logger.info(f"{BLUE}Loaded {len(secrets)} potential secrets from environment variables{RESET}")
    return secrets

# [Інші функції залишаються без змін]