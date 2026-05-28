FROM python:3.13-slim

WORKDIR /app

# 安装 FFmpeg（yt-dlp 依赖）
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 数据目录挂载
RUN mkdir -p /data/downloads
VOLUME ["/data"]

ENV MF_PORT=9000
ENV MF_DOWNLOADS_DIR=/data/downloads

EXPOSE 9000

CMD ["python", "server.py"]
