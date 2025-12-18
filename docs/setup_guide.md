# 安裝指南 - Pi Laser Cat Toy

本指南涵蓋 Raspberry Pi 4 (Bullseye/Bookworm) 所需的所有軟體與驅動程式安裝步驟。

## 1. 系統更新
首先，確保您的系統是最新的。
```bash
sudo apt-get update
sudo apt-get upgrade
```

## 2. 硬體與驅動程式設定 (關鍵)

### A. 相機 (Legacy 模式)
本專案使用 `picamera` 函式庫，這需要啟用 **Legacy Camera Stack**。
1. 執行 `sudo raspi-config`
2. 進入 **Interface Options** -> **Legacy Camera**
3. 選擇 **Yes** 啟用。
4. **重新啟動** 您的 Pi。

### B. Coral Edge TPU (USB 加速器)
您必須安裝 USB 加速器的系統驅動程式。 (詳見 [官方安裝教學](https://coral.ai/docs/accelerator/get-started/#2-install-the-pycoral-library))

1. **加入 Google Coral 套件庫:**
   ```bash
   echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
   curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
   sudo apt-get update
   ```

2. **安裝 Edge TPU Runtime:**
   ```bash
   # 標準時脈速度 (建議，較穩定)
   sudo apt-get install libedgetpu1-std

   # 或 最大時脈速度 (需要良好的散熱)
   # sudo apt-get install libedgetpu1-max
   ```

3. **驗證裝置:**
   插上您的 Coral USB。執行 `lsusb`，您應該會看到一個 Google Inc 的裝置。

### C. Pigpio (伺服馬達控制)
我們使用 `pigpio` 來達成無抖動的伺服馬達控制。
```bash
sudo apt-get install pigpio python3-pigpio
# 啟用並啟動 daemon
sudo systemctl enable pigpiod
sudo systemctl start pigpiod
```

## 3. Python 環境設定

我們強烈建議使用虛擬環境，並設定讓它能存取系統套件 (如 PyCoral 和 Pigpio)。

```bash
# 1. 全域安裝 PyCoral (官方推薦方法)
sudo apt-get install python3-pycoral

# 2. 建立可存取系統套件的 venv
python3 -m venv venv --system-site-packages
source venv/bin/activate

# 3. 安裝其他專案依賴
pip install -r requirements.txt
```

*注意: 使用 `--system-site-packages` 參數可以讓您的虛擬環境直接使用透過 `apt-get` 安裝的 `pycoral` 和 `pigpio` 函式庫，這在 Raspberry Pi 上通常比用 pip 安裝更穩定。*

## 4. 硬體設定檢查
- **Camera**: 確保已啟用 Legacy Camera 支援。
- **I2C/GPIO**: 確保這些介面已在 `raspi-config` 中啟用。

## 5. 執行應用程式
```bash
# 1. 啟動 Pigpio Daemon (如果尚未執行)
sudo systemctl start pigpiod

# 2. 執行伺服器
python3 app.py
```

## 6. 常見問題排除 (Troubleshooting)

*   **Error: `libedgetpu.so.1` not found**
    *   原因：Edge TPU Runtime 未安裝。
    *   解法：重新執行 `sudo apt-get install libedgetpu1-std`。

*   **Fallback to CPU (自動切換回 CPU)**
    *   原因：找不到 Coral USB 加速器。
    *   解法：檢查 USB 是否插好，並執行 `lsusb` 確認是否有 Google Inc 裝置。

*   **Fallback to Mock (自動切換回模擬模式)**
    *   原因：找不到模型檔案或 TFLite 初始化失敗。
    *   解法：檢查 `config.json` 中的 `model_path` 路徑是否正確。

## 7. 進階：編譯自定義模型

如果您想使用自己的 TFLite 模型，必須先針對 Edge TPU 進行編譯 (且模型必須是 **int8 quantized**)。

1.  下載 Edge TPU 編譯器:
    ```bash
    sudo apt-get install edgetpu-compiler
    ```
2.  編譯您的模型:
    ```bash
    edgetpu_compiler model.tflite
    ```
3.  編譯完成後會產生 `model_edgetpu.tflite`，請將其路徑更新至 `config.json` 的 `model_path_tpu` 欄位。
