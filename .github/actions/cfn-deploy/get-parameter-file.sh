#!/bin/bash
set -eu # Increase bash strictness

blue="\\e[36m"
reset="\\e[0m"

tmpPath="/tmp/${GITHUB_RUN_ID}${GITHUB_RUN_NUMBER}"
paramFile="${tmpPath}/cfn-parameter-${GITHUB_RUN_ID}-${GITHUB_RUN_NUMBER}.json"

if [[ "${INPUT_PARAMETER_OVERRIDES}" != "" ]]; then
    echo -e "${blue}parameter-overrides are available.${reset}"
    echo "PARAM_FILE=${INPUT_PARAMETER_OVERRIDES}" >> $GITHUB_OUTPUT
    exit 0

elif [[ "${INPUT_INLINE_JSON_PARAMETERS}" != "" ]]; then
    echo -e "${blue}inline-json-parameters are available.${reset}"
    mkdir ${tmpPath} 2>&1 || exit_val="$?"
    echo -e "${blue}${tmpPath} created..${reset}"
    echo "${INPUT_INLINE_JSON_PARAMETERS}" > ${paramFile}
    echo -e "${blue}${paramFile} created..${reset}"
    echo "PARAM_FILE=file:///${paramFile}" >> $GITHUB_OUTPUT
    exit 0

else
    echo -e "${blue}No CFN parameters are available.${reset}"
    echo "PARAM_FILE=" >> $GITHUB_OUTPUT
fi