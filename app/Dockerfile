FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the full repo so the API and the POS source data are available in the container
COPY . /app

# Install python requirements from app/requirements.txt
RUN pip install --no-cache-dir -r /app/app/requirements.txt

# Set env variables
ENV DB_PATH=/data/store_intelligence.db
ENV PORT=8000
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
