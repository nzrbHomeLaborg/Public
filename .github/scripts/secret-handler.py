#!/usr/bin/env python3
import os
import json
import sys
import base64
import hashlib
import logging
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

BLUE = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

def generate_key(salt_key, github_run_id):
    """
    Generate a secure encryption key using the salt key and GitHub run ID
    
    Args:
        salt_key (str): Salt key used for additional security
        github_run_id (str): GitHub run ID to make key unique for each run
        
    Returns:
        bytes: Encryption key
    """
    # Combine salt key with run ID to make it unique per workflow run
    combined_key = f"{salt_key}:{github_run_id}"
    salt = hashlib.sha256(combined_key.encode()).digest()
    
    # Use PBKDF2 to derive a secure key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    
    key = base64.urlsafe_b64encode(kdf.derive(salt_key.encode()))
    return key

def encrypt_secrets(secrets_dict, salt_key, github_run_id):
    """
    Encrypt secrets dictionary with Fernet symmetric encryption
    
    Args:
        secrets_dict (dict): Dictionary of secrets to encrypt
        salt_key (str): Salt key for encryption
        github_run_id (str): GitHub run ID
        
    Returns:
        str: Base64 encoded encrypted string
    """
    key = generate_key(salt_key, github_run_id)
    fernet = Fernet(key)
    
    # Convert secrets dict to JSON string
    secrets_json = json.dumps(secrets_dict)
    
    # Encrypt the JSON string
    encrypted_data = fernet.encrypt(secrets_json.encode())
    
    # Convert to base64 for storage/transmission
    return base64.b64encode(encrypted_data).decode()

def decrypt_secrets(encrypted_data, salt_key, github_run_id):
    """
    Decrypt encrypted secrets data
    
    Args:
        encrypted_data (str): Base64 encoded encrypted data
        salt_key (str): Salt key used for encryption
        github_run_id (str): GitHub run ID used for encryption
        
    Returns:
        dict: Decrypted secrets dictionary
    """
    key = generate_key(salt_key, github_run_id)
    fernet = Fernet(key)
    
    # Decode from base64
    encrypted_bytes = base64.b64decode(encrypted_data)
    
    # Decrypt the data
    decrypted_data = fernet.decrypt(encrypted_bytes).decode()
    
    # Parse JSON back to dictionary
    return json.loads(decrypted_data)

def load_github_secrets():
    """
    Load GitHub secrets from environment variables
    
    Returns:
        dict: Dictionary with secret names as keys and their values
    """
    secrets = {}
    
    # Iterate through all environment variables
    for key, value in os.environ.items():
        # Include only variables that could be GitHub secrets
        # Exclude standard GitHub environment variables
        if not key.startswith('GITHUB_') and not key.startswith('INPUT_') and not key.startswith('RUNNER_'):
            secrets[key] = value
    
    logger.info(f"{BLUE}Loaded {len(secrets)} potential secrets from environment variables{RESET}")
    return secrets

def store_encrypted_secrets(secrets, salt_key, output_path=None):
    """
    Encrypt and store secrets to a file
    
    Args:
        secrets (dict): Secrets dictionary to encrypt
        salt_key (str): Salt key for encryption
        output_path (str, optional): Path to save encrypted secrets
    
    Returns:
        str: Path to the encrypted secrets file
    """
    github_run_id = os.environ.get('GITHUB_RUN_ID', '')
    github_run_number = os.environ.get('GITHUB_RUN_NUMBER', '')
    
    if not output_path:
        tmp_path = f"/tmp/{github_run_id}{github_run_number}"
        Path(tmp_path).mkdir(parents=True, exist_ok=True)
        output_path = f"{tmp_path}/encrypted-secrets-{github_run_id}.b64"
    
    encrypted_data = encrypt_secrets(secrets, salt_key, github_run_id)
    
    try:
        with open(output_path, 'w') as f:
            f.write(encrypted_data)
        logger.info(f"{GREEN}Encrypted secrets stored at: {output_path}{RESET}")
        return output_path
    except Exception as e:
        logger.error(f"{RED}Failed to write encrypted secrets: {e}{RESET}")
        return None

def read_encrypted_secrets(encrypted_file_path, salt_key):
    """
    Read and decrypt secrets from a file
    
    Args:
        encrypted_file_path (str): Path to encrypted secrets file
        salt_key (str): Salt key for decryption
        
    Returns:
        dict: Decrypted secrets dictionary
    """
    github_run_id = os.environ.get('GITHUB_RUN_ID', '')
    
    try:
        with open(encrypted_file_path, 'r') as f:
            encrypted_data = f.read()
        
        secrets = decrypt_secrets(encrypted_data, salt_key, github_run_id)
        logger.info(f"{GREEN}Successfully decrypted secrets from: {encrypted_file_path}{RESET}")
        return secrets
    except Exception as e:
        logger.error(f"{RED}Failed to read/decrypt secrets: {e}{RESET}")
        return {}

def process_parameters_with_secrets(parameters, secrets):
    """
    Process parameters and replace SECRET: references with actual values
    
    Args:
        parameters (list or dict): Parameters to process
        secrets (dict): Secrets dictionary
        
    Returns:
        list or dict: Processed parameters
    """
    if isinstance(parameters, list):
        # For list format (ParameterKey/ParameterValue)
        for param in parameters:
            if isinstance(param.get("ParameterValue"), str) and param["ParameterValue"].startswith("SECRET:"):
                secret_name = param["ParameterValue"].replace("SECRET:", "")
                if secret_name in secrets:
                    logger.info(f"{GREEN}Replacing SECRET:{secret_name} with actual secret value{RESET}")
                    param["ParameterValue"] = secrets[secret_name]
                else:
                    logger.warning(f"{YELLOW}Secret {secret_name} not found in available secrets{RESET}")
        return parameters
    elif isinstance(parameters, dict):
        # For dictionary format
        processed = {}
        for key, value in parameters.items():
            if isinstance(value, str) and value.startswith("SECRET:"):
                secret_name = value.replace("SECRET:", "")
                if secret_name in secrets:
                    logger.info(f"{GREEN}Replacing SECRET:{secret_name} with actual secret value{RESET}")
                    processed[key] = secrets[secret_name]
                else:
                    logger.warning(f"{YELLOW}Secret {secret_name} not found in available secrets{RESET}")
                    processed[key] = value
            else:
                processed[key] = value
        return processed
    else:
        logger.warning(f"{YELLOW}Unsupported parameter type: {type(parameters)}{RESET}")
        return parameters

# Command-line interface functions
def encrypt_command(args):
    """Handle the encrypt command"""
    if len(args) < 1:
        logger.error(f"{RED}Missing salt key argument{RESET}")
        print("Usage: secret-handler.py encrypt <salt_key> [output_path]")
        sys.exit(1)
    
    salt_key = args[0]
    output_path = args[1] if len(args) > 1 else None
    
    secrets = load_github_secrets()
    if not secrets:
        logger.warning(f"{YELLOW}No secrets found to encrypt{RESET}")
        sys.exit(1)
    
    encrypted_file = store_encrypted_secrets(secrets, salt_key, output_path)
    if encrypted_file:
        # Add file path to GitHub outputs
        if 'GITHUB_OUTPUT' in os.environ:
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f"SECRETS_FILE={encrypted_file}\n")
        print(f"::set-output name=secrets_file::{encrypted_file}")
    else:
        sys.exit(1)

def decrypt_command(args):
    """Handle the decrypt command"""
    if len(args) < 2:
        logger.error(f"{RED}Missing arguments{RESET}")
        print("Usage: secret-handler.py decrypt <encrypted_file> <salt_key>")
        sys.exit(1)
    
    encrypted_file = args[0]
    salt_key = args[1]
    
    secrets = read_encrypted_secrets(encrypted_file, salt_key)
    if not secrets:
        logger.error(f"{RED}Failed to decrypt secrets or no secrets found{RESET}")
        sys.exit(1)
    
    # Set each secret as an environment variable
    for key, value in secrets.items():
        os.environ[key] = value
    
    logger.info(f"{GREEN}Successfully set {len(secrets)} secrets as environment variables{RESET}")

def process_parameters_command(args):
    """Handle the process-parameters command"""
    if len(args) < 3:
        logger.error(f"{RED}Missing arguments{RESET}")
        print("Usage: secret-handler.py process-parameters <encrypted_file> <salt_key> <parameter_file> [output_file]")
        sys.exit(1)
    
    encrypted_file = args[0]
    salt_key = args[1]
    parameter_file = args[2]
    output_file = args[3] if len(args) > 3 else None
    
    secrets = read_encrypted_secrets(encrypted_file, salt_key)
    if not secrets:
        logger.error(f"{RED}Failed to decrypt secrets or no secrets found{RESET}")
        sys.exit(1)
    
    # Read parameters file
    try:
        with open(parameter_file, 'r') as f:
            parameters = json.load(f)
    except Exception as e:
        logger.error(f"{RED}Failed to read parameters file: {e}{RESET}")
        sys.exit(1)
    
    # Process parameters
    processed_parameters = process_parameters_with_secrets(parameters, secrets)
    
    # Write processed parameters
    if output_file:
        try:
            with open(output_file, 'w') as f:
                json.dump(processed_parameters, f, indent=2)
            logger.info(f"{GREEN}Processed parameters written to: {output_file}{RESET}")
            
            # Add file path to GitHub outputs
            if 'GITHUB_OUTPUT' in os.environ:
                with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                    f.write(f"PROCESSED_PARAM_FILE={output_file}\n")
            print(f"::set-output name=processed_param_file::{output_file}")
        except Exception as e:
            logger.error(f"{RED}Failed to write processed parameters: {e}{RESET}")
            sys.exit(1)
    else:
        # Print processed parameters to stdout (as JSON)2131231
        print(json.dumps(processed_parameters))

def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: secret-handler.py <command> [args...]")
        print("\nCommands:")
        print("  encrypt <salt_key> [output_path]         - Encrypt secrets from environment")
        print("  decrypt <encrypted_file> <salt_key>      - Decrypt secrets to environment")
        print("  process-parameters <encrypted_file> <salt_key> <parameter_file> [output_file]")
        print("                                           - Process parameters with secrets")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    args = sys.argv[2:]
    
    if command == "encrypt":
        encrypt_command(args)
    elif command == "decrypt":
        decrypt_command(args)
    elif command == "process-parameters":
        process_parameters_command(args)
    else:
        logger.error(f"{RED}Unknown command: {command}{RESET}")
        sys.exit(1)

if __name__ == "__main__":
    main()
