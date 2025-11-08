# P.R.I.S.M.-Predictive-Real-time-Intersection-Surveillance-Management-

# P.R.I.S.M.: Predictive Real-time Intersection Surveillance & Management

<p align="center">
  <img src="https://img.shields.io/badge/Version-v2.0.0-blue.svg" alt="Version 2.0.0">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License MIT">
  <img src="https://img.shields.io/badge/Language-Python%20%7C%20C%23-informational" alt="Language Python | C#">
</p>

**P.R.I.S.M.** is a novel, open-source framework for traffic research that integrates the **SUMO** traffic simulation, the **Unity 3D** environment, and the **ThingsBoard** IoT platform. It utilizes Q-Learning to implement a dynamic, adaptive Traffic Light Signal (TLS) control system, simulating a complete Cyber-Physical System (CPS) for urban intersection management.

---

## ✨ Key Features

* **Cyber-Physical Co-simulation:** Synchronous bidirectional coupling between **SUMO** (physics and control core) and **Unity** (3D visualization and Human-in-the-Loop input).
* **Adaptive Traffic Control:** Implements a **Q-Learning** Reinforcement Learning (RL) agent within the simulation loop to dynamically optimize traffic signal phases based on real-time queue lengths.
* **IoT Visualization:** Real-time telemetry data (queue lengths, agent reward, waiting time, and GPS location) is pushed to the **ThingsBoard** cloud dashboard.
* **ESP32 Gateway Simulation:** The Python script models the resilient communication architecture of a low-power **ESP32** device, featuring asynchronous HTTP batching and retry logic for reliable data transmission.
* **Performance Monitoring:** Calculates and logs the **Real-Time Factor (RTF)** to ensure the simulation maintains synchronized, predictable execution speed.

---

## 🏗️ System Architecture

P.R.I.S.M. is built on a three-tiered architecture that separates simulation, visualization, and cloud telemetry:

### 1. Simulation and Control Layer (SUMO / Q-Learning)
* **Role:** Maintains the ground truth state of the road network, runs the traffic flow models, and executes the Q-Learning algorithm to determine the optimal action (`keep` or `switch`) for the target intersection (J1).
* **Telemetry:** Collects sensor data (queue lengths from 12 detectors), calculates performance metrics (reward, average waiting time), and packages them for transmission.

### 2. Visualization and HIL Layer (Unity)
* **Role:** Provides a high-fidelity 3D rendering of the traffic scene for visualization, vehicle tracking, and potential Human-in-the-Loop (HIL) studies (controlling the ego vehicle).
* **Communication:** Uses **ZeroMQ (ZMQ)** for low-latency, real-time message passing with SUMO (PUB on `5556` and ROUTER on `5557`).

### 3. IoT Telemetry Layer (Virtual ESP32 / ThingsBoard)
* **Role:** Receives processed telemetry data from the SUMO script and pushes it to the cloud for external monitoring.
* **Mechanism:** An independent Python thread mimics an **ESP32 IoT gateway**, managing a queue and implementing HTTP POST requests to the ThingsBoard REST API using batching and exponential backoff for fault tolerance.

---

## 🚦 Q-Learning Agent Configuration

The Q-Learning agent is configured to maximize traffic flow efficiency at the intersection (`TLS_ID = "J1"`).

| Parameter | Value | Description |
| :--- | :--- | :--- |
| **State Space** | 13 elements | 12 detector queue lengths + 1 current phase index. |
| **Action Space** | [0, 1] | 0 = Keep Current Phase; 1 = Switch Phase. |
| **Reward ($R$)** | $-1 \times (\sum \text{Queue Lengths})$ | The agent maximizes the reward by minimizing the total queue length. |
| **Discount ($\Gamma$)** | 0.9 | High discount factor prioritizes long-term traffic flow benefits. |
| **Exploration ($\epsilon$)** | 0.1 | Maintains a 10\% chance of random action to explore better control strategies. |
| **Constraint** | Minimum Green Time (100 steps) | Prevents rapid, unstable phase switching. |

---

## 📈 Dashboard Metrics

The following critical traffic and control metrics are pushed to the ThingsBoard dashboard for visualization:

| Metric (Telemetry Key) | Widget Type | Purpose |
| :--- | :--- | :--- |
| `latitude`, `longitude` | Map Widget | Pinpoints the intersection location. |
| `reward` | Line Graph | Tracks the agent's learning convergence. |
| `avg_wait_time` | Line Graph | Key KPI for overall intersection efficiency. |
| `total_EB/WB/NB/SB` | Time Series Graph | Visualizes demand imbalance and queue management. |
| `action` | Card/Indicator | Displays the agent's last decision ("switch" or "keep"). |
| `phase_color` | Card/Indicator | Shows the current, detailed traffic light state string. |

---

## 🚀 Getting Started

### Prerequisites

1.  **SUMO** (`sumo-gui` and `sumo` binaries) must be installed, and the `SUMO_HOME` environment variable must be set.
2.  **Unity** project setup with the corresponding ZMQ client logic.
3.  **Python 3.x** and required libraries:
    ```bash
    pip install pyzmq requests pillow numpy matplotlib
    ```

### ThingsBoard Setup

1.  Create a device on ThingsBoard and obtain its **Device Access Token**.
2.  Set the `TB_DEVICE_TOKEN` environment variable, or manually replace `"YOUR_DEVICE_TOKEN"` in the Python script (around line 40).

### Running the Co-simulation

1.  **Start the Unity Client:** Launch the Unity application to begin sending the ego-vehicle control signals and preparing to receive vehicle state data.
2.  **Start the Python Tool:** Run the main script. The Tkinter GUI will appear, allowing configuration of simulation parameters (start/end times, step length, etc.).
    ```bash
    python Sumo2UnityTool_combined.py
    ```
3.  **Start Simulation:** Click the **"Start simulation"** button. This launches SUMO (with or without GUI, depending on settings) and initiates the Q-Learning, TraCI communication, and asynchronous telemetry threads.
4.  **Monitor:** View real-time traffic statistics, agent actions, and performance trends on your configured ThingsBoard dashboard.

---

## ✍️ Contact and License

This project is maintained by:

**Ahmad Mohammadi, PhD**
* **LinkedIn:** [ahmadmohammadi1441](https://www.linkedin.com/in/ahmadmohammadi1441/)

This project is licensed under the **MIT License**. See the repository for details.
