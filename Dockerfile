# Image for running the workflows and their tests: key4hep from
# CVMFS (mounted by /mount.sh of the base image when the container
# starts) and this repository with a Python environment using the
# Python binary of key4hep on top of it.
#
# The CVMFS mount does not persist across RUN instructions, so
# everything that needs key4hep (creating the Python environment)
# happens in a single RUN that mounts CVMFS first. This requires
# BuildKit with
#   docker buildx build --allow security.insecure ...
#
# The build context is the repository (see .dockerignore). Usage:
#   docker buildx build --allow security.insecure -t hep-workflows .
#   docker run --privileged -it hep-workflows
# then e.g.: source hep_workflows/setup.sh && pytest -m integration

FROM ghcr.io/key4hep/key4hep-images/alma9-cvmfs:latest AS base

# the key4hep stack to use; K4H_NIGHTLY (a weekday of the LCG nightly, or latest)
# takes priority over K4H_RELEASE (see setup.sh). full simulation and the k4run steering files of the test configurations require a nightly
ARG K4H_NIGHTLY=""
ARG K4H_RELEASE=""

ARG DATA_PATH="/data"
ARG PYTHON_ENVIRONMENT_PATH="/hep_workflows/testenv"
# dependencies not in the key4hep stack that are provisioned on demand, see hep_workflows/configs/provisioning.py
ARG PROVISION_DIR="/deps"

# environment read by hep_workflows/setup.sh
ENV K4H_NIGHTLY=${K4H_NIGHTLY}
ENV K4H_RELEASE=${K4H_RELEASE}
ENV DATA_PATH=${DATA_PATH}
ENV PYTHON_ENVIRONMENT_PATH=${PYTHON_ENVIRONMENT_PATH}
ENV PROVISION_DIR=${PROVISION_DIR}

# source, abort on any error
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# blas and lapack are required to compile SGV; git and curl to install it and ILDConfig;
# libtirpc-devel provides the libtirpc.so link-time symlink: Whizard links its process libraries against -ltirpc at run time
RUN dnf install -y blas-devel lapack-devel git curl libtirpc-devel && dnf clean all

COPY . /hep_workflows
WORKDIR /hep_workflows

RUN mkdir -p "$DATA_PATH" "$PROVISION_DIR"

# Everything that is tied to the stack is done in one RUN, which has to mount CVMFS itself:
# - K4H_NIGHTLY (a weekday Mon, ..., Sat, or latest) is resolved to the weekday of the LCG devkey-head view and pinned in hep_workflows/.env
#   (read by setup.sh, overrides ENV) so that containers started later use the stack the image
#   was built with. Keep in mind this only works for one week (after that you might want to use
#   env_setup_nightly.sh to switch to the then-newest nightly and reinstall the Python environment)
# - the Python environment must be created with the Python of the stack
# - the law index (hep_workflows/.law is not part of the build context) must be created, as `law run <task>` does not find any task without it
# - SGV is compiled against the stack
# ILDConfig (required by ddsim/k4run based simulation and reconstruction) does not depend on the stack and is large:
# it is cloned by the configurations that need it (see hep_workflows/configs/provisioning.py) when the tests run.
# None of this may be cached by the builder: the result depends on the content of CVMFS, not on this file.
RUN --security=insecure \
    /mount.sh \
    && [ -d /cvmfs/sw.hsf.org/key4hep ] && echo "key4hep found" \
    && if [ "${K4H_NIGHTLY,,}" = "latest" ]; then \
         K4H_NIGHTLY="$(basename "$(dirname "$(readlink /cvmfs/sft-nightlies.cern.ch/lcg/views/devkey-head/latest/x86_64-el9-gcc16-opt)")")"; \
       fi \
    && echo "Using the key4hep nightly: ${K4H_NIGHTLY:-none}" \
    && printf 'K4H_NIGHTLY="%s"\n' "$K4H_NIGHTLY" > /hep_workflows/hep_workflows/.env \
    && set +e && source /hep_workflows/hep_workflows/setup.sh; set -e \
    && [ -n "$KEY4HEP_STACK" ] \
    && python -m venv --system-site-packages "$PYTHON_ENVIRONMENT_PATH" \
    && source "$PYTHON_ENVIRONMENT_PATH/bin/activate" \
    && pip install -e ".[test]" \
    && law index --verbose \
    && python -c "from hep_workflows.configs.provisioning import provision_sgv; provision_sgv()" \
    && [ -f "$PROVISION_DIR/sgv/tests/usesgvlcio.exe" ] \
    && echo "hep_workflows setup. Done"

ENTRYPOINT ["/mount.sh"]
CMD ["/bin/bash"]
