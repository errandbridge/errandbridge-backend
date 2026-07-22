#!/bin/bash
# Script to extract the latest OTP code from backend terminal output (dev mode)
# Usage: ./extract_otp.sh <backend_log_file_or_terminal_output>

# If you run the backend with output redirected to a file, e.g.:
#   python3 main.py > backend.log 2>&1
# then run:
#   ./extract_otp.sh backend.log
#
# If you want to use the current terminal scrollback, copy-paste it to a file first.

LOGFILE="$1"
if [ -z "$LOGFILE" ]; then
  echo "Usage: $0 <backend_log_file_or_terminal_output>"
  exit 1
fi

# Extract the latest OTP code from the dev email printout
OTP=$(awk '/--- EMAIL \(dev mode\) ---/{flag=1;next}/--- END EMAIL ---/{flag=0}flag' "$LOGFILE" | grep -Eo '[0-9]{6}' | tail -1)

if [ -z "$OTP" ]; then
  echo "No OTP code found in $LOGFILE"
  exit 2
fi

echo "Latest OTP code: $OTP"
echo "To use for smoke test:"
echo "export SMOKE_OTP_CODE=$OTP"
