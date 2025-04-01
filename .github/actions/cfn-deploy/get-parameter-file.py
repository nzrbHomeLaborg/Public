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
        
            if isinstance(file_parameters, list):
                for param in file_parameters:
                    if isinstance(param.get("ParameterValue"), str) and param["ParameterValue"].startswith("SECRET:"):
                        secret_name = param["ParameterValue"].replace("SECRET:", "")
                        if secret_name in github_secrets:
                            logger.info(f"{GREEN}Replacing SECRET:{secret_name} in parameter file with actual secret value{RESET}")
                            param["ParameterValue"] = github_secrets[secret_name]
                        else:
                            logger.warning(f"{YELLOW}Secret {secret_name} not found in available secrets{RESET}")
                combined_parameters = file_parameters
            else:
           
                parameter_dict = {}
                for key, value in file_parameters.items():
                    if isinstance(value, str) and value.startswith("SECRET:"):
                        secret_name = value.replace("SECRET:", "")
                        if secret_name in github_secrets:
                            logger.info(f"{GREEN}Replacing SECRET:{secret_name} in parameter file with actual secret value{RESET}")
                            parameter_dict[key] = github_secrets[secret_name]
                        else:
                            logger.warning(f"{YELLOW}Secret {secret_name} not found in available secrets{RESET}")
                            parameter_dict[key] = value
                    else:
                        parameter_dict[key] = value
               
                for key, value in parameter_dict.items():
                    combined_parameters.append({
                        "ParameterKey": key,
                        "ParameterValue": value
                    })
        else:
            logger.warning(f"Could not read parameters from file: {parameter_file_path}")
    

    if inline_parameters and inline_parameters != 'null':
        logger.info(f"{BLUE}inline-json-parameters are available.{RESET}")
        
        try:

            inline_params = json.loads(inline_parameters)
            
            if not isinstance(inline_params, list):
                inline_params_list = []
                for key, value in inline_params.items():
                    inline_params_list.append({
                        "ParameterKey": key,
                        "ParameterValue": value
                    })
                inline_params = inline_params_list
            existing_params = {param["ParameterKey"]: i for i, param in enumerate(combined_parameters)}
            

            for param in inline_params:
                key = param["ParameterKey"]

                if isinstance(param["ParameterValue"], str) and param["ParameterValue"].startswith("SECRET:"):
                    secret_name = param["ParameterValue"].replace("SECRET:", "")
                    if secret_name in github_secrets:
                        logger.info(f"{GREEN}Replacing SECRET:{secret_name} with actual secret value{RESET}")
                        param["ParameterValue"] = github_secrets[secret_name]
                    else:
                        logger.warning(f"{YELLOW}Secret {secret_name} not found in available secrets{RESET}")
                
                if key in existing_params:
                    combined_parameters[existing_params[key]] = param
                else:
                    combined_parameters.append(param)
                
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing inline JSON parameters: {e}")
            logger.error(f"Raw value: {inline_parameters}")
            if not combined_parameters:
                sys.exit(1)

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
            logger.error(f"Error writing parameter file: {e}")
            sys.exit(1)
    else:
        logger.info(f"{BLUE}No CFN parameters are available.{RESET}")
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write("PARAM_FILE=\n")

def load_github_secrets():
    """
    Load GitHub secrets from encrypted file
    
    Returns:
        dict: Dictionary with secret names as keys and their values
    """
    secrets = {}
    
    secrets_path = os.environ.get('GITHUB_SECRETS_PATH', '')
    salt_key = os.environ.get('SECRET_SALT_KEY', '')
    
    if not salt_key:
        logger.error(f"{YELLOW}No SECRET_SALT_KEY found in environment. Cannot decrypt secrets.{RESET}")
        return {}
    
    if secrets_path and os.path.exists(secrets_path):
        try:
            import hashlib
            import subprocess
            
            key = hashlib.sha256(salt_key.encode()).hexdigest()
            
            try:
                result = subprocess.run(
                    ['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '10000', '-salt', 
                     '-in', secrets_path, 
                     '-pass', f'pass:{key}'],
                    capture_output=True, text=True, check=True
                )

                secrets = json.loads(result.stdout)
                logger.info(f"{BLUE}Successfully decrypted and loaded secrets from file: {secrets_path}{RESET}")
                logger.info(f"{BLUE}Number of secrets loaded: {len(secrets)}{RESET}")
                

                try:
                    os.remove(secrets_path)
                    logger.info(f"{BLUE}Removed encrypted secrets file after reading{RESET}")
                except Exception as e:
                    logger.warning(f"{YELLOW}Could not remove secrets file: {e}{RESET}")
                    
            except subprocess.CalledProcessError as e:
                logger.error(f"{YELLOW}Error decrypting secrets: {e.stderr}{RESET}")
                logger.error(f"{YELLOW}Check if SECRET_SALT_KEY is correct.{RESET}")
                
        except Exception as e:
            logger.error(f"{YELLOW}Error loading secrets from encrypted file: {e}{RESET}")
    else:
        logger.warning(f"{YELLOW}No secrets file found at {secrets_path}{RESET}")
    
    if not secrets:
        logger.info(f"{YELLOW}Failed to load secrets from encrypted file. Trying environment variables.{RESET}")
        
        env_var_count = 0
        for key, value in os.environ.items():
            if not key.startswith('GITHUB_') and not key.startswith('INPUT_'):
                secrets[key] = value
                env_var_count += 1
        
        logger.info(f"{BLUE}Loaded {env_var_count} environment variables as potential secrets{RESET}")
    
    return secrets
def read_from_s3(s3_path):
    """
    Read parameters from an S3 bucket.
    
    Args:
        s3_path (str): The S3 path in the format s3://bucket-name/key
        
    Returns:
        dict or list: The parameters read from the S3 file
    """
    try:
        # Extract bucket and key from S3 path
        path_parts = s3_path.replace('s3://', '').split('/', 1)
        bucket = path_parts[0]
        key = path_parts[1] if len(path_parts) > 1 else ''
        
        s3_client = boto3.client('s3')
        
        response = s3_client.get_object(Bucket=bucket, Key=key)
        
        content = response['Body'].read().decode('utf-8')
    
        return json.loads(content)
    except ClientError as e:
        logger.error(f"Error reading from S3: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON from S3: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return []

def read_from_local(file_path):
    """
    Read parameters from a local file.
    
    Args:
        file_path (str): The path to the local file
        
    Returns:
        dict or list: The parameters read from the local file
    """
    try:
        with open(file_path, 'r') as f:
            return json.loads(f.read())
    except FileNotFoundError:
        logger.error(f"Parameter file not found: {file_path}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON from file: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return []

if __name__ == "__main__":
    main()