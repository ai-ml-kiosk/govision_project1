import spidev
import numpy as np
import cv2
import time

# --- UPDATED CONFIGURATION ---
BUS = 0
DEVICE = 1  # Changed from 0 to 1 based on your scan
SPEED = 18000000 
PACKET_SIZE = 164
WIDTH = 80
HEIGHT = 60
# -----------------------------

def capture_test_frame():
    spi = spidev.SpiDev()
    spi.open(BUS, DEVICE)
    # Lepton requires SPI Mode 3
    spi.mode = 3
    spi.max_speed_hz = SPEED
    
    print(f"Communicating with Lepton on /dev/spidev{BUS}.{DEVICE}...")
    
    # VoSPI Reset: If we are out of sync, the Lepton needs a 
    # short break (deassert CS) to reset its internal counter.
    time.sleep(0.2)
    
    frame_buffer = []
    # We may need to read thousands of packets to find the start of a frame
    for _ in range(10000):
        packet = spi.readbytes(PACKET_SIZE)
        
        # Check for discard packet
        if (packet[0] & 0x0F) == 0x0F:
            continue
            
        row_num = packet[1]
        
        # If we see row 0, start a new frame
        if row_num == 0:
            frame_buffer = []
            
        if len(frame_buffer) == row_num:
            payload = np.frombuffer(bytes(packet[4:]), dtype='>u2')
            frame_buffer.append(payload)
            
            if len(frame_buffer) == HEIGHT:
                print("Captured full 80x60 frame!")
                img = np.array(frame_buffer, dtype=np.uint16)
                img_8bit = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                cv2.imwrite("lepton_success.jpg", img_8bit)
                return True
                
    print("Could not find a valid frame start. Try increasing SPI buffer size.")
    return False

if __name__ == "__main__":
    capture_test_frame()