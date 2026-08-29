# 🚀 Oracle Cloud (Always Free Tier) 24/7 Deployment Guide

This guide walks you step-by-step through deploying your **Autonomous Startup Job & Founder Outreach Agent** on an **Oracle Cloud Always Free Tier** VM (AMD or ARM Ampere).

---

## 🌟 Why Oracle Cloud Always Free Tier?

* **100% Free Forever**: 2x AMD Compute VMs or 1x 4 OCPU / 24 GB RAM ARM Ampere VM with no credit expiration.
* **Built-in Anti-Idle Protection**: The repo includes an automated CPU & memory pulse (`heartbeat.py`) to prevent Oracle from reclaiming your idle instance.
* **Zero Public Inbound Ports Needed**: The Telegram bot uses outbound long-polling (`getUpdates`). You don't need domain names, SSL certificates, or open inbound firewall ports.

---

## 📋 Step 1: Create Your Free VM on Oracle Cloud

1. Log into your [Oracle Cloud Console](https://cloud.oracle.com).
2. Go to **Compute** $\rightarrow$ **Instances** $\rightarrow$ Click **Create Instance**.
3. **Configure the Instance**:
   * **Name**: `job-outreach-agent`
   * **Image**: **Ubuntu 24.04 LTS** or **Ubuntu 22.04 LTS** (Canonical Ubuntu).
   * **Shape**: 
     * Option A (Recommended): **VM.Standard.A1.Flex** (ARM Ampere - 2 to 4 OCPUs, 12 to 24 GB RAM - Always Free Eligible).
     * Option B: **VM.Standard.E2.1.Micro** (AMD - 1 OCPU, 1 GB RAM - Always Free Eligible).
4. **Networking**: Keep default Virtual Cloud Network (VCN) and ensure **Assign a public IPv4 address** is selected.
5. **SSH Keys**:
   * Click **Save Private Key** to download `ssh-key.key` to your local computer.
6. Click **Create** and wait 60 seconds for status to show **Running** with a Public IP (e.g. `140.238.xxx.xxx`).

---

## 🔑 Step 2: Connect to Your Oracle VM via SSH

On your local machine (Terminal or PowerShell):

```bash
# Set secure permissions for the downloaded private key
chmod 400 ~/Downloads/ssh-key.key  # On Linux/macOS
# On Windows PowerShell: Use ssh directly

# Connect to the instance
ssh -i /path/to/ssh-key.key ubuntu@<YOUR_ORACLE_PUBLIC_IP>
```

---

## 📦 Step 3: Install Python 3.12, Git & System Dependencies

Run the following commands inside your Oracle VM terminal:

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3, pip, venv, and build tools
sudo apt install -y python3 python3-pip python3-venv git curl ufw

# Verify Python version
python3 --version
```

---

## 📥 Step 4: Clone the Repository & Setup Virtual Environment

```bash
# Clone the repository
git clone https://github.com/your-handle/jobs_agent.git /home/ubuntu/job_outreach

# Navigate to project directory
cd /home/ubuntu/job_outreach

# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Upgrade pip and install all project dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## ⚙️ Step 5: Configure Your Production `.env` File

Create and edit your `.env` configuration on the server:

```bash
nano /home/ubuntu/job_outreach/.env
```

Paste your production keys (replace with your active credentials):

```ini
# ==============================================================================
# 🤖 LLM GATEWAY PROVIDER (Toggle: 'tokenrouter', 'groq', or 'openrouter')
# ==============================================================================
LLM_PROVIDER=tokenrouter

# --- TOKENROUTER CONFIGURATION (Main Model: GLM 5.3 Flash / Free) ---
TOKENROUTER_API_KEY=your_tokenrouter_api_key_here
TOKENROUTER_BASE_URL=https://api.tokenrouter.com/v1
TOKENROUTER_FAST_MODEL=z-ai/glm-5.3-free
TOKENROUTER_SMART_MODEL=z-ai/glm-5.3-free

# --- GROQ CONFIGURATION (Optional fallback) ---
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_FAST_MODEL=openai/gpt-oss-20b
GROQ_SMART_MODEL=openai/gpt-oss-120b

# --- OPENROUTER CONFIGURATION (Optional fallback) ---
OPENROUTER_API_KEY=sk-or-your-openrouter-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_FAST_MODEL=deepseek/deepseek-chat
OPENROUTER_SMART_MODEL=deepseek/deepseek-chat

# ==============================================================================
# 🔍 SEARCH & CONTACT ENRICHMENT
# ==============================================================================
TAVILY_API_KEY=your_tavily_api_key_here
APOLLO_API_KEY=your_apollo_api_key_here
HUNTER_API_KEY=

# ==============================================================================
# 📱 TELEGRAM BOT
# ==============================================================================
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

# ==============================================================================
# ☁️ ORACLE CLOUD & SAFETY DEFAULTS
# ==============================================================================
ORACLE_HEARTBEAT_ENABLED=True
HEARTBEAT_INTERVAL_HOURS=4
DRY_RUN=True
MIN_FIT_SCORE=70
MAX_ALERTS_PER_DAY=10
```

Press `Ctrl + O` then `Enter` to save, and `Ctrl + X` to exit.

---

## 🧪 Step 6: Verify Single Run

Test the application in your terminal to verify everything runs smoothly:

```bash
# Run pytest verification
python -m pytest

# Run the app manually for 10 seconds to test bot connectivity
python app.py
```

Check your Telegram: Send `/status` or `/sources` to the bot. If it replies, press `Ctrl + C` in your terminal to stop the manual process.

---

## 🛡️ Step 7: Create a 24/7 `systemd` Background Service

To ensure the agent runs continuously in the background, automatically starts on VM boot, and restarts itself if anything fails:

1. Create the systemd service file:
```bash
sudo nano /etc/systemd/system/outreach.service
```

2. Paste the following configuration:
```ini
[Unit]
Description=Autonomous Job & Founder Outreach Agent
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/job_outreach
ExecStart=/home/ubuntu/job_outreach/venv/bin/python /home/ubuntu/job_outreach/app.py
Restart=always
RestartSec=10
StandardOutput=append:/home/ubuntu/job_outreach/data/logs/systemd.log
StandardError=append:/home/ubuntu/job_outreach/data/logs/systemd_err.log
EnvironmentFile=/home/ubuntu/job_outreach/.env

[Install]
WantedBy=multi-user.target
```

3. Reload systemd, enable the service on boot, and start it:
```bash
# Reload daemon
sudo systemctl daemon-reload

# Enable service to start on every server reboot
sudo systemctl enable outreach.service

# Start the service now
sudo systemctl start outreach.service
```

4. Check service status:
```bash
sudo systemctl status outreach.service
```

You should see: `Active: active (running)`.

---

## 📊 Step 8: Useful Monitoring & Maintenance Commands

### Check Live Application Logs:
```bash
# View live rotating logs in real-time
tail -f /home/ubuntu/job_outreach/data/logs/outreach.log

# Or view systemd service logs
sudo journalctl -u outreach.service -f
```

### Restart or Stop the Service:
```bash
# Restart service (e.g. after editing .env or user_profile.yaml)
sudo systemctl restart outreach.service

# Stop service
sudo systemctl stop outreach.service
```

### Updating the Code with Git:
```bash
cd /home/ubuntu/job_outreach
git pull origin main
sudo systemctl restart outreach.service
```

---

## 📱 What Happens Next?

* **Every 1 Hour**: The server scans **2 rotating discovery sources** (e.g., YC + HackerNews), evaluates incoming leads, and posts an **Hourly Discovery Report** to your Telegram.
* **When a Match is Found ($\ge 70$)**: You receive an interactive Telegram Approval Card with **1-tap `[Approve & Send]`**, **`[Edit Draft]`**, or **`[Reject]`** buttons.
* **Every Morning at 09:30 AM**: Scans for sent emails older than 5 days and prepares follow-up bump check-ins.
* **Every 4 Hours**: Sends an anti-idle CPU pulse to keep your Oracle Free Tier VM permanently active.
