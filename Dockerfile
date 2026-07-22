# Use lightweight Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies (important!)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire project
COPY . .

# Create working directories (optional but safe)
RUN mkdir -p shorts_automation_work/uploads \
             shorts_automation_work/exports \
             shorts_automation_work/templates \
             shorts_automation_work/transcripts \
             shorts_automation_work/thumbnails \
             shorts_automation_work/fonts

# Expose Streamlit port
EXPOSE 8501

# Streamlit config (avoid CORS & allow external access)
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ENABLECORS=false
ENV STREAMLIT_SERVER_PORT=8501

# Run the app
CMD ["sh", "-c", "streamlit run shorts_automation_app.py --server.address=0.0.0.0 --server.port=$PORT"]
