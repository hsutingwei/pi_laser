import cv2
import time
import os

def test_camera():
    print("=== Camera Module Test ===")
    
    # Common camera indices to try
    indices_to_try = [0, -1, 1]
    
    camera_found = False
    
    for index in indices_to_try:
        print(f"\nAttempting to open camera at index {index}...")
        try:
            cap = cv2.VideoCapture(index)
            
            if cap.isOpened():
                print(f"✅ Success! Connection established at index {index}.")
                
                # Warm up camera
                time.sleep(1)
                
                # Try to capture a frame
                ret, frame = cap.read()
                
                if ret:
                    print("✅ Frame captured successfully.")
                    
                    # Save the image
                    filename = "camera_test.jpg"
                    path = os.path.join(os.getcwd(), filename)
                    cv2.imwrite(path, frame)
                    
                    print(f"📸 Test image saved to: {path}")
                    print("-> Please download/open this image to verify clarity and orientation.")
                    
                    # Get resolution
                    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    print(f"ℹ️ Resolution: {int(width)}x{int(height)}")
                    
                    camera_found = True
                    cap.release()
                    break
                else:
                    print("❌ Error: Connected but failed to read frame (blank output).")
            else:
                print("❌ Failed: Could not open device.")
                
            cap.release()
            
        except Exception as e:
            print(f"❌ Exception: {e}")

    if not camera_found:
        print("\n❌ CRITICAL: No working camera module found.")
        print("troubleshooting:")
        print("1. Run 'vcgencmd get_camera' (if using Pi Camera Module via ribbon)")
        print("2. Run 'lsusb' (if using USB Webcam)")
        print("3. Ensure 'libcamera' or legacy camera support is enabled in raspi-config.")

if __name__ == "__main__":
    test_camera()
