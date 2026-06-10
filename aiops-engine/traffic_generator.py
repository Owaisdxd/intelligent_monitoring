import requests
import time
import random

print("Starting sending requests to application...")
while True:
    try:
        requests.post("http://127.0.0.1:5000/checkout")
        time.sleep(random.uniform(0.1, 2.0))
    except:
        pass