#!/usr/bin/env bash
#
# Provisions (or refreshes) a Python virtualenv built from the CURRENT key4hep
# nightly build's own python3 interpreter - not the system python, and not a
# fixed/pinned one. This matters: a venv based on some other python (or one
# based on a nightly that has since aged out of CVMFS) will eventually diverge
# from whatever PYTHONPATH the *current* nightly injects (e.g. numpy/podio/
# pyLCIO), causing hard-to-diagnose ABI mismatches at import time.
#
# On every invocation ("on-load"), checks whether the key4hep nightly currently
# available on CVMFS is newer than the one the environment was last built
# against (recorded in a marker file inside the venv); if so, the environment
# directory is removed and rebuilt from scratch against the new nightly.
#
# Usage: source env_setup_nightly.sh [env_name]
#   env_name: directory name for the venv, created as a sibling of this repo's
#             root directory. If omitted, reuses .env's existing ENV_NAME, or
#             falls back to "testenv" if neither is set.
#
# Must be sourced (not executed) for the venv activation to take effect in the
# calling shell, e.g. from setup.sh or interactively:
#   source hep_workflows/env_setup_nightly.sh
#
# Stores the environment's name in .env under ENV_NAME (and updates
# PYTHON_ENVIRONMENT_PATH, the key setup.sh actually activates, to match), so
# later invocations - of this script or of setup.sh - find it again without
# needing env_name to be passed explicitly.

action() {
    # key4hep's own setup.sh is not nounset-safe, so -u is intentionally not set
    set -eo pipefail

    local shell_is_zsh this_file this_dir repo_root env_file env_name env_path nightly_marker latest_link latest_nightly

    # ${BASH_SOURCE[0]} doesn't exist under zsh - same detection setup.sh uses
    shell_is_zsh="$( [ -z "${ZSH_VERSION}" ] && echo "false" || echo "true" )"
    this_file="$( ${shell_is_zsh} && echo "${(%):-%x}" || echo "${BASH_SOURCE[0]}" )"
    this_dir="$(cd "$(dirname "${this_file}")" && pwd)"
    repo_root="$(dirname "$this_dir")"
    env_file="$this_dir/.env"

    # 1) resolve the requested/existing environment name
    if [ -n "$1" ]; then
        env_name="$1"
    elif [ -f "$env_file" ] && grep -q '^ENV_NAME=' "$env_file"; then
        env_name="$(grep '^ENV_NAME=' "$env_file" | tail -1 | cut -d= -f2- | tr -d '"')"
    else
        env_name="testenv"
    fi
    env_path="$repo_root/$env_name"
    nightly_marker="$env_path/.key4hep_nightly_date"

    # 2) determine the currently available "latest" key4hep nightly release date -
    # all *-opt platform symlinks under releases/latest-opt point at the same date,
    # so picking whichever exists on this machine is enough
    latest_link="$(find /cvmfs/sw-nightlies.hsf.org/key4hep/releases/latest-opt -mindepth 1 -maxdepth 1 -iname '*-opt' | head -1)"
    if [ -z "$latest_link" ]; then
        echo "env_setup_nightly.sh: could not find a key4hep nightly under /cvmfs/sw-nightlies.hsf.org/key4hep/releases/latest-opt" >&2
        return 1
    fi
    latest_nightly="$(basename "$(dirname "$(readlink -f "$latest_link")")")"

    # 3) if the env exists but was built against an older nightly, drop it so step 4
    # rebuilds it fresh
    if [ -d "$env_path" ]; then
        if [ ! -f "$nightly_marker" ] || [ "$(cat "$nightly_marker")" != "$latest_nightly" ]; then
            echo "env_setup_nightly.sh: newer key4hep nightly available ($latest_nightly) - recreating $env_path"
            rm -rf "$env_path"
        fi
    fi

    # 4) (re-)create the venv against the current nightly's own python3
    if [ ! -d "$env_path" ]; then
        echo "env_setup_nightly.sh: provisioning $env_path against key4hep nightly $latest_nightly"

        source /cvmfs/sw-nightlies.hsf.org/key4hep/setup.sh
        if [ -z "$KEY4HEP_STACK" ]; then
            echo "env_setup_nightly.sh: failed to source the key4hep nightly stack" >&2
            return 1
        fi

        "$(command -v python3)" -m venv --system-site-packages "$env_path"
        source "$env_path/bin/activate"
        pip install --quiet --upgrade pip
        if [ -f "$repo_root/requirements.txt" ]; then
            pip install --quiet -r "$repo_root/requirements.txt"
        fi

        echo "$latest_nightly" > "$nightly_marker"
    else
        source "$env_path/bin/activate"
    fi

    # 5) record env_name/PYTHON_ENVIRONMENT_PATH in .env, preserving all other keys
    touch "$env_file"
    local tmp_file="$env_file.tmp"
    { grep -v -e '^ENV_NAME=' -e '^PYTHON_ENVIRONMENT_PATH=' "$env_file" || true; } > "$tmp_file"
    {
        cat "$tmp_file"
        echo "ENV_NAME=\"$env_name\""
        echo "PYTHON_ENVIRONMENT_PATH=\"$env_path\""
    } > "$env_file"
    rm -f "$tmp_file"

    echo "env_setup_nightly.sh: using $env_path (key4hep nightly $(cat "$nightly_marker"))"
}
action "$@"
