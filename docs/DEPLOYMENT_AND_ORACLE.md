# Deployment Guide & Oracle Cloud Always Free Setup

This guide details how to deploy the Personal AI Outreach System on **Oracle Cloud Always Free Tier** (or local hardware) with zero-cost 24/7 uptime.

---

## 1. Why Oracle Cloud Free Tier is Ideal

- **Cost**: **$0.00 / month forever**.
- **Specs**:
  - **Ampere A1 (ARM64)**: Up to 4 OCPUs & 24 GB RAM (or 1 OCPU / 6 GB RAM slice).
  - **AMD (x86_64)**: 1 OCPU & 1 GB RAM.
- **Networking Simplicity**:
  - The system uses **Telegram Long-Polling** and connects outbound over HTTPS (port 443) and SMTP (port 587/465).
  - **No Ingress Rules, VCN port openings, public IP configuration, or SSL certificates are needed** in Oracle Cloud Console.

---

## 2. Oracle Anti-Idle Heartbeat Job

### The Oracle Reclamation Rule:
Oracle Cloud automatically flags and stops Always Free instances if CPU and RAM utilization average < 20% over a rolling 7-day period.

### Our Built-in Solution (`heartbeat.py`):
1. Runs inside APScheduler every 4 hours.
2. Executes a controlled 30-second CPU & memory matrix computation that momentarily utilizes ~20% of 1 CPU core and 50MB RAM.
3. Automatically logs health metrics into `audit_log`.
4. Keeps Oracle's metric active without draining resources or affecting bot responsiveness.

> [!TIP]
> **Pro-Tip**: You can also upgrade your Oracle Cloud account to **"Pay As You Go" (PAYG)**. Oracle still gives you all Always Free resources for $0.00/month, but PAYG accounts are permanently exempt from idle VM reclamation.

---

## 3. Gmail SMTP Setup (Primary Email Sending)

To send emails from your personal Gmail address with high deliverability:

1. Go to your **Google Account Security Settings** (with 2-Factor Authentication enabled).
2. Navigate to **App Passwords** (`https://myaccount.google.com/apppasswords`).
3. Create a new App Password named `Job Outreach System`.
4. Copy the 16-character password into your `.env` file:
   ```env
   GMAIL_USER=yourname@gmail.com
   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
   ```

---

## 4. 3-Minute Deployment on Oracle VM

Once your Oracle Ubuntu 22.04 / 24.04 instance is spun up:

### Step 1: Install Docker & Docker Compose
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

### Step 2: Clone & Configure
```bash
git clone https://github.com/your-username/job_outreach.git
cd job_outreach

cp .env.example .env
nano .env              # Set your TELEGRAM_BOT_TOKEN, DEEPSEEK_API_KEY, GMAIL_USER, etc.
nano user_profile.yaml # Review/update your background & proof-of-work highlights
```

### Step 3: Launch with Docker Compose
```bash
docker compose up -d --build
```

### Step 4: Verify
```bash
docker compose logs -f
```
You will see:
- SQLite database initialized (`data/outreach.db`).
- APScheduler started (Discovery, Follow-up checker, Anti-idle heartbeat).
- Telegram bot listening via long-polling.

---

## 5. Automated SQLite Backups

The system includes an automated backup job that creates timestamped snapshots in `data/backups/outreach_backup_YYYYMMDD.db`.

To sync backups to a private GitHub repo or S3 bucket, a simple cron command can be added:
```bash
# Example: rsync to local machine or push to private backup repo
rclone copy ./data/backups remote:outreach-backups/
```

---

## 6. Native Linux Service (`systemd`) Alternative

If you prefer running without Docker:
```bash
sudo cp systemd/job_outreach.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now job_outreach
sudo journalctl -u job_outreach -f
```
