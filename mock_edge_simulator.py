import os
import time
import httpx
import json
from datetime import datetime

backend_url = f"http://localhost:{os.environ.get('PORT', '8443')}"
print(f"Mock Edge Simulator starting. Targeting {backend_url}")

time.sleep(10)

# Load real events from the saved JSON so boxes and scores are 100% accurate
events_file = os.path.join(os.path.dirname(__file__), "current_events_utf8.json")
with open(events_file, "r", encoding="utf-8") as f:
    real_events = json.load(f)

# Sort events chronologically based on their original timestamp
real_events.sort(key=lambda x: x["timestamp"])

while True:
    for i, event in enumerate(real_events):
        # Calculate delay based on original timestamps, if not first event
        if i > 0:
            t1 = datetime.strptime(real_events[i-1]["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
            t2 = datetime.strptime(event["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
            delay = (t2 - t1).total_seconds()
            # Cap delay to avoid huge gaps if the log has them
            if delay > 0 and delay < 10:
                time.sleep(delay)
            else:
                time.sleep(1)
        else:
            time.sleep(2)
        
        # Create a deep copy to mutate
        payload = dict(event)
        
        # Update timestamp to right now so the UI sees it as a live event
        payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Generate a new unique ID so the DB accepts it as a new event
        import uuid
        payload["id"] = str(uuid.uuid4())
        
        try:
            response = httpx.post(f"{backend_url}/api/sync/events", json=[payload])
            if response.status_code in [200, 201, 202]:
                print(f"Injected real event {payload['event_type']} from {payload['camera_id']}")
            else:
                print(f"Failed to inject: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Simulator error: {e}")
            
    # Short pause before restarting the loop
    time.sleep(5)
