#!/usr/bin/env python3
"""
Tries to connect to a running SUMO (started by your Sumo2Unity tool) on several common TraCI ports.
When connected it looks for two vehicles on the same edge and forces a collision by stopping
one vehicle and disabling safety checks on the other.

Usage:
  python force_collision.py [--leader LEADER_ID] [--follower FOLLOWER_ID]

If no IDs are provided the script selects the first two vehicles it finds that share an edge.
"""
import sys
import time
import argparse

ports_to_try = [8813, 8814, 8815, 13333, 1337]

parser = argparse.ArgumentParser()
parser.add_argument('--leader', help='Optional leader vehicle ID to stop')
parser.add_argument('--follower', help='Optional follower vehicle ID to force unsafe behaviour')
parser.add_argument('--steps', type=int, default=600, help='Max simulation steps to wait')
parser.add_argument('--connect-delay', type=float, default=0.1, help='Delay between steps (for human-observable runs)')
parser.add_argument('--port', type=int, help='Optional TraCI port to try first')
args = parser.parse_args()

if args.port:
    try:
        ports_to_try.insert(0, int(args.port))
    except Exception:
        pass

try:
    import traci
except Exception as e:
    print("ERROR: traci module not found. Use the SUMO python or install traci.")
    print(str(e))
    sys.exit(1)

conn = None
used_port = None
for p in ports_to_try:
    try:
        print(f"Trying TraCI port {p}...")
        traci.init(port=p)
        conn = traci
        used_port = p
        print(f"Connected on port {p}")
        break
    except Exception:
        # older SUMO/traci uses traci.connect
        try:
            traci.connect(port=p)
            conn = traci
            used_port = p
            print(f"Connected on port {p}")
            break
        except Exception:
            continue

if conn is None:
    print("Failed to connect to any common TraCI ports. Make sure SUMO-GUI (started by Sumo2Unity) is running and exposes TraCI.")
    sys.exit(2)

print("Waiting for vehicles to appear...")

leader_id = args.leader
follower_id = args.follower

for step in range(args.steps):
    try:
        conn.simulationStep()
    except Exception as e:
        print("Traci simulationStep error:", e)
        break

    ids = conn.vehicle.getIDList()
    if len(ids) >= 2:
        # If user provided IDs, validate
        if leader_id and leader_id not in ids:
            print(f"Requested leader {leader_id} not present yet")
        if follower_id and follower_id not in ids:
            print(f"Requested follower {follower_id} not present yet")

        if leader_id and follower_id and leader_id in ids and follower_id in ids:
            chosen_leader = leader_id
            chosen_follower = follower_id
        else:
            # find two vehicles that share the same edge
            chosen_leader = None
            chosen_follower = None
            edge_map = {}
            for vid in ids:
                try:
                    edge = conn.vehicle.getRoadID(vid)
                except Exception:
                    continue
                edge_map.setdefault(edge, []).append(vid)

            for edge, vids in edge_map.items():
                if len(vids) >= 2:
                    # choose the rearmost (higher position along edge) as follower
                    # get position along edge using lane position if available
                    vids_sorted = vids
                    chosen_leader = vids_sorted[0]
                    chosen_follower = vids_sorted[1]
                    break

        if chosen_leader and chosen_follower:
            print(f"Selected leader={chosen_leader}, follower={chosen_follower} on same edge. Forcing collision...")

            # stop the leader immediately
            try:
                conn.vehicle.setSpeed(chosen_leader, 0.0)
            except Exception as e:
                print("Could not set leader speed:", e)

            # disable safety checks on follower (speedMode=0, laneChangeMode=0)
            try:
                conn.vehicle.setSpeedMode(chosen_follower, 0)
                conn.vehicle.setLaneChangeMode(chosen_follower, 0)
                # optionally keep follower moving at current speed to cause overlap - do NOT force extremely high speed
                sp = conn.vehicle.getSpeed(chosen_follower)
                print(f"Follower current speed: {sp}")
                if sp > 0:
                    # attempt to keep follower at same speed (override controllers)
                    conn.vehicle.setSpeed(chosen_follower, sp)
            except Exception as e:
                print("Could not modify follower modes:", e)

            print("Commands sent. Let the simulation run a bit to create overlap (if collision conditions satisfied).")

            # run a few more steps to let collision happen
            for _ in range(200):
                try:
                    conn.simulationStep()
                except Exception:
                    break
                time.sleep(args.connect_delay)

            print("Done. Inspect SUMO-GUI and Unity to see the collision.")
            conn.close()
            sys.exit(0)

    time.sleep(args.connect_delay)

print("Timed out waiting for suitable vehicles. Try increasing --steps or specify IDs with --leader/--follower.")
conn.close()
sys.exit(3)
