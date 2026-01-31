FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY adapter.py .
COPY config.example.yaml config.yaml

# Expose the default port
EXPOSE 44555

# Run the adapter
CMD ["python", "adapter.py", "--config", "/app/config.yaml"]
