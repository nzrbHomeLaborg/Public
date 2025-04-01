#!/bin/bash

# This script processes CloudFormation parameter files and inline parameters to replace secret placeholders
# Usage: ./process-parameters.sh <input-file> <output-file> [inline-params]

INPUT_FILE=$1
OUTPUT_FILE=$2
INLINE_PARAMS=$3

echo "DEBUG: Script started with:"
echo "DEBUG: Input file: $INPUT_FILE"
echo "DEBUG: Output file: $OUTPUT_FILE"
echo "DEBUG: Inline params: $INLINE_PARAMS"

# Function to replace secrets in a string
replace_secrets() {
  local input=$1
  local output=$input
  
  # Get all secrets from environment
  local ALL_SECRETS=$(env | grep "^SECRETS_" | cut -d= -f1)
  echo "DEBUG: Found secrets: ${ALL_SECRETS:-none}"
  
  # Replace each secret
  for SECRET_VAR in $ALL_SECRETS; do
    # Get the actual secret name without the SECRETS_ prefix
    local SECRET_NAME=${SECRET_VAR#SECRETS_}
    
    # Get the secret value (mask it in logs)
    local SECRET_VALUE=${!SECRET_VAR}
    local MASKED_VALUE="****"
    
    echo "DEBUG: Replacing 'secrets.$SECRET_NAME' with '$MASKED_VALUE'"
    
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
  
  echo "DEBUG: Processing parameter file"
  
  # Copy the input file to the output file
  mkdir -p $(dirname "$OUTPUT_FILE")
  cp "$INPUT_FILE" "$OUTPUT_FILE"
  
  # Get all secrets from environment
  ALL_SECRETS=$(env | grep "^SECRETS_" | cut -d= -f1)
  
  if [ -z "$ALL_SECRETS" ]; then
    echo "WARNING: No secrets found in environment. No replacements will be made."
  else
    # Replace each secret
    for SECRET_VAR in $ALL_SECRETS; do
      # Get the actual secret name without the SECRETS_ prefix
      SECRET_NAME=${SECRET_VAR#SECRETS_}
      
      # Get the secret value (mask it in logs)
      SECRET_VALUE=${!SECRET_VAR}
      MASKED_VALUE="****"
      
      echo "DEBUG: Looking for \"secrets.${SECRET_NAME}\" pattern in parameter file"
      MATCHES=$(grep -c "secrets.${SECRET_NAME}" "$OUTPUT_FILE" || echo "0")
      echo "DEBUG: Found $MATCHES occurrences"
      
      # Replace the secret placeholder
      sed -i "s/\"secrets.${SECRET_NAME}\"/\"${SECRET_VALUE}\"/g" "$OUTPUT_FILE"
      
      # Verify replacement
      REMAINING=$(grep -c "secrets.${SECRET_NAME}" "$OUTPUT_FILE" || echo "0")
      echo "DEBUG: After replacement, $REMAINING occurrences remain"
    done
  fi
  
  echo "Parameters file processed: $OUTPUT_FILE"
fi

# Process inline parameters if provided
if [ -n "$INLINE_PARAMS" ] && [ "$INLINE_PARAMS" != "null" ]; then
  echo "DEBUG: Processing inline parameters"
  PROCESSED_INLINE_PARAMS=$(replace_secrets "$INLINE_PARAMS")
  echo "DEBUG: Original inline parameters: $INLINE_PARAMS"
  echo "DEBUG: Processed inline parameters: $PROCESSED_INLINE_PARAMS"
  echo "inline_params_output=$PROCESSED_INLINE_PARAMS"
else
  echo "DEBUG: No inline parameters to process"
fi

echo "DEBUG: Script completed"
# Exit with success regardless of replacements
exit 0
