using UnityEngine;
using System.Collections.Generic;

public class NumberPlate : MonoBehaviour
{
    private static HashSet<string> usedPlates = new HashSet<string>();
    private static string letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

    [Header("Number Plate Tuning")]
    [Tooltip("How far behind the rear-most mesh the plate should sit (in local X).")]
    public float plateBackOffset = 0.05f;
    [Tooltip("Height above the vehicle bottom to place the plate (in local Y).")]
    public float plateHeightAboveBottom = 0.90f;

    void Start()
    {
        string plate = GenerateUniquePlate();

        // Determine rear-most point using mesh bounds so plate sits on the bumper
        MeshFilter[] mfs = GetComponentsInChildren<MeshFilter>(true);
        if (mfs == null || mfs.Length == 0)
        {
            // fallback: small offset on negative local X (rear)
            Vector3 rearLocal = new Vector3(-1.2f, 0.4f, 0f);
            Quaternion rearRot = Quaternion.LookRotation(transform.TransformDirection(-Vector3.right), transform.up);
            CreatePlate("RearPlate", rearLocal, rearRot, plate);
            return;
        }

        float minLocalX = float.PositiveInfinity;
        float minLocalY = float.PositiveInfinity;
        float maxLocalY = float.NegativeInfinity;
        float minLocalZ = float.PositiveInfinity;
        float maxLocalZ = float.NegativeInfinity;

        foreach (var mf in mfs)
        {
            if (mf.sharedMesh == null) continue;
            var b = mf.sharedMesh.bounds;
            Vector3 c = b.center;
            Vector3 e = b.extents;

            // 8 corners in mesh-local space
            for (int sx = -1; sx <= 1; sx += 2)
            for (int sy = -1; sy <= 1; sy += 2)
            for (int sz = -1; sz <= 1; sz += 2)
            {
                Vector3 corner = c + Vector3.Scale(e, new Vector3(sx, sy, sz));
                Vector3 worldPt = mf.transform.TransformPoint(corner);
                Vector3 localPt = transform.InverseTransformPoint(worldPt);
                minLocalX = Mathf.Min(minLocalX, localPt.x);
                minLocalY = Mathf.Min(minLocalY, localPt.y);
                maxLocalY = Mathf.Max(maxLocalY, localPt.y);
                minLocalZ = Mathf.Min(minLocalZ, localPt.z);
                maxLocalZ = Mathf.Max(maxLocalZ, localPt.z);
            }
        }

        // Place plate slightly behind the rear-most point and slightly above the bottom of the vehicle
        float plateLocalX = minLocalX - plateBackOffset;
        float plateLocalY = minLocalY + plateHeightAboveBottom; // near bumper height
        float plateLocalZ = (minLocalZ + maxLocalZ) * 0.5f;

        Vector3 rearLocalPos = new Vector3(plateLocalX, plateLocalY, plateLocalZ);
        Quaternion rearWorldRot = Quaternion.LookRotation(transform.TransformDirection(-Vector3.right), transform.up);

        CreatePlate("RearPlate", rearLocalPos, rearWorldRot, plate);
    }

    BoxCollider EnsureCollider()
    {
        BoxCollider col = GetComponentInChildren<BoxCollider>();
        if (col != null) return col;

        // Don't add collider to vehicle, just use existing bounds
        MeshRenderer mr = GetComponentInChildren<MeshRenderer>();
        if (mr == null) return null;

        // Create a temporary collider for bounds calculation only
        col = mr.gameObject.AddComponent<BoxCollider>();
        col.center = mr.bounds.center - mr.transform.position;
        col.size   = mr.bounds.size;
        col.isTrigger = true; // Make it a trigger so it doesn't affect physics

        return col;
    }

    void CreatePlate(string name, Vector3 localPos, Quaternion rot, string text)
    {
        GameObject plate = new GameObject(name);
        plate.transform.SetParent(transform, worldPositionStays: true);
        // localPos is provided in vehicle-local coordinates; convert to world then parent
        Vector3 worldPos = transform.TransformPoint(localPos);
        plate.transform.position = worldPos;
        // Flip 180 degrees around Y so TextMesh faces outward (fix inverted plates)
        plate.transform.rotation = rot * Quaternion.Euler(0f, 180f, 0f);

        TextMesh tm = plate.AddComponent<TextMesh>();
        tm.text = text;
        tm.fontSize = 30;
        tm.characterSize = 0.05f;
        tm.anchor = TextAnchor.MiddleCenter;
        tm.alignment = TextAlignment.Center;
        tm.color = Color.white;
        tm.richText = false;
    }

    string GenerateUniquePlate()
    {
        string plate;
        do
        {
            plate =
                letters[Random.Range(0, 26)].ToString() +
                letters[Random.Range(0, 26)].ToString() +
                Random.Range(10, 99).ToString() +
                letters[Random.Range(0, 26)].ToString() +
                letters[Random.Range(0, 26)].ToString() +
                Random.Range(1000, 9999).ToString();
        }
        while (usedPlates.Contains(plate));

        usedPlates.Add(plate);
        return plate;
    }
}
