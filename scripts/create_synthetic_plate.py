"""Create a clearly labelled, fully synthetic Indian-style plate test image."""

from pathlib import Path

import cv2
import numpy as np

root = Path(__file__).resolve().parents[1]
output = root / "backend/data/synthetic_indian_plate.png"
output.parent.mkdir(parents=True, exist_ok=True)
image = np.full((720, 1280, 3), (202, 216, 231), dtype=np.uint8)
cv2.rectangle(image, (0, 470), (1280, 720), (100, 113, 128), -1)
cv2.rectangle(image, (235, 155), (1045, 635), (61, 79, 101), -1)
cv2.rectangle(image, (275, 190), (1005, 370), (99, 121, 146), -1)
cv2.rectangle(image, (305, 395), (975, 590), (45, 62, 81), -1)
cv2.rectangle(image, (420, 452), (860, 555), (250, 250, 250), -1)
cv2.rectangle(image, (420, 452), (860, 555), (38, 38, 38), 3)
cv2.putText(image, "GJ01AB1234", (442, 525), cv2.FONT_HERSHEY_SIMPLEX,
            2.0, (25, 25, 25), 5, cv2.LINE_AA)
cv2.circle(image, (330, 575), 45, (36, 45, 58), -1)
cv2.circle(image, (950, 575), 45, (36, 45, 58), -1)
cv2.imwrite(str(output), image)
print(output)
