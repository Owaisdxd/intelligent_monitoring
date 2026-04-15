import requests
import time
import random

print("🚀 Starting Synthetic Traffic...")
while True:
    try:
        # Simulate users hitting checkout
        requests.post("http://127.0.0.1:5000/checkout")
        # Random sleep to create a "Natural" pattern
        time.sleep(random.uniform(0.1, 2.0))
    except:
        pass