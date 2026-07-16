#!/usr/bin/env bash

# this script loads the environment for scheduling law tasks
# you may define three environment variables to control it:
# DOT_ENVIRONMENT_FILE: file with entries of <NAME>=<VALUE>
# SH_ENVIRONMENT_FILE: 
# K4H_RELEASE: if 

action() {    
    local shell_is_zsh="$( [ -z "${ZSH_VERSION}" ] && echo "false" || echo "true" )"
    local this_file="$( ${shell_is_zsh} && echo "${(%):-%x}" || echo "${BASH_SOURCE[0]}" )"
    local this_dir="$( cd "$( dirname "${this_file}" )" && pwd )"

    export PYTHONPATH="${this_dir}:${PYTHONPATH}"
    export PATH="${this_dir}/bin:${PATH}"
    export LAW_HOME="${this_dir}/.law"
    export LAW_CONFIG_FILE="$(realpath "$this_dir/../law.cfg")"

    # either define here or load from .env file
    export ANALYSIS_PATH="${this_dir}"

    # if DOT_ENVIRONMENT_FILE is empty but an .env file in ANALYSIS_PATH was found, use that
    if [ -z "$DOT_ENVIRONMENT_FILE" ] && [ -f "$ANALYSIS_PATH/.env" ]; then
        export DOT_ENVIRONMENT_FILE="$ANALYSIS_PATH/.env"
    fi

    # load env variables from DOT_ENVIRONMENT_FILE
    if [ -f "$DOT_ENVIRONMENT_FILE" ]; then
        export $(grep -v '^#' "$DOT_ENVIRONMENT_FILE" | xargs)
    fi

    # load SW environment: either from SH_ENVIRONMENT_FILE OR key4hep release specified by K4H_RELEASE 
    if [ -f "$SH_ENVIRONMENT_FILE" ]; then
        # handle the case SH_ENVIRONMENT_FILE == this_file 
        local SH_ENVIRONMENT_FILE__="$SH_ENVIRONMENT_FILE"
        unset SH_ENVIRONMENT_FILE

        source "$SH_ENVIRONMENT_FILE"
        export SH_ENVIRONMENT_FILE="$SH_ENVIRONMENT_FILE__"
        unset SH_ENVIRONMENT_FILE
    elif [ ! -z "$K4H_RELEASE" ]; then
        export SH_ENVIRONMENT_FILE="$ANALYSIS_PATH/setup.sh" # set SH_ENVIRONMENT_FILE to this file if K4H_RELEASE exists and no SH_ENVIRONMENT_FILE was defined before
        source /cvmfs/sw.hsf.org/key4hep/setup.sh -r "$K4H_RELEASE"
    fi

    if [ -z "$KEY4HEP_STACK" ]; then
        echo "Critical Error: Did not find key4hep stack"
        return 1
    fi
    
    source "$PYTHON_ENVIRONMENT_PATH/bin/activate"
    source "$( law completion )" ""
}
action
