FROM python:3.11-slim

WORKDIR /app

# Install Pillow dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

# Install Pillow
RUN pip install --no-cache-dir Pillow

COPY function.py .

RUN mkdir -p /tmp/thumbnailer_test

ENV ITERATIONS=1
ENV THUMB_WIDTH=200
ENV THUMB_HEIGHT=200
ENV WORK_DIR=/tmp/thumbnailer_test

CMD ["python3", "function.py"]
