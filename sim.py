"""
sim.py - fake world for developing without the dog or phones.

Hidden objects come from the "sim_truth" field of each spot in the spots file.
Includes Earth's field (Boston-ish), a constant offset from the dog's own
magnetism at each phone, and sensor noise.
"""
import numpy as np

from dipole import dipole_b


class SimWorld:
    def __init__(self, spots, h_low, h_high, sensor_start, noise_per_sample=0.5, seed=0):
        inc = np.radians(66)
        self.earth = 51.0 * np.array([np.cos(inc), 0.0, -np.sin(inc)])  # arena +x = north
        e_hat = self.earth / np.linalg.norm(self.earth)
        self.dog = [np.array([1.5, -0.8, 0.6]), np.array([0.9, -0.5, 0.4])]  # uT at low/high phone
        self.h = [h_low, h_high]
        self.sensor = np.array(sensor_start, float)
        self.noise = noise_per_sample
        self.rng = np.random.default_rng(seed)
        self.objects = []
        for s in spots:
            t = s.get("sim_truth")
            if not t:
                continue
            src = np.array([s["x"] + t.get("dx", 0.0), s["y"] + t.get("dy", 0.0), -t["depth"]])
            m = np.array(t["m_vec"]) if "m_vec" in t else t["moment"] * e_hat
            self.objects.append((src, m))

    def field(self, which):
        obs = np.array([[*self.sensor, self.h[which]]])
        b = self.earth + self.dog[which]
        for src, m in self.objects:
            b = b + dipole_b(obs, src, m)[0]
        return b


class SimPhone:
    def __init__(self, world, which, rate_hz=50):
        self.w, self.which, self.rate = world, which, rate_hz

    def start(self):
        pass

    def sample(self, seconds):
        b = self.w.field(self.which)
        n = max(3, int(seconds * self.rate))
        arena = b + self.w.rng.normal(0, self.w.noise, (n, 3))
        return np.column_stack([-arena[:, 1], arena[:, 0], arena[:, 2]])  # arena -> phone frame


class SimMover:
    def __init__(self, world):
        self.w = world

    def preflight(self):
        pass

    def move(self, dx, dy, target=None):
        self.w.sensor = self.w.sensor + np.array([dx, dy])

    def observe(self):
        return "(sim) photo of cardboard square"
