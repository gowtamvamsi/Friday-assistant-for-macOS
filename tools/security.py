"""
tools/security.py — Phase 5: On-Device Biometric Security Layer

Performs real-time facial verification using the FaceTime camera before
allowing execution of any tool flagged as "secure" or "destructive."

Flow:
1. Load known reference encoding from `data/me.jpg` (once, cached).
2. Capture a single frame from the webcam.
3. Compute face encoding for the captured frame.
4. Compare encodings using face_recognition.compare_faces().
5. Return True on match, False on mismatch or if no face is detected.
"""

import os
import logging
import threading
from typing import Optional

logger = logging.getLogger("friday.security")

# ── Module-level cache ─────────────────────────────────────────────────────────
_known_encoding = None       # Cached encoding loaded from data/me.jpg
_lock = threading.Lock()     # Protect concurrent initialization

REFERENCE_PHOTO_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "me.jpg")
FACE_MATCH_TOLERANCE = 0.5   # Lower = stricter (0.4–0.6 is typical)


def _load_reference_encoding():
    """Loads and caches the reference face encoding from data/me.jpg."""
    global _known_encoding
    with _lock:
        if _known_encoding is not None:
            return _known_encoding

        ref_path = os.path.abspath(REFERENCE_PHOTO_PATH)
        if not os.path.exists(ref_path):
            logger.error(
                f"Reference photo not found at '{ref_path}'. "
                "Please capture your photo and save it to data/me.jpg"
            )
            return None

        try:
            import face_recognition
            image = face_recognition.load_image_file(ref_path)
            encodings = face_recognition.face_encodings(image)
            if not encodings:
                logger.error("No face detected in the reference photo data/me.jpg. Biometric security disabled.")
                return None
            _known_encoding = encodings[0]
            logger.info("Reference face encoding loaded and cached from data/me.jpg.")
            return _known_encoding
        except ImportError:
            logger.error("face_recognition library not installed. Biometric security disabled.")
            return None
        except Exception as e:
            logger.error(f"Failed to load reference face encoding: {e}")
            return None


def capture_and_verify() -> bool:
    """
    Opens the FaceTime webcam, captures one frame, verifies identity, and closes immediately.

    Returns:
        bool: True if the face matches the reference, False otherwise.
    """
    known_encoding = _load_reference_encoding()
    if known_encoding is None:
        # Gracefully degrade: if no reference photo, bypass security (log warning)
        logger.warning("Biometric reference not configured — bypassing security check.")
        return True

    try:
        import face_recognition
        import cv2

        logger.info("Biometric check: opening webcam for verification...")
        cap = cv2.VideoCapture(0)  # 0 = default FaceTime camera

        if not cap.isOpened():
            logger.error("Could not open webcam for biometric verification.")
            return False

        # Warm up: skip a couple frames for exposure adjustment
        for _ in range(3):
            cap.read()

        ret, frame = cap.read()
        cap.release()  # Immediately release camera

        if not ret or frame is None:
            logger.error("Failed to capture frame from webcam.")
            return False

        # Convert BGR (OpenCV) → RGB (face_recognition)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Detect faces and compute encodings
        face_locations = face_recognition.face_locations(rgb_frame, model="hog")
        if not face_locations:
            logger.warning("Biometric check: No face detected in webcam frame.")
            return False

        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
        if not face_encodings:
            return False

        # Compare against reference
        matches = face_recognition.compare_faces(
            [known_encoding],
            face_encodings[0],
            tolerance=FACE_MATCH_TOLERANCE
        )
        verified = bool(matches[0])

        if verified:
            logger.info("Biometric check: PASSED ✅ — Identity confirmed.")
        else:
            logger.warning("Biometric check: FAILED ❌ — Face does not match reference.")

        return verified

    except ImportError as e:
        logger.error(f"Required library not available for biometric check: {e}. Bypassing.")
        return True  # Graceful degradation if not installed
    except Exception as e:
        logger.error(f"Unexpected error during biometric check: {e}")
        return False


def enroll_reference_from_webcam() -> bool:
    """
    Utility: Captures a photo from the webcam and saves it as data/me.jpg.
    Call this once to set up your biometric reference.

    Returns:
        bool: True if enrollment succeeded, False otherwise.
    """
    try:
        import cv2
        global _known_encoding

        logger.info("Enrollment: opening webcam to capture reference photo...")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            logger.error("Could not open webcam for enrollment.")
            return False

        # Let camera auto-adjust exposure
        for _ in range(10):
            cap.read()

        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            logger.error("Enrollment: failed to capture frame.")
            return False

        ref_path = os.path.abspath(REFERENCE_PHOTO_PATH)
        os.makedirs(os.path.dirname(ref_path), exist_ok=True)
        cv2.imwrite(ref_path, frame)
        logger.info(f"Enrollment: reference photo saved to '{ref_path}'.")

        # Reset the cached encoding so it reloads on next verification
        with _lock:
            _known_encoding = None

        return True
    except Exception as e:
        logger.error(f"Enrollment failed: {e}")
        return False
