# Custom Open Terminal image with PaperQA baked in.
#
# Extends the official Open Terminal image (Python 3.12, runs as the "user"
# account) by installing PaperQA globally and baking the query scripts into
# /opt/paperqa so they are available to every user the container creates
# (including dynamically created accounts in OPEN_TERMINAL_MULTI_USER mode).
FROM ghcr.io/open-webui/open-terminal

# Install PaperQA + deps as root so they land in the global site-packages and
# are importable by all users (mirrors how the base image installs its libs).
USER root

COPY requirements.txt /opt/paperqa/requirements.txt
RUN pip install --no-cache-dir -r /opt/paperqa/requirements.txt

# Bake the skill scripts and docs. World-readable so every user can run them.
COPY pqa_settings.py pqa_query.py PAPERQA.md /opt/paperqa/
RUN chmod -R a+rX /opt/paperqa

# Drop back to the unprivileged user the base image runs as.
USER user

# Entrypoint, CMD, WORKDIR, and EXPOSE are inherited from the base image.
