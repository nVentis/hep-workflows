#!/usr/bin/env bash

# Bootstrap file for batch jobs that is sent with all jobs and
# automatically called by the law remote job wrapper script to find the
# setup.sh file sets up software and some environment variables
# The variables in curly braces are "rendered" in framework.py
# and the output file is written to task_dir/
# - ANALYSIS_PATH={{ANALYSIS_PATH}}
# - DOT_ENVIRONMENT_FILE={{DOT_ENVIRONMENT_FILE}}
# - SH_ENVIRONMENT_FILE={{SH_ENVIRONMENT_FILE}}

action() {
    if [ -f "{{DOT_ENVIRONMENT_FILE}}" ]; then
        export $(grep -v '^#' "{{DOT_ENVIRONMENT_FILE}}" | xargs)
    fi

    if [ -f "{{SH_ENVIRONMENT_FILE}}" ]; then
        export SH_ENVIRONMENT_FILE="$SH_ENVIRONMENT_FILE"
        source "{{SH_ENVIRONMENT_FILE}}"
    elif [ -f "{{ANALYSIS_PATH}}/setup.sh" ]; then
        export SH_ENVIRONMENT_FILE="{{ANALYSIS_PATH}}/setup.sh"
        source "{{ANALYSIS_PATH}}/setup.sh"
    fi
}
action
