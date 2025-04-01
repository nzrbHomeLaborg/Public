#!/usr/bin/env python3
import os
import json
import sys
import boto3
from botocore.exceptions import ClientError
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

def main():
    github_run_id = os.environ.get('GITHUB_RUN_ID', '')
    github_run_number = os.environ.get('GITHUB_RUN_NUMBER', '')
    parameter_file_path = os.environ.get('INPUT_PARAMETER_OVERRIDES', '')
    inline_parameters = os.environ.get('INPUT_INLINE_JSON_PARAMETERS', '').strip()

github_secrets = load_github_secrets()

tmp_path = f"/tmp/{github_run_id}{github_run_number}"
param_file = f"{tmp_path}/cfn-parameter-{github_run_id}-{github_run_number}.json"

combined_parameters = []
if parameter_file_path:
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
                        param["ParameterValue"] = github_secrets[secret_name]
            combined_parameters = file_parameters
        else:
            parameter_dict = {}
            for key, value in file_parameters.items():
                if isinstance(value, str) and value.startswith("SECRET:"):
                    secret_name = value.replace("SECRET:", "")
                    if secret_name in github_secrets:
                        parameter_dict[key] = github_secrets[secret_name]
                    else:
                        parameter_dict[key] = value
                else:
                    parameter_dict[key] = value
           
            for key, value in parameter_dict.items():
                combined_parameters.append({
                    "ParameterKey": key,
                    "ParameterValue": value
                })

if inline_parameters and inline_parameters != 'null':
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
                    param["ParameterValue"] = github_secrets[secret_name]
            
            if key in existing_params:
                combined_parameters[existing_params[key]] = param
            else:
                combined_parameters.append(param)
            
    except json.JSONDecodeError as e:
        if not combined_parameters:
            sys.exit(1)

if combined_parameters:
    try:
        Path(tmp_path).mkdir(parents=True, exist_ok=True)
        with open(param_file, 'w') as f:
            json.dump(combined_parameters, f, indent=2)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"PARAM_FILE=file:///{param_file}\\n")
    except Exception as e:
        sys.exit(1)
else:
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write("PARAM_FILE=\\n")

def load_github_secrets():
    secrets = {}

secrets_path = os.environ.get('GITHUB_SECRETS_PATH', '')
salt_key = os.environ.get('SECRET_SALT_KEY', '')

if not salt_key:
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
            
            try:
                os.remove(secrets_path)
            except Exception:
                pass
                
        except subprocess.CalledProcessError:
            pass
            
    except Exception:
        pass

if not secrets:
    for key, value in os.environ.items():
        if not key.startswith('GITHUB_') and not key.startswith('INPUT_'):
            secrets[key] = value

return secrets

def read_from_s3(s3_path):
    try:
        path_parts = s3_path.replace('s3://', '').split('/', 1)
        bucket = path_parts[0]
        key = path_parts[1] if len(path_parts) > 1 else ''

    s3_client = boto3.client('s3')
    
    response = s3_client.get_object(Bucket=bucket, Key=key)
    
    content = response['Body'].read().decode('utf-8')

    return json.loads(content)
except ClientError:
    return []
except json.JSONDecodeError:
    return []
except Exception:
    return []

def read_from_local(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.loads(f.read())
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []
    except Exception:
        return []

if name == "main":
    main()