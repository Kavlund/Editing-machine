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
# Caveat  → replaces Noteworthy      (handwritten title line)
# Oswald  → replaces Impact          (big title caps + condensed captions)
# Poppins → replaces Arial Bold      (default word captions)
# Nunito  → replaces Arial Rounded   (rounded caption style — the Reels look)
#
# -f is essential: without it curl happily writes a 404 page into the .ttf and
# exits 0, so the image builds "fine" and every render then dies with PIL's
# "unknown file format". Caveat/Oswald/Nunito are variable fonts upstream now — the
# old static files (Caveat-Regular / static/Oswald-Bold) were deleted from the
# repo, which is exactly how this broke. The size check catches any other junk.
RUN mkdir -p /app/fonts && \
    curl -fsSL "https://github.com/google/fonts/raw/main/ofl/caveat/Caveat%5Bwght%5D.ttf" \
         -o /app/fonts/Caveat.ttf && \
    curl -fsSL "https://github.com/google/fonts/raw/main/ofl/oswald/Oswald%5Bwght%5D.ttf" \
         -o /app/fonts/Oswald.ttf && \
    curl -fsSL "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-SemiBold.ttf" \
         -o /app/fonts/Poppins-SemiBold.ttf && \
    curl -fsSL "https://github.com/google/fonts/raw/main/ofl/nunito/Nunito%5Bwght%5D.ttf" \
         -o /app/fonts/Nunito.ttf && \
    for f in /app/fonts/*.ttf; do \
      sz=$(wc -c < "$f"); \
      [ "$sz" -gt 20000 ] || { echo "BAD FONT (probably an error page): $f ($sz bytes)"; exit 1; }; \
    done

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data and uploads survive redeploys when mounted as volumes
RUN mkdir -p /app/data /app/uploads

EXPOSE 8765
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8765", "--proxy-headers", "--forwarded-allow-ips=*"]
