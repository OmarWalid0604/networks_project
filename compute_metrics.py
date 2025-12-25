import argparse
import os
import numpy as np
import pandas as pd

def interp_server_metrics(serv_metrics, query_ts):
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
    p.add_argument("--clients", required=True)   # combined clients file (concatenated per-client CSVs)
    p.add_argument("--server_metrics", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    server = pd.read_csv(args.server)
    clients = pd.read_csv(args.clients)
    serv_metrics = pd.read_csv(args.server_metrics)

    # normalize column names
    server = server.rename(columns={"timestamp_ms": "server_timestamp_ms", "x": "server_x", "y": "server_y"})
    clients = clients.rename(columns={"timestamp_ms": "recv_time_ms", "displayed_x": "client_x", "displayed_y": "client_y"})

    # quick checks
    required_client_cols = {"recv_time_ms", "snapshot_id", "seq_num", "player_id", "client_x", "client_y", "lost_snapshots_total"}
    if not required_client_cols.issubset(set(clients.columns)):
        raise SystemExit(f"clients CSV missing required columns: {required_client_cols - set(clients.columns)}")

    # Per-client stats: compute received, lost, expected (per-client window), update_rate
    per_client_rows = []
    for cid, grp in clients.groupby("player_id"):
        rec_snaps = int(grp["snapshot_id"].nunique())
        lost_reported = int(grp["lost_snapshots_total"].max()) if "lost_snapshots_total" in grp.columns else 0
        first_ms = grp["recv_time_ms"].min()
        last_ms = grp["recv_time_ms"].max()
        client_dur_s = max(1e-6, (last_ms - first_ms) / 1000.0)
        # authoritative loss from client snapshot ID gaps
        lost_snaps = lost_reported
        expected_client_snaps = rec_snaps + lost_snaps
        update_rate_client = rec_snaps / client_dur_s if client_dur_s > 0 else np.nan
        loss_rate_client = lost_snaps / (rec_snaps + lost_snaps) if (rec_snaps + lost_snaps) > 0 else 0.0

        per_client_rows.append({
            "client_id": cid,
            "received_snapshots": rec_snaps,
            "lost_snapshots": lost_snaps,
            "expected_snapshots": rec_snaps + lost_snaps,
            "update_rate": update_rate_client,
            "loss_rate": loss_rate_client,
            "client_duration_s": client_dur_s
        })

    pc_df = pd.DataFrame(per_client_rows)

    # Merge client per-snapshot metrics with server rows where possible
    merged = pd.merge(clients, server, on=["snapshot_id", "player_id"], how="inner")

    if merged.empty:
        print("[warn] merged dataset empty, creating empty output files.")
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        pd.DataFrame().to_csv(args.out, index=False)
        pd.DataFrame().to_csv(os.path.join(os.path.dirname(args.out), "statistics.csv"))
        return

    # Latency
    merged["latency_ms"] = merged["recv_time_ms"].astype(float) - merged["server_timestamp_ms"].astype(float)

    # Perceived Position Error
    merged["perceived_position_error"] = np.sqrt((merged["server_x"] - merged["client_x"])**2 + (merged["server_y"] - merged["client_y"])**2)

    # Interpolate server metrics
    query_ts = merged["server_timestamp_ms"].astype(float).to_numpy()
    cpu_interp, bw_interp = interp_server_metrics(serv_metrics, query_ts)
    merged["cpu_percent"] = cpu_interp
    merged["bandwidth_per_client_kbps"] = bw_interp

    # Jitter per player (RFC1889)
    merged = merged.sort_values(["player_id", "recv_time_ms"])
    merged["jitter_ms"] = np.nan
    for pid, idxs in merged.groupby("player_id").groups.items():
        grp = merged.loc[idxs].sort_values("recv_time_ms")
        merged.loc[grp.index, "jitter_ms"] = compute_rfc1889_jitter(grp)

    # Attach per-client stats back to merged (each row carries client-level update/loss)
    merged = merged.merge(pc_df.rename(columns={"client_id": "player_id"}), on="player_id", how="left")

    # Save per-snapshot metrics.csv
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    merged.to_csv(args.out, index=False)

    # Save statistics.csv: record per-client rows + scenario summary
    scenario_summary = {
        "clients": len(pc_df),
        "update_rate_mean": pc_df["update_rate"].mean() if not pc_df.empty else np.nan,
        "loss_rate_mean": pc_df["loss_rate"].mean() if not pc_df.empty else np.nan,
        "total_received_snapshots": int(clients["snapshot_id"].nunique()),
        "total_lost_snapshots": int(pc_df["lost_snapshots"].sum()) if not pc_df.empty else 0
    }

    stats_path = os.path.join(os.path.dirname(args.out), "statistics.csv")
    # write per-client stats and scenario_summary as two CSVs: clients_stats.csv and statistics_summary.csv
    pc_df.to_csv(os.path.join(os.path.dirname(args.out), "clients_stats.csv"), index=False)
    pd.DataFrame([scenario_summary]).to_csv(stats_path, index=False)

    print(f"[done] Saved {args.out}, clients_stats.csv, and statistics.csv")

if __name__ == "__main__":
    main()
