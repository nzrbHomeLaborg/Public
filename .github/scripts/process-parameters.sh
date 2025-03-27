#!/bin/bash

# This script processes CloudFormation parameter files to replace secret placeholders
# Usage: ./process-parameters.sh <input-file> <output-file>

INPUT_FILE=$1
OUTPUT_FILE=$2

if [ -z "$INPUT_FILE" ] || [ -z "$OUTPUT_FILE" ]; then
  echo "Error: Missing required parameters"
  echo "Usage: $0 <input-file> <output-file>"
  exit 1
fi

if [ ! -f "$INPUT_FILE" ]; then
  echo "Error: Input file $INPUT_FILE does not exist"
  exit 1
fi

# Copy the input file to the output file
mkdir -p $(dirname "$OUTPUT_FILE")
cp "$INPUT_FILE" "$OUTPUT_FILE"

# Get all secrets from environment
ALL_SECRETS=$(env | grep "^SECRETS_" | cut -d= -f1)

# Replace each secret
for SECRET_VAR in $ALL_SECRETS; do
  # Get the actual secret name without the SECRETS_ prefix
  SECRET_NAME=${SECRET_VAR#SECRETS_}
  
  # Get the secret value
  SECRET_VALUE=${!SECRET_VAR}
  
  # Replace the secret placeholder
  sed -i "s/\"secrets.${SECRET_NAME}\"/\"${SECRET_VALUE}\"/g" "$OUTPUT_FILE"
done

echo "Parameters processed: $OUTPUT_FILE"
