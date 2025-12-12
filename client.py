#!/usr/bin/env python3
import socket, struct, time, csv, os

# ======================================================
#                 PROTOCOL CONSTANTS
# ======================================================
MAGIC = b"GCL1"; VERSION = 1
MT_INIT, MT_SNAPSHOT, MT_EVENT, MT_ACK, MT_HEARTBEAT = range(5)
HDR_FMT = ">4sBBIIQH"
HDR_LEN = struct.calcsize(HDR_FMT)
SERVER_ADDR = ("127.0.0.1", 7777)

# Use env DURATION if provided; fallback to 10 for local runs
RUN_SECONDS = int(os.environ.get("DURATION", os.environ.get("RUN_SECONDS", "10")))

SMOOTH = 0.35
EVENT_RTO_MS = 120
MAX_EVENT_RETRIES = 4

# ======================================================
#                 HELPERS
# ======================================================
def monotonic_ms():
    return time.time_ns() // 1_000_000

def pack_header(msg_type, snapshot_id, seq_num, ts, payload):
    return struct.pack(HDR_FMT, MAGIC, VERSION, msg_type, snapshot_id, seq_num, ts, len(payload)) + payload

def smooth_pos(old, new):
    if old is None:
        return new
    ox, oy = old
    nx, ny = new
    return (ox + SMOOTH*(nx-ox), oy + SMOOTH*(ny-oy))

# ======================================================
#                 CLIENT MAIN
# ======================================================
def main(client_name="player1"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.1)
    seq_out = 1
    last_recv = None
    expected_snapshot = None   # will initialize on first snapshot
    lost_snapshots_total = 0
    client_id = None
    players_smooth = {}

    # CSV file handles will be opened after we know client_id
    pos_fname = None
    pos_f = None
    pos_w = None

    # send INIT
    init_payload = bytes([len(client_name)]) + client_name.encode()
    pkt = pack_header(MT_INIT, 0, seq_out, monotonic_ms(), init_payload)
    sock.sendto(pkt, SERVER_ADDR)
    seq_out += 1

    # Wait for INIT-ACK with client id and initial position
    while client_id is None:
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            pkt = pack_header(MT_INIT, 0, seq_out, monotonic_ms(), init_payload)
            sock.sendto(pkt, SERVER_ADDR)
            seq_out += 1
            continue
        if len(data) < HDR_LEN:
            continue
        magic, ver, mtype, snap, seq, ser_ms, plen = struct.unpack(HDR_FMT, data[:HDR_LEN])
        if magic != MAGIC or ver != VERSION or mtype != MT_ACK:
            continue
        payload = data[HDR_LEN:HDR_LEN+plen]
        if len(payload) < 3:
            continue
        cid, x, y = struct.unpack(">BBB", payload)
        client_id = int(cid)
        players_smooth[client_id] = (float(x), float(y))
        print(f"Connected as client {client_id} at ({x},{y})")

        # open per-client positions file (in cwd, so runner must run client in its folder)
        pos_fname = f"client_positions_{client_id}.csv"
        # overwrite existing file if any
        if os.path.exists(pos_fname):
            os.remove(pos_fname)
        pos_f = open(pos_fname, "w", newline="")
        pos_w = csv.writer(pos_f)
        # header includes lost_snapshots_total
        pos_w.writerow(["timestamp_ms", "snapshot_id", "seq_num", "player_id", "displayed_x", "displayed_y", "lost_snapshots_total","lost_snapshots_total"])
        pos_f.flush()

    # Event RDT placeholders (unchanged behavior)
    event_seq = 0
    outstanding_event = None
    next_event_time = time.time() + 2.0

    def send_critical_event(event_type, now_ms):
        nonlocal event_seq, seq_out, outstanding_event
        event_seq += 1
        payload = struct.pack(">BI", event_type, event_seq)
        pkt = pack_header(MT_EVENT, 0, seq_out, now_ms, payload)
        sock.sendto(pkt, SERVER_ADDR)
        seq_out += 1
        outstanding_event = {"seq": event_seq, "type": event_type, "attempts": 1, "last": now_ms}
        print(f"[EVENT] Sent event {event_type}, seq={event_seq}")

    start = time.time()
    last_applied = 0

    print(f"[CLIENT] Starting main loop, RUN_SECONDS={RUN_SECONDS}")

    # loop until duration expires (runner kills remaining processes)
    while time.time() - start < RUN_SECONDS:
        now_ms = monotonic_ms()
        try:
            data, _ = sock.recvfrom(4096)
            recv_ms = monotonic_ms()
        except socket.timeout:
            data = None

        if data and len(data) >= HDR_LEN:
            magic, ver, mtype, snap, seq, ser_ms, plen = struct.unpack(HDR_FMT, data[:HDR_LEN])
            payload = data[HDR_LEN:HDR_LEN+plen]

            if mtype == MT_SNAPSHOT:
                # initialize expected_snapshot on first snapshot
                if expected_snapshot is None:
                    expected_snapshot = snap
                # packet loss estimation (count gaps)
                if snap > expected_snapshot:
                    lost_here = snap - expected_snapshot
                    lost_snapshots_total += lost_here
                    # don't crash if lots lost; just accumulate
                expected_snapshot = snap + 1

                # ignore snapshots already applied (dedup)
                if snap <= last_applied:
                    continue

                if plen < 2:
                    continue
                (num_players,) = struct.unpack_from(">H", payload, 0)
                offset = 2
                new_positions = {}
                for _ in range(num_players):
                    if offset + 3 > len(payload):
                        break
                    pid, x, y = struct.unpack_from(">BBB", payload, offset)
                    offset += 3
                    new_positions[int(pid)] = (float(x), float(y))

                # latency & jitter
                latency = recv_ms - ser_ms
                jitter = 0 if last_recv is None else abs((recv_ms - last_recv))
                last_recv = recv_ms

                # apply smoothing only to players present in this snapshot
                for pid, pos in new_positions.items():
                    old_pos = players_smooth.get(pid)
                    players_smooth[pid] = smooth_pos(old_pos, pos)

                # write displayed positions for all currently known players (only those we have smooth for)
                for pid, (sx, sy) in players_smooth.items():
                    pos_w.writerow([int(recv_ms), int(snap), int(seq), int(pid), float(sx), float(sy), int(lost_snapshots_total)])
                pos_f.flush()
                last_applied = snap
                print(f"[SNAP {snap}] latency={latency}, jitter={jitter}, lost_total={lost_snapshots_total}")

            elif mtype == MT_ACK and plen >= 4:
                (ack_seq,) = struct.unpack(">I", payload[:4])
                if outstanding_event and ack_seq == outstanding_event["seq"]:
                    print(f"[EVENT-ACK] seq={ack_seq}")
                    outstanding_event = None

        # retransmit logic for outstanding event
        if outstanding_event:
            if now_ms - outstanding_event["last"] >= EVENT_RTO_MS:
                if outstanding_event["attempts"] >= MAX_EVENT_RETRIES:
                    print(f"[EVENT] Giving up on seq={outstanding_event['seq']}")
                    outstanding_event = None
                else:
                    payload = struct.pack(">BI", outstanding_event["type"], outstanding_event["seq"])
                    pkt = pack_header(MT_EVENT, 0, seq_out, now_ms, payload)
                    sock.sendto(pkt, SERVER_ADDR)
                    seq_out += 1
                    outstanding_event["attempts"] += 1
                    outstanding_event["last"] = now_ms
                    print(f"[EVENT] Retransmit seq={outstanding_event['seq']} attempt {outstanding_event['attempts']}")

        if outstanding_event is None and time.time() >= next_event_time:
            send_critical_event(event_type=2, now_ms=now_ms)
            next_event_time = time.time() + 1.5

    # cleanup
    if pos_f:
        pos_f.close()
    sock.close()
    print("Client finished.")

if __name__ == "__main__":
    main("player1")
