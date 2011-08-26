import pygame
import time
import hashlib
import math
import StringIO
from PIL import Image

from p2pool.util.vector import v

@apply
class color(object):
    def __getattr__(self, name):
        res = pygame.Color(name)
        setattr(self, name, res)
        return res

def get_uniform(bound, *data):
    x = int(hashlib.sha256(repr(data)).hexdigest(), 16)
    return x % bound

def get_pos(share, t, d):
    x = 5 + get_uniform(d.get_width() - 10, share.hash, "pos")
    y = d.get_height() - (t - share.time_seen)*10
    if y < -10000: y = -10000
    if y > 10000: y = 10000
    return v(x, y)

def get_color(data):
    return [get_uniform(256, data, x) for x in "rgb"]

def perp_and_normalize_to((dx, dy), d):
    m = math.sqrt(dx**2 + dy**2)
    return v(-dy/m*d, dx/m*d)

def go(share, tracker, t, d):
    #c = color.green if share.peer is None else color.red
    c = get_color(share.new_script)
    pos = get_pos(share, t, d)
    pygame.draw.circle(d, c, pos.rounded, 5)
    if share.previous_hash in tracker.shares:
        previous_share = tracker.shares[share.previous_hash]
        previous_pos = get_pos(previous_share, t, d)
        vec_to_previous = previous_pos - pos
        pygame.draw.polygon(d, c, [
            (pos + perp_and_normalize_to(vec_to_previous, 5)).rounded,
            (pos + perp_and_normalize_to(vec_to_previous, -5)).rounded,
            previous_pos.rounded,
        ])
    if share.peer is None:
        pygame.draw.circle(d, c, pos.rounded, 10, 2)
    for child_hash in tracker.reverse_shares.get(share.hash, set()):
        go(tracker.shares[child_hash], tracker, t, d)

def get(tracker, best):
    d = pygame.Surface((400, 600), 32)
    if tracker.get_height(best) >= 100:
        t = time.time()
        start = tracker.get_nth_parent_hash(best, 100)
        d.fill((0, 0, 0))
        go(tracker.shares[start], tracker, t, d)
    f = StringIO.StringIO()
    Image.fromstring("RGB", d.get_size(), pygame.image.tostring(d, "RGB")).save(f, "png")
    return f.getvalue()
