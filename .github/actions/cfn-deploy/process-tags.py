#!/usr/bin/env python3
import os
import json
import sys
from pathlib import Path
import re

def main():
    """
    Process CloudFormation tags from both JSON input and key=value pairs,
    and verify that tags are provided according to guidelines.
    """
    github_run_id = os.environ.get('GITHUB_RUN_ID', '')
    github_run_number = os.environ.get('GITHUB_RUN_NUMBER', '')
    tags_json = os.environ.get('INPUT_TAGS', '')
    tags_key_value = os.environ.get('INPUT_TAGS_KEY_VALUE', '')
    
    # Initialize empty tags list
    combined_tags = []
    
    # Process key=value format tags first
    if tags_key_value:
        # Process each line in the key=value input
        for line in tags_key_value.splitlines():
            line = line.strip()
            
            # Skip empty lines and comment lines
            if not line or line.startswith('#'):
                continue
                
            # Split the line by the first '=' and create a tag
            if '=' in line:
                key, value = line.split('=', 1)
                
                # Strip quotes from key and value
                key = key.strip()
                value = value.strip()
                
                # Remove surrounding quotes (both single and double)
                value = re.sub(r'^["\'](.*)["\']$', r'\1', value)
                
                combined_tags.append({
                    "Key": key,
                    "Value": value
                })
    
    # Process direct JSON tags input second (will override duplicates)
    if tags_json:
        try:
            # Parse JSON tags
            json_tags = json.loads(tags_json)
            
            # Create a dictionary of existing tags for easy lookup
            existing_tags = {tag["Key"]: i for i, tag in enumerate(combined_tags)}
            
            # Process each JSON tag
            for tag in json_tags:
                key = tag["Key"]
                if key in existing_tags:
                    # Override existing tag
                    combined_tags[existing_tags[key]] = tag
                else:
                    # Add new tag
                    combined_tags.append(tag)
        except json.JSONDecodeError:
            # If JSON parsing fails, just use what we have from key=value
            pass
    
    # Check if any tags were provided
    if not combined_tags:
        # No tags provided - this is an error condition
        error_message = "No tags are provided for this stack. Please follow the AWS tagging guidelines (https://catdigital.atlassian.net/wiki/spaces/CD/pages/105349296/AWS+Tagging)."
        print(f"\033[31m{error_message}\033[0m", file=sys.stderr)
        sys.exit(1)
    
    # Output the final combined tags
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f"TAGS={json.dumps(combined_tags)}\n")

if __name__ == "__main__":
    main()