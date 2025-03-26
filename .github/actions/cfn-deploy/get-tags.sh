#!/bin/bash
set -eu # Increase bash strictness

blue="\\e[36m"
reset="\\e[0m"

tmpPath="/tmp/${GITHUB_RUN_ID}${GITHUB_RUN_NUMBER}"
tagsFile="${tmpPath}/cfn-tags-${GITHUB_RUN_ID}-${GITHUB_RUN_NUMBER}.json"

if [[ "${INPUT_TAGS}" != "" ]]; then
    echo -e "${blue}tags are available.${reset}"
    echo "TAGS=${INPUT_TAGS}" >> $GITHUB_OUTPUT

elif [[ "${INPUT_TAGS_KEY_VALUE}" != "" ]]; then
    echo -e "${blue}tags-key-values are available.${reset}"
    mkdir ${tmpPath} 2>&1 || exit_val="$?"
    echo -e "${blue}${tmpPath} created..${reset}"
    echo "${INPUT_TAGS_KEY_VALUE}" > $tagsFile
    # remove all " from the file
    sed -i -e 's|"||g' "${tagsFile}"

    last_line=$(wc -l < $tagsFile)
    current_line=0
    tags_content=$(echo -n "[" 
                    while read line 
                    do 
                        current_line=$(($current_line + 1)) 
                        if [[ $current_line -ne $last_line ]]; then 
                        [ -z "$line" ] && continue 
                            echo -n "$line" | awk -F'='  '{ printf "{\"Key\":\""$1"\",\"Value\":\""$2"\"},"}' | grep -iv '\"#' 
                        else 
                            echo -n "$line" | awk -F'='  '{ printf "{\"Key\":\""$1"\",\"Value\":\""$2"\"}"}' | grep -iv '\"#' 
                        fi 
                    done < $tagsFile 
                    echo -n "]" 
                )
    tags_content=$(echo ${tags_content} | sed -z 's/}, ]/} ]/g')
    # echo "${tags_content}" | sed -z 's/\n/ /g'
    echo "TAGS=$(echo ${tags_content} | sed -z 's/\n/ /g')" >> $GITHUB_OUTPUT

else
    echo -e "${blue}No tags parameters are available.${reset}"
    echo "TAGS=" >> $GITHUB_OUTPUT
fi