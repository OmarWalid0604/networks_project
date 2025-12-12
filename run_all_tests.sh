#!/usr/bin/env bash
set -euo pipefail

# Configurable variables
IFACE="${IFACE:-lo}"
DURATION="${DURATION:-15}"     # <-- scenario duration
CLIENTS="${CLIENTS:-2}"
RESULTS_ROOT="results_phase2"
PORT=7777
PYTHON="${PYTHON:-python3}"

mkdir -p "$RESULTS_ROOT"

apply_netem() {
    local args="${1:-}"
    sudo tc qdisc del dev "$IFACE" root 2>/dev/null || true
    if [[ -n "$args" ]]; then
        sudo tc qdisc add dev "$IFACE" root netem $args
        echo "[netem] applied: $args"
    else
        echo "[netem] cleared"
    fi
}

start_client_in_dir() {
    local dir="$1"
    mkdir -p "$dir"
    cp client.py "$dir/" || true
    (
      cd "$dir"
      # pass duration via argument
      nohup $PYTHON client.py --duration "$DURATION" > client_output.txt 2>&1 &
      echo $! > client_pid.txt
    )
    cat "$dir/client_pid.txt"
}

run_scenario() {
    local name="$1"
    local netem_args="$2"
    local outdir="$RESULTS_ROOT/$name"

    mkdir -p "$outdir"
    echo "=== Scenario: $name (netem: ${netem_args:-none}) ==="

    apply_netem "$netem_args"

    rm -f server_positions.csv server_metrics.csv client_positions_*.csv client_positions.csv

    # Start server in background
    ( cd "$(pwd)" && python3 server.py ) > "$outdir/server_output.txt" 2>&1 &
    SERVER_PID=$!
    sleep 1
    echo "[server] pid=$SERVER_PID"

    sudo tcpdump -i "$IFACE" udp port $PORT -w "$outdir/trace.pcap" >/dev/null 2>&1 &
    TCPDUMP_PID=$!

    CLIENT_PIDS=()
    for i in $(seq 1 $CLIENTS); do
        C_DIR="$outdir/client_$i"
        pid=$(start_client_in_dir "$C_DIR")
        CLIENT_PIDS+=("$pid")
        echo "[client] started client $i pid=$pid in $C_DIR"
    done

    echo "[info] running for ${DURATION}s"
    sleep "$DURATION"

    # Stop clients and server
    for pid in "${CLIENT_PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
    kill "$SERVER_PID" 2>/dev/null || true
    sudo kill "$TCPDUMP_PID" 2>/dev/null || true
    sleep 1

    # Move server logs
    [[ -f server_positions.csv ]] && mv server_positions.csv "$outdir/"
    [[ -f server_metrics.csv ]] && mv server_metrics.csv "$outdir/"

    # Combine clients logs
    combined="$outdir/client_positions.csv"
    echo "timestamp_ms,snapshot_id,seq_num,player_id,displayed_x,displayed_y" > "$combined"
    for i in $(seq 1 $CLIENTS); do
        C_DIR="$outdir/client_$i"
        for f in "$C_DIR"/client_positions_*.csv; do
            [[ -f "$f" ]] && tail -n +2 "$f" >> "$combined"
        done
    done

    # Compute metrics
    if [[ -f "$outdir/server_positions.csv" && -s "$combined" && -f "$outdir/server_metrics.csv" ]]; then
        $PYTHON compute_metrics.py \
            --server "$outdir/server_positions.csv" \
            --clients "$combined" \
            --server_metrics "$outdir/server_metrics.csv" \
            --out "$outdir/metrics.csv"
    else
        echo "[warn] missing CSVs — skipping compute_metrics"
    fi

    # Cleanup client folders
    for i in $(seq 1 $CLIENTS); do rm -rf "$outdir/client_$i"; done

    apply_netem ""
    echo "=== Scenario $name done ==="
}

run_scenario "baseline" ""
run_scenario "loss_2pct" "loss 2%"
run_scenario "loss_5pct" "loss 5%"
run_scenario "delay_100ms" "delay 100ms"
run_scenario "jitter_10ms" "delay 20ms 10ms"
run_scenario "reorder_20pct" "delay 10ms reorder 20%"
run_scenario "duplicate_5pct" "duplicate 5%"

echo "[done] all scenarios stored in $RESULTS_ROOT"
