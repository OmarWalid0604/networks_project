#!/usr/bin/env python3
"""
compute_metrics.py
This version adds:
 - update_rate (snapshots/sec)
 - loss_rate (% lost snapshots)
 - scenario-level statistics summary

Outputs:
   metrics.csv     -> per-snapshot rows
   statistics.csv  -> one row containing scenario summary
"""

import argparse
import os
import numpy as np
import pandas as pd


def interp_server_metrics(serv_metrics, query_ts):
    """Linear interpolation of cpu_percent and bandwidth_kbps."""
    if serv_metrics.empty:
        return (
            np.full_like(query_ts, np.nan, dtype=float),
            np.full_like(query_ts, np.nan, dtype=float),
        )

    serv_metrics = serv_metrics.sort_values("timestamp_ms")
    times = serv_metrics["timestamp_ms"].to_numpy(dtype=float)
    cpu = serv_metrics["cpu_percent"].to_numpy(dtype=float)
    bw = serv_metrics["bandwidth_kbps"].to_numpy(dtype=float)

    cpu_interp = np.interp(query_ts, times, cpu, left=cpu[0], right=cpu[-1])
    bw_interp = np.interp(query_ts, times, bw, left=bw[0], right=bw[-1])

    return cpu_interp, bw_interp


def compute_rfc1889_jitter(group):
    """RFC1889 jitter implementation."""
    R = group["recv_time_ms"].to_numpy(dtype=float)
    S = group["server_timestamp_ms"].to_numpy(dtype=float)

    n = len(R)
    if n == 0:
        return np.array([], dtype=float)

    J = 0.0
    out = np.full(n, np.nan, dtype=float)

    for i in range(1, n):
        D = abs((R[i] - R[i - 1]) - (S[i] - S[i - 1]))
        J = J + (D - J) / 16.0
        out[i] = J

    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", required=True)
    p.add_argument("--clients", required=True)
    p.add_argument("--server_metrics", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    # Load CSVs
    server = pd.read_csv(args.server)
    clients = pd.read_csv(args.clients)
    serv_metrics = pd.read_csv(args.server_metrics)

    # Check headers
    expected_server_cols = {"timestamp_ms", "snapshot_id", "player_id", "x", "y"}
    expected_client_cols = {
        "timestamp_ms",
        "snapshot_id",
        "seq_num",
        "player_id",
        "displayed_x",
        "displayed_y",
    }
    expected_servmet_cols = {"timestamp_ms", "cpu_percent", "bandwidth_kbps"}

    if not expected_server_cols.issubset(server.columns):
        raise SystemExit("server.csv missing required columns")
    if not expected_client_cols.issubset(clients.columns):
        raise SystemExit("client.csv missing required columns")
    if not expected_servmet_cols.issubset(serv_metrics.columns):
        raise SystemExit("server_metrics.csv missing required columns")

    # Rename columns
    server = server.rename(
        columns={"timestamp_ms": "server_timestamp_ms", "x": "server_x", "y": "server_y"}
    )
    clients = clients.rename(
        columns={
            "timestamp_ms": "recv_time_ms",
            "displayed_x": "client_x",
            "displayed_y": "client_y",
        }
    )

    # Merge
    merged = pd.merge(
        clients,
        server,
        on=["snapshot_id", "player_id"],
        how="inner",
    )

    if merged.empty:
        print("[warn] merged dataset empty, creating empty output files.")
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        pd.DataFrame().to_csv(args.out, index=False)
        pd.DataFrame().to_csv(os.path.join(os.path.dirname(args.out), "statistics.csv"))
        return

    # Latency
    merged["latency_ms"] = (
        merged["recv_time_ms"].astype(float) - merged["server_timestamp_ms"].astype(float)
    )

    # Perceived Error
    merged["perceived_position_error"] = np.sqrt(
        (merged["server_x"] - merged["client_x"]) ** 2
        + (merged["server_y"] - merged["client_y"]) ** 2
    )

    # Interpolated server metrics
    query_ts = merged["server_timestamp_ms"].astype(float).to_numpy()
    cpu_interp, bw_interp = interp_server_metrics(serv_metrics, query_ts)
    merged["cpu_percent"] = cpu_interp
    merged["bandwidth_per_client_kbps"] = bw_interp

    # Compute jitter per player
    merged = merged.sort_values(["player_id", "recv_time_ms"])
    merged["jitter_ms"] = np.nan
    for pid, idxs in merged.groupby("player_id").groups.items():
        grp = merged.loc[idxs].sort_values("recv_time_ms")
        merged.loc[grp.index, "jitter_ms"] = compute_rfc1889_jitter(grp)

    # --------------------------------------------------------
    # NEW: Compute update_rate and loss_rate
    # --------------------------------------------------------
    # Received snapshots
    received_snaps = merged["snapshot_id"].nunique()

    # Expected snapshots: deduce from server log
    duration_ms = (
        server["server_timestamp_ms"].max() - server["server_timestamp_ms"].min()
    )
    duration_s = duration_ms / 1000.0
    expected_snaps = duration_s * 20  # TICK_HZ = 20

    loss_rate = max(0.0, (expected_snaps - received_snaps) / expected_snaps)
    update_rate = received_snaps / duration_s if duration_s > 0 else np.nan

    # --------------------------------------------------------
    # Save per‑snapshot metrics
    # --------------------------------------------------------
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    merged.to_csv(args.out, index=False)

    # --------------------------------------------------------
    # Save scenario statistics
    # --------------------------------------------------------
    stats = {
        "mean_latency": merged["latency_ms"].mean(),
        "mean_jitter": merged["jitter_ms"].mean(),
        "mean_error": merged["perceived_position_error"].mean(),
        "update_rate": update_rate,
        "loss_rate": loss_rate,
        "duration_s": duration_s,
        "snapshots_received": received_snaps,
        "snapshots_expected": expected_snaps,
    }

    stats_path = os.path.join(os.path.dirname(args.out), "statistics.csv")
    pd.DataFrame([stats]).to_csv(stats_path, index=False)

    print(f"[done] Saved {args.out} and statistics.csv")


if __name__ == "__main__":
    main()
