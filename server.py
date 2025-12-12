#!/usr/bin/env python3
import socket, struct, time, csv, threading, random

# ======================================================
#                 PROTOCOL CONSTANTS
# ======================================================
MAGIC = b"GCL1"; VERSION = 1
MT_INIT, MT_SNAPSHOT, MT_EVENT, MT_ACK, MT_HEARTBEAT = range(5)

HDR_FMT = ">4sBBIIQH"
HDR_LEN = struct.calcsize(HDR_FMT)

SERVER_ADDR = ("127.0.0.1", 7777)
PAYLOAD_LIMIT = 1200
TICK_HZ = 20
MAX_CLIENTS = 4

# ======================================================
#                 STATE VARIABLES
# ======================================================
players = {}               # client_id -> (x, y)
clients = {}               # addr -> client_id
seq_nums = {}              # addr -> next seq num
next_client_id = 1
snapshot_id = 0

packet_sent = 0
packet_recv = 0
bytes_sent_per_client = {}

metrics_lock = threading.Lock()

# ======================================================
#                 HELPER FUNCTIONS
# ======================================================
def monotonic_ms():
    return time.time_ns() // 1_000_000


def pack_header(msg_type, snapshot_id, seq_num, ts, payload):
    if len(payload) > PAYLOAD_LIMIT:
        raise ValueError("Payload too large")
    return struct.pack(
        HDR_FMT,
        MAGIC, VERSION, msg_type,
        snapshot_id, seq_num, ts, len(payload)
    ) + payload

# ======================================================
#                 CSV LOGGING FILES
# ======================================================
metrics_file = open("server_metrics.csv", "w", newline="")
metrics_writer = csv.writer(metrics_file)
metrics_writer.writerow(["cpu_percent", "bandwidth_per_client_kbps"])
metrics_file.flush()

server_pos_file = open("server_positions.csv", "w", newline="")
server_pos_writer = csv.writer(server_pos_file)
server_pos_writer.writerow(["timestamp_ms", "snapshot_id", "player_id", "x", "y"])
server_pos_file.flush()

# ======================================================
#                 RECEIVE LOOP
# ======================================================
def recv_loop(sock: socket.socket):
    global packet_recv, next_client_id, packet_sent

    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue

        with metrics_lock:
            packet_recv += 1

        if len(data) < HDR_LEN:
            continue

        magic, ver, mtype, snap, seq, ser_ms, plen = struct.unpack(
            HDR_FMT, data[:HDR_LEN]
        )
        if magic != MAGIC or ver != VERSION:
            continue

        payload = data[HDR_LEN:HDR_LEN+plen]

        # ----------------------
        # INIT FROM NEW CLIENT
        # ----------------------
        if mtype == MT_INIT:
            if addr not in clients and len(clients) < MAX_CLIENTS:
                cid = next_client_id
                next_client_id += 1

                clients[addr] = cid
                seq_nums[addr] = 1
                players[cid] = (random.randint(0, 19), random.randint(0, 19))
                with metrics_lock:
                    bytes_sent_per_client[cid] = 0

                x, y = players[cid]
                ack_payload = struct.pack(">BBB", cid, x, y)

                pkt = pack_header(MT_ACK, 0, seq_nums[addr], monotonic_ms(), ack_payload)
                sock.sendto(pkt, addr)

                with metrics_lock:
                    bytes_sent_per_client[cid] += len(pkt)
                    packet_sent += 1

            continue

        if addr not in clients:
            continue

        cid = clients[addr]

        # ----------------------
        # CRITICAL EVENT FROM CLIENT
        # ----------------------
        if mtype == MT_EVENT and plen >= 5:
            event_type, event_seq = struct.unpack(">BI", payload[:5])

            # ACK the event
            seq_nums[addr] += 1
            ack_payload = struct.pack(">I", event_seq)
            pkt = pack_header(MT_ACK, 0, seq_nums[addr], monotonic_ms(), ack_payload)
            sock.sendto(pkt, addr)

            with metrics_lock:
                bytes_sent_per_client[cid] += len(pkt)
                packet_sent += 1

            continue

        # Ignore ACKs (server does no retransmission for snapshots)

# ======================================================
#                 SNAPSHOT LOOP
# ======================================================
def snapshot_loop(sock: socket.socket):
    global snapshot_id, packet_sent

    while True:
        time.sleep(1 / TICK_HZ)
        snapshot_id += 1

        # movement simulation
        for pid, (x, y) in list(players.items()):
            nx = (x + random.choice([-1, 0, 1])) % 20
            ny = (y + random.choice([-1, 0, 1])) % 20
            players[pid] = (nx, ny)

        ts = monotonic_ms()
        for pid, (x, y) in players.items():
            server_pos_writer.writerow([ts, snapshot_id, pid, x, y])
        server_pos_file.flush()

        payload = struct.pack(">H", len(players))
        for pid, (x, y) in players.items():
            payload += struct.pack(">BBB", pid, x, y)

        for addr, cid in clients.items():
            seq_nums[addr] += 1
            pkt = pack_header(MT_SNAPSHOT, snapshot_id, seq_nums[addr], ts, payload)
            sock.sendto(pkt, addr)

            with metrics_lock:
                bytes_sent_per_client[cid] += len(pkt)
                packet_sent += 1

# ======================================================
#                 METRICS LOOP
# ======================================================
def metrics_loop():
    last_time = time.time()
    last_cpu = time.process_time()
    last_bytes = {}

    while True:
        time.sleep(1)
        now = time.time()
        now_cpu = time.process_time()
        dt = now - last_time
        cpu_dt = now_cpu - last_cpu

        cpu_percent = (cpu_dt / dt) * 100 if dt > 0 else 0.0

        with metrics_lock:
            bw_per_client = []
            for cid, total_bytes in bytes_sent_per_client.items():
                prev = last_bytes.get(cid, 0)
                delta = total_bytes - prev
                kbps = (delta * 8) / 1000.0
                bw_per_client.append(kbps)
                last_bytes[cid] = total_bytes

        avg_bw = sum(bw_per_client) / len(bw_per_client) if bw_per_client else 0.0
        metrics_writer.writerow([cpu_percent, avg_bw])
        metrics_file.flush()

        last_time = now
        last_cpu = now_cpu

# ======================================================
#                 MAIN SERVER FUNCTION
# ======================================================
def run_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(SERVER_ADDR)
    sock.settimeout(0.001)

    print("SERVER running at", SERVER_ADDR)

    threading.Thread(target=recv_loop, args=(sock,), daemon=True).start()
    threading.Thread(target=snapshot_loop, args=(sock,), daemon=True).start()
    threading.Thread(target=metrics_loop, daemon=True).start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Server shutting down.")
        metrics_file.close()
        server_pos_file.close()


if __name__ == "__main__":
    run_server()
