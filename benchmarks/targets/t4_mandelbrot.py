
TARGET_NAME = "mandelbrot_escape"
TIER = 4
function_name = "mandelbrot_escape"
source = """
def mandelbrot_escape(width, height, max_iter=100, xmin=-2.0, xmax=1.0, ymin=-1.5, ymax=1.5):
    img = [[0]*width for _ in range(height)]
    for py in range(height):
        for px in range(width):
            c_real = xmin + (xmax - xmin) * px / (width - 1)
            c_imag = ymin + (ymax - ymin) * py / (height - 1)
            zr, zi = 0.0, 0.0
            for it in range(max_iter):
                nr = zr*zr - zi*zi + c_real
                ni = 2.0*zr*zi + c_imag
                zr, zi = nr, ni
                if zr*zr + zi*zi > 4.0:
                    img[py][px] = it
                    break
            else:
                img[py][px] = max_iter
    return img
"""
def _ref(width, height, max_iter=100, xmin=-2.0, xmax=1.0, ymin=-1.5, ymax=1.5):
    img=[[0]*width for _ in range(height)]
    for py in range(height):
        for px in range(width):
            cr=xmin+(xmax-xmin)*px/(width-1); ci=ymin+(ymax-ymin)*py/(height-1)
            zr,zi=0.0,0.0; img[py][px]=max_iter
            for it in range(max_iter):
                nr=zr*zr-zi*zi+cr; ni=2.0*zr*zi+ci; zr,zi=nr,ni
                if zr*zr+zi*zi>4.0: img[py][px]=it; break
    return img
test_cases = [
    {"function": "mandelbrot_escape", "args": [5, 5, 50], "expected": _ref(5,5,50), "comparison": "equal"},
    {"function": "mandelbrot_escape", "args": [3, 3, 20, -0.5, 0.5, -0.5, 0.5], "expected": _ref(3,3,20,-0.5,0.5,-0.5,0.5), "comparison": "equal"},
]
invariants = ['all(0 <= v <= x[2] for row in out for v in row)']
input_strategy = "st.tuples(st.integers(min_value=2,max_value=8), st.integers(min_value=2,max_value=8), st.integers(min_value=10,max_value=80))"
