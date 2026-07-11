# Scenario2 Detailed Reference

Last updated: 2026-04-04
Scope: Scenario2 folder only

## 1) Purpose of this folder
This folder contains a complete SUMO scenario plus Python controllers used to run SUMO-TraCI-Unity co-simulation, including RL and fixed-timing variants.

Main capabilities in this folder:
- Start and control SUMO with TraCI.
- Exchange vehicle and traffic light states with Unity through ZeroMQ.
- Run traffic signal control strategies (Q-learning, fixed-timing, DQN experiment).
- Generate outputs such as Q-table, graphs, and logs.

## 2) Important quick start
Prerequisites:
- SUMO installed and SUMO_HOME environment variable set.
- Unity project open separately (same repository root).
- Python 3.11+ recommended.

Python packages used by scripts in this folder:
- traci
- numpy
- matplotlib
- pyzmq
- pillow
- requests
- tensorflow (only for traci7.DQL.py)

Suggested run order for current workflow:
1. Open Unity project and scene used by simulation.
2. Run Sumo2UnityTool_combined.py from this folder.
3. In GUI, set integration and experiment times, then click Start simulation.
4. Review generated outputs:
   - Scenario2/Results images
   - root Results rtf report
   - Scenario2/Q_table.pkl

## 3) File-by-file catalog

### Core control scripts
- Sumo2UnityTool_combined.py
  - Primary orchestration script (747 lines).
  - Provides Tkinter GUI and starts SUMO with TraCI.
  - Controls traffic light J1 via Q-learning (12 detector state + current phase).
  - Publishes traffic lights and vehicle snapshots on ZMQ PUB tcp://*:5556.
  - Receives Unity updates on ZMQ ROUTER tcp://*:5557.
  - Sends telemetry payloads (queue, reward, phase, waiting stats) to ThingsBoard HTTP endpoint.
  - Autosaves RL table to Q_table.pkl.
  - Generates 3 plots in Scenario2/Results.
  - Can optionally write RTF report to root Results/rtf_report.txt.

- Sumo2UnityTool_combined_FT.py
  - Variant controller (539 lines) with optional fixed-timing mode.
  - Similar GUI and integration behavior to the main combined script.
  - Supports disabling RL and forcing fixed phase durations.
  - Uses same ZMQ channels and telemetry style.

- netmq_bridge.py
  - Dedicated bridge script (145 lines) to connect RL-controlled SUMO and Unity.
  - Connects TraCI on port 54078.
  - Opens ZMQ PUB 5556 and ROUTER 5557.
  - Forwards vehicle and traffic light updates to Unity, receives ego updates from Unity.
  - Important note: function create_sumo_data_json references TLS_ID but TLS_ID is not defined in this file. This must be fixed before reliable use.

### RL experiment scripts
- traci5.FT.py
  - Fixed-timing baseline style experiment (201 lines).
  - Starts SUMO and records cumulative reward and queue trend plots.
  - Action policy currently effectively keeps phase in sampled code segment.

- traci6.QL.py
  - Tabular Q-learning experiment script (250 lines).
  - Uses 12 detector queue values plus phase in state representation.
  - Prints sampled Q-table states and plots reward and queue trends.

- traci7.DQL.py
  - DQN experiment script (241 lines).
  - Uses TensorFlow/Keras model for Q-value approximation.
  - Saves model weights to dqn_traffic_model_weights.h5.

- traci8.SUMO-QL.py
  - Q-learning experiment variant (256 lines).
  - Uses 12 detector queues and phase in state, logs training progress and visualizations.

### Scenario and network files
- Sumo2Unity.sumocfg
  - Main SUMO runtime config.
  - References:
    - Sumo2Unity.net.xml
    - Sumo2Unity.rou.xml
    - Sumo2Unity.Poly.xml

- Sumo2Unity.net.xml
  - Road network definition generated from SUMO tools.

- Sumo2Unity.netecfg
  - Netedit configuration used to edit/regenerate scenario network settings.

- Sumo2Unity.rou.xml
  - Vehicle types and demand definitions.
  - Includes flows and ego trip f_0.0 departing at 540s.

- Sumo2Unity.Poly.xml
  - Additional polygon/map context for SUMO visualization.

### Detector output files (E2)
These files store interval statistics exported by SUMO E2 detectors. They represent sampled queue and occupancy measures over time windows.

- e2_0.xml: Node1_2_EB_0 and Node2_7_SB_0 intervals.
- e2_1.xml: Node1_2_EB_1 and Node2_7_SB_1 intervals.
- e2_2.xml: Node1_2_EB_2 and Node2_7_SB_2 intervals.
- e2_6.xml: Node2_3_WB_1 intervals.
- e2_7.xml: Node2_3_WB_0 intervals.
- e2_8.xml: Node2_3_WB_2 intervals.
- e2_9.xml: Node2_5_NB_0 intervals.
- e2_10.xml: Node2_5_NB_1 intervals.
- e2_11.xml: Node2_5_NB_2 intervals.

### Binary, model, log, and temporary files
- Sumo2UnityTool.exe
  - Packaged executable build of tool (~31.4 MB).

- Q_table.pkl
  - Serialized RL Q-table used by combined script and Q-learning workflows.
  - Reused across runs to continue learning state values.

- sumo_start.log
  - SUMO startup and performance log from a sample run.
  - Example run ended at sim time 368 with high UPS/RTF metrics.

- tempCodeRunnerFile.py
  - Temporary editor artifact (1 line). Safe to remove.

- __pycache__/Sumo2UnityTool_combined.cpython-311.pyc
  - Python bytecode cache file.

### Results subfolder
- Results/Avg_Waiting_Time_Graph.png
- Results/Q_Learning_Reward_Graph.png
- Results/Queue_Length_TimeSeries.png

These are performance graphs generated from telemetry collected by Sumo2UnityTool_combined.py.

## 4) Data flow summary
Primary live data loop in combined scripts:
1. Unity sends ego updates to ZMQ ROUTER 5557.
2. Python controller applies ego movements in SUMO via TraCI.
3. Python controller steps SUMO and reads vehicles, detectors, and traffic lights.
4. Python publishes vehicle and traffic light snapshots to ZMQ PUB 5556 for Unity.
5. Controller computes RL decision (or fixed timing), updates policy, and logs telemetry.
6. Telemetry optionally sent to ThingsBoard via HTTP.

## 5) Outputs and where they are written
- Scenario2/Q_table.pkl
  - RL table persistence.

- Scenario2/Results/*.png
  - Reward, average wait time, and queue time-series graphs.

- ../Results/rtf_report.txt
  - RTF report when Calculate RTF is enabled in GUI.
  - Note: this path is repository root Results folder, not Scenario2/Results.

## 6) Known issues and caution notes
- netmq_bridge.py uses TLS_ID without local definition.
- Several scripts include placeholder ThingsBoard credentials and host values; these must be configured before cloud telemetry is expected to work.
- Detector files are output snapshots and may represent historical runs, not current scenario after edits.
- tempCodeRunnerFile.py is non-functional temporary file.

## 7) Maintenance recommendations
- Keep only one primary runner for production use (recommended: Sumo2UnityTool_combined.py).
- Archive or label experiment scripts traci5-8 clearly as research variants.
- Add a small requirements file for Scenario2 Python dependencies.
- Add a short run script that sets env checks and starts the primary runner.
- Remove temporary files before sharing or release.

## 8) Minimal command examples
From Scenario2 folder:

- Run primary tool:
  python Sumo2UnityTool_combined.py

- Run fixed timing variant:
  python Sumo2UnityTool_combined_FT.py

- Run Q-learning experiment script:
  python traci6.QL.py

- Run DQN experiment script:
  python traci7.DQL.py

If SUMO_HOME is missing, scripts will terminate with environment setup error.