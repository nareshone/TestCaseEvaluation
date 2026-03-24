# Base Python image
FROM python:3.10

# Create a non-root user
RUN useradd -m -u 1000 user
ENV PATH="/home/user/.local/bin:$PATH"
WORKDIR /app

# Switch to root temporarily to install system packages
USER root

# Install system dependencies (PortAudio for sounddevice)
RUN apt-get update && apt-get install -y \
    portaudio19-dev ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies as root
COPY ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
RUN pip install sounddevice

# Copy all app files and set ownership to user
COPY --chown=user . /app

# Switch back to non-root user for security
USER user

# Expose the Space port (Hugging Face expects port 7860)
EXPOSE 7860

# Start the app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
    