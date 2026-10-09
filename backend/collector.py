import time
import datetime
from pylxd import Client
from pylxd.exceptions import LXDAPIException
from tinyflux import TinyFlux, Point
from requests.exceptions import ConnectionError

TINYFLUX_PATH = 'metrics.db'
POLL_INTERVAL = 10  # Seconds

def collect_metrics():
    # Initialize TinyFlux Database
    db = TinyFlux(TINYFLUX_PATH)
    
    print(f"Background Collector started. Polling every {POLL_INTERVAL} seconds...")
    
    while True:
        try:
            # Connect to LXD (this runs locally, so no args needed)
            client = Client()
            
            # Fetch all containers
            containers = client.containers.all()
            points = []
            now = datetime.datetime.now(datetime.timezone.utc)
            
            for container in containers:
                # We only care about running containers
                if container.status != 'Running':
                    continue
                
                try:
                    # Get the current state (memory, cpu, network, etc.)
                    state = container.state()
                    
                    # Memory parsing
                    mem_used = state.memory.get('usage', 0)
                    
                    # CPU parsing (nanoseconds used)
                    cpu_used = state.cpu.get('usage', 0)
                    
                    # Network parsing (summing eth0 or all interfaces)
                    net_rx = 0
                    net_tx = 0
                    for interface, data in state.network.items():
                        if interface != 'lo':  # Ignore localhost loopback
                            net_rx += data.counters.get('bytes_received', 0)
                            net_tx += data.counters.get('bytes_sent', 0)
                            
                    # Disk usage parsing (root disk)
                    disk_used = 0
                    if 'root' in state.disk:
                        disk_used = state.disk['root'].get('usage', 0)
                        
                    # Create a TinyFlux data point
                    point = Point(
                        time=now,
                        tags={"container_name": container.name},
                        fields={
                            "memory_usage_bytes": mem_used,
                            "cpu_usage_ns": cpu_used,
                            "network_rx_bytes": net_rx,
                            "network_tx_bytes": net_tx,
                            "disk_usage_bytes": disk_used,
                        }
                    )
                    points.append(point)
                    
                except Exception as e:
                    print(f"[{now}] Error collecting metrics for container {container.name}: {e}")
            
            # Insert all points into TinyFlux at once
            if points:
                db.insert_multiple(points)
                print(f"[{now}] Saved metrics for {len(points)} containers.")
                
        except (ConnectionError, LXDAPIException) as e:
            # Requirements: Ensure it doesn't crash if LXD is temporarily unavailable
            print(f"[{datetime.datetime.now(datetime.timezone.utc)}] LXD is unreachable. Will retry in 10s... ({e})")
        except Exception as e:
            print(f"[{datetime.datetime.now(datetime.timezone.utc)}] Unexpected error: {e}")
            
        # Wait for the next interval
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    collect_metrics()
