#  Author  : Ahmad Mohammadi, PhD – York University
#  License : MIT
# ────────────────────────────────────────────────────────────────
import os, sys, json, math, time, queue, threading, statistics, datetime, pickle
import tkinter as tk, webbrowser
from tkinter import ttk, messagebox
from PIL import Image, ImageTk   
import zmq, logging              
import requests                  
import matplotlib.pyplot as plt 
import numpy as np  # REQUIRED for Q-learning math
# ════════════════════════════════════════════════════════════════
#  DEFAULTS (shared by GUI & simulation)
# ════════════════════════════════════════════════════════════════
DEFAULTS = {
    "IntegrationStartTime": 540,
    "ExperimentStartTime" : 600,
    "ExperimentEndTime"   : 720,
    "steplength"          : 0.1,
    "lateral_resolution"  : 0.3,
    "zoom"                : 150.0,   # (bigger value → closer)
    "subscribe_radius"    : 250.0    # ★ NEW (TraCI context radius)
}

VERSION      = "Sumo2Unity v2.0.0"
LINKEDIN_URL = "https://www.linkedin.com/in/ahmadmohammadi1441/"

# ------------------ ThingsBoard HTTP Sender (background) ------------------
TB_HTTP_URL_TEMPLATE = "https://thingsboard.cloud/api/v1/t998vexqr2z9j1sknv63/telemetry"
TB_TOKEN = os.environ.get("TB_DEVICE_TOKEN", "YOUR_DEVICE_TOKEN")  # set env var or replace here
TB_URL = TB_HTTP_URL_TEMPLATE.format(token=TB_TOKEN)
TB_TIMEOUT = 2.0
TB_BATCH_SIZE = 10        # how many payloads to bundle (set 1 for single)
TB_RETRY_MAX = 3
TB_RETRY_BASE = 0.5       # seconds between retries

tb_queue = queue.Queue()
tb_stop = threading.Event()
zmq_stop = threading.Event()

# ═════════════════ PLOTTING UTILITY (generate_plots) ════════════════
def moving_average(data, window_size):
    """Applies simple moving average smoothing to a 1D NumPy array."""
    if len(data) < window_size:
        return np.array(data)
    weights = np.repeat(1.0, window_size) / window_size
    return np.convolve(data, weights, 'valid')

def generate_plots(telemetry_log, output_dir="Results"):
    """Generates and saves the required performance graphs."""
    
    if not telemetry_log:
        logging.getLogger(__name__).warning("Telemetry log is empty. Skipping plot generation.")
        return

    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Extract Data
    sim_time = np.array([d.get('sim_time', 0) for d in telemetry_log])
    reward = np.array([d.get('reward', 0) for d in telemetry_log])
    avg_wait_time = np.array([d.get('avg_wait_time', 0) for d in telemetry_log])
    total_EB = np.array([d.get('total_EB', 0) for d in telemetry_log])
    total_WB = np.array([d.get('total_WB', 0) for d in telemetry_log])
    total_NB = np.array([d.get('total_NB', 0) for d in telemetry_log])
    total_SB = np.array([d.get('total_SB', 0) for d in telemetry_log])

    # Smoothing configuration
    WINDOW = 20 # Smoothing window size for visual clarity
    
    # --- Plot 1: Q-Learning Reward ---
    plt.figure(figsize=(10, 5))
    if len(reward) >= WINDOW:
        smoothed_reward = moving_average(reward, WINDOW)
        time_offset = sim_time[WINDOW - 1:]
        plt.plot(time_offset, smoothed_reward, label='Smoothed Reward', color='#00A36C')
    else:
        plt.plot(sim_time, reward, label='Raw Reward', color='#00A36C')

    plt.title('Q-Learning Agent Reward over Time')
    plt.xlabel('Simulation Time (s)')
    plt.ylabel('Smoothed Reward (Negative Total Queue)')
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.savefig(os.path.join(output_dir, 'Q_Learning_Reward_Graph.png'))
    plt.close()
    
    # --- Plot 2: Average Waiting Time ---
    plt.figure(figsize=(10, 5))
    if len(avg_wait_time) >= WINDOW:
        smoothed_wait_time = moving_average(avg_wait_time, WINDOW)
        time_offset = sim_time[WINDOW - 1:]
        plt.plot(time_offset, smoothed_wait_time, label='Smoothed Avg Wait Time', color='#FF4500')
    else:
        plt.plot(sim_time, avg_wait_time, label='Raw Avg Wait Time', color='#FF4500')
        
    plt.title('Average Vehicle Waiting Time over Time')
    plt.xlabel('Simulation Time (s)')
    plt.ylabel('Average Waiting Time (s)')
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.savefig(os.path.join(output_dir, 'Avg_Waiting_Time_Graph.png'))
    plt.close()

    # --- Plot 3: Queue Length Time Series ---
    plt.figure(figsize=(10, 5))
    plt.plot(sim_time, total_EB, label='Eastbound Queue', alpha=0.8, color='b')
    plt.plot(sim_time, total_WB, label='Westbound Queue', alpha=0.8, color='r')
    plt.plot(sim_time, total_NB, label='Northbound Queue', alpha=0.8, color='g')
    plt.plot(sim_time, total_SB, label='Southbound Queue', alpha=0.8, color='m')
    
    plt.title('Queue Length Time Series by Approach')
    plt.xlabel('Simulation Time (s)')
    plt.ylabel('Number of Vehicles in Queue')
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.savefig(os.path.join(output_dir, 'Queue_Length_TimeSeries.png'))
    plt.close()

    logging.getLogger(__name__).info(f"Generated 3 performance plots in {output_dir}/")



def tb_sender_thread():
    session = requests.Session()
    while not tb_stop.is_set():
        try:
            batch = []
            # block up to 1s waiting for an item
            item = tb_queue.get(timeout=1.0)
            batch.append(item)
            # gather up to TB_BATCH_SIZE (non-blocking)
            while len(batch) < TB_BATCH_SIZE:
                try:
                    batch.append(tb_queue.get_nowait())
                except queue.Empty:
                    break

            # If batching, send as list; ThingsBoard accepts arrays of telemetry objects.
            payload = batch[0] if len(batch) == 1 else batch
            # retry loop
            for attempt in range(1, TB_RETRY_MAX + 1):
                try:
                    r = session.post(TB_URL, json=payload, timeout=TB_TIMEOUT)
                    if r.status_code in (200, 201, 202):
                        break
                    else:
                        time.sleep(TB_RETRY_BASE * (2**(attempt-1)))
                except Exception:
                    time.sleep(TB_RETRY_BASE * (2**(attempt-1)))
            # mark queue items done
            for _ in batch:
                try:
                    tb_queue.task_done()
                except Exception:
                    pass
        except queue.Empty:
            continue
    session.close()

# start ThingsBoard sender thread (daemon)
threading.Thread(target=tb_sender_thread, daemon=True).start()

# ═════════ helper to reach packaged resources ═══════════════════
def resource_path(fname: str) -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, fname)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), fname)

# ═════════════════ GUI  SET-UP ══════════════════════════════════
root = tk.Tk(); root.title("Sumo2Unity Tool"); root.resizable(True, True)

def load_resized(path: str, target_w: int) -> ImageTk.PhotoImage:
    img = Image.open(resource_path(path))
    r   = img.height / img.width
    return ImageTk.PhotoImage(img.resize((target_w, int(target_w*r))))

# banner images (if packaged)
try:
    IMG_W = 600
    banner_imgs = [load_resized("2.Integration.JPG", IMG_W),
                   load_resized("2.Integration_B.JPG", IMG_W)]
except Exception:
    IMG_W = 600
    banner_imgs = ["",""]
banner_lbl  = tk.Label(root, image=banner_imgs[0])
banner_lbl.grid(row=0, column=0, columnspan=4, pady=(6, 12))
def swap(idx=[0]):
    idx[0] = (idx[0] + 1) % len(banner_imgs)
    try:
        banner_lbl.configure(image=banner_imgs[idx[0]])
    except Exception:
        pass
    root.after(2000, swap)
root.after(2000, swap)

root.columnconfigure(1, weight=1)
entries, row = {}, 1
for k, v in DEFAULTS.items():
    label_text = ("zoom (bigger value → closer)" if k == "zoom"
                  else "subscribe radius (m)"    if k == "subscribe_radius"
                  else k)
    ttk.Label(root, text=label_text).grid(row=row, column=0,
                                          sticky="e", padx=6, pady=3)
    e = ttk.Entry(root); e.insert(0, str(v))
    e.grid(row=row, column=1, sticky="we", padx=6, pady=3)
    entries[k] = e; row += 1

# ── NEW OPTIONS ────────────────────────────────────────────────
use_gui_var   = tk.BooleanVar(value=True)
rtf_var       = tk.BooleanVar(value=True)
free_cam_var  = tk.BooleanVar(value=False)        # ★ NEW (Free-cam)
collision_flags_var = tk.BooleanVar(value=False)  # opt-in: launch SUMO with collision flags

ttk.Checkbutton(root, text="Run SUMO with GUI",  variable=use_gui_var)\
   .grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=3); row += 1
ttk.Checkbutton(root, text="Calculate RTF",      variable=rtf_var)\
   .grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=3); row += 1
ttk.Checkbutton(root, text="Free camera (no follow ego vehicle)",
                variable=free_cam_var) \
   .grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=3); row += 1  # ★ NEW
ttk.Checkbutton(root, text="Enable SUMO collision flags (opt-in)", variable=collision_flags_var) \
    .grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=3); row += 1
# ────────────────────────────────────────────────────────────────

def center(win):
    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    x = (win.winfo_screenwidth()-w)//2
    y = (win.winfo_screenheight()-h)//2
    win.geometry(f"{w}x{h}+{x}+{y}")

def pop_img(title, img_path, w):
    pop = tk.Toplevel(root); pop.title(title); pop.resizable(False, False)
    im  = load_resized(img_path, w); tk.Label(pop, image=im).pack()
    pop.im = im; ttk.Button(pop, text="Close", command=pop.destroy).pack(pady=6)
    center(pop)

def show_help():    pop_img("Help", "Help.JPG", 874)
def show_contact():
    pop = tk.Toplevel(root); pop.title("Contact / License")
    t   = tk.Text(pop, wrap="word", width=80, height=24)
    t.insert("1.0", f"{VERSION}\n\nContact: Ahmad Mohammadi\nLinkedIn: {LINKEDIN_URL}\n\nMIT License — see repository")
    t.config(state="disabled"); t.pack(expand=True, fill="both"); center(pop)
def show_pubs():
    pop = tk.Toplevel(root); pop.title("Publications")
    txt = tk.Text(pop, wrap="word", width=100, height=18)
    pubs = """\
1. Mohammadi, A., Park, P. Y., Nourinejad, M., Cherakkatil, M. S. B., & Park, H. S. (2024, June).
   SUMO2Unity: An Open-Source Traffic Co-Simulation Tool to Improve Road Safety.
   In 2024 IEEE Intelligent Vehicles Symposium (IV) (pp. 2523-2528). IEEE.

2. Mohammadi, A., Park, P. Y., Nourinejad, M., & Cherakkatil, M. S. B. (2025, May).
   Development of a Virtual Reality Traffic Simulation to Analyze Road User Behavior.
   In 2025 7th International Congress on Human-Computer Interaction, Optimization
   and Robotic Applications (ICHORA) (pp. 1-5). IEEE.
   
3. Mohammadi, A., Cherakkatil, M. S. B., Park, P. Y., Nourinejad, M., & Asgary, A. (2025). 
   A novel virtual reality traffic simulation for enhanced traffic safety assessment [Preprint].
   Preprints. https://doi.org/10.20944/preprints202508.0112.v1
"""
    txt.insert("1.0", pubs); txt.config(state="disabled")
    txt.pack(expand=True, fill="both", padx=8, pady=8); center(pop)
# ═════════════════ SIMULATION (run_sim) ═════════════════════════


# ═════════════════ SIMULATION (run_sim) ═════════════════════════
def run_sim(cfg: dict):
    import traci
    from traci.constants import VAR_POSITION3D, VAR_ANGLE, VAR_TYPE
   
    import random       # REQUIRED for exploration

    # ---------- apply GUI parameters ----------
    IntegrationStartTime = cfg["IntegrationStartTime"]
    ExperimentStartTime  = cfg["ExperimentStartTime"]
    ExperimentEndTime    = cfg["ExperimentEndTime"]
    steplength           = cfg["steplength"]
    lateral_resolution   = cfg["lateral_resolution"]
    zoom_level           = cfg["zoom"]
    subscribe_radius     = cfg["subscribe_radius"]   # ★ NEW
    use_gui              = cfg["use_gui"]
    calc_rtf             = cfg["calc_rtf"]
    free_cam             = cfg["free_cam"]           # ★ NEW
    enable_collision_flags = cfg.get("enable_collision_flags", False)

    # ---------- logging ----------
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s")
    logger = logging.getLogger(__name__)

    # --- 1. Q-LEARNING PARAMETERS AND VARIABLES ---
    TLS_ID = "J1" # Target Traffic Light ID

    # Hyperparameters
    TOTAL_STEPS = 10000
    ALPHA = 0.1
    GAMMA = 0.9
    EPSILON = 0.1
    ACTIONS = [0, 1] # 0 = Keep, 1 = Switch

    # RL Control State
    Q_table = {}
    MIN_GREEN_STEPS = 100
    last_switch_step = -MIN_GREEN_STEPS
    current_simulation_step = 0 # Q-Learning step counter

    # --- Q-table persistence ---
    QTABLE_PATH = os.path.join(os.path.dirname(__file__), "Q_table.pkl")
    AUTOSAVE_INTERVAL = 1000  # steps

    if os.path.exists(QTABLE_PATH):
        try:
            with open(QTABLE_PATH, "rb") as f:
                Q_table = pickle.load(f)
            logger.info(f"Loaded existing Q-table with {len(Q_table)} states.")
        except Exception as e:
            logger.warning(f"Failed to load Q-table: {e}")
    else:
        logger.info("No previous Q-table found. Starting fresh.")

    # Detector IDs (12 total)
    DETECTORS_EB = ["Node1_2_EB_0", "Node1_2_EB_1", "Node1_2_EB_2"]
    DETECTORS_SB = ["Node2_7_SB_0", "Node2_7_SB_1", "Node2_7_SB_2"]
    DETECTORS_WB = ["Node2_3_WB_0", "Node2_3_WB_1", "Node2_3_WB_2"]
    DETECTORS_NB = ["Node2_5_NB_0", "Node2_5_NB_1", "Node2_5_NB_2"]
    ALL_DETECTORS = DETECTORS_EB + DETECTORS_SB + DETECTORS_WB + DETECTORS_NB

    # --- 2. RL HELPER FUNCTIONS ---
    def get_queue_length(detector_id):
        try:
            return traci.lanearea.getLastStepVehicleNumber(detector_id)
        except Exception:
            return 0

    def get_current_phase(tls_id):
        try:
            return traci.trafficlight.getPhase(tls_id)
        except Exception:
            return 0

    def get_max_Q_value_of_state(s):
        if s not in Q_table:
            Q_table[s] = np.zeros(len(ACTIONS))
        return np.max(Q_table[s])

    def get_reward(state):
        """Negative of total queue length (first 12 elements of state)."""
        total_queue = sum(state[:-1])
        return -float(total_queue)

    def get_state():
        state_list = []
        for det_id in ALL_DETECTORS:
            state_list.append(get_queue_length(det_id))
        current_phase = get_current_phase(TLS_ID)
        state_list.append(current_phase)
        return tuple(state_list)

    def apply_action(action, tls_id=TLS_ID):
        nonlocal last_switch_step, current_simulation_step
        if action == 0:
            return # Keep current phase
        elif action == 1:
            if current_simulation_step - last_switch_step >= MIN_GREEN_STEPS:
                try:
                    program = traci.trafficlight.getAllProgramLogics(tls_id)[0]
                    num_phases = len(program.phases)
                    next_phase = (get_current_phase(tls_id) + 1) % num_phases
                    traci.trafficlight.setPhase(tls_id, next_phase) # <-- TRAFFIC CONTROL COMMAND
                    last_switch_step = current_simulation_step
                except Exception:
                    pass

    def update_Q_table(old_state, action, reward, new_state):
        # periodic autosave handled after update
        if old_state not in Q_table:
            Q_table[old_state] = np.zeros(len(ACTIONS))

        old_q = Q_table[old_state][action]
        best_future_q = get_max_Q_value_of_state(new_state)
        Q_table[old_state][action] = old_q + ALPHA * (reward + GAMMA * best_future_q - old_q)

        if AUTOSAVE_INTERVAL and current_simulation_step % AUTOSAVE_INTERVAL == 0:
            try:
                with open(QTABLE_PATH, "wb") as f:
                    pickle.dump(Q_table, f)
                logger.info(f"Autosaved Q-table at step {current_simulation_step} ({len(Q_table)} states).")
            except Exception as e:
                logger.warning(f"Failed to autosave Q-table: {e}")

    def get_action_from_policy(state):
        if random.random() < EPSILON:
            return random.choice(ACTIONS)
        else:
            if state not in Q_table:
                Q_table[state] = np.zeros(len(ACTIONS))
            return int(np.argmax(Q_table[state]))

    # ---------- SUMO paths ----------
    if 'SUMO_HOME' not in os.environ:
        sys.exit("Set SUMO_HOME env variable.")
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))

    base_dir = os.path.dirname(sys.executable) if getattr(sys,"frozen",False) \
               else os.path.dirname(__file__)
    sumo_cfg = os.path.join(base_dir, "Sumo2Unity.sumocfg")
    sumo_bin = "sumo-gui" if use_gui else "sumo"
    sumo_cmd = [sumo_bin,"-c",sumo_cfg,"--step-length",str(steplength),
                "--lateral-resolution",str(lateral_resolution)]
    # Append optional collision flags when user enabled them in GUI
    if enable_collision_flags:
        sumo_cmd += [
            "--collision.mingap-factor","0",
            "--collision.action","none",
            "--collision.stoptime","0",
            "--collision.check-junctions","true"
        ]
    if use_gui:
        sumo_cmd += ["--delay","0"]   # keep 0-delay only when GUI present

    # ---------- connect TraCI ----------
    traci.start(sumo_cmd)

    # ---------- gui camera helper ----------
    ego = "f_0.0"

    if use_gui and not free_cam:                             # ★ NEW
        view_id = "View #0"
        try:
            traci.gui.trackVehicle(view_id, ego)
            traci.gui.setSchema(view_id, "real world")
        except Exception:
            pass

    def cam_follow(view_id, veh_id):
        if free_cam:
            return
        try:
            traci.gui.trackVehicle(view_id, veh_id)
            traci.gui.setZoom(view_id, zoom_level)
        except traci.TraCIException:
            pass
    # ------------------------------------------------------------

    # ---------- TraCI context subscription ----------
    try:
        traci.vehicle.subscribeContext(
            ego,
            traci.constants.CMD_GET_VEHICLE_VARIABLE,
            subscribe_radius,                    # ★ NEW (was 250)
            [VAR_POSITION3D, VAR_ANGLE, VAR_TYPE]
        )
    except Exception:
        # continue even if subscription fails
        pass

    # ---------- ZMQ sockets ----------
    ctx  = zmq.Context()
    pub  = ctx.socket(zmq.PUB);    pub.bind("tcp://*:5556")
    rout = ctx.socket(zmq.ROUTER); rout.bind("tcp://*:5557")

    # ---------- background Unity RX ----------
    # ---------- background Unity RX ----------
    u_q = queue.Queue()
    def rx_unity():
        # Use NOBLOCK and check the stop flag to exit gracefully
        while not zmq_stop.is_set():
            try:
                # Poll for 100ms. If data is ready, recv with NOBLOCK.
                if rout.poll(100, zmq.POLLIN):
                    _ident, msg = rout.recv_multipart(zmq.NOBLOCK)
                    u_q.put(json.loads(msg.decode()))
            except zmq.Again:
                # Expected when using NOBLOCK and no message is waiting
                continue
            except Exception:
                # Only log an unexpected error if we weren't trying to shut down
                if not zmq_stop.is_set():
                    logger.exception("Unity RX (Unexpected Error)")

    threading.Thread(target=rx_unity, daemon=True).start()

    # ---------- helpers ----------
    WINDOW = 10
    last_pos, last_pos_z, rw_hist = {}, {}, {}
    prof = {k: [] for k in ("Unity","Step","Collect","Send","DataProc","Total")}
    def sleep_precise(d):
        t0 = time.perf_counter()
        while (rem := d - (time.perf_counter()-t0)) > 0:
            if rem > 0.002: time.sleep(0.001)

    # ---------- results dir / RTF file ----------
    if calc_rtf:
        res_dir = os.path.join(os.path.abspath(os.path.join(base_dir, os.pardir)),
                               "Results")
        os.makedirs(res_dir, exist_ok=True)
        rtf_f = open(os.path.join(res_dir,"rtf_report.txt"),"w",encoding="utf-8")
        rtf_f.write("Time(s);RTF\n")
    else:
        rtf_f = None

    # ---------- containers ----------
    # ---------- containers ----------
    # ADD this line:
    telemetry_log = [] 
    # one-time collision injector state
    collision_injected = False

    def try_force_collision():
        """Find two non-ego vehicles on the same road and force a collision.

        Strategy: pick two vehicles on the same road edge (leader ahead, follower behind),
        stop the leader and disable safety on the follower so it will close the gap.
        Returns True if an injection was attempted.
        """
        nonlocal collision_injected
        try:
            vlist = traci.vehicle.getIDList()
            if not vlist or len(vlist) < 2:
                return False

            # group by road id
            by_road = {}
            for v in vlist:
                if v == ego:  # never target the ego
                    continue
                try:
                    road = traci.vehicle.getRoadID(v)
                except Exception:
                    continue
                by_road.setdefault(road, []).append(v)

            for road, vids in by_road.items():
                if road is None or road == "":
                    continue
                if len(vids) < 2:
                    continue

                # sort by lane position (ascending), assume higher => further along
                try:
                    vids_sorted = sorted(vids, key=lambda vid: traci.vehicle.getLanePosition(vid))
                except Exception:
                    continue

                # choose the last two (leader is furthest along)
                leader = vids_sorted[-1]
                follower = vids_sorted[-2]
                # safety: avoid ego and identical ids
                if leader == ego or follower == ego or leader == follower:
                    continue

                try:
                    # stop the leader
                    traci.vehicle.setSpeed(leader, 0.0)
                    # disable automatic safety modes on follower
                    try:
                        traci.vehicle.setSpeedMode(follower, 0)
                    except Exception:
                        pass
                    try:
                        traci.vehicle.setLaneChangeMode(follower, 0)
                    except Exception:
                        pass
                    # nudge follower to a bit higher speed so it will close gap
                    try:
                        cur_sp = traci.vehicle.getSpeed(follower)
                        # be more aggressive so follower closes gap quickly
                        trig_sp = max(cur_sp * 1.5, 15.0)
                        traci.vehicle.setSpeed(follower, float(trig_sp))
                    except Exception:
                        pass

                    logger.info(f"Forced collision injection: leader={leader}, follower={follower}, road={road}")
                    collision_injected = True
                    return True
                except Exception:
                    # try next candidate
                    continue
        except Exception:
            return False
        return False
    
    last_send = None; current_sec = 0
    send_int, sim_speeds = [], []
    # ... rest of containers ...

    last_send = None;   current_sec = 0
    send_int, sim_speeds = [], []
    start_rec_sent = False
    start_sim_t = start_wall_t = None
    rtf_started  = False; last_sim, last_wall = 0, 0

    # ---------- warm-up ----------
    while traci.simulation.getTime() < IntegrationStartTime:
        traci.simulationStep(); cam_follow("View #0", ego) if use_gui else None

    # ---------- main loop ----------
    STEP = steplength
    next_step = time.perf_counter() + STEP
    TL_INT = 1.0; last_tl_t = 0.0

    # ThingsBoard telemetry controls
    SEND_INTERVAL = 1.0  # seconds between telemetry updates (simulation time)
    last_tb_send = -9999.0

    try:
        while traci.simulation.getMinExpectedNumber() > 0 \
              and traci.simulation.getTime() < ExperimentEndTime:

            # --- loop timing
            loop_t0 = time.perf_counter()
            sim_t = traci.simulation.getTime()

            # --- Q-LEARNING EXECUTION (per-step)
            current_simulation_step += 1

            # ❶ RL: STATE OBSERVATION, DECISION & ACTION
            old_state = get_state()
            action = get_action_from_policy(old_state)
            apply_action(action) # Changes traffic light phase in SUMO

            # ❷ Unity → SUMO positions (Original code)
            t0 = time.perf_counter()
            while not u_q.empty():
                for v in u_q.get().get("vehicles", []):
                    if v["vehicle_id"] == ego:
                        traci.vehicle.moveToXY(ego,"",0,
                            float(v["position"][0]), float(v["position"][1]),
                            float(v["angle"]), keepRoute=2)
            prof["Unity"].append(time.perf_counter()-t0)

            # ❸ SUMO step (This advances time, applying the RL action set above)
            t0 = time.perf_counter(); traci.simulationStep()
            prof["Step"].append(time.perf_counter()-t0)
            if use_gui: cam_follow("View #0", ego)

            # --- RL: UPDATE Q-TABLE ---
            new_state = get_state()
            reward = get_reward(new_state)
            update_Q_table(old_state, action, reward, new_state)
            # ------------------------------------

            # ❹ send START_RECORDING after warm-up (independent of RTF)
            if sim_t >= ExperimentStartTime and not start_rec_sent:
                pub.send_string(json.dumps(
                    {"type":"command","command":"START_RECORDING"}))
                start_rec_sent = True

            # ❺ initialise RTF after warm-up (only if enabled)
            if calc_rtf and (not rtf_started) and sim_t >= ExperimentStartTime:
                rtf_started = True
                start_sim_t  = sim_t
                start_wall_t = time.perf_counter()
                last_sim, last_wall = sim_t, start_wall_t

            # ❻ collect ego + context vehicles
            t0 = time.perf_counter()
            vlist = traci.vehicle.getIDList()
            vdata = []
            if ego in vlist: # START Original vehicle collection code
                x,y,z   = traci.vehicle.getPosition3D(ego)
                ang     = traci.vehicle.getAngle(ego)
                vtype   = traci.vehicle.getTypeID(ego)
                vdata.append({"vehicle_id":ego,
                              "position":(round(x,2),round(y,2),round(z,2)),
                              "angle":round(ang,2),"type":vtype,
                              "timestamp":round(time.time(),2)})
                ctx_res = traci.vehicle.getContextSubscriptionResults(ego)
                if ctx_res:
                    for vid in ctx_res.keys():
                        if vid==ego: continue
                        x,y,z = traci.vehicle.getPosition3D(vid)
                        ang   = traci.vehicle.getAngle(vid)
                        vtype = traci.vehicle.getTypeID(vid)
                        vlong = traci.vehicle.getSpeed(vid)
                        vlat  = traci.vehicle.getLateralSpeed(vid)
                        if vid in last_pos_z:
                            pz,pt = last_pos_z[vid]; dt=sim_t-pt
                            vvert = (z-pz)/dt if dt>0 else 0.0
                        else: vvert=0.0
                        last_pos_z[vid]=(z,sim_t)
                        vdata.append({"vehicle_id":vid,
                                      "position":(round(x,3),round(y,3),round(z,3)),
                                      "angle":round(ang,3),"type":vtype,
                                      "long_speed":round(vlong,2),
                                      "vert_speed":round(vvert,3),
                                      "lat_speed":round(vlat,2)})
            # END Original vehicle collection code
            vjson = json.dumps({"type":"vehicles","vehicles":vdata},
                               separators=(',',':'))
            prof["Collect"].append(time.perf_counter()-t0)

            # --- Automatic collision injection trigger (one-time) ---
            try:
                # Trigger as soon as there are at least two non-ego vehicles present
                if (not collision_injected):
                    # vlist was collected above
                    non_ego_count = sum(1 for vid in vlist if vid != ego)
                    if non_ego_count >= 2:
                        try_force_collision()
            except Exception:
                # don't let injection errors stop simulation
                pass

            # ❼ traffic lights once per second (Original code)
            if sim_t-last_tl_t >= TL_INT:
                tls = [{"junction_id":tl,
                        "state":traci.trafficlight.getRedYellowGreenState(tl)}
                       for tl in traci.trafficlight.getIDList()]
                pub.send_string(json.dumps({"type":"trafficlights","lights":tls},
                                           separators=(',',':')))
                last_tl_t = sim_t

            # ❽ publish vehicles (Original code)
            t0 = time.perf_counter(); pub.send_string(vjson)
            prof["Send"].append(time.perf_counter()-t0)

            # ❾ incremental RTF (if enabled)
            if calc_rtf and rtf_started and sim_t >= ExperimentStartTime:
                now = time.perf_counter()
                if sim_t == ExperimentStartTime:
                    rtf_f.write("0.00;0.00\n")
                else:
                    sim_d  = sim_t - last_sim
                    real_d = now   - last_wall
                    rtf_f.write(f"{sim_t-ExperimentStartTime:.2f};{sim_d/real_d:.2f}\n")
                last_sim, last_wall = sim_t, now

            # --- Telemetry (rate-limited by SEND_INTERVAL in sim time) ---
            try:
                if sim_t - last_tb_send >= SEND_INTERVAL:
                    #13.347312937036158, 74.7841435058439
                    lat, lon = 13.347312937036158, 74.7841435058439
                    phase_color = traci.trafficlight.getRedYellowGreenState(TLS_ID)
                    phase_index = traci.trafficlight.getPhase(TLS_ID)
                    detectors_payload = {
                        "EB": [get_queue_length(d) for d in DETECTORS_EB],
                        "WB": [get_queue_length(d) for d in DETECTORS_WB],
                        "NB": [get_queue_length(d) for d in DETECTORS_NB],
                        "SB": [get_queue_length(d) for d in DETECTORS_SB],
                    }
                    totals_payload = {
                        "EB": sum(get_queue_length(d) for d in DETECTORS_EB),
                        "WB": sum(get_queue_length(d) for d in DETECTORS_WB),
                        "NB": sum(get_queue_length(d) for d in DETECTORS_NB),
                        "SB": sum(get_queue_length(d) for d in DETECTORS_SB),
                    }
                    total_queue = sum(get_queue_length(d) for d in ALL_DETECTORS)
                    num_vehicles = len(traci.vehicle.getIDList())  # all active vehicles in network
                    avg_wait_time = (float)(total_queue / num_vehicles) if num_vehicles > 0 else 0
                    payload = {
                        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                        "junction_id": TLS_ID,
                        "latitude": lat,         # 👈 required for map
                        "longitude": lon,
                        "sim_time": sim_t,
                        "phase_index": phase_index,
                        "phase_color": phase_color,
                        "detectors": detectors_payload,
                        "totals": totals_payload,
                        "total_EB": totals_payload["EB"],
                        "total_WB": totals_payload["WB"],
                        "total_NB": totals_payload["NB"],
                        "total_SB": totals_payload["SB"],
                        "total_queue": sum(get_queue_length(d) for d in ALL_DETECTORS),
                        "avg_wait_time": avg_wait_time, 
                        "reward": reward,
                        "action": "switch" if action == 1 else "keep",
                        "phase_duration_steps": current_simulation_step - last_switch_step
                    }
                    telemetry_log.append(payload) 
                    print(payload)
                    try:
                        tb_queue.put_nowait(payload)
                    except queue.Full:
                        logger.warning("ThingsBoard queue full; dropping telemetry")
                    last_tb_send = sim_t
            except Exception:
                logger.exception("Telemetry collection error")

            # ❿ step pacing (preserve original precise pacing)
            sleep_precise(max(0.0, next_step - time.perf_counter()))
            next_step += STEP
            prof["Total"].append(time.perf_counter()-loop_t0)

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        # Final Q-Table status:
        try:
            logger.info(f"Q-Learning Training completed. Final Q-table size: {len(Q_table)}")
        except Exception:
            pass
        try:
            zmq_stop.set() # <--- NEW: Stop the ZMQ receiver thread first
        except Exception:
            pass
        try:
            generate_plots(telemetry_log)
        except Exception as e:
            logger.error(f"Error generating plots: {e}")
        # --- final save ---
        try:
            with open(QTABLE_PATH, "wb") as f:
                pickle.dump(Q_table, f)
            logger.info(f"Final Q-table saved with {len(Q_table)} states to {QTABLE_PATH}")
        except Exception as e:
            logger.warning(f"Failed to save final Q-table: {e}")

        # overall RTF
        if calc_rtf and rtf_started:
            try:
                total_w   = time.perf_counter() - start_wall_t
                total_sim = traci.simulation.getTime() - start_sim_t
                if total_w>0: logger.info("RTF overall %.2f", total_sim/total_w)
            except Exception:
                pass
        if start_rec_sent:
            pub.send_string(json.dumps({"type":"command","command":"STOP_RECORDING"}))
        if rtf_f: rtf_f.close()
        try:
            traci.close()
        except Exception:
            pass
        try:
            pub.close(); rout.close(); ctx.term()
        except Exception:
            pass
        logger.info("Finished, connections closed.")
        # stop tb thread gracefully (daemon will exit on program end)
        try:
            tb_stop.set()
        except Exception:
            pass

# ═════════════════════ GUI → START BTN ═════════════════════════
def start_clicked():
    try:
        cfg = {k: (int(v.get()) if "Time" in k else float(v.get()))
               for k,v in entries.items()}
        cfg["use_gui"]  = bool(use_gui_var.get())
        cfg["calc_rtf"] = bool(rtf_var.get())
        cfg["free_cam"] = bool(free_cam_var.get())          # ★ NEW
        cfg["enable_collision_flags"] = bool(collision_flags_var.get())
    except ValueError:
        messagebox.showerror("Invalid input","Please enter numeric values.")
        return
    root.destroy(); run_sim(cfg)

# buttons
ttk.Button(root,text="Help",command=show_help)        .grid(row=row,column=0,pady=12,padx=6,sticky="w")
ttk.Button(root,text="Contact / License",command=show_contact)\
                                                     .grid(row=row,column=1,pady=12,padx=6,sticky="w")
ttk.Button(root,text="Publications",command=show_pubs)\
                                                     .grid(row=row,column=2,pady=12,padx=6,sticky="w")
ttk.Button(root,text="Start simulation",command=start_clicked)\
                                                     .grid(row=row,column=3,pady=12,padx=6,sticky="e")

root.update_idletasks()
root.geometry("+{}+{}".format((root.winfo_screenwidth()-root.winfo_width())//2,
                              (root.winfo_screenheight()-root.winfo_height())//2))
root.mainloop()
