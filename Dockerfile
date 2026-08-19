FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY squidward/ ./squidward/
COPY run.py run_bot.py ./

# The bot serves whatever digest is on this volume; refresh writes to it.
ENV SQUIDWARD_OUT_DIR=/data
VOLUME /data

CMD ["python", "run_bot.py"]
