#!/usr/bin/env python3
import argparse, pandas as pd, numpy as np
import os

def load_csv(path):
    return pd.read_csv(path)

def nearest_metric_for_snapshot(metrics_df, snap_ts):
    # metrics_df has timestamp_ms, cpu_percent, bandwidth_kbps
    # return the last row with timestamp_ms <= snap_ts, or NaN if none
    df = metrics_df[metrics_df["timestamp_ms"] <= snap_ts]
    if df.empty:
        return (np.nan, np.nan)
    row = df.iloc[-1]
    return (row["cpu_percent"], row["bandwidth_kbps"])

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", required=True)
    p.add_argument("--clients", required=True)
    p.add_argument("--server_metrics", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    server = pd.read_csv(args.server)  # columns: timestamp_ms,snapshot_id,player_id,x,y
    clients = pd.read_csv(args.clients)  # timestamp_ms,snapshot_id,seq_num,player_id,displayed_x,displayed_y
    serv_metrics = pd.read_csv(args.server_metrics)  # timestamp_ms,cpu_percent,bandwidth_kbps

    # Rename columns for clarity
    server = server.rename(columns={"timestamp_ms":"server_timestamp_ms","x":"server_x","y":"server_y"})
    clients = clients.rename(columns={"timestamp_ms":"recv_time_ms","displayed_x":"client_x","displayed_y":"client_y"})

    # Merge server and client on snapshot_id and player_id
    merged = pd.merge(
        clients,
        server,
        on=["snapshot_id","player_id"],
        how="left"
    )

    # compute latency = recv_time_ms - server_timestamp_ms
    merged["latency_ms"] = merged["recv_time_ms"] - merged["server_timestamp_ms"]

    # compute perceived_position_error
    merged["perceived_position_error"] = np.sqrt((merged["server_x"] - merged["client_x"])**2 + (merged["server_y"] - merged["client_y"])**2)

    # attach cpu_percent and bandwidth by finding nearest server metric timestamp <= snapshot timestamp
    cpus = []
    bw = []
    serv_metrics_sorted = serv_metrics.sort_values("timestamp_ms")
    for st in merged["server_timestamp_ms"]:
        cpu_val, bw_val = nearest_metric_for_snapshot(serv_metrics_sorted, st)
        cpus.append(cpu_val)
        bw.append(bw_val)

    merged["cpu_percent"] = cpus
    merged["bandwidth_per_client_kbps"] = bw

    # Now select and rename columns to match the required metrics.csv
    # Required columns: client_id, snapshot_id, seq_num, server_timestamp_ms, recv_time_ms, latency_ms, jitter_ms, perceived_position_error, cpu_percent, bandwidth_per_client_kbps
    # jitter_ms: compute per-client sequence of recv_time differences per client
    merged = merged.sort_values(["player_id","recv_time_ms"])
    # compute jitter per player: inter-arrival time variation
    merged["jitter_ms"] = np.nan
    for pid, grp in merged.groupby("player_id"):
        recv_times = grp["recv_time_ms"].values
        diffs = np.diff(recv_times)
        # jitter defined as absolute difference between successive inter-arrival times: we approximate per-row using preceding difference
        # for first row we keep NaN
        jitter_vals = np.concatenate([[np.nan], np.abs(np.concatenate([[0], diffs]) - np.concatenate([diffs, [0]]))])[:len(recv_times)]
        # simpler: set jitter as abs(diff) for row i: abs(recv_i - recv_{i-1})
        jitter_vals = np.concatenate([[np.nan], np.abs(np.diff(recv_times))])
        merged.loc[grp.index, "jitter_ms"] = jitter_vals

    # final columns
    out_df = merged[[
        "player_id",
        "snapshot_id",
        "seq_num",
        "server_timestamp_ms",
        "recv_time_ms",
        "latency_ms",
        "jitter_ms",
        "perceived_position_error",
        "cpu_percent",
        "bandwidth_per_client_kbps"
    ]].copy()

    out_df = out_df.rename(columns={"player_id":"client_id"})

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    out_df.to_csv(args.out, index=False)
    print(f"Saved metrics to {args.out}")

if __name__ == "__main__":
    main()
