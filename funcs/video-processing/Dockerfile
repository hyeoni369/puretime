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
ENV VIDEO_URL=https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/1080/Big_Buck_Bunny_1080_10s_20MB.mp4

CMD ["python3", "function.py"]
