import requests
import csv
import datetime

PROMETHEUS_URL = "http://localhost:9090"  # Change if running elsewhere


# Example queries for API latency and error rate
def query_prometheus(query, start, end, step="60"):
    url = f"{PROMETHEUS_URL}/api/v1/query_range"
    params = {"query": query, "start": start, "end": end, "step": step}
    try:
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[CI-SAFE] Prometheus not available: {e}. Skipping export.")
        return {"data": {"result": []}}


def save_to_csv(result, filename):
    with open(filename, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["timestamp", "value"])
        results = result["data"].get("result", [])
        if not results:
            print(
                f"Warning: No data found for {filename}. File will be empty except for header."
            )
            return
        for v in results[0]["values"]:
            writer.writerow(v)


def main():
    # Set your time range (last 7 days)
    end = int(datetime.datetime.now().timestamp())
    start = end - 7 * 24 * 60 * 60

    # Query p95 latency
    latency_query = 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_highr_seconds_bucket{job="fastapi"}[5m])))'
    latency_result = query_prometheus(latency_query, start, end)
    save_to_csv(latency_result, "api_latency_p95.csv")

    # Query error rate (5xx)
    error_query = 'increase(http_request_duration_highr_seconds_count{job="fastapi",status=~"5.."}[5m])'
    error_result = query_prometheus(error_query, start, end)
    save_to_csv(error_result, "api_error_rate.csv")

    print("Export complete: api_latency_p95.csv, api_error_rate.csv")


if __name__ == "__main__":
    main()

# ---
# To automate inference and alerting, schedule the following script (see infer_and_alert_latency_anomaly.py):
# 1. Run export_prometheus_metrics.py to refresh data.
# 2. Run train_latency_anomaly_model.py to retrain the model (optional, e.g., weekly).
# 3. Run infer_and_alert_latency_anomaly.py to detect and alert on anomalies (e.g., every 10 min).
#
# Example cron (every 10 min):
# */10 * * * * cd /Users/admin/Desktop/ErrandBridge\ 2/errandbridge-backend && \
#   /Users/admin/Desktop/ErrandBridge\ 2/.venv/bin/python export_prometheus_metrics.py && \
#   /Users/admin/Desktop/ErrandBridge\ 2/.venv/bin/python infer_and_alert_latency_anomaly.py
#
# For secure alerting, use environment variables for email credentials and restrict script permissions.
