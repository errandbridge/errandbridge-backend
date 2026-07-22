# TODO: Install prometheus_client and uncomment the import below
from prometheus_client import Counter, start_http_server
import threading

# Counter for anomaly alerts
anomaly_alerts_total = Counter('anomaly_alerts_total', 'Total number of anomaly alerts sent')

# Start Prometheus metrics server in a background thread
# (Port 9101 to avoid conflict with main Prometheus server)
def start_metrics_server():
    start_http_server(9101)

threading.Thread(target=start_metrics_server, daemon=True).start()

def increment_anomaly_alert_metric():
    anomaly_alerts_total.inc()
