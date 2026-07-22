"""MASSIVE-like scientific kernel para testing."""


def compute_kinetic_energy(mass, velocity):
    """Energía cinética: 0.5 * m * v²"""
    return 0.5 * mass * velocity * velocity


def compute_potential_energy(mass, height):
    """Energía potencial: m * g * h"""
    return mass * 9.81 * height


def compute_total_energy(particles):
    """Calcula energía total de un conjunto de partículas."""
    total = 0.0
    for p in particles:
        total += compute_kinetic_energy(p["mass"], p["vx"])
        total += compute_kinetic_energy(p["mass"], p["vy"])
        total += compute_potential_energy(p["mass"], p["y"])
    return total


def update_positions(particles, dt):
    """Actualiza posiciones usando velocidad."""
    for p in particles:
        p["x"] += p["vx"] * dt
        p["y"] += p["vy"] * dt


def update_velocities(particles, dt):
    """Actualiza velocidades con gravedad."""
    for p in particles:
        p["vy"] -= 9.81 * dt


def energy_step(particles, dt):
    """Un paso de simulación con energía."""
    update_velocities(particles, dt)
    update_positions(particles, dt)
    energy = compute_total_energy(particles)
    mass = sum(p["mass"] for p in particles)
    return {"total_energy": energy, "mass_delta": 0.0,
            "temperature": energy / max(mass, 1e-10)}


def run_simulation(num_particles=1000, steps=100, dt=0.01):
    """Ejecuta simulación completa."""
    import random
    rng = random.Random(42)
    particles = [{"x": rng.uniform(0, 100), "y": rng.uniform(0, 100),
                  "vx": rng.uniform(-10, 10), "vy": rng.uniform(-10, 10),
                  "mass": rng.uniform(0.1, 10.0)}
                 for _ in range(num_particles)]
    trajectory = []
    for _ in range(steps):
        trajectory.append(energy_step(particles, dt))
    return trajectory