FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY function.py .

RUN mkdir -p /tmp/video_test

ENV ITERATIONS=1
ENV OPERATION=gif
ENV WORK_DIR=/tmp/video_test
ENV VIDEO_URL=https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4

CMD ["python3", "function.py"]
