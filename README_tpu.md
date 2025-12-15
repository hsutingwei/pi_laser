# Edge TPU Integration Guide

This project supports Google Coral Edge TPU for hardware-accelerated object detection.

## Prerequisites

1.  **Hardware**: Coral USB Accelerator (or Dev Board).
2.  **OS**: Raspberry Pi OS (Debian Bullseye/Bookworm).
3.  **Drivers**: `libedgetpu` must be installed.

### Installation

```bash
# 1. Add Debian package repository
echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -

# 2. Install runtime
sudo apt-get update
sudo apt-get install libedgetpu1-std
# (Use libedgetpu1-max for max performance, but higher heat)

# 3. Install Python bindings (tflite_runtime)
# Usually pre-installed on RPi, or:
pip3 install tflite-runtime
```

## Model Preparation

TPU requires models compiled specifically for it using `edgetpu_compiler`. They must be **int8 quantized**.

1.  Download a quantized TFLite model (e.g., `mobilenet_ssd_v2_coco_quant_postprocess.tflite`).
2.  Install compiler: `sudo apt-get install edgetpu-compiler`.
3.  Compile:
    ```bash
    edgetpu_compiler model.tflite
    ```
4.  It outputs `model_edgetpu.tflite`. Place this file in your accessible format.

## Configuration (`config/config.json`)

To enable TPU:

```json
"detector": {
    "tflite": {
        "backend": "tpu",
        "fallback_backend": "cpu",
        "model_path": "path/to/detect.tflite",
        "model_path_tpu": "path/to/detect_edgetpu.tflite",
        "edgetpu_delegate": "libedgetpu.so.1",
        "inference_fps": 10
    }
}
```

*   `backend`: Set to `"tpu"` to attempt acceleration.
*   `fallback_backend`: If TPU fails (missing hardware/drivers), fallback to `"cpu"` or `"mock"`.
*   `inference_fps`: Limits how many times per second detection runs (~10-15 recommended for Pi 3/4).

## Troubleshooting

*   **Error: `libedgetpu.so.1` not found**: Reinstall `libedgetpu1-std`.
*   **Fallback to CPU**: Check if USB stick is plugged in. Check `dmesg` for USB enumeration.
*   **Fallback to Mock**: Both TPU and CPU models failed to load. Check file paths.
