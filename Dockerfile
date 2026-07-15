FROM python:3.12-slim

# Default timezone (Denmark). Overridable via a TZ env var on the host.
# tzdata (installed below) provides the zone database so named zones resolve.
ENV TZ=Europe/Copenhagen

# ffmpeg for video processing, curl for font downloads, tzdata for local time
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        tzdata \
        fonts-liberation \
        fonts-freefont-ttf && \
    rm -rf /var/lib/apt/lists/*

# Download Google Fonts — free substitutes for macOS system fonts
# Caveat  → replaces Noteworthy  (handwritten title line)
# Oswald  → replaces Impact      (big title caps)
# Poppins → replaces Arial Bold  (word captions)
RUN mkdir -p /app/fonts && \
    curl -sL "https://github.com/google/fonts/raw/main/ofl/caveat/Caveat-Regular.ttf" \
         -o /app/fonts/Caveat-Regular.ttf && \
    curl -sL "https://github.com/google/fonts/raw/main/ofl/oswald/static/Oswald-Bold.ttf" \
         -o /app/fonts/Oswald-Bold.ttf && \
    curl -sL "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-SemiBold.ttf" \
         -o /app/fonts/Poppins-SemiBold.ttf

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data and uploads survive redeploys when mounted as volumes
RUN mkdir -p /app/data /app/uploads

EXPOSE 8765
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8765"]
