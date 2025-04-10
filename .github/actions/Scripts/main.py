#!/usr/bin/env python3
"""
Modular Python System for GitHub Actions.

Combines multiple scripts into a unified modular structure:
1. ParameterProcessor - processes CloudFormation parameters
2. TagProcessor - processes tags for AWS resources
3. DeploymentMatrixGenerator - generates deployment matrices
4. ChangeDetector - detects changed applications

Usage:
  python main.py parameter_processor
  python main.py tag_processor
  python main.py matrix_generator
  python main.py change_detector
"""

import os
import sys
import json
import yaml
import re
import subprocess
import hashlib
import logging
import datetime
import requests
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, List, Set, Any, Optional, Tuple, Union
from datetime import datetime as dt

import boto3
from botocore.exceptions import ClientError


###############################################################################
#                           Base Action (Abstract)                            #
###############################################################################
class Action(ABC):
    """Base abstract class for all actions."""

    def __init__(self):
        """Initialize logger for the action."""
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """
        Set up the logger.
        Returns:
            logging.Logger: Configured logger
        """
        logger = logging.getLogger(self.__class__.__name__)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def log(self, message: str, level: str = "INFO") -> None:
        """
        Log a message with timestamp and level.
        Args:
            message: Message to log
            level: Log level (INFO, WARNING, ERROR, DEBUG)
        """
        timestamp = dt.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"{timestamp} [{level}] - {message}"

        if level == "ERROR":
            self.logger.error(full_message)
            # Output error message in GitHub Actions format
            print(f"::error::{message}")
        elif level == "WARNING":
            self.logger.warning(full_message)
            # Output warning in GitHub Actions format
            print(f"::warning::{message}")
        elif level == "DEBUG":
            self.logger.debug(full_message)
        else:
            self.logger.info(full_message)

    @abstractmethod
    def execute(self) -> int:
        """
        Execute the action.
        Returns:
            int: Return code (0 - success, non-0 - error)
        """
        pass

    def write_output(self, key: str, value: str) -> None:
        """
        Write result to GITHUB_OUTPUT file.
        Args:
            key: Result key
            value: Result value
        """
        github_output = os.environ.get('GITHUB_OUTPUT')
        if github_output:
            try:
                if '\n' in value:
                    with open(github_output, 'a') as f:
                        f.write(f"{key}<<EOF\n{value}\nEOF\n")
                else:
                    with open(github_output, 'a') as f:
                        f.write(f"{key}={value}\n")
                self.log(f"Wrote result '{key}' to GITHUB_OUTPUT")
            except Exception as e:
                self.log(f"Error writing to GITHUB_OUTPUT: {str(e)}", "ERROR")
        else:
            self.log("GITHUB_OUTPUT environment variable not set", "WARNING")
            print(f"{key}={value}")


###############################################################################
#                         Parameter Processor Action                          #
###############################################################################
class ParameterProcessor(Action):
    """Process parameters for CloudFormation deployment."""

    def execute(self) -> int:
        """
        Process CloudFormation parameters from files and JSON strings.
        Returns:
            int: Return code (0 - success, non-0 - error)
        """
        self.log("Starting CloudFormation parameter processing")

        # Get environment variables
        github_run_id = os.environ.get('GITHUB_RUN_ID', '')
        github_run_number = os.environ.get('GITHUB_RUN_NUMBER', '')
        parameter_file_path = os.environ.get('INPUT_PARAMETER_OVERRIDES', '')
        inline_parameters = os.environ.get('INPUT_INLINE_JSON_PARAMETERS', '').strip()

        # Load GitHub secrets
        github_secrets = self._load_github_secrets()

        # Prepare temporary path for output
        tmp_path = f"/tmp/{github_run_id}{github_run_number}"
        param_file = f"{tmp_path}/cfn-parameter-{github_run_id}-{github_run_number}.json"

        # Process parameters from file
        combined_parameters = []
        if parameter_file_path:
            file_parameters = self._read_parameters_from_file(parameter_file_path)
            combined_parameters = self._process_file_parameters(file_parameters, github_secrets)

        # Process inline parameters
        if inline_parameters and inline_parameters != 'null':
            combined_parameters = self._process_inline_parameters(
                inline_parameters, combined_parameters, github_secrets
            )

        # Write results to output file
        if combined_parameters:
            return self._save_parameters(combined_parameters, tmp_path, param_file)
        else:
            self.write_output("PARAM_FILE", "")
            return 0

    def _load_github_secrets(self) -> Dict[str, str]:
        """
        Load GitHub secrets.
        Returns:
            Dict[str, str]: Dictionary with GitHub secrets
        """
        secrets = {}

        secrets_path = os.environ.get('GITHUB_SECRETS_PATH', '')
        salt_key = os.environ.get('SECRET_SALT_KEY', '')

        if not salt_key:
            self.log("SECRET_SALT_KEY not set, loading secrets from environment")
            return self._load_secrets_from_env()

        if secrets_path and os.path.exists(secrets_path):
            try:
                key = hashlib.sha256(salt_key.encode()).hexdigest()

                try:
                    # Decrypt secrets file
                    result = subprocess.run(
                        [
                            'openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '10000', '-salt',
                            '-in', secrets_path,
                            '-pass', f'pass:{key}'
                        ],
                        capture_output=True, text=True, check=True
                    )

                    secrets = json.loads(result.stdout)
                    self.log("Secrets successfully loaded from encrypted file")

                    try:
                        # Remove secrets file after loading
                        os.remove(secrets_path)
                        self.log(f"Secrets file removed: {secrets_path}")
                    except Exception:
                        self.log(f"Failed to remove secrets file: {secrets_path}", "WARNING")

                except subprocess.CalledProcessError as e:
                    self.log(f"Error decrypting secrets file: {e}", "ERROR")

            except Exception as e:
                self.log(f"Error loading secrets: {e}", "ERROR")

        # If secrets couldn't be loaded, try from environment
        if not secrets:
            secrets = self._load_secrets_from_env()

        return secrets

    def _load_secrets_from_env(self) -> Dict[str, str]:
        """
        Load secrets from environment variables.
        Returns:
            Dict[str, str]: Dictionary with secrets from environment variables
        """
        secrets = {}
        for key, value in os.environ.items():
            # Exclude GitHub Actions service variables
            if not key.startswith('GITHUB_') and not key.startswith('INPUT_'):
                secrets[key] = value

        self.log(f"Loaded {len(secrets)} secrets from environment variables")
        return secrets

    def _read_parameters_from_file(self, parameter_file_path: str) -> Dict[str, Any]:
        """
        Read parameters from file (local or S3).
        Args:
            parameter_file_path: Path to parameters file
        Returns:
            Dict[str, Any]: Dictionary with parameters
        """
        if parameter_file_path.startswith('s3://'):
            self.log(f"Reading parameters from S3: {parameter_file_path}")
            return self._read_from_s3(parameter_file_path)
        else:
            local_path = parameter_file_path.replace('file:///', '')
            self.log(f"Reading parameters from local file: {local_path}")
            return self._read_from_local(local_path)

    def _read_from_s3(self, s3_path: str) -> Dict[str, Any]:
        """
        Read parameters from S3 file.
        Args:
            s3_path: Path to file in S3 (s3://bucket/key)
        Returns:
            Dict[str, Any]: Dictionary with parameters
        """
        try:
            path_parts = s3_path.replace('s3://', '').split('/', 1)
            bucket = path_parts[0]
            key = path_parts[1] if len(path_parts) > 1 else ''

            s3_client = boto3.client('s3')

            response = s3_client.get_object(Bucket=bucket, Key=key)

            content = response['Body'].read().decode('utf-8')

            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                self.log(f"Error decoding JSON from S3: {e}", "ERROR")
                return {}

        except ClientError as e:
            self.log(f"S3 error reading file {s3_path}: {e}", "ERROR")
        except Exception as e:
            self.log(f"Unexpected error reading from S3: {e}", "ERROR")

        return {}

    def _read_from_local(self, file_path: str) -> Dict[str, Any]:
        """
        Read parameters from local file.
        Args:
            file_path: Path to local file
        Returns:
            Dict[str, Any]: Dictionary with parameters
        """
        try:
            with open(file_path, 'r') as f:
                return json.loads(f.read())
        except FileNotFoundError:
            self.log(f"File not found: {file_path}", "ERROR")
        except json.JSONDecodeError as e:
            self.log(f"Error decoding JSON from file {file_path}: {e}", "ERROR")
        except Exception as e:
            self.log(f"Unexpected error reading file {file_path}: {e}", "ERROR")

        return {}

    def _process_file_parameters(self, file_parameters: Dict[str, Any],
                                 github_secrets: Dict[str, str]) -> List[Dict[str, str]]:
        """
        Process parameters from file.
        Args:
            file_parameters: Dictionary with parameters from file
            github_secrets: Dictionary with GitHub secrets
        Returns:
            List[Dict[str, str]]: Parameters list for CloudFormation
        """
        if not file_parameters:
            return []

        combined_parameters = []

        # Format with array of ParameterKey/ParameterValue objects
        if isinstance(file_parameters, list):
            self.log("Detected parameters format as a list")
            for param in file_parameters:
                if isinstance(param.get("ParameterValue"), str) and param["ParameterValue"].startswith("SECRET:"):
                    secret_name = param["ParameterValue"].replace("SECRET:", "")
                    if secret_name in github_secrets:
                        param["ParameterValue"] = github_secrets[secret_name]
                        self.log(f"Applied secret {secret_name} to parameter {param.get('ParameterKey', '')}")
            combined_parameters = file_parameters

        # Format with flat key/value dictionary
        else:
            self.log("Detected parameters format as a dictionary")
            parameter_dict = {}
            for key, value in file_parameters.items():
                if isinstance(value, str) and value.startswith("SECRET:"):
                    secret_name = value.replace("SECRET:", "")
                    if secret_name in github_secrets:
                        parameter_dict[key] = github_secrets[secret_name]
                        self.log(f"Applied secret {secret_name} to parameter {key}")
                    else:
                        parameter_dict[key] = value
                else:
                    parameter_dict[key] = value

            # Convert dictionary to CloudFormation format
            for key, value in parameter_dict.items():
                combined_parameters.append({
                    "ParameterKey": key,
                    "ParameterValue": value
                })

        self.log(f"Processed {len(combined_parameters)} parameters from file")
        return combined_parameters

    def _process_inline_parameters(self, inline_parameters: str,
                                   combined_parameters: List[Dict[str, str]],
                                   github_secrets: Dict[str, str]) -> List[Dict[str, str]]:
        """
        Process inline parameters from JSON string.
        Args:
            inline_parameters: JSON string with parameters
            combined_parameters: Current parameters list
            github_secrets: Dictionary with GitHub secrets
        Returns:
            List[Dict[str, str]]: Updated parameters list
        """
        try:
            inline_params = json.loads(inline_parameters)
            self.log(f"Successfully parsed inline parameters: {type(inline_params)}")

            # Convert from dictionary to list if needed
            if not isinstance(inline_params, list):
                self.log("Converting inline parameters from dictionary to list")
                inline_params_list = []
                for key, value in inline_params.items():
                    inline_params_list.append({
                        "ParameterKey": key,
                        "ParameterValue": value
                    })
                inline_params = inline_params_list

            # Create dictionary for quick lookup of existing parameters
            existing_params = {param["ParameterKey"]: i for i, param in enumerate(combined_parameters)}

            # Process each inline parameter
            for param in inline_params:
                key = param["ParameterKey"]

                # Substitute secrets if needed
                if (isinstance(param["ParameterValue"], str) and
                        param["ParameterValue"].startswith("SECRET:")):
                    secret_name = param["ParameterValue"].replace("SECRET:", "")
                    if secret_name in github_secrets:
                        param["ParameterValue"] = github_secrets[secret_name]
                        self.log(f"Applied secret {secret_name} to inline parameter {key}")

                # Update or add parameter
                if key in existing_params:
                    combined_parameters[existing_params[key]] = param
                    self.log(f"Updated parameter {key}")
                else:
                    combined_parameters.append(param)
                    self.log(f"Added new parameter {key}")

            self.log(f"Total parameters after inline processing: {len(combined_parameters)}")
            return combined_parameters

        except json.JSONDecodeError as e:
            self.log(f"Error parsing JSON inline parameters: {e}", "ERROR")
            if not combined_parameters:
                self.log("No parameters after processing", "ERROR")
            return combined_parameters

    def _save_parameters(self, combined_parameters: List[Dict[str, str]],
                         tmp_path: str, param_file: str) -> int:
        """
        Save parameters to JSON file.
        Args:
            combined_parameters: Parameters list
            tmp_path: Temporary path for file
            param_file: Full path to parameters file
        Returns:
            int: Return code (0 - success, non-0 - error)
        """
        try:
            Path(tmp_path).mkdir(parents=True, exist_ok=True)
            with open(param_file, 'w') as f:
                json.dump(combined_parameters, f, indent=2)
            self.log(f"Parameters saved to {param_file}")

            # Write path to parameters file to output
            self.write_output("PARAM_FILE", f"file:///{param_file}")
            return 0
        except Exception as e:
            self.log(f"Error saving parameters: {e}", "ERROR")
            return 1


###############################################################################
#                            Tag Processor Action                             #
###############################################################################
class TagProcessor(Action):
    """Process tags for AWS resources."""

    def execute(self) -> int:
        """
        Process tags from various sources and formats.
        Returns:
            int: Return code (0 - success, non-0 - error)
        """
        self.log("Starting tag processing for AWS resources")

        # Get input data from environment variables
        tags_json = os.environ.get('INPUT_TAGS', '')
        tags_key_value = os.environ.get('INPUT_TAGS_KEY_VALUE', '')

        # Initialize empty tags list
        combined_tags = []

        # Process JSON tags
        if tags_json:
            combined_tags = self._process_json_tags(tags_json, combined_tags)

        # Process key-value tags
        if tags_key_value:
            combined_tags = self._process_key_value_tags(tags_key_value, combined_tags)

        # Check if any tags are provided
        if not combined_tags:
            error_message = (
                "No tags are provided for this stack. Please follow "
                "the AWS tagging guidelines (https://catdigital.atlassian.net/wiki/spaces/CD/pages/105349296/AWS+Tagging)."
            )
            self.log(error_message, "ERROR")
            return 1

        # Write results
        self.write_output("TAGS", json.dumps(combined_tags))
        self.log(f"Processed and saved {len(combined_tags)} tags")
        return 0

    def _process_json_tags(self, tags_json: str,
                           combined_tags: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Process tags from JSON string.
        Args:
            tags_json: JSON string with tags
            combined_tags: Current tags list
        Returns:
            List[Dict[str, str]]: Updated tags list
        """
        try:
            json_tags = json.loads(tags_json)
            self.log(f"Successfully parsed JSON tags, found {len(json_tags)} tags")
            combined_tags.extend(json_tags)
            return combined_tags
        except json.JSONDecodeError as e:
            self.log(f"Error parsing JSON tags: {e}", "WARNING")
            return combined_tags

    def _process_key_value_tags(self, tags_key_value: str,
                                combined_tags: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Process tags in key-value format.
        Args:
            tags_key_value: String with tags in key=value format
            combined_tags: Current tags list
        Returns:
            List[Dict[str, str]]: Updated tags list
        """
        # Create dictionary of existing tags for quick lookup
        existing_tags = {tag["Key"]: i for i, tag in enumerate(combined_tags)}

        # Parse string by lines
        tag_lines = [line.strip() for line in tags_key_value.splitlines()]
        processed_count = 0

        for line in tag_lines:
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Parse line in key=value format
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()

                # Remove quotes if present
                value = re.sub(r'^["\'](.*)["\']$', r'\1', value)

                # If key already exists, replace value
                if key in existing_tags:
                    combined_tags[existing_tags[key]] = {
                        "Key": key,
                        "Value": value
                    }
                    self.log(f"Updated tag: {key}={value}")
                else:
                    # Add new tag
                    combined_tags.append({
                        "Key": key,
                        "Value": value
                    })
                    existing_tags[key] = len(combined_tags) - 1
                    self.log(f"Added tag: {key}={value}")

                processed_count += 1

        self.log(f"Processed {processed_count} tags in key-value format")
        return combined_tags


###############################################################################
#                      Deployment Matrix Generator Action                     #
###############################################################################
class DeploymentMatrixGenerator(Action):
    """Generate deployment matrices for different environments."""

    def execute(self) -> int:
        """
        Generate deployment matrices based on configuration files.
        Returns:
            int: Return code (0 - success, non-0 - error)
        """
        self.log("Starting deployment matrices generation")

        # Initialize empty lists for matrix items
        dev_matrix_items = []
        int_matrix_items = []
        prod_matrix_items = []
        custom_matrix_items = []

        # Get input parameters from environment variables
        resource_paths = os.environ.get("INPUT_RESOURCE_PATHS", "")
        specific_environment = os.environ.get("INPUT_SPECIFIC_ENVIRONMENT", "")

        self.log(f"Input resource paths: {resource_paths}")
        self.log(f"Specific environment: {specific_environment}")

        # Get path to GitHub Actions output file
        github_output = os.environ.get("GITHUB_OUTPUT", "")
        if not github_output:
            self.log("GITHUB_OUTPUT environment variable not set", "ERROR")
            return 1

        # Parse input resource paths
        if not resource_paths:
            self.log("No resource paths provided")
            resource_paths_list = []
        else:
            resource_paths_list = [path.strip() for path in resource_paths.split(',') if path.strip()]
            self.log(f"Processing {len(resource_paths_list)} resource paths")

        # Process each resource path
        for resource_path in resource_paths_list:
            matrix_items = self._process_resource_path(resource_path, specific_environment)

            # Add items to appropriate matrices
            dev_matrix_items.extend(matrix_items["dev"])
            int_matrix_items.extend(matrix_items["int"])
            prod_matrix_items.extend(matrix_items["prod"])
            custom_matrix_items.extend(matrix_items["custom"])

        # Create matrices for different environments
        dev_matrix_json = {"include": dev_matrix_items}
        int_matrix_json = {"include": int_matrix_items}
        prod_matrix_json = {"include": prod_matrix_items}
        custom_matrix_json = {"include": custom_matrix_items}

        # Log matrices summary
        self.log("Generated matrices summary:")
        self.log(f"  - dev matrix: {len(dev_matrix_items)} items")
        self.log(f"  - int matrix: {len(int_matrix_items)} items")
        self.log(f"  - prod matrix: {len(prod_matrix_items)} items")
        self.log(f"  - custom matrix: {len(custom_matrix_items)} items")

        # Convert matrices to JSON strings
        try:
            dev_matrix_str = json.dumps(dev_matrix_json, ensure_ascii=False)
            int_matrix_str = json.dumps(int_matrix_json, ensure_ascii=False)
            prod_matrix_str = json.dumps(prod_matrix_json, ensure_ascii=False)
            custom_matrix_str = json.dumps(custom_matrix_json, ensure_ascii=False)
            self.log("Successfully converted matrices to JSON")
        except Exception as e:
            self.log(f"Error converting matrices to JSON: {str(e)}", "ERROR")
            return 1

        # Write matrices to GITHUB_OUTPUT
        with open(github_output, 'a') as f:
            f.write(f"dev_matrix<<EOF\n{dev_matrix_str}\nEOF\n")
            f.write(f"int_matrix<<EOF\n{int_matrix_str}\nEOF\n")
            f.write(f"prod_matrix<<EOF\n{prod_matrix_str}\nEOF\n")
            f.write(f"custom_matrix<<EOF\n{custom_matrix_str}\nEOF\n")

        self.log("Matrices successfully written to GITHUB_OUTPUT")
        return 0

    def _process_resource_path(self, resource_path: str,
                               specific_environment: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Process a resource path to extract deployment configurations.
        Args:
            resource_path: Path to CloudFormation resource
            specific_environment: Optional specific environment to filter
        Returns:
            Dict[str, List[Dict[str, Any]]]: Dictionary with matrix items for each environment type
        """
        self.log(f"Processing resource path: {resource_path}")

        # Initialize empty lists for matrix items
        matrix_items = {
            "dev": [],
            "int": [],
            "prod": [],
            "custom": []
        }

        # Check both extensions: YAML and YML
        config_path = f"{resource_path}/deployment-config.yaml"
        if not os.path.isfile(config_path):
            config_path = f"{resource_path}/deployment-config.yml"
            if not os.path.isfile(config_path):
                self.log(f"Configuration file not found for {resource_path}", "WARNING")
                return matrix_items

        # Read YAML configuration file
        self.log(f"Reading YAML configuration from {config_path}")
        config_content = self._load_yaml_config(config_path)

        # Validate config structure
        if not config_content or not isinstance(config_content, dict):
            self.log(f"Invalid YAML structure in {config_path}", "WARNING")
            return matrix_items

        # Extract app and resource from path
        app = os.path.dirname(resource_path)
        resource = os.path.basename(resource_path)

        self.log(f"Using APP={app} and RESOURCE={resource}")

        # Get deployments
        deployments = config_content.get('deployments', [])
        if not deployments or not isinstance(deployments, list) or len(deployments) == 0:
            self.log(f"Deployments not found in {config_path}", "WARNING")
            return matrix_items

        # Get environments list
        environments = deployments[0].get('environments', [])
        if not environments:
            self.log(f"Environments not found in {config_path}", "WARNING")
            return matrix_items

        self.log(f"Found environments: {' '.join(environments)}")

        # Filter by specific environment if provided
        if specific_environment:
            environments = self._filter_environments(environments, specific_environment, config_path)
            if not environments:
                return matrix_items

        # Process each environment for this resource
        for env in environments:
            matrix_item = self._process_environment(env, resource_path, app, resource, deployments[0], config_path)
            if matrix_item:
                # Add to appropriate matrix based on environment
                if env == "dev":
                    matrix_items["dev"].append(matrix_item)
                    self.log(f"Added to dev matrix: {app}/{resource}")
                elif env == "int":
                    matrix_items["int"].append(matrix_item)
                    self.log(f"Added to int matrix: {app}/{resource}")
                elif env == "prod":
                    matrix_items["prod"].append(matrix_item)
                    self.log(f"Added to prod matrix: {app}/{resource}")

                # Add to custom deployment matrix if enabled
                custom_deployment = str(matrix_item.get("parameters", {}).get("custom_deployment", "false")).lower()
                if custom_deployment == "true":
                    matrix_items["custom"].append(matrix_item)
                    self.log(f"Added to custom matrix: {app}/{resource}")

        return matrix_items

    def _filter_environments(self, environments: List[str], specific_environment: str,
                             config_path: str) -> List[str]:
        """
        Filter environments based on specific_environment.
        Args:
            environments: List of available environments
            specific_environment: Environment(s) to filter by (comma-separated)
            config_path: Path to config file (for warning messages)
        Returns:
            List[str]: Filtered list of environments
        """
        if ',' in specific_environment:
            # Multiple environments specified
            selected_envs = [env.strip() for env in specific_environment.split(',') if env.strip()]
            self.log(f"Multiple environments selected: {selected_envs}")

            # Create regex pattern for matching
            selected_envs_pattern = f"^({'|'.join(selected_envs)})$"
            self.log(f"Environment regex pattern: {selected_envs_pattern}")

            # Filter environments
            filtered_environments = []
            for env_candidate in environments:
                if re.match(selected_envs_pattern, env_candidate):
                    filtered_environments.append(env_candidate)
                    self.log(f"Selected environment: {env_candidate}")

            if not filtered_environments:
                self.log(f"None of the specified environments found in {config_path}", "WARNING")
                return []

            self.log(f"Filtered environments: {' '.join(filtered_environments)}")
            return filtered_environments
        else:
            # Single environment specified
            if specific_environment in environments:
                self.log(f"Selected single environment: {specific_environment}")
                return [specific_environment]
            else:
                self.log(f"Specified environment not found in {config_path}", "WARNING")
                return []

    def _process_environment(self, env: str, resource_path: str, app: str, resource: str,
                             deployment: Dict[str, Any], config_path: str) -> Optional[Dict[str, Any]]:
        """
        Process a single environment for a resource.
        Args:
            env: Environment name (dev, int, prod)
            resource_path: Path to CloudFormation resource
            app: Application name
            resource: Resource name
            deployment: Deployment configuration
            config_path: Path to config file
        Returns:
            Optional[Dict[str, Any]]: Matrix item or None if required fields are missing
        """
        self.log(f"Processing environment: {env} for {resource_path}")

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
        self.log(f"Custom deployment for {env}: {custom_deployment}")

        # Skip if any required field is empty
        if (
            not params or
            not runner or
            not gh_env or
            not aws_region
        ):
            self.log(f"Missing required configuration for {resource_path} in {env} environment", "WARNING")
            self.log(
                f"Params: {params is not None}, Runner: {runner is not None}, "
                f"GitHub Env: {gh_env is not None}, AWS Region: {aws_region is not None}"
            )
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

        self.log(f"Created matrix item for {resource_path} in {env} environment")
        return matrix_item

    def _load_yaml_config(self, file_path: str) -> Dict[str, Any]:
        """
        Load YAML configuration from file.
        Args:
            file_path: Path to YAML configuration file
        Returns:
            Dict[str, Any]: Dictionary with configuration or empty dict on error
        """
        self.log(f"Attempting to load YAML file: {file_path}")
        try:
            with open(file_path, 'r') as file:
                config = yaml.safe_load(file)
                self.log(f"YAML file successfully loaded: {file_path}")
                return config
        except FileNotFoundError:
            self.log(f"File not found: {file_path}", "ERROR")
            return {}
        except yaml.YAMLError as e:
            self.log(f"Error parsing YAML file {file_path}: {str(e)}", "ERROR")
            return {}
        except Exception as e:
            self.log(f"Unexpected error loading YAML file {file_path}: {str(e)}", "ERROR")
            return {}


###############################################################################
#                           Change Detector Action                            #
###############################################################################
class ChangeDetector(Action):
    """
    Detect changed applications (CloudFormation resources) based on the event type:
    pull_request, push, or workflow_dispatch.
    """

    def execute(self) -> int:
        """
        Main entry point to detect changed CloudFormation resources, then write them to GITHUB_OUTPUT.
        Returns:
            int: Return code (0 - success, non-0 - error)
        """
        # Gather environment variables
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        github_token = os.environ.get("GITHUB_TOKEN", "")
        github_repository = os.environ.get("GITHUB_REPOSITORY", "")
        github_sha = os.environ.get("GITHUB_SHA", "")
        event_before = os.environ.get("GITHUB_EVENT_BEFORE", "")
        github_output = os.environ.get("GITHUB_OUTPUT", "")

        event_path = os.environ.get("GITHUB_EVENT_PATH")
        event_data = {}
        if event_path and os.path.exists(event_path):
            with open(event_path, 'r') as f:
                event_data = json.load(f)

        # Extract specific event data
        resource_path = None
        app_name = None
        pr_number = None
        pr_head_sha = None

        # workflow_dispatch
        if event_name == "workflow_dispatch":
            if "inputs" in event_data and "resource_path" in event_data["inputs"]:
                resource_path = event_data["inputs"]["resource_path"]
            # app_name might come from environment
            app_name = os.environ.get("INPUT_APP_NAME", "")

        # pull_request
        elif event_name == "pull_request":
            if "pull_request" in event_data:
                pr_number = event_data["pull_request"].get("number")
                if "head" in event_data["pull_request"]:
                    pr_head_sha = event_data["pull_request"]["head"].get("sha")

        # detect changed paths
        paths = self._detect_changed_applications(
            event_name=event_name,
            github_token=github_token,
            github_repository=github_repository,
            github_sha=github_sha,
            event_before=event_before,
            pr_number=pr_number,
            pr_head_sha=pr_head_sha,
            resource_path=resource_path,
            app_name=app_name
        )

        # Output the result
        if github_output:
            with open(github_output, 'a') as f:
                f.write(f"paths={paths}\n")
            self.log(f"Detected paths: {paths}")
        else:
            print(f"paths={paths}")

        return 0

    ###########################################################################
    #                       Internal Helper Methods                            #
    ###########################################################################
    def _log(self, message: str) -> None:
        """Simple log (similar to self.log but simpler)."""
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"{timestamp} - {message}")

    def _run_command(self, command: str) -> str:
        """Run a shell command and return the output."""
        try:
            result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            self.log(f"Command failed: {command}", "ERROR")
            self.log(f"Error: {e}", "ERROR")
            return ""

    def _get_changed_files_pull_request(self, github_token: str, repo: str,
                                        pr_number: int, head_sha: str) -> List[str]:
        """
        Get changed files from a pull request using git and GitHub API as a fallback.
        """
        # Try to get the SHA of the commit before the latest one
        prev_sha = self._run_command(f"git rev-parse {head_sha}^")

        if prev_sha:
            # Get changes from just the latest commit, not the entire PR
            changed_files = self._run_command(f"git diff --name-only {prev_sha} {head_sha}")
            if changed_files:
                return changed_files.splitlines()

        # Fallback to GitHub API
        api_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
        headers = {"Authorization": f"token {github_token}"}
        response = requests.get(api_url, headers=headers)

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                return [file['filename'] for file in data]

        # Final fallback
        return self._run_command("git diff --name-only HEAD~1 HEAD").splitlines()

    def _get_changed_files_push(self, before_sha: str, after_sha: str) -> List[str]:
        """Get changed files from a push event."""
        parent_count = self._run_command(f"git cat-file -p {after_sha} | grep -c '^parent '")

        try:
            parent_count = int(parent_count)
        except ValueError:
            parent_count = 0

        if parent_count > 1:
            merge_base = self._run_command(f"git merge-base {before_sha} {after_sha}")
            return self._run_command(f"git diff --name-only {merge_base} {after_sha}").splitlines()
        else:
            changed_files = self._run_command(f"git diff --name-only {before_sha} {after_sha}")
            if not changed_files:
                changed_files = self._run_command(f"git diff --name-only {before_sha}..{after_sha}")
            return changed_files.splitlines()

    def _detect_changed_applications(
        self,
        event_name: str,
        github_token: str,
        github_repository: str,
        github_sha: str,
        event_before: Optional[str] = None,
        pr_number: Optional[int] = None,
        pr_head_sha: Optional[str] = None,
        resource_path: Optional[str] = None,
        app_name: Optional[str] = None
    ) -> str:
        """Detect changed applications (cloud-formation paths)."""

        # For workflow_dispatch events
        if event_name == "workflow_dispatch" and resource_path:
            # Validate resource path against app_name if provided
            if app_name:
                expected_prefix = f"cloud-formation/{app_name}/"
                if not resource_path.startswith(expected_prefix):
                    self.log(f"ERROR: Resource path '{resource_path}' is not valid for app '{app_name}'", "ERROR")
                    self.log(f"Resource path must start with '{expected_prefix}'", "ERROR")
                    return ""
            return resource_path

        changed_paths = set()
        changed_files = []

        # Get changed files based on event type
        if event_name == "pull_request" and pr_number and pr_head_sha:
            changed_files = self._get_changed_files_pull_request(
                github_token, github_repository, pr_number, pr_head_sha
            )
        elif event_name == "push" and event_before:
            changed_files = self._get_changed_files_push(event_before, github_sha)
        else:
            changed_files = self._run_command("git diff --name-only HEAD~1 HEAD").splitlines()

        # Process changed files to find cloud-formation changes
        for file in changed_files:
            if not file:
                continue

            # Check if the file is a deployment config file
            if file.startswith("cloud-formation/") and (file.endswith(".yml") or file.endswith(".yaml")):
                path_dir = os.path.dirname(file)
                changed_paths.add(path_dir)

        # Convert set to comma-separated string
        paths = ",".join(sorted(changed_paths))

        # Debug info if no paths found
        if not paths:
            self.log("No cloud-formation paths detected. Debug information:", "WARNING")
            self.log(f"Event name: {event_name}", "WARNING")
            self.log(f"SHA: {github_sha}", "WARNING")
            self.log(f"Before: {event_before or 'N/A'}", "WARNING")

        return paths


###############################################################################
#                                Entry Point                                  #
###############################################################################
def main():
    """Main CLI entry point to invoke specific actions based on arguments."""
    if len(sys.argv) < 2:
        print("Usage: python main.py <action_name>")
        print("Actions: parameter_processor, tag_processor, matrix_generator, change_detector")
        sys.exit(1)

    action_name = sys.argv[1].strip().lower()

    # Map the action names to their classes
    actions_map = {
        "parameter_processor": ParameterProcessor,
        "tag_processor": TagProcessor,
        "matrix_generator": DeploymentMatrixGenerator,
        "change_detector": ChangeDetector
    }

    if action_name not in actions_map:
        print(f"Unknown action '{action_name}'")
        sys.exit(1)

    # Instantiate the appropriate class
    action_class = actions_map[action_name]
    action_instance = action_class()

    # Execute and return its exit code
    result_code = action_instance.execute()
    sys.exit(result_code)


if __name__ == "__main__":
    main()