import numpy as np
import cv2
import pathlib
import subprocess
import svgwrite
from hatched import hatched
from typing import Iterable
from shapely.geometry import MultiLineString

print("OpenCV:", cv2.__version__)

cap = cv2.VideoCapture(0)
while True:
    _, frame = cap.read()
    if _ != True: print("ERROR")
    monochrome = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    cv2.imshow("Camera",monochrome)
    if cv2.waitKey(1) == ord(' '):
        break

#image 캡쳐 후 실행
cap.release()
cv2.destroyAllWindows()

print("PostProcessing...")


#PNG_Postprocessing
potrace_Path=r"C:/potrace.exe"
inkScape_Path=r"C:\Program Files\Inkscape\bin\inkscape.exe"
turdsize=2
# 노이즈 제거
gray = cv2.GaussianBlur(monochrome, (3, 3), 0)

# 적응형 이진화
binary = cv2.adaptiveThreshold(
    gray,
    255,
    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
    cv2.THRESH_BINARY,
    19,
    5,
)

# 선 두께 약간 보정
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

cmd = [
    potrace_Path,
    "-s",                  # SVG 출력
    "-o",
    "-",
    "--turdsize",
    str(turdsize),
    "--alphamax",
    "1",
    "--opttolerance",
    "0.2",
    "--unit",
    "10",
]

potrace = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

potrace.stdin.write(f"P4\n{640} {480}\n".encode() + np.packbits((binary == 0).astype(np.uint8), axis=1).tobytes())

inkscape = subprocess.Popen([inkScape_Path, "--pipe", "--export-type=png", "--export-background=white", "--export-filename=-"], stdin=potrace.stdout, stdout=subprocess.PIPE)

png_bytes = inkscape.stdout.read()
img = cv2.imdecode(
    np.frombuffer(png_bytes, np.uint8),
    cv2.IMREAD_GRAYSCALE
)

height, width = monochrome.shape[:2]
Edges_resized = cv2.resize(img, (width, height))

#cv2.imwrite(f"{pathlib.Path(__file__).parent}/output.png", cv2.addWeighted(Edges_resized, 0.55, monochrome, 0.8,1))
print("Done.")
print("converting to SVG...")
#svgPath1 = hatched.hatch(f'{pathlib.Path(__file__).parent}/output.png', hatch_pitch=1, levels=(20, 100, 180), blur_radius=0, show_plot=False,save_svg=False, hatch_angle=45)
#svgPath2 = hatched.hatch(f'{pathlib.Path(__file__).parent}/output.png', hatch_pitch=1, levels=(20, 100, 180), blur_radius=0, show_plot=False,save_svg=False, hatch_angle=-45)
#print("Done.")
#print("converting to arduino plotter code...")

def svgPathCombine(file_path: str, w: int, h: int, vectors1: Iterable[MultiLineString], vectors2: Iterable[MultiLineString]) -> None:
    dwg = svgwrite.Drawing(file_path, size=(w, h), profile="tiny", debug=False)

    dwg.add(
        dwg.path(
            " ".join(
                " ".join(
                    ("M" + " L".join(f"{x},{y}" for x, y in ls.coords)) for ls in mls.geoms
                )
                for mls in vectors1
            ),
            fill="none",
            stroke="black",
        )
    )
    
    dwg.add(
        dwg.path(
            " ".join(
                " ".join(
                    ("M" + " L".join(f"{x},{y}" for x, y in ls.coords)) for ls in mls.geoms
                )
                for mls in vectors2
            ),
            fill="none",
            stroke="black",
        )
    )
    dwg.save()

def svgFormatter(mls):
    for ls in mls.geoms: yield "M " + "L ".join(f"{min(int(x*100), 65535) - 32768} {min(int(y*400/3), 65535) - 32768}\n" for x, y in ls.coords)
    
svgPath = hatched._build_hatch(cv2.addWeighted(Edges_resized, 0.55, monochrome, 0.8,1), hatch_pitch=1, levels=(20, 100, 180), hatch_angle=45)[0]
#svgPath2 = hatched._build_hatch(cv2.addWeighted(Edges_resized, 0.55, monochrome, 0.8,1), hatch_pitch=1, levels=(20, 100, 180), hatch_angle=-45)[0]

# for command in svgFormatter(svgPath1):
#     print(command)
print("Done.")
print("Saving SVG File...")
hatched._save_to_svg(f"{pathlib.Path(__file__).parent}/output.svg", 640, 480,[svgPath])
#svgPathCombine(f"{pathlib.Path(__file__).parent}/output.svg", 640, 480, [svgPath1], [svgPath2])
print("Done.")