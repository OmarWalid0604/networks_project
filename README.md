Game Client–Server Telemetry Protocol (GCL1)
Overview
This project implements a custom UDP‑based telemetry protocol for a simple multiplayer game environment.
The system consists of:

A UDP server that periodically sends authoritative world snapshots

One or more UDP clients that receive snapshots, smooth positions, and send critical events

A metrics pipeline to evaluate latency, jitter, packet loss, bandwidth, and position error

A set of network impairment scenarios (delay, loss, jitter, duplication, reordering)

The protocol demonstrates application‑level reliability for critical messages on top of UDP, while tolerating loss for high‑rate snapshot traffic.

Repository Structure
.
├── client.py                  # UDP game client
├── server.py                  # UDP game server
├── compute_metrics.py         # Offline metrics computation
├── scenarios/                 # Network impairment scripts
│   ├── baseline.sh
│   ├── delay_100ms.sh
│   ├── jitter_10ms.sh
│   ├── loss_2pct.sh
│   ├── loss_5pct.sh
│   ├── duplicate_5pct.sh
│   └── reorder_20pct.sh
├── artifacts/                 # Generated experiment outputs
│   ├── baseline/
│   ├── delay_100ms/
│   ├── loss_5pct/
│   └── ...
├── server_metrics.csv         # Server‑side metrics (CPU, bandwidth)
├── server_positions.csv       # Ground‑truth positions
├── client_positions_*.csv     # Per‑client displayed positions
├── plots/                     # Generated plots
└── README.md
Protocol Summary
Transport: UDP

Header Size: Fixed (struct‑packed)

Message Types:

INIT – Client join request

SNAPSHOT – Periodic world state updates (unreliable)

EVENT – Critical client action (reliable via retransmission)

ACK – Acknowledgment for INIT and EVENT

HEARTBEAT – Reserved (not used)

Reliability Model
Snapshots:

Sent at fixed tick rate

No retransmission (loss tolerated)

Client detects loss via snapshot ID gaps

Critical Events:

Stop‑and‑wait retransmission

Fixed RTO (EVENT_RTO_MS)

Maximum retry count (MAX_EVENT_RETRIES)

Server always ACKs received events (even duplicates)

Running the System
1. Start the Server
python3 server.py
The server listens on:

127.0.0.1:7777
2. Run the Client
python3 client.py
Environment variables:

RUN_SECONDS=10 python3 client.py
Each client produces:

client_positions_<client_id>.csv
Network Scenarios
All experiments are run using Linux tc netem.

Available Scenarios
Scenario	Description
baseline	No impairment
delay_100ms	Fixed 100 ms one‑way delay
jitter_10ms	±10 ms variable delay
loss_2pct	2% packet loss
loss_5pct	5% packet loss
duplicate_5pct	5% packet duplication
reorder_20pct	20% packet reordering
Example
sudo ./scenarios/loss_5pct.sh
python3 server.py
python3 client.py
Metrics Collection
Server Metrics (server_metrics.csv)
Timestamp

CPU utilization (%)

Average bandwidth (kbps)

Tick rate

Client Metrics (client_positions_*.csv)
Snapshot ID

Displayed position

Lost snapshot count

Used to compute:

Position error

Latency

Jitter

Computing Metrics
python3 compute_metrics.py \
  --server_positions server_positions.csv \
  --client_positions client_positions_1.csv \
  --output metrics.csv
Generated outputs include:

Mean latency

Jitter distribution

Position error over time

Scenario comparison plots

Key Design Decisions
UDP chosen for low latency and full protocol control

Reliability added only where necessary (critical events)

Snapshot loss tolerated and smoothed client‑side

Server remains stateless for snapshots

Metrics collected offline for reproducibility



HERE IS THE LINK FOR THE VIDEO

https://engasuedu-my.sharepoint.com/:f:/g/personal/22p0166_eng_asu_edu_eg/IgBFTO_jr-CLQoZvTh3OLiQbASBqq10as9nV95aFGDy7zqM?e=OD9JXL
