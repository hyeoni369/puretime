FROM python:3.11-slim

# opencv-python-headless = no GUI/GL deps; numpy for the compute.
RUN pip install --no-cache-dir opencv-python-headless==4.10.0.84 numpy

WORKDIR /app
COPY function.py .

# Bundle a real frontal-face image (Lena — Haar frontalface detects it). Tiled at runtime
# to synthesize N faces. Build-time download; the function falls back to a textured tile if absent.
ADD https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg /app/face.jpg

ENV NUM_FACES=5
ENV SENTIMENT_ITERS=2500
# single-thread numpy/BLAS (design: single-threaded victim)
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1

CMD ["python3", "function.py"]
