FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY syssentry ./syssentry
COPY config.example.yaml /etc/syssentry/config.yaml
RUN useradd --system syssentry && mkdir -p /var/lib/syssentry /var/log/syssentry \
    && chown syssentry /var/lib/syssentry /var/log/syssentry
USER syssentry
EXPOSE 8085
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/healthz')"
# Mount the host's /proc and logs read-only to monitor the host rather than the container:
#   docker run -d --pid=host -v /var/log:/var/log:ro -p 8085:8085 syssentry
CMD ["python", "-m", "syssentry", "-c", "/etc/syssentry/config.yaml", "run", "--with-web"]
