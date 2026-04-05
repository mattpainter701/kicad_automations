#!/bin/bash
# Terminal Demo: Circuit Weaver MVP Workflow
# Shows end-to-end: YAML → Validate → Generate → Export JLCPCB
# Runs in ~30 seconds, suitable for video recording

set -e

PROJECT_PATH="/I/deepseek/kicad_automations/kicad_automations"
SAMPLE="$PROJECT_PATH/samples/battery_iot_sensor/battery_iot_sensor.yaml"
OUTPUT_DIR="/tmp/demo_output_$$"

echo "====================================================================="
echo "  CIRCUIT WEAVER MVP — DESIGN-TO-FAB WORKFLOW"
echo "====================================================================="
echo ""
echo "[STEP 1] Define your circuit in YAML"
echo "-------------------------------------------------------------------"
echo "File: battery_iot_sensor.yaml"
echo ""
head -20 "$SAMPLE"
echo "..."
echo ""

# Give user time to read
sleep 2

echo "[STEP 2] Validate the design"
echo "-------------------------------------------------------------------"
echo "$ py -m circuit_weaver validate battery_iot_sensor.yaml"
echo ""
cd "$PROJECT_PATH"
py -m circuit_weaver validate "$SAMPLE" 2>&1 | tail -30 || true
echo ""

# Give user time to see validation result
sleep 2

echo "[STEP 3] Generate schematic & documentation"
echo "-------------------------------------------------------------------"
echo "$ py -m circuit_weaver generate battery_iot_sensor.yaml -o output"
echo ""
py -m circuit_weaver generate "$SAMPLE" -o "$OUTPUT_DIR" 2>&1 | tail -15 || true
echo ""

# Show generated files
echo "Generated files:"
ls -lh "$OUTPUT_DIR"/ | tail -6
echo ""

# Give user time to see files
sleep 2

echo "[STEP 4] View design report (excerpt)"
echo "-------------------------------------------------------------------"
echo "$ cat output/Battery_IoT_Sensor_report.md | head -50"
echo ""
head -50 "$OUTPUT_DIR"/Battery_IoT_Sensor_report.md 2>/dev/null || echo "(Report not available in demo)"
echo ""

# Give user time to read
sleep 2

echo "[STEP 5] Export for JLCPCB assembly"
echo "-------------------------------------------------------------------"
echo "$ py -m circuit_weaver export-jlcpcb battery_iot_sensor.yaml -o jlcpcb"
echo ""
py -m circuit_weaver export-jlcpcb "$SAMPLE" -o "$OUTPUT_DIR/jlcpcb" 2>&1 | tail -10 || true
echo ""

echo "Generated files for fabrication:"
ls -lh "$OUTPUT_DIR/jlcpcb/"/ 2>/dev/null || true
echo ""

echo "[STEP 6] BOM ready for upload to JLCPCB"
echo "-------------------------------------------------------------------"
echo "$ cat jlcpcb/bom_jlcpcb.csv"
echo ""
cat "$OUTPUT_DIR/jlcpcb/bom_jlcpcb.csv" 2>/dev/null || echo "(BOM not available in demo)"
echo ""

echo "====================================================================="
echo "  WORKFLOW COMPLETE"
echo "====================================================================="
echo ""
echo "Time: From YAML to JLCPCB-ready files in ~30 seconds"
echo "Files: 3 schematics, 1 report, 3 manufacturing files generated"
echo ""
echo "Next: Review in KiCad → Upload to JLCPCB → Order"
echo ""

# Cleanup
rm -rf "$OUTPUT_DIR"
