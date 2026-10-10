# Build context is the repository root (see docker-compose.yml)
FROM python:3.12-slim
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ /app/
COPY sql /app/sql
COPY scripts /app/scripts
ENV PYTHONPATH=/app DATA_DIR=/data
RUN mkdir -p /data && useradd -u 10001 -m runner && chown -R runner /data /app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "ranker.api:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
