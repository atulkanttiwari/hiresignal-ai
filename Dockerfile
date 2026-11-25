FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer logs cleanly
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (leverages Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files and ensure runtime folders exist
COPY . .
RUN mkdir -p data logs

EXPOSE 8501

# Default command launches the Streamlit dashboard
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]