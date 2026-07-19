#!/bin/bash

# Port range
PORTS=(8000 8001 8002)
PIDS=()

echo "Starting Sentinel Backend Cluster..."

# Ensure we're in virtualenv if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run each instance of the server
for PORT in "${PORTS[@]}"; do
    echo "Starting Sentinel worker on port $PORT..."
    PORT=$PORT python -m uvicorn src.web.app:app --host 127.0.0.1 --port $PORT > "server_$PORT.log" 2>&1 &
    PIDS+=($!)
done

echo "Cluster started with PIDs: ${PIDS[@]}"
echo "To terminate cluster, run: kill ${PIDS[@]}"

# Write a quick script to stop them
cat <<EOF > stop_cluster.sh
#!/bin/bash
echo "Stopping Sentinel Backend Cluster..."
kill ${PIDS[@]}
rm stop_cluster.sh
echo "Cluster stopped."
EOF
chmod +x stop_cluster.sh

echo "A stop script 'stop_cluster.sh' has been generated."
