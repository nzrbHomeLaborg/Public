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
    """
    Process parameter files and inline parameters, combining them with
    inline parameters taking precedence over file parameters.
    """
    github_run_id = os.environ.get('GITHUB_RUN_ID', '')
    github_run_number = os.environ.get('GITHUB_RUN_NUMBER', '')
    parameter_file_path = os.environ.get('INPUT_PARAMETER_OVERRIDES', '')
    inline_parameters = os.environ.get('INPUT_INLINE_JSON_PARAMETERS', '')
    
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
                combined_parameters = file_parameters
            else:
                for key, value in file_parameters.items():
                    combined_parameters.append({
                        "ParameterKey": key,
                        "ParameterValue": value
                    })
        else:
            logger.warning(f"Could not read parameters from file: {parameter_file_path}")
    
    # Process inline parameters if provided
    if inline_parameters:
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
            
            # Process each inline parameter
            for param in inline_params:
                key = param["ParameterKey"]
                if key in existing_params:
                    combined_parameters[existing_params[key]] = param
                else:
                    combined_parameters.append(param)
                
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing inline JSON parameters: {e}")
            logger.error(f"Raw value: {inline_parameters}")
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
            logger.error(f"Error writing parameter file: {e}")
            sys.exit(1)
    else:
        logger.info(f"{BLUE}No CFN parameters are available.{RESET}")
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write("PARAM_FILE=\n")

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