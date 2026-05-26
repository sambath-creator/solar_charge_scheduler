# Solar Charging Scheduler Design Approach

This document outlines the design decisions, mathematical models, and architectural framework chosen to implement the Solar Charging Scheduler.

---

## 1. System Architecture

The agent is designed to run locally, minimizing external service dependencies. It uses a zero-dependency Python structure scheduled by standard OS processes.

## 2. Solar Estimation & Mathematical Calculations

### Panel Orientation Coordinates
For a property in Dartford, UK:
- **Latitude & Longitude**: Resolved to `51.458° N, 0.208° E`.
- **Tilt**: The default is set to `35°` relative to the horizontal, capturing optimal year-round sunlight in the UK.
- **Azimuth**: Open-Meteo uses the convention: `0° = South`, `90° = West`. Since the panels face South-West, the azimuth is mathematically mapped to `45°`.

### Global Tilted Irradiance (GTI)
Instead of using standard Global Horizontal Irradiance (GHI) which assumes flat panels, the agent fetches **Global Tilted Irradiance (GTI)**. The Open-Meteo API calculates this dynamically using the specified `tilt` and `azimuth` to estimate the real sunlight hitting the SW-angled panel plane.

### Optimal Battery Charging Window Algorithm
We define the window based on peak daily intensity to maximize charging efficiency:

1. **Calculate Daily Energy Density**:
   $$\text{Total Daily Energy (Wh/m}^2) = \sum_{t=0}^{23} \text{GTI}(t) \text{ W/m}^2 \times 1\text{ hour}$$
   This sum is divided by 1000 to report the day's solar potential in **$\text{kWh/m}^2$**.

2. **Compute Optimal Window**:
   - Find Peak Irradiance: $I_{\text{peak}} = \max(\text{GTI}(t))$
   - Define Threshold: $I_{\text{threshold}} = 0.5 \times I_{\text{peak}}$
   - A hour $h$ is qualified for charging if:
     $$\text{GTI}(h) \geq I_{\text{threshold}} \quad \text{and} \quad I_{\text{peak}} \geq 20 \text{ W/m}^2$$
   - The charging window begins at the minimum qualified hour $h_{\text{start}}$ and ends at $h_{\text{end}} + 1$ (representing the end of the last hourly block).

### Solar Rating System
Days are categorized dynamically to give users context at a glance:
- **Excellent**: $\geq 5.0\text{ kWh/m}^2$ (Max battery charging potential)
- **Good**: $3.0\text{ to }5.0\text{ kWh/m}^2$ (Highly efficient charging)
- **Moderate**: $1.5\text{ to }3.0\text{ kWh/m}^2$ (Partial charging)
- **Poor**: $< 1.5\text{ kWh/m}^2$ (Minimal charging utility)

---

## 3. UI/UX & Email Aesthetics

To ensure a high-end experience, the email is structured like a premium SaaS dashboard:
* **Dark Theme Palette**: Employs slate-blue backgrounds (`#0a0f1d` and `#0f172a`) to match modern smart home aesthetics.
* **Glassmorphism Metrics**: High-priority data cards feature glowing gradients (e.g. golden yellow for battery/sun intensity).
* **Relative Strength Bars**: The hourly breakdown features inline CSS data bars mapping the percentage of relative irradiance relative to the day's peak, allowing the user to scan the peak hours visually in under 2 seconds.

---

## 4. Robustness & Portability

- **No Third-Party Python Dependencies**: The core script uses standard libraries (`urllib`, `smtplib`, `ssl`, etc.) to run on any machine containing a Python installation without executing complex environment setup.
- **Fail-Safe "Dry-Run" Mode**: If SMTP parameters are missing or an error occurs during email transmission, the script does not crash. It automatically creates local text and HTML files (`last_email.txt` / `last_email.html`) and log details to let the user preview the output easily.
- **Windows Task Scheduler Integration**: Windows Task Scheduler executes a batch script (`run.bat`) which resolves relative file paths locally, preventing errors caused by running the script from different active folders.
