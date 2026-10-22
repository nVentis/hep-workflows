FROM ghcr.io/key4hep/key4hep-images/alma9-cvmfs:latest AS base

# defaults
ARG branch=main
ARG link_repo

ARG K4H_NIGHTLY=latest
ARG K4H_RELEASE=""
ARG DATA_PATH="/data"

ARG SGV_DIR
ARG ILD_CONFIG_DIR

ARG ENV_NAME="testenv"
ARG PYTHON_ENVIRONMENT_PATH="/hep_workflows/testenv"

# environment variables
ENV K4H_NIGHTLY=${K4H_NIGHTLY}
ENV K4H_RELEASE=${K4H_RELEASE}
ENV DATA_PATH=${DATA_PATH}

ENV SGV_DIR=${SGV_DIR}
ENV ILD_CONFIG_DIR=${ILD_CONFIG_DIR}
ENV ENV_NAME=${ENV_NAME}
ENV PYTHON_ENVIRONMENT_PATH=${PYTHON_ENVIRONMENT_PATH}

# during CI or for development branch must be replaced accordingly,
# otherwise link_repo can be used to point to an already downloaded repo

RUN dnf update; dnf install blas-devel lapack-devel; dnf clean all

# use `git fetch --all` later for dev
RUN if [ ! -z "$branch" ]; then \
    git clone "https://github.com/nVentis/hep-workflows.git" --branch $branch --single-branch /hep_workflows && cd /hep_workflows; \
elif [ -d "$link_repo" ]; then ln -s "$link_repo" /hep_workflows; cd /hep_workflows; else exit 1; fi

RUN --security=insecure \
    echo "Mounting CVMFS"; /mount.sh; \
    echo "Checking whether key4hep exists..."; \
    [ -d /cvmfs/sw.hsf.org/key4hep ] && echo "key4hep found" || exit 1

RUN cd /hep_workflows && python -m venv --system-site-packages "$ENV_NAME"; \
    source /hep_workflows/hep_workflows/setup.sh; \
    pip install -r requirements.txt && pip install -e . ; \
    echo "hep_workflows setup. Done" || exit 2

ENTRYPOINT ["/mount.sh"]
CMD ["/bin/bash"]