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
        fonts-freefont-ttf \
        libgomp1 && \
    rm -rf /var/lib/apt/lists/*
# libgomp1: OpenMP runtime required by ctranslate2 (faster-whisper) on slim Debian.

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

# Bake the local-transcription model into the image so there is NO runtime
# download (stable, offline-capable). 'small' is the default; WHISPER_MODEL can be
# raised per-instance (medium/large-v3) but a larger model then downloads on first
# use. This is the fallback that fires when ElevenLabs Scribe quota is exhausted.
ENV WHISPER_MODEL=small
ENV WHISPER_MODEL_DIR=/app/models
# Non-fatal: if the HF download hiccups at build, the model downloads at first use
# instead (runtime has network + a writable /app/models). A model hiccup must never
# break the whole deploy the way a bad font would.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='/app/models')" \
    || echo "WARN: whisper model prefetch failed — it will download on first render"

# ── Optional: Node + Remotion for code-based motion graphics ──────────────────
# Gated behind a build arg so instances that don't use it stay light and build
# fast. To enable on an instance: set service vars WITH_REMOTION=1 (build) and
# REMOTION_GRAPHICS=1 (runtime). When off, no Node/Chromium is installed and the
# pipeline uses the PIL overlays exactly as before.
ARG WITH_REMOTION=0
ENV REMOTION_DIR=/app/remotion
RUN if [ "$WITH_REMOTION" = "1" ]; then \
      curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
      apt-get install -y --no-install-recommends \
        nodejs \
        libnss3 libdbus-1-3 libatk1.0-0 libgbm1 libasound2 libxrandr2 \
        libxkbcommon0 libxfixes3 libxcomposite1 libxdamage1 \
        libatk-bridge2.0-0 libpango-1.0-0 libcairo2 libcups2 && \
      rm -rf /var/lib/apt/lists/*; \
    fi
COPY remotion/package.json remotion/package-lock.json /app/remotion/
RUN if [ "$WITH_REMOTION" = "1" ]; then \
      cd /app/remotion && npm ci --no-audit --no-fund && \
      ( npx remotion browser ensure || echo "WARN: remotion browser prefetch failed — downloads on first render" ); \
    fi

COPY . .

# Data and uploads survive redeploys when mounted as volumes
RUN mkdir -p /app/data /app/uploads

EXPOSE 8765
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8765", "--proxy-headers", "--forwarded-allow-ips=*"]
