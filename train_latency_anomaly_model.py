# NOTE: If you see 'Import "sklearn.ensemble" could not be resolved', run:
#   pip install scikit-learn
import pandas as pd
from sklearn.ensemble import IsolationForest
import joblib

# Load the exported latency data
latency_df = pd.read_csv('api_latency_p95.csv')

# Drop rows with missing or non-numeric values
latency_df = latency_df.dropna()
latency_df['value'] = pd.to_numeric(latency_df['value'], errors='coerce')
latency_df = latency_df.dropna(subset=['value'])

# Reshape for model
X = latency_df['value'].values.reshape(-1, 1)

if X.size == 0:
    latency_df.assign(anomaly=pd.Series(dtype=int)).to_csv(
        'api_latency_p95_with_anomalies.csv', index=False
    )
    joblib.dump(None, 'latency_anomaly_model.joblib')
    print(
        'No latency samples available after cleaning; wrote empty results and placeholder model.'
    )
    raise SystemExit(0)

# Train Isolation Forest for anomaly detection
model = IsolationForest(contamination=0.01, random_state=42)
model.fit(X)

# Predict anomalies (-1 = anomaly, 1 = normal)
latency_df['anomaly'] = model.predict(X)

# Save results and model
latency_df.to_csv('api_latency_p95_with_anomalies.csv', index=False)
joblib.dump(model, 'latency_anomaly_model.joblib')

print('Anomaly detection complete. Results saved to api_latency_p95_with_anomalies.csv and model to latency_anomaly_model.joblib')
