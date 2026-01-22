FROM python:3.11-slim

WORKDIR /app

# No additional dependencies needed - pure Python
COPY function.py .

# Default command
CMD ["python", "function.py", "50000", "100"]
