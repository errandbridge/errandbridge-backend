from anomaly_metrics import increment_anomaly_alert_metric  # Prometheus metric
import os
import requests
import pandas as pd
import joblib
import datetime

import smtplib
from email.mime.text import MIMEText
from sms_alert import send_sms_alert

PROMETHEUS_URL = "http://localhost:9090"
MODEL_PATH = "latency_anomaly_model.joblib"
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "alerts@errandbridge.com")  # Default fallback
SMTP_SERVER = os.environ.get("SMTP_SERVER", "localhost")
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")

# Optionally, support dynamic recipient for per-user or per-admin alerts
def get_recipient():
    # Use environment variable or extend to fetch from DB/user context
    # Set RECIPIENT_EMAIL to your email to receive alerts
    return os.environ.get("RECIPIENT_EMAIL", ALERT_EMAIL)

# Query latest latency data from Prometheus
def query_latest_latency():
    end = int(datetime.datetime.now().timestamp())
    start = end - 60*10  # last 10 minutes
    query = 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_highr_seconds_bucket{job="fastapi"}[5m])))'
    url = f"{PROMETHEUS_URL}/api/v1/query_range"
    params = {"query": query, "start": start, "end": end, "step": "60"}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    result = resp.json()["data"].get("result", [])
    if not result:
        return pd.DataFrame(columns=["timestamp", "value"])
    values = result[0]["values"]
    df = pd.DataFrame(values, columns=["timestamp", "value"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["value"])

def send_alert(latency, timestamp):
    # Increment Prometheus metric for Grafana
    increment_anomaly_alert_metric()
    recipient = get_recipient()
    alert_message = f"Anomaly detected in API latency!\nTimestamp: {timestamp}\nLatency: {latency}s"
    # Send email
    msg = MIMEText(alert_message)
    msg["Subject"] = "API Latency Anomaly Detected"
    msg["From"] = ALERT_EMAIL
    msg["To"] = recipient
    with smtplib.SMTP(SMTP_SERVER) as server:
        if SMTP_USERNAME and SMTP_PASSWORD:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
    print(f"Alert sent to {recipient} for anomaly at {timestamp} (latency: {latency}s)")
    # Send SMS if phone number is set
    sms_to = os.environ.get("ALERT_PHONE")
    if sms_to:
        sms_sent = send_sms_alert(sms_to, alert_message)
        if sms_sent:
            print(f"SMS alert sent to {sms_to}")
        else:
            print(f"Failed to send SMS alert to {sms_to}")
    # Log alert for dashboard
    try:
        with open("anomaly_alerts.log", "a") as f:
            f.write(f"{timestamp},{latency}\n")
    except Exception as e:
        print(f"Failed to log anomaly alert: {e}")

def main():
    import os
    if os.environ.get("TEST_ALERT") == "1":
        # Always send a test alert
        send_alert("TEST", datetime.datetime.now())
        print("Test alert sent.")
        return
    # Load model
    model = joblib.load(MODEL_PATH)
    # Query latest data
    df = query_latest_latency()
    if df.empty:
        print("No latency data found for inference.")
        return
    X = df["value"].values.reshape(-1, 1)
    preds = model.predict(X)
    anomalies = df[preds == -1]
    if not anomalies.empty:
        for _, row in anomalies.iterrows():
            send_alert(row["value"], datetime.datetime.fromtimestamp(float(row["timestamp"])) )
    else:
        print("No anomalies detected.")

# ---
# To send signup or business event alerts to individuals:
#   Set RECIPIENT_EMAIL to your email (or the user's email) and call send_alert() with event details.
#   Example:
#   RECIPIENT_EMAIL="alerts@errandbridge.com" ALERT_EMAIL="alerts@errandbridge.com" SMTP_SERVER="smtp.server" python infer_and_alert_latency_anomaly.py
#
# For backend integration, import send_alert() and call it with the appropriate recipient and message.

if __name__ == "__main__":
    main()
