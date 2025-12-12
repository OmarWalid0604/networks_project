#!/usr/bin/env python3
"""
compute_metrics.py

Usage:
  python3 compute_metrics.py --server server_positions.csv \
                             --clients client_positions.csv \
                             --server_metrics server_metrics.csv \
                             --out results_phase2/<scenario>/metrics.csv
"""
import argparse
import os
import numpy as np
import pandas as pd

def interp_server_metrics(serv_metrics, query_ts):
    """
    Interpolate cpu_percent and bandwidth_kbps for each query_ts using linear interpolation.
    serv_metrics: DataFrame with columns ['timestamp_ms','cpu_percent','bandwidth_kbps']
    query_ts: numpy array of timestamps
    returns: cpu_vals, bw_vals arrays aligned with query_ts
    """
    if serv_metrics.empty:
        return np.full_like(query_ts, np.nan, dtype=float), np.full_like(query_ts, np.nan, dtype=float)

    serv_metrics = serv_metrics.sort_values("timestamp_ms")
    times = serv_metrics["timestamp_ms"].to_numpy(dtype=float)
    cpu = serv_metrics["cpu_percent"].to_numpy(dtype=float)
    bw = serv_metrics["bandwidth_kbps"].to_numpy(dtype=float)

    # np.interp requires ascending x and returns value for each query; extrapolate with edge values
    cpu_interp = np.interp(query_ts, times, cpu, left=cpu[0], right=cpu[-1])
    bw_interp = np.interp(query_ts, times, bw, left=bw[0], right=bw[-1])
    return cpu_interp, bw_interp

def compute_rfc1889_jitter(group):
    """
    Compute RFC 1889 jitter per group (per client/player).
    We use: D = (R_i - R_{i-1}) - (S_i - S_{i-1})
    And update J: J += (|D| - J) / 16
    We'll return a jitter array aligned with rows (first row = NaN).
    group must be sorted by recv_time_ms.
    """
    R = group["recv_time_ms"].to_numpy(dtype=float)
    S = group["server_timestamp_ms"].to_numpy(dtype=float)
    n = len(R)
    if n == 0:
        return np.array([], dtype=float)
    J = 0.0
    jit = np.full(n, np.nan, dtype=float)
    # start at i=1
    for i in range(1, n):
        D = (R[i] - R[i-1]) - (S[i] - S[i-1])
        D = abs(D)
        J = J + (D - J) / 16.0
        jit[i] = J
    return jit

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", required=True, help="server_positions.csv (timestamp_ms,snapshot_id,player_id,x,y)")
    p.add_argument("--clients", required=True, help="client_positions.csv (timestamp_ms,snapshot_id,seq_num,player_id,displayed_x,displayed_y)")
    p.add_argument("--server_metrics", required=True, help="server_metrics.csv (timestamp_ms,cpu_percent,bandwidth_kbps)")
    p.add_argument("--out", required=True, help="output metrics.csv path")
    args = p.parse_args()

    # Load CSVs
    server = pd.read_csv(args.server)
    clients = pd.read_csv(args.clients)
    serv_metrics = pd.read_csv(args.server_metrics)

    # Validate basic headers
    expected_server_cols = {"timestamp_ms","snapshot_id","player_id","x","y"}
    expected_client_cols = {"timestamp_ms","snapshot_id","seq_num","player_id","displayed_x","displayed_y"}
    expected_servmet_cols = {"timestamp_ms","cpu_percent","bandwidth_kbps"}

    if not expected_server_cols.issubset(set(server.columns)):
        raise SystemExit(f"[ERROR] server CSV missing required columns; found {server.columns.tolist()}")
    if not expected_client_cols.issubset(set(clients.columns)):
        raise SystemExit(f"[ERROR] clients CSV missing required columns; found {clients.columns.tolist()}")
    if not expected_servmet_cols.issubset(set(serv_metrics.columns)):
        raise SystemExit(f"[ERROR] server_metrics CSV missing required columns; found {serv_metrics.columns.tolist()}")

    # Normalize column names and dtypes
    server = server.rename(columns={"timestamp_ms":"server_timestamp_ms","x":"server_x","y":"server_y"})
    clients = clients.rename(columns={"timestamp_ms":"recv_time_ms","displayed_x":"client_x","displayed_y":"client_y"})

    # Merge server and client on snapshot_id + player_id (inner join to include only rows present on both sides)
    merged = pd.merge(
        clients,
        server,
        on=["snapshot_id","player_id"],
        how="inner",
        suffixes=("_client","_server")
    )

    print(f"[info] server rows: {len(server)}")
    print(f"[info] client rows: {len(clients)}")
    print(f"[info] merged rows (after inner join): {len(merged)}")

    if merged.empty:
        print("[warn] merged dataset is empty. Nothing to compute. Exiting.")
        # Still produce an empty metrics file
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        pd.DataFrame(columns=[
            "client_id","snapshot_id","seq_num","server_timestamp_ms","recv_time_ms",
            "latency_ms","jitter_ms","perceived_position_error","cpu_percent","bandwidth_per_client_kbps"
        ]).to_csv(args.out, index=False)
        return

    # compute latency
    merged["latency_ms"] = merged["recv_time_ms"].astype(float) - merged["server_timestamp_ms"].astype(float)

    # compute perceived position error
    merged["perceived_position_error"] = np.sqrt(
        (merged["server_x"].astype(float) - merged["client_x"].astype(float))**2 +
        (merged["server_y"].astype(float) - merged["client_y"].astype(float))**2
    )

    # Interpolate server metrics (cpu, bw) to each merged row's server_timestamp_ms
    query_ts = merged["server_timestamp_ms"].to_numpy(dtype=float)
    cpu_interp, bw_interp = interp_server_metrics(serv_metrics, query_ts)
    merged["cpu_percent"] = cpu_interp
    merged["bandwidth_per_client_kbps"] = bw_interp

    # compute RFC-1889 jitter per player (player_id acts as client_id)
    merged = merged.sort_values(["player_id","recv_time_ms"]).reset_index(drop=True)
    merged["jitter_ms"] = np.nan
    for pid, grp_idx in merged.groupby("player_id").groups.items():
        grp = merged.loc[grp_idx].sort_values("recv_time_ms")
        jit = compute_rfc1889_jitter(grp)
        merged.loc[grp.index, "jitter_ms"] = jit

    # Final column selection & rename player_id -> client_id
    out_df = merged[[
        "player_id","snapshot_id","seq_num","server_timestamp_ms","recv_time_ms",
        "latency_ms","jitter_ms","perceived_position_error","cpu_percent","bandwidth_per_client_kbps"
    ]].copy()
    out_df = out_df.rename(columns={"player_id":"client_id"})

    # Validate NaNs
    n_missing = out_df.isna().any(axis=1).sum()
    print(f"[info] merged rows with any NaN: {n_missing}")

    # Write output
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    out_df.to_csv(args.out, index=False)
    print(f"[info] Saved metrics.csv to {args.out}")
    print("[done] compute_metrics.py complete.")

if __name__ == "__main__":
    main()
