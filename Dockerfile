FROM python:3.11-slim

# Install system dependencies needed for OpenCV/OCR
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only the runtime requirements needed by the Streamlit app
COPY requirements-docker.txt .

# This command will take a while only the FIRST time
RUN pip install --no-cache-dir -r requirements-docker.txt

# Now copy the rest of your code
COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]