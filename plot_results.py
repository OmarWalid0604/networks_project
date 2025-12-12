import pandas as pd
import argparse
import os
import matplotlib.pyplot as plt

def plot_metric(df, metric, outdir):
    os.makedirs(outdir, exist_ok=True)

    # Plot vs update rate (snapshot_id)
    plt.figure()
    df.plot(x="snapshot_id", y=metric)
    plt.title(f"{metric} vs Update Rate")
    plt.savefig(os.path.join(outdir, f"{metric}_vs_update_rate.png"))
    plt.close()

    # Plot vs loss rate (latency/jitter/error grouped by scenario loss)
    if "loss_rate" in df.columns:
        plt.figure()
        df.plot(x="loss_rate", y=metric)
        plt.title(f"{metric} vs Loss Rate")
        plt.savefig(os.path.join(outdir, f"{metric}_vs_loss_rate.png"))
        plt.close()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", required=True, help="Path to metrics.csv")
    p.add_argument("--out", required=True, help="Directory to save plots")
    args = p.parse_args()

    df = pd.read_csv(args.in)

    metrics = ["latency_ms", "jitter_ms", "perceived_position_error"]
    for m in metrics:
        if m in df.columns:
            plot_metric(df, m, args.out)

if __name__ == "__main__":
    main()
