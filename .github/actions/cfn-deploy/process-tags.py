#!/usr/bin/env python3
import os
import json
import sys
from pathlib import Path
import re

def main():
    
    github_run_id = os.environ.get('GITHUB_RUN_ID', '')
    github_run_number = os.environ.get('GITHUB_RUN_NUMBER', '')
    
    # Get tags from environment variables
    tags_json = os.environ.get('INPUT_TAGS', '')
    tags_key_value = os.environ.get('INPUT_TAGS_KEY_VALUE', '')
    
    # Initialize empty tags list
    combined_tags = []
    
    # Process direct JSON tags input first
    if tags_json:
        try:
            json_tags = json.loads(tags_json)
            combined_tags.extend(json_tags)
        except json.JSONDecodeError:
            pass
    
    # Process key-value pair tags second (will override JSON tags)
    if tags_key_value:
        existing_tags = {tag["Key"]: i for i, tag in enumerate(combined_tags)}
        
        for line in tags_key_value.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                value = re.sub(r'^["\'](.*)["\']$', r'\1', value)
                
                # If the key already exists, replace the existing tag
                if key in existing_tags:
                    combined_tags[existing_tags[key]] = {
                        "Key": key,
                        "Value": value
                    }
                else:
                    # Add new tag
                    combined_tags.append({
                        "Key": key,
                        "Value": value
                    })
    
    # Check if any tags were provided
    if not combined_tags:
        error_message = "No tags are provided for this stack. Please follow the AWS tagging guidelines (https://catdigital.atlassian.net/wiki/spaces/CD/pages/105349296/AWS+Tagging)."
        print(f"\033[31m{error_message}\033[0m", file=sys.stderr)
        sys.exit(1)
    
    # Output the final combined tags
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f"TAGS={json.dumps(combined_tags)}\n")

if __name__ == "__main__":
    main()