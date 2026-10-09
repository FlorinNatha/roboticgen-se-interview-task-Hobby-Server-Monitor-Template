#!/bin/bash
echo "Installing Hobby Server Monitor Systemd Services..."

# Copy service files to systemd directory
sudo cp *.service /etc/systemd/system/

# Reload systemd to recognize new files
sudo systemctl daemon-reload

# Enable them to start on boot
sudo systemctl enable hobby-monitor-api
sudo systemctl enable hobby-monitor-collector
sudo systemctl enable hobby-monitor-dashboard

# Start the services right now
sudo systemctl start hobby-monitor-api
sudo systemctl start hobby-monitor-collector
sudo systemctl start hobby-monitor-dashboard

echo "Services installed and started! They will now survive reboots."
