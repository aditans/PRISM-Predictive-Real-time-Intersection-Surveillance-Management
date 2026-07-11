using UnityEngine;
using System.Collections;
using System.Collections.Generic;
using System;
using System.Linq;
using System.Threading;
using System.Collections.Concurrent;
using System.IO;
using System.Text;

public class SimulationController : MonoBehaviour
{
    private ExchangeData _ExchangeData;
    private GameObject vehiclePrefab;
    private Dictionary<string, GameObject> vehicleObjects = new Dictionary<string, GameObject>();
    private string vehicleDataJson = "{}";
    private object vehicleDataLock = new object();
    private string egoVehicleId = "f_0.0";
    public GameObject egoVehicle;
    private GameObject f_1_0;
    private Vector3 previousPosition;
    private Vector3 currentPosition;
    private float long_speed;
    private float distanceAccumulator = 0f;
    private float timeAccumulator = 0f;
    private readonly ConcurrentQueue<Action> mainThreadActions = new ConcurrentQueue<Action>();
    public Vector3 egoVehicleInitialPosition = new Vector3(0f, 0f, 0f);
    public Quaternion egoVehicleInitialRotation = Quaternion.Euler(0f, 90f, 0f);

    private StreamWriter writer;

    [Header("Unity Step Length (seconds)")]
    public float unityStepLength = 0.10f;

    private float fixedTimeAccum = 0f; // Accumulator for FixedUpdate logging

    // New variables for timestamp offset
    private bool firstTimestampLogged = false;
    private float firstLoggedTime = 0f;

    // ‑‑‑‑ NEW: traffic‑light handling ‑‑‑‑
    [Header("Add all Junction GameObjects")]
    public GameObject junctions;           // drag ‘Junctions’ root here
    private readonly Dictionary<string, GameObject> junctionCache = new();

    [Header("Accident Event UI / FX")]
    public GameObject accidentExplosionPrefab;
    public GameObject accidentSmokePrefab;
    public float accidentExplosionDuration = 3f;
    public float accidentSmokeDuration = 10f;
    [Range(0f, 1f)]
    public float accidentSfxVolume = 0.9f;
    public float accidentSfxMaxDistance = 90f;
    public AudioClip[] accidentSfxClips;
    public float accidentBannerDuration = 4f;
    public bool showAccidentIndicator = true;
    public float accidentIndicatorDuration = 20f;
    private string accidentBannerText = string.Empty;
    private float accidentBannerUntil = -1f;
    private Vector3 accidentIndicatorWorldPos = Vector3.zero;
    private float accidentIndicatorUntil = -1f;

    [Serializable]
    public class Vehicle
    {
        public string vehicle_id;
        public double[] position;
        public double angle;
        public string type;
        public float long_speed;
        public float vert_speed;
        public float lat_speed;
    }

    private static bool HasValidBodyCollider(GameObject go)
    {
        var cols = go.GetComponentsInChildren<Collider>(includeInactive: true);
        foreach (var col in cols)
        {
            if (col is WheelCollider) continue;
            // MeshCollider without mesh is invalid
            if (col is MeshCollider mc && mc.sharedMesh == null) continue;
            // Trigger colliders don't block
            if (col.isTrigger) continue;
            return true;
        }
        return false;
    }

    private static void EnsureBodyCollider(GameObject go)
    {
        // Disable trigger on any existing non-wheel collider
        foreach (var col in go.GetComponentsInChildren<Collider>(includeInactive: true))
        {
            if (col is WheelCollider) continue;
            col.isTrigger = false;
        }

        var renderers = go.GetComponentsInChildren<Renderer>(includeInactive: true);
        if (renderers == null || renderers.Length == 0)
        {
            var bc = go.GetComponent<BoxCollider>();
            if (bc == null) bc = go.AddComponent<BoxCollider>();
            bc.isTrigger = false;
            return;
        }
        var bounds = renderers[0].bounds;
        for (int i = 1; i < renderers.Length; i++) bounds.Encapsulate(renderers[i].bounds);
        var root = go.transform;
        var centerWS = bounds.center;
        var sizeWS = bounds.size;
        var centerLS = root.InverseTransformPoint(centerWS);
        var bcFinal = go.GetComponent<BoxCollider>();
        if (bcFinal == null) bcFinal = go.AddComponent<BoxCollider>();
        bcFinal.center = centerLS;
        bcFinal.size = new Vector3(
            Mathf.Abs(sizeWS.x / Mathf.Max(root.lossyScale.x, 0.0001f)),
            Mathf.Abs(sizeWS.y / Mathf.Max(root.lossyScale.y, 0.0001f)),
            Mathf.Abs(sizeWS.z / Mathf.Max(root.lossyScale.z, 0.0001f))
        );
        bcFinal.isTrigger = false;
    }

    private static void EnsureMeshBodyCollider(GameObject go)
{
    // If a valid non-wheel MeshCollider already exists, do nothing
    foreach (var mc in go.GetComponentsInChildren<MeshCollider>(includeInactive: true))
    {
        if (mc.sharedMesh != null && mc.convex)
            return;
    }

    // Find the visual body mesh
    MeshFilter mf = go.GetComponentInChildren<MeshFilter>();
    if (mf == null || mf.sharedMesh == null)
    {
        Debug.LogWarning($"[{go.name}] No MeshFilter found for MeshCollider");
        return;
    }

    // Add MeshCollider to the SAME object as the mesh
    MeshCollider meshCol = mf.gameObject.AddComponent<MeshCollider>();
    meshCol.sharedMesh = mf.sharedMesh;
    meshCol.convex = true;              // REQUIRED for Rigidbody
    meshCol.isTrigger = false;
}


    [Serializable]
    private class VehicleWrapper
    {
        public Vehicle[] vehicles;
    }

    [Serializable]
    public class TrafficLight
    {
        public string junction_id;
        public string state;
    }

    [Serializable]
    public class AccidentMessage
    {
        public string type;
        public string @event;
        public string message;
        public float sim_time;
        public string[] vehicle_ids;
        public float[] position;
    }

    [Serializable]
    private class TrafficLightsWrapper
    {
        public TrafficLight[] lights;
    }

    [System.Serializable]
    public class CarModel
    {
        public string sumoVehicleType;
        public GameObject unityVehiclePrefab;
    }

    [Header("Add Unity Vehicle Prefab (3DModel) according to Sumo Vehicle Type")]
    public List<CarModel> carModelsList = new List<CarModel>();

    // ── new fields ─────────────────────────────────────────────
    /// last time we processed a TL message
    private float _lastTlTime = 0f;
    /// minimum seconds between TL updates
    private float tlUpdateInterval = 1f;

    /// cache last seen state per junction
    private Dictionary<string, string> _lastTlState = new();

    /// <summary>Finds (or creates) SUMO2Unity\SUMOData\Results next to the project.</summary>
    /// <summary>Finds (or creates) SUMO2Unity\Results next to the project.</summary>
    private static string LocateOrCreateResultsFolder()
    {
        // projectRoot = folder that *contains* "Assets"
        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        DirectoryInfo dir = new DirectoryInfo(projectRoot);

        while (dir != null)
        {
            string candidate = Path.Combine(dir.FullName, "Results");
            if (Directory.Exists(candidate))
                return candidate;

            dir = dir.Parent;                       // walk upward
        }

        // Not found – create it next to the project
        string fallback = Path.Combine(projectRoot, "Results");
        Directory.CreateDirectory(fallback);
        return fallback;
    }

    private void Start()
    {
        vehiclePrefab = Resources.Load("EloraGold") as GameObject;

        if (vehiclePrefab == null)
        {
            Debug.LogError("Vehicle prefab 'EloraGold' not found in Resources.");
            return;
        }

        _ExchangeData = GetComponent<ExchangeData>();
        if (_ExchangeData == null)
        {
            _ExchangeData = gameObject.AddComponent<ExchangeData>();
        }

        SumoRequesterStart();
        //StartCoroutine(FindGameObjectAfterDelay(1.0f));

        // 3) open log file in SUMOData folder
        string sumoDataDir = LocateOrCreateResultsFolder();
        string logPath = Path.Combine(sumoDataDir, "vehicle_data_report.txt");
        writer = new StreamWriter(logPath, append: false, Encoding.UTF8);
        writer.WriteLine("timestep_time;vehicle_id;vehicle_x;vehicle_y;vehicle_z");
    }

    public void SumoRequesterStart()
    {
        if (egoVehicle == null)
        {
            Debug.LogError("Ego vehicle GameObject is not assigned.");
            return;
        }

        Vector3 initialPosition = egoVehicleInitialPosition;
        Quaternion initialRotation = egoVehicleInitialRotation;
        egoVehicle = GameObject.Instantiate(egoVehicle, initialPosition, initialRotation);
        egoVehicle.name = egoVehicleId;
        vehicleObjects.Add(egoVehicleId, egoVehicle);

        // Add number plate to ego vehicle
        egoVehicle.AddComponent<NumberPlate>();

        // Ensure a valid body collider exists on the ego (non-wheel, non-trigger, valid mesh)
        if (!HasValidBodyCollider(egoVehicle))
        {
            ForceAddMeshColliders(egoVehicle);


        }
        // Force any MeshColliders to convex
        foreach (var mc in egoVehicle.GetComponentsInChildren<MeshCollider>(includeInactive: true)) mc.convex = true;
        var egoRb = egoVehicle.GetComponent<Rigidbody>();
        if (egoRb == null) egoRb = egoVehicle.AddComponent<Rigidbody>();
        egoRb.isKinematic = false;
        egoRb.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
        egoRb.interpolation = RigidbodyInterpolation.Interpolate;
        egoRb.detectCollisions = true;
        var egoMeshCols = egoVehicle.GetComponentsInChildren<MeshCollider>(includeInactive: true);
        foreach (var mc in egoMeshCols) mc.convex = true;
    }

    void Update()
    {
        try
        {
            string data = CollectVehicleData();
            lock (vehicleDataLock)
            {
                vehicleDataJson = data;
            }

            while (mainThreadActions.TryDequeue(out var action))
            {
                action();
            }
        }
        catch (Exception ex)
        {
            Debug.LogError($"Exception in Update(): {ex.Message}\n{ex.StackTrace}");
        }
    }

    private void FixedUpdate()
    {
        // Only log if we have started and not stopped recording
        if (!RecordingManager.startRecordingFromZero)
        {
            return;
        }

        fixedTimeAccum += Time.fixedDeltaTime;
        if (fixedTimeAccum >= unityStepLength - 0.002)
        {
            float currentTime = Time.fixedTime;

            // If this is the first timestamp we log, record it as the start
            if (!firstTimestampLogged)
            {
                firstLoggedTime = currentTime;
                firstTimestampLogged = true;
            }

            // Log time adjusted by first logged time
            float logTime = currentTime - firstLoggedTime;
            LogVehicleData(logTime);
            fixedTimeAccum = 0f;
        }

    }

    private void LogVehicleData(float relativeLogTime)
    {
        foreach (var kvp in vehicleObjects)
        {
            string vehicleId = kvp.Key;
            GameObject vehicleObj = kvp.Value;
            Vector3 pos = vehicleObj.transform.position;
            writer.WriteLine($"{relativeLogTime:F3};{vehicleId};{pos.x:F2};{pos.y:F2};{pos.z:F2}");
        }
    }

    private void OnDestroy()
    {
        if (writer != null)
        {
            writer.Flush();
            writer.Close();
            writer = null;
        }
    }

    public void EnqueueMainThreadAction(Action action)
    {
        mainThreadActions.Enqueue(action);
    }

    public string CollectVehicleData()
    {
        if (!vehicleObjects.ContainsKey(egoVehicleId))
        {
            UnityEngine.Debug.LogWarning("Ego vehicle not found. Sending empty JSON.");
            return "{}";
        }

        GameObject egoVehicle = vehicleObjects[egoVehicleId];
        var rb = egoVehicle.GetComponent<Rigidbody>();
        long_speed = rb.linearVelocity.magnitude;

        Vector3 position = egoVehicle.transform.position;
        float unroundangle = egoVehicle.transform.rotation.eulerAngles.y;
        double angle = Math.Round(unroundangle, 2);
        double x = Math.Round(position.x, 2);
        double y = Math.Round(position.z, 2);
        double z = Math.Round(position.y, 2);
        string type = "ego";

        float vertical_speed = (float)Math.Round(rb.linearVelocity.y, 2);
        float lateral_speed = (float)Math.Round(rb.linearVelocity.z, 2);

        Vehicle egoVehicleData = new Vehicle();
        egoVehicleData.vehicle_id = egoVehicleId;
        egoVehicleData.position = new double[] { x, y, z };
        egoVehicleData.angle = angle;
        egoVehicleData.type = type;
        egoVehicleData.long_speed = (float)Math.Round(long_speed, 2);
        egoVehicleData.vert_speed = vertical_speed;
        egoVehicleData.lat_speed = lateral_speed;

        string jsonData = JsonHelper.ToJson(new Vehicle[] { egoVehicleData });
        return jsonData;
    }

    public string GetVehicleDataJson()
    {
        lock (vehicleDataLock)
        {
            return vehicleDataJson;
        }
    }
    private static void ForceAddMeshColliders(GameObject go)
{
    MeshFilter[] meshes = go.GetComponentsInChildren<MeshFilter>(true);

    if (meshes == null || meshes.Length == 0)
    {
        Debug.LogError($"[{go.name}] No MeshFilters found!");
        return;
    }

    foreach (var mf in meshes)
    {
        if (mf.sharedMesh == null) continue;

        string n = mf.gameObject.name.ToLower();

        // Skip wheels & glass & lights
        if (n.Contains("wheel") || n.Contains("glass") || n.Contains("light"))
            continue;

        MeshCollider mc = mf.gameObject.GetComponent<MeshCollider>();
        if (mc == null)
        {
            mc = mf.gameObject.AddComponent<MeshCollider>();
        }

        mc.sharedMesh = mf.sharedMesh;
        mc.convex = true;
        mc.isTrigger = false;
    }

    Debug.Log($"[{go.name}] MeshColliders added to {meshes.Length} meshes");
}


    public void HandleMessage(string message)
    {
        CommonMessage common = JsonUtility.FromJson<CommonMessage>(message);

        if (common == null || string.IsNullOrEmpty(common.type))
        {
            Debug.LogError("Received message with no type field or invalid JSON.");
            return;
        }

        if (common.type == "command")
        {
            if (common.command == "START_RECORDING")
            {
                RecordingManager.startRecordingFromZero = true;
                RecordingManager.recordingStartTime = Time.time;
                Debug.Log("Received START_RECORDING command from SUMO. Starting logs from zero now.");

                // Reset offset logging variables when we start recording
                firstTimestampLogged = false;
                firstLoggedTime = 0f;
            }
            else if (common.command == "STOP_RECORDING")
            {
                // Stop recording
                RecordingManager.startRecordingFromZero = false;
                Debug.Log("Received STOP_RECORDING command from SUMO. Stopping logs.");

                // Remove all surrounding cars except ego
                var nonEgoKeys = vehicleObjects.Keys.Where(k => k != egoVehicleId).ToList();
                foreach (var vid in nonEgoKeys)
                {
                    GameObject obj = vehicleObjects[vid];
                    Destroy(obj);
                    vehicleObjects.Remove(vid);
                }
            }

            return; // No further vehicle parsing needed
        }
        else if (common.type == "vehicles")
        {
            VehicleWrapper wrapper = JsonUtility.FromJson<VehicleWrapper>(message);
            Vehicle[] vehicleArray = wrapper.vehicles;
            List<Vehicle> vehiclesData = vehicleArray != null ? vehicleArray.ToList() : new List<Vehicle>();

            HashSet<string> incomingVehicleIds = new HashSet<string>(vehiclesData.Select(v => v.vehicle_id));
            var vehiclesToRemove = vehicleObjects.Keys.Where(id => !incomingVehicleIds.Contains(id) && id != egoVehicleId).ToList();

            foreach (var id in vehiclesToRemove)
            {
                GameObject vehicleToDestroy = vehicleObjects[id];
                GameObject.Destroy(vehicleToDestroy);
                vehicleObjects.Remove(id);
            }

            foreach (var vehicle in vehiclesData)
            {
                Vector3 newPosition = new Vector3((float)vehicle.position[0], (float)vehicle.position[2], (float)vehicle.position[1]);
                Quaternion newRotation = Quaternion.Euler(0, (float)vehicle.angle - 90f, 0);
                float vehicleSpeed = vehicle.long_speed;
                float vehiclevertical_speed = vehicle.vert_speed;
                float vehiclelateral_speed = vehicle.lat_speed;

                if (vehicle.vehicle_id == egoVehicleId)
                {
                    continue;
                }

                if (vehicleObjects.ContainsKey(vehicle.vehicle_id))
                {
                    GameObject existingVehicle = vehicleObjects[vehicle.vehicle_id];
                    VehicleController vehicleController = existingVehicle.GetComponent<VehicleController>();
                    if (vehicleController != null)
                    {
                        vehicleController.UpdateTarget(newPosition, newRotation, vehicleSpeed, vehiclevertical_speed, vehiclelateral_speed);
                    }
                }
                else
                {
                    GameObject prefabToInstantiate = vehiclePrefab;
                    foreach (CarModel carModel in carModelsList)
                    {
                        if (carModel.sumoVehicleType == vehicle.type)
                        {
                            prefabToInstantiate = carModel.unityVehiclePrefab;
                            break;
                        }
                    }

                    GameObject newVehicle = GameObject.Instantiate(prefabToInstantiate, newPosition, newRotation);
                    newVehicle.name = vehicle.vehicle_id;

                    // Add number plate to new vehicle
                    newVehicle.AddComponent<NumberPlate>();

                    // Ensure a valid body collider exists on the spawned vehicle
                    if (!HasValidBodyCollider(newVehicle))
                    {
                       ForceAddMeshColliders(newVehicle);


                    }
                    // Force any MeshColliders to convex
                    foreach (var mc in newVehicle.GetComponentsInChildren<MeshCollider>(includeInactive: true)) mc.convex = true;
                    var rb2 = newVehicle.GetComponent<Rigidbody>();
                    if (rb2 == null) rb2 = newVehicle.AddComponent<Rigidbody>();
                    rb2.isKinematic = false; // dynamic for proper collisions
                    rb2.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
                    rb2.interpolation = RigidbodyInterpolation.Interpolate;
                    rb2.detectCollisions = true;
                    foreach (var mc in newVehicle.GetComponentsInChildren<MeshCollider>(includeInactive: true)) mc.convex = true;

                    VehicleController vc = newVehicle.GetComponent<VehicleController>();
                    if (vc == null)
                    {
                        vc = newVehicle.AddComponent<VehicleController>();
                    }

                    vc.UpdateTarget(newPosition, newRotation, vehicleSpeed, vehiclevertical_speed, vehiclelateral_speed);
                    vehicleObjects.Add(vehicle.vehicle_id, newVehicle);
                }
            }

        }
        else if (common.type == "accident")
        {
            var accident = JsonUtility.FromJson<AccidentMessage>(message);
            TriggerAccidentFeedback(accident);
            return;
        }
        else if (common.type == "trafficlights")
        {
            // 2) parse wrapper
            var wrapper = JsonUtility.FromJson<TrafficLightsWrapper>(message);

            foreach (var tl in wrapper.lights)
            {
                // only repaint if state actually changed
                if (!_lastTlState.TryGetValue(tl.junction_id, out var prev)
                 || prev != tl.state)
                {
                    ChangeTrafficStatus(tl.junction_id, tl.state);
                    _lastTlState[tl.junction_id] = tl.state;
                }
            }
        }
        else
        {
            Debug.LogWarning("Received message with unknown type: " + common.type);
        }
    }

    private void TriggerAccidentFeedback(AccidentMessage accident)
    {
        if (accident == null)
        {
            return;
        }

        string vehicles = (accident.vehicle_ids != null && accident.vehicle_ids.Length > 0)
            ? string.Join(", ", accident.vehicle_ids)
            : "unknown";

        string msg = string.IsNullOrWhiteSpace(accident.message)
            ? "Accident detected"
            : accident.message;

        accidentBannerText = $"{msg}  |  Vehicles: {vehicles}  |  t={accident.sim_time:F2}s";
        accidentBannerUntil = Time.time + Mathf.Max(1f, accidentBannerDuration);
        Debug.LogWarning($"[ACCIDENT] {accidentBannerText}");

        Vector3 fxPosition;
        bool hasExplicitPosition = accident.position != null && accident.position.Length >= 3;

        if (hasExplicitPosition)
        {
            // SUMO sends [x, y, z], Unity world mapping in this project is (x, z, y).
            fxPosition = new Vector3(accident.position[0], accident.position[2], accident.position[1]);
        }
        else
        {
            fxPosition = ResolveAccidentPositionFromVehicles(accident.vehicle_ids);
        }

        if (accidentExplosionPrefab != null)
        {
            var fx = Instantiate(accidentExplosionPrefab, fxPosition + Vector3.up * 0.6f, Quaternion.identity);
            Destroy(fx, Mathf.Max(1f, accidentExplosionDuration));
        }

        if (accidentSmokePrefab != null)
        {
            var smoke = Instantiate(accidentSmokePrefab, fxPosition + Vector3.up * 0.4f, Quaternion.identity);
            Destroy(smoke, Mathf.Max(1f, accidentSmokeDuration));
        }

        if (accidentSfxClips != null && accidentSfxClips.Length > 0)
        {
            AudioClip clip = accidentSfxClips[UnityEngine.Random.Range(0, accidentSfxClips.Length)];
            if (clip != null)
            {
                GameObject sfxObj = new GameObject("AccidentSfx");
                sfxObj.transform.position = fxPosition;
                AudioSource src = sfxObj.AddComponent<AudioSource>();
                src.spatialBlend = 1f;  // 3D sound
                src.rolloffMode = AudioRolloffMode.Linear;
                src.maxDistance = Mathf.Max(5f, accidentSfxMaxDistance);
                src.volume = Mathf.Clamp01(accidentSfxVolume);
                src.clip = clip;
                src.Play();
                Destroy(sfxObj, clip.length + 0.2f);
            }
        }

        if (showAccidentIndicator)
        {
            accidentIndicatorWorldPos = fxPosition;
            accidentIndicatorUntil = Time.time + Mathf.Max(2f, accidentIndicatorDuration);
        }
    }

    private Vector3 ResolveAccidentPositionFromVehicles(string[] ids)
    {
        if (ids != null)
        {
            foreach (var id in ids)
            {
                if (string.IsNullOrEmpty(id))
                {
                    continue;
                }

                if (vehicleObjects.TryGetValue(id, out var go) && go != null)
                {
                    return go.transform.position;
                }
            }
        }

        if (vehicleObjects.TryGetValue(egoVehicleId, out var ego) && ego != null)
        {
            return ego.transform.position;
        }

        return Vector3.zero;
    }

    private void OnGUI()
    {
        if (string.IsNullOrEmpty(accidentBannerText) || Time.time > accidentBannerUntil)
        {
            DrawAccidentIndicator();
            return;
        }

        GUIStyle style = new GUIStyle(GUI.skin.label)
        {
            alignment = TextAnchor.MiddleCenter,
            fontSize = 24,
            fontStyle = FontStyle.Bold,
            normal = { textColor = Color.red }
        };

        Rect rect = new Rect(0f, 20f, Screen.width, 36f);
        GUI.Label(rect, accidentBannerText, style);

        DrawAccidentIndicator();
    }

    private void DrawAccidentIndicator()
    {
        if (!showAccidentIndicator || Time.time > accidentIndicatorUntil)
        {
            return;
        }

        Camera cam = Camera.main;
        if (cam == null)
        {
            return;
        }

        Vector3 screenPos3 = cam.WorldToScreenPoint(accidentIndicatorWorldPos);
        Vector2 screenPos = new Vector2(screenPos3.x, Screen.height - screenPos3.y);
        Vector2 center = new Vector2(Screen.width * 0.5f, Screen.height * 0.5f);

        GUIStyle style = new GUIStyle(GUI.skin.box)
        {
            fontSize = 16,
            alignment = TextAnchor.MiddleCenter,
            fontStyle = FontStyle.Bold
        };

        string label;
        if (screenPos3.z <= 0f)
        {
            label = "ACCIDENT BEHIND";
            Rect behindRect = new Rect(center.x - 90f, Screen.height - 70f, 180f, 30f);
            GUI.Box(behindRect, label, style);
            return;
        }

        bool onScreen = screenPos.x >= 0f && screenPos.x <= Screen.width && screenPos.y >= 0f && screenPos.y <= Screen.height;
        if (onScreen)
        {
            Rect targetRect = new Rect(screenPos.x - 60f, screenPos.y - 45f, 120f, 28f);
            GUI.Box(targetRect, "ACCIDENT", style);
            return;
        }

        Vector2 dir = (screenPos - center).normalized;
        float margin = 30f;
        float x = Mathf.Clamp(screenPos.x, margin, Screen.width - margin);
        float y = Mathf.Clamp(screenPos.y, margin, Screen.height - margin);

        string arrow;
        if (Mathf.Abs(dir.x) > Mathf.Abs(dir.y))
        {
            arrow = dir.x > 0 ? ">>" : "<<";
        }
        else
        {
            arrow = dir.y > 0 ? "vv" : "^^";
        }

        label = arrow + " ACCIDENT";
        Rect edgeRect = new Rect(x - 70f, y - 15f, 140f, 30f);
        GUI.Box(edgeRect, label, style);
    }

    public void EnqueueOnMainThread(string message)
    {
        EnqueueMainThreadAction(() => HandleMessage(message));
    }

    private void ChangeTrafficStatus(string junctionID, string state)
    {
        // find & cache the J4 GameObject exactly as before
        if (!junctionCache.TryGetValue(junctionID, out GameObject junctionGO))
        {
            var t = junctions.transform.Find(junctionID);
            if (t == null) { Debug.LogWarning($"Junction {junctionID} not found"); return; }
            junctionGO = t.gameObject;
            junctionCache[junctionID] = junctionGO;
        }

        // now for each character in the state string
        for (int i = 0; i < state.Length; i++)
        {
            // look for the child named "Head0", "Head1", etc.
            var headTransform = junctionGO.transform.Find($"Head{i}");
            if (headTransform == null)
            {
                Debug.LogWarning($"  Head{i} not found under {junctionID}");
                continue;
            }
            SetSignalState(state[i], headTransform.gameObject);
        }
    }


    private void SetSignalState(char c, GameObject head)
    {
        // look for your three meshes under each head
        var green = FindChildRecursive(head.transform, "green_light");
        var yellow = FindChildRecursive(head.transform, "yellow_light");
        var red = FindChildRecursive(head.transform, "red_light");
        if (green) green.SetActive(c == 'G' || c == 'g');
        if (yellow) yellow.SetActive(c == 'y' || c == 'Y');
        if (red) red.SetActive(!(c == 'G' || c == 'g' || c == 'y' || c == 'Y'));
    }

    private GameObject FindChildRecursive(Transform parent, string name)
    {
        foreach (Transform child in parent)
        {
            if (child.name == name) return child.gameObject;
            var found = FindChildRecursive(child, name);
            if (found) return found;
        }
        return null;
    }


    public static class JsonHelper
    {
        public static T[] FromJson<T>(string json)
        {
            string newJson = "{ \"vehicles\": " + json + "}";
            Wrapper<T> wrapper = JsonUtility.FromJson<Wrapper<T>>(newJson);
            return wrapper.vehicles;
        }

        public static string ToJson<T>(T[] array)
        {
            Wrapper<T> wrapper = new Wrapper<T> { vehicles = array };
            return JsonUtility.ToJson(wrapper);
        }

        [Serializable]
        private class Wrapper<T>
        {
            public T[] vehicles;
        }
    }
}