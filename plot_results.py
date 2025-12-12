import os
import argparse
import pandas as pd
import matplotlib.pyplot as plt

def plot_metric(df, metric, x_col, outdir):
    """
    df: dataframe containing metrics.csv
    metric: column name to plot (latency_ms, jitter_ms, perceived_error)
    x_col: update_rate or loss_rate
    outdir: directory to save plots in
    """
    if x_col not in df.columns:
        print(f"[skip] Missing column {x_col}")
        return
    if metric not in df.columns:
        print(f"[skip] Missing metric {metric}")
        return

    plt.figure(figsize=(8, 5))
    plt.plot(df[x_col], df[metric], label=metric)
    plt.xlabel(x_col)
    plt.ylabel(metric)
    plt.title(f"{metric} vs {x_col}")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    os.makedirs(outdir, exist_ok=True)
    save_path = os.path.join(outdir, f"{metric}_vs_{x_col}.png")
    plt.savefig(save_path)
    plt.close()
    print(f"[ok] Saved {save_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="infile", required=True,
                        help="path to metrics.csv")
    parser.add_argument("--out", dest="outdir", required=True,
                        help="output directory for plots")
    args = parser.parse_args()

    df = pd.read_csv(args.infile)
    os.makedirs(args.outdir, exist_ok=True)

    metrics = ["latency_ms", "jitter_ms", "perceived_error"]
    x_axes = ["update_rate", "loss_rate"]

    for metric in metrics:
        for x in x_axes:
            plot_metric(df, metric, x, args.outdir)


if __name__ == "__main__":
    main()
