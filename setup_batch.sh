#!/usr/bin/env bash

if [ -z "$MARLIN_DLL" ]; then
    if [ -d "$ANALYSIS_PATH" ] && [ -f "${ANALYSIS_PATH}/.env" ]; then
        export $(grep -v '^#' "${this_dir}/.env" | xargs)
    fi

    source /cvmfs/sw.hsf.org/key4hep/setup.sh -r "$K4H_RELEASE"
fi