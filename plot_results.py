import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

def plot_metric(metric_name, df, outdir="plots"):
    os.makedirs(outdir, exist_ok=True)

    # Extract needed columns
    metric = df[metric_name].to_numpy(dtype=float)
    update_rates = df["update_rate"].to_numpy(dtype=float)
    loss_rates = df["loss_rate"].to_numpy(dtype=float)

    # ==========================
    # Plot metric vs update rate
    # ==========================
    plt.figure(figsize=(8,5))
    plt.plot(update_rates, metric, marker='o')
    plt.title(f"{metric_name} vs Update Rate")
    plt.xlabel("Update Rate (Hz)")
    plt.ylabel(metric_name)
    plt.grid(True)
    plt.savefig(f"{outdir}/{metric_name}_vs_update_rate.png")
    plt.close()

    # ==========================
    # Plot metric vs loss rate
    # ==========================
    plt.figure(figsize=(8,5))
    plt.plot(loss_rates, metric, marker='o', color='red')
    plt.title(f"{metric_name} vs Loss Rate")
    plt.xlabel("Packet Loss Rate (%)")
    plt.ylabel(metric_name)
    plt.grid(True)
    plt.savefig(f"{outdir}/{metric_name}_vs_loss_rate.png")
    plt.close()

def main():
    df = pd.read_csv("metrics.csv")

    # You must add these parameters manually to the metrics file OR
    # compute_metrics should add them for each scenario run
    # For now we assume present:
    # update_rate, loss_rate columns

    for metric in ["latency_ms", "jitter_ms", "perceived_position_error"]:
        plot_metric(metric, df)

    print("All graphs generated in /plots folder.")

if __name__ == "__main__":
    main()
