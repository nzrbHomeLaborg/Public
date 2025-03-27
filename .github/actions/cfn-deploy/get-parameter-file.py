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
RESET = "\033[0m"

def main():
    github_run_id = os.environ.get('GITHUB_RUN_ID', '')
    github_run_number = os.environ.get('GITHUB_RUN_NUMBER', '')
    parameter_file_path = os.environ.get('INPUT_PARAMETER_OVERRIDES', '')
    inline_parameters_raw = os.environ.get('INPUT_INLINE_JSON_PARAMETERS', '').strip()
    
    tmp_path = f"/tmp/{github_run_id}{github_run_number}"
    param_file = f"{tmp_path}/cfn-parameter-{github_run_id}-{github_run_number}.json"
    
    combined_parameters = []
    
    # Existing logic for file parameters
    if parameter_file_path:
        file_parameters = read_parameters_from_file(parameter_file_path)
        combined_parameters.extend(file_parameters)

    # Process inline parameters from environment
    if inline_parameters_raw and inline_parameters_raw != 'null':
        try:
            inline_params = json.loads(inline_parameters_raw)

            for param in inline_params:
                key = param.get("ParameterKey")
                value = param.get("ParameterValue")
                secret_name = param.get("ParameterValueSecretName")

                # Якщо це секрет, читаємо його зі змінних середовища
                if secret_name:
                    secret_value = os.environ.get(key)
                    if secret_value is None:
                        logger.error(f"Secret for '{key}' not found in environment variables.")
                        sys.exit(1)
                    value = secret_value

                combined_parameters.append({
                    "ParameterKey": key,
                    "ParameterValue": value
                })
            
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing inline JSON parameters: {e}")
            sys.exit(1)

    # Write combined parameters to file
    write_parameters_to_file(param_file, tmp_path, combined_parameters)

def read_parameters_from_file(path):
    if path.startswith('s3://'):
        return read_from_s3(path)
    else:
        local_path = path.replace('file:///', '')
        return read_from_local(local_path)

def read_from_s3(s3_path):
    try:
        bucket, key = s3_path.replace('s3://', '').split('/', 1)
        s3_client = boto3.client('s3')
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(response['Body'].read())
    except Exception as e:
        logger.error(f"S3 error: {e}")
        return []

def read_from_local(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.loads(f.read())
    except Exception as e:
        logger.error(f"Local file error: {e}")
        return []

def write_parameters_to_file(param_file, tmp_path, parameters):
    if parameters:
        Path(tmp_path).mkdir(parents=True, exist_ok=True)
        with open(param_file, 'w') as f:
            json.dump(parameters, f, indent=2)
        logger.info(f"{BLUE}{param_file} created with {len(parameters)} parameters{RESET}")
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"PARAM_FILE=file:///{param_file}\n")
    else:
        logger.info(f"{BLUE}No CFN parameters available.{RESET}")
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write("PARAM_FILE=\n")

if __name__ == "__main__":
    main()
