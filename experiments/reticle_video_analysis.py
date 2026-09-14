"""Temporal Video Analysis for Reticle Gameplay Sample (2026-09-03 19-43-11.mp4)."""

import cv2
import numpy as np
from pathlib import Path

video_path = r"C:\Users\grant\Videos\2026-09-03 19-43-11.mp4"

def inspect_video_timeline():
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video: {total_frames} frames @ {fps} fps ({total_frames/fps:.2f}s)")
    
    # We sample every 10 frames (6 fps equivalent, ~269 samples) to map state transitions
    sample_stride = 6  # every 0.1s
    timeline = []
    
    prev_small = None
    frame_idx = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        if frame_idx % sample_stride == 0:
            t = frame_idx / fps
            small = cv2.resize(frame, (320, 180))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            
            # Motion energy relative to previous sampled frame
            motion = 0.0
            if prev_small is not None:
                diff = cv2.absdiff(gray, prev_small)
                motion = float(np.sqrt(np.mean((diff.astype(np.float32) / 255.0) ** 2)))
            prev_small = gray
            
            # Overall frame brightness
            brightness = float(np.mean(gray))
            
            # Crop key HUD zones
            # Ammo region (around x: 1290-1360, y: 925-965 on 1920x1080)
            ammo_crop = frame[920:965, 1290:1360]
            ammo_mean = float(np.mean(ammo_crop))
            
            # Abilities region (x: 750-1170, y: 900-965)
            abilities_crop = frame[900:965, 750:1170]
            abilities_mean = float(np.mean(abilities_crop))
            
            # Location region (x: 50-250, y: 15-50)
            loc_crop = frame[15:50, 50:250]
            loc_mean = float(np.mean(loc_crop))
            
            timeline.append({
                "frame": frame_idx,
                "time_s": round(t, 2),
                "motion": round(motion, 4),
                "brightness": round(brightness, 2),
                "ammo_mean": round(ammo_mean, 2),
                "abilities_mean": round(abilities_mean, 2),
                "loc_mean": round(loc_mean, 2)
            })
            
        frame_idx += 1
        
    cap.release()
    print(f"Sampled {len(timeline)} points across the video.")
    return timeline

if __name__ == "__main__":
    tl = inspect_video_timeline()
