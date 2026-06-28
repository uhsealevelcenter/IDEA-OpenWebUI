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

# In OPEN_TERMINAL_MULTI_USER mode every command runs via `sudo -u <user>`,
# which by default does env_reset and strips the container environment. That
# drops OPENAI_API_KEY before PaperQA runs, so authentication fails. Whitelist
# the OpenAI vars so they pass through into the per-user shell.
RUN echo 'Defaults env_keep += "OPENAI_API_KEY OPENAI_BASE_URL OPENAI_API_BASE"' \
      > /etc/sudoers.d/paperqa-openai \
 && chmod 0440 /etc/sudoers.d/paperqa-openai \
 && visudo -cf /etc/sudoers.d/paperqa-openai

# Drop back to the unprivileged user the base image runs as.
USER user

# Entrypoint, CMD, WORKDIR, and EXPOSE are inherited from the base image.
