import json
from collections import deque

d = json.load(open(r'C:/Users/24f20/Downloads/maze-solve.json'))
W, H = d['width'], d['height']
sx, sy = d['start']
ex, ey = d['end']
mask = d['openMask']

# U=1, R=2, D=4, L=8 ; openMask[y][x]
DIRS = [(1, 0, -1, 'U'), (2, 1, 0, 'R'), (4, 0, 1, 'D'), (8, -1, 0, 'L')]

prev = {(sx, sy): None}
q = deque([(sx, sy)])
while q:
    x, y = q.popleft()
    if (x, y) == (ex, ey):
        break
    for bit, dx, dy, ch in DIRS:
        if mask[y][x] & bit:
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in prev:
                prev[(nx, ny)] = ((x, y), ch)
                q.append((nx, ny))

assert (ex, ey) in prev, "no path"
path = []
cur = (ex, ey)
while prev[cur] is not None:
    p, ch = prev[cur]
    path.append(ch)
    cur = p
path.reverse()
s = ''.join(path)

# verify replay
x, y = sx, sy
M = {'U': (1, 0, -1), 'R': (2, 1, 0), 'D': (4, 0, 1), 'L': (8, -1, 0)}
for ch in s:
    bit, dx, dy = M[ch]
    assert mask[y][x] & bit, f"illegal move {ch} at {x},{y}"
    x, y = x + dx, y + dy
assert (x, y) == (ex, ey), f"ended at {x},{y}"
print("LEN", len(s))
print(s)
open('answers_Q1_maze.txt', 'w').write(s)
