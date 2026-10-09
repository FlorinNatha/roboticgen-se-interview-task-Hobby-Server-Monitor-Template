# Final Report — Hobby Server Monitor

## Time Spent

Rough breakdown, not a timesheet.

| Area | Time |
| --- | --- |
| Backend (API, auth, authorization) | ~3 hours |
| Dashboard (Astro frontend) | ~3.5 hours |
| LXD integration | ~2.5 hours |
| Background collector / TSDB | ~2.5 hours |
| Debugging | ~1.5 hour |
| Documentation / report | ~1 hours |
| **Total** | **~14 hours** |

## Key Decisions

**1. Where in your system does an authorization decision get made, and how do you stop an endpoint written next month from missing it?**
I implemented an `AuthMiddleware` at the Falcon application level that is applied universally before any route logic executes. It intercepts every request and validates the JWT from `session_token`. The context object is then populated with the user (`req.context.user`). This means any endpoint written next month will inherently reject unauthenticated requests. Inside specific resources (like `UsersResource`), role-based authorization is performed explicitly (e.g., `if user['role'] != 'admin': raise falcon.HTTPForbidden()`).

**2. How does this run on the machine, and how does it come back after a reboot?**
I chose to write `systemd` service files (`systemd/hobby-monitor-api.service`, `systemd/hobby-monitor-collector.service`, and `systemd/hobby-monitor-dashboard.service`). This integrates natively with Linux's standard init system. By using `Restart=always` and `WantedBy=multi-user.target`, Linux ensures that the API, background collector, and frontend are all automatically restarted if they crash and are turned on immediately when the physical host finishes booting up. This avoids hacks like `@reboot` in cron.

**3. What exactly does a quota measure, and what happens at the moment someone reaches theirs?**
A quota in this system measures the **total allocated limits** across all containers a user owns, regardless of their current running state. It does *not* measure real-time dynamic usage. If a user is allocated a 2GB RAM quota, they cannot create three 1GB containers, even if they only run one at a time. The check happens on the `POST /api/containers` endpoint and `PUT /api/containers/{name}/limits`. If a creation or limit increase would cause the sum of their container limits to exceed their quota, the API rejects it with an HTTP 400.

**4. How real is your terminal, and what can an authenticated user do with it that you did not intend?**
The web terminal sends arbitrary shell commands via the `/terminal` API endpoint which executes them using `pylxd`'s `container.execute()`. This is highly privileged. While the user is authenticated and isolated to their specific container, they have `root` inside that container. If LXD is not perfectly sandboxed (e.g., privileged containers instead of unprivileged), a user could potentially escape to the host. The alternative was restricting them to predefined scripts or safe commands, but I decided the requirement of a "secure terminal" meant they should have full shell access inside their container namespace.

## Issues Encountered and Solutions

- **TinyFlux and Multi-Threading:** We initially ran into file-locking and concurrency issues between the background `collector.py` writing to `metrics.db` and the Falcon `app.py` reading it for historical charts. We mitigated this by ensuring the collector only appends, and reading queries from `app.py` use snapshotting.
- **LXD Networking Object API:** Accessing `container.state().network` returned a dictionary in some pylxd versions but was documented as an object. Accessing `.counters` on it crashed the collector. I solved this by using dictionary `.get('counters', {})` with fallbacks.
- **Chart.js Reactivity:** The historical charts on the dashboard were redrawing on top of themselves during polling refreshes. I handled this by ensuring the chart canvas is completely destroyed and re-instantiated in the DOM on refresh, keeping it stateless.

## What You Learned

I learned the importance of true separation of concerns when building telemetry systems. By decoupling the `collector.py` process entirely from the `app.py` web server, I experienced firsthand how much simpler it is to reason about data freshness and polling logic. The API simply serves what it finds in the TSDB without complex async loops blocking web requests.

## Bonus Features Implemented

- **Systemd Unit Files:** Provided a full suite of `.service` files and a `setup.sh` installer to guarantee the system restarts on reboot.
- **Historical Charting:** Integrated `Chart.js` on the dashboard to provide real-time updating graphs of the last 10 minutes of RAM usage for every running container.
- **Host Accounting:** Created an admin panel that uses `psutil` to query the physical host server's total RAM and CPU and alerts the admin if they have over-provisioned the container limits beyond physical capacity.
- **Dynamic Limit Scaling:** Users can instantly update the RAM and CPU limits of a container on the fly via the dashboard without needing to recreate it.

## Resource Measurements

- **Collector Idle:** Hovering around `18MB` of RAM and `< 1%` CPU on Ubuntu 24.04. Measured using `top -p $(pgrep -f collector.py)`.
- **Falcon API Idle:** Hovering around `22MB` of RAM and `0%` CPU. Measured using `ps aux | grep app.py`.
- **Astro Frontend:** Minimal browser footprint (Chart.js adds slight rendering overhead but is destroyed efficiently).

## Known Limitations

- **LXD Cumulative CPU:** Currently, CPU metrics are captured but calculating exact percentage usage requires delta math between two polling intervals. It is partially implemented, but heavily fluctuating workloads may show delayed spikes due to the 10-second polling interval.
- **HTTPS/WSS:** The terminal currently works over standard HTTP. For production, it must be upgraded to WSS/HTTPS to prevent packet sniffing of terminal sessions.

## AI Tool Usage

I paired with Antigravity AI for this project.
- **Backend:** Used AI to architect the `TinyFlux` query patterns and debug the `pylxd` dictionary access errors in the collector.
- **Frontend:** Used AI to heavily style the CSS interface, set up the grid system, and integrate the `Chart.js` components into the Astro components.
- **DevOps:** Prompted AI to generate the `systemd` `.service` definitions and verify the `WantedBy` targets.
I reviewed, modified, and approved all code injected by the assistant, particularly ensuring the RBAC logic in Falcon endpoints was solid.
