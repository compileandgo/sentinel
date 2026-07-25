# AWS EC2 & Nginx Deployment Guide

This document outlines the step-by-step production deployment process on AWS EC2 with Nginx and systemd.

---

## Infrastructure Overview

* **Server**: AWS EC2 (`t3.micro` or larger) running **Ubuntu 26.04 LTS**.
* **Swap Space**: **2GB Swap file** (`/swapfile`) to prevent OOM errors during model loading.
* **Web Server**: **Nginx** reverse proxying port 80 to FastAPI on `127.0.0.1:8000`.
* **Process Supervisor**: **systemd** (`sentinel.service`) ensuring auto-start on boot and auto-restart on crashes.

---

## 1. Swap Space Setup (2GB)

To prevent Linux Out-Of-Memory (OOM) killer from terminating Python during heavy RAG operations:

```bash
sudo swapoff -a 2>/dev/null || true
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 2. Nginx Configuration (`/etc/nginx/sites-available/sentinel`)

Nginx acts as the reverse proxy. Crucially, **`proxy_buffering off;`** must be configured so Server-Sent Events (SSE) stream to the browser in real time without buffering:

```nginx
server {
 listen 80;
 server_name _;

 client_max_body_size 50M;

 location / {
 proxy_pass http://127.0.0.1:8000;
 proxy_set_header Host $host;
 proxy_set_header X-Real-IP $remote_addr;
 proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
 proxy_set_header X-Forwarded-Proto $scheme;

 # Disable proxy buffering for real-time SSE research log streaming
 proxy_http_version 1.1;
 proxy_set_header Connection "";
 proxy_buffering off;
 proxy_cache off;
 proxy_read_timeout 86400s;
 }
}
```

Enable site and test:
```bash
sudo ln -sf /etc/nginx/sites-available/sentinel /etc/nginx/sites-enabled/sentinel
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

---

## 3. Systemd Service Setup (`/etc/systemd/system/sentinel.service`)

Create a systemd unit file so Uvicorn runs continuously in the background:

```ini
[Unit]
Description=Sentinel Geopolitical Intelligence Platform
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/sentinel
ExecStart=/home/ubuntu/.local/bin/uv run uvicorn src.web.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
EnvironmentFile=/home/ubuntu/sentinel/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel
sudo systemctl status sentinel
```
