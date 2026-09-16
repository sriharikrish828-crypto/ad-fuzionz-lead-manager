FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

WORKDIR /app

# Prevent interactive prompts during apt-get
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ensure Playwright chromium browser is installed
RUN playwright install chromium

# Copy app directory
COPY . .

# Expose port (Render sets $PORT dynamically)
EXPOSE 8020

# Launch Uvicorn server
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8020}"]
