#!/usr/bin/env python3
"""
friday_enroll.py — One-time facial enrollment for Friday's biometric security gate.

Run this script once to capture your face using the FaceTime webcam and save it
to data/me.jpg. From then on, secure tools (like set_volume, dead_drop, etc.)
will require your face to match before executing.

Usage:
    python friday_enroll.py

Requirements:
    - Face must be clearly visible and well-lit
    - The script will capture after 3 seconds of preview (optional via OpenCV window)
"""

import sys
import os
import time

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    print("\n" + "═" * 60)
    print("   Friday Biometric Enrollment")
    print("═" * 60)
    print("\nThis will capture your face from the FaceTime webcam and")
    print("save it as data/me.jpg for the biometric security gate.\n")
    print("📷  Please look directly at the camera...")
    print("    Capturing in 3 seconds...\n")
    time.sleep(3)

    from tools.security import enroll_reference_from_webcam

    success = enroll_reference_from_webcam()

    if success:
        print("\n✅  Enrollment successful!")
        print("   data/me.jpg has been saved.")
        print("   The biometric security gate is now active.")
        print("\n   Secure tools that require verification:")
        print("     • set_volume / mute_volume / unmute_volume")
        print("     • close_application")
        print("     • dead_drop (file sharing)")
        print("\n   To disable: simply delete data/me.jpg\n")
    else:
        print("\n❌  Enrollment failed.")
        print("   Please ensure your webcam is working and your face is visible.")
        print("   Check that OpenCV (cv2) is installed: pip install opencv-python\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
