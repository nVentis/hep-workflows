#!/usr/bin/env bash

action() {    
    local shell_is_zsh="$( [ -z "${ZSH_VERSION}" ] && echo "false" || echo "true" )"
    local this_file="$( ${shell_is_zsh} && echo "${(%):-%x}" || echo "${BASH_SOURCE[0]}" )"
    local this_dir="$( cd "$( dirname "${this_file}" )" && pwd )"

    export PYTHONPATH="${this_dir}:${PYTHONPATH}"
    export LAW_HOME="${this_dir}/.law"
    export LAW_CONFIG_FILE="${this_dir}/law.cfg"

    # either define here or load from .env file
    export ANALYSIS_PATH="${this_dir}"

    if [ -f "${this_dir}/.env" ]; then
        export $(grep -v '^#' "${this_dir}/.env" | xargs)
    fi

    source /cvmfs/sw.hsf.org/key4hep/setup.sh -r "$K4H_RELEASE"
    source "$ENVIRONMENT_PATH/bin/activate"

    source "$( law completion )" ""
}
action
