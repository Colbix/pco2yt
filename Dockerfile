FROM python:3.11-slim

ARG DEFUID=1000
ARG DEFGID=1000

ENV UID=$DEFUID
ENV GID=$DEFGID

# Set an environment variable path at /opt/venv
ENV VENV_PATH=/opt/venv

# Create the python virutal environment
RUN python -m venv ${VENV_PATH}

# Upgrade pip and install everything into the venv.
RUN ${VENV_PATH}/bin/pip install --upgrade pip

# Install OS deps and create the non-root user
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
 build-essential \
 && groupadd --gid ${GID} appuser \
 && useradd --uid ${UID} --gid ${GID} --create-home --shell /bin/bash appuser \
 && chown -R ${UID}:${GID} ${VENV_PATH} \
 && rm -rf /var/lib/apt/lists/*

ENV PATH=/home/appuser/.local/bin:$PATH

WORKDIR /app

# Ensure the non-root user can write here
RUN chown -R ${UID}:${GID} /app

# Switch to non-root user
USER $UID:$GID

# Set venv’s bin directory
ENV PATH="${VENV_PATH}/bin:${PATH}"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]