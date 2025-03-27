#!/bin/bash

# This script processes CloudFormation parameter files and inline parameters to replace secret placeholders
# Usage: ./process-parameters.sh <input-file> <output-file> [inline-params]

INPUT_FILE=$1
OUTPUT_FILE=$2
INLINE_PARAMS=$3

# Function to replace secrets in a string
replace_secrets() {
  local input=$1
  local output=$input
  
  # Get all secrets from environment
  local ALL_SECRETS=$(env | grep "^SECRETS_" | cut -d= -f1)
  
  # Replace each secret
  for SECRET_VAR in $ALL_SECRETS; do
    # Get the actual secret name without the SECRETS_ prefix
    local SECRET_NAME=${SECRET_VAR#SECRETS_}
    
    # Get the secret value
    local SECRET_VALUE=${!SECRET_VAR}
    
    # Replace the secret placeholder
    output=$(echo "$output" | sed "s/secrets.$SECRET_NAME/$SECRET_VALUE/g")
  done
  
  echo "$output"
}

# Process parameter file if provided
if [ -n "$INPUT_FILE" ] && [ -n "$OUTPUT_FILE" ]; then
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
  
  echo "Parameters file processed: $OUTPUT_FILE"
fi

# Process inline parameters if provided
if [ -n "$INLINE_PARAMS" ]; then
  PROCESSED_INLINE_PARAMS=$(replace_secrets "$INLINE_PARAMS")
  echo "inline_params_output=$PROCESSED_INLINE_PARAMS"
fi
