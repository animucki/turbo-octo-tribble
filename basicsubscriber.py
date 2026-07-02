from email.utils import formatdate
from gzip import GzipFile
from io import BytesIO, TextIOWrapper
from pyproj import Transformer
from xml.etree import ElementTree

import csv
import datetime
import os
import requests
import shutil
import threading
import urllib.error
import urllib.request
import yaml
import zipfile
import zmq

# --- config ---
config = yaml.safe_load(open("config.yaml"))
TELEGRAM_TOKEN = config["telegram"]["token"]
TELEGRAM_CHAT_ID = int(config["telegram"]["chat_id"])
LOG_PATH = "/home/bxa/tram.log"

# --- mute state ---
muted = False
muted_lock = threading.Lock()

# --- memory util ---
def mem_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    return 0

# --- coordinate conversion ---
rd_to_wgs84 = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)

def maps_link(rd_x, rd_y):
    try:
        lon, lat = rd_to_wgs84.transform(int(rd_x), int(rd_y))
        return f"https://maps.google.com/?q={lat},{lon}"
    except:
        return None

# --- GTFS loading ---
GTFS_URL = "https://gtfs.ovapi.nl/nl/gtfs-nl.zip"
GTFS_PATH = "gtfs-nl.zip"
USER_AGENT = "animucki-turbo-octo-tribble/1.0"

def load_gtfs(url=GTFS_URL, path=GTFS_PATH):
    headers = {"User-Agent": USER_AGENT}
    if os.path.exists(path):
        headers["If-Modified-Since"] = formatdate(os.path.getmtime(path), usegmt=True)

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            print("GTFS updated on server, downloading...")
            with open(path, "wb") as f:
                shutil.copyfileobj(r, f)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            print("GTFS unchanged, using cached file")
        else:
            raise

    def build_stops(zf):
        stops = {}
        with zf.open("stops.txt") as f:
            for row in csv.DictReader(TextIOWrapper(f, encoding="utf-8-sig")):
                if row["stop_code"]:
                    stops[row["stop_code"]] = row["stop_name"]
        print(f"Stops loaded: {len(stops)} entries, {mem_mb()}MB")
        return stops

    def build_trips(zf):
        trips = {}
        with zf.open("trips.txt") as f:
            for row in csv.DictReader(TextIOWrapper(f, encoding="utf-8-sig")):
                if row.get("realtime_trip_id", "").startswith("GVB:") and row.get("trip_short_name"):
                    trips[row["trip_short_name"]] = row.get("trip_headsign", "")
        print(f"Trips loaded: {len(trips)} entries, {mem_mb()}MB")
        return trips

    with zipfile.ZipFile(path) as zf:
        print(f"Zip opened: {mem_mb()}MB")
        stops = build_stops(zf)
        trips = build_trips(zf)

    return stops, trips

stops, trips = load_gtfs()

# --- GTFS lookups ---
def lookup_stop(stop_code):
    return stops.get(stop_code, stop_code)

def lookup_headsign(journey_number):
    return trips.get(journey_number)

# --- alerting ---
def send_telegram(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram send error: {e}")

def log(text):
    with open(LOG_PATH, "a") as f:
        f.write(text + "\n")

def alert(text):
    log(text)
    with muted_lock:
        is_muted = muted
    if not is_muted:
        send_telegram(text)

# --- Telegram command polling ---
def telegram_poll():
    global muted
    offset = None
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            r = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params=params,
                timeout=40
            )
            for update in r.json().get("result", []):
                offset = update["update_id"] + 1

                message = update.get("message", {})

                # ignore messages from anyone other than the configured chat
                if message.get("chat", {}).get("id") != TELEGRAM_CHAT_ID:
                    continue

                text = message.get("text", "").strip().lower()
                if text == "/mute":
                    with muted_lock:
                        muted = True
                    send_telegram("Muted. Still logging.")
                elif text == "/unmute":
                    with muted_lock:
                        muted = False
                    send_telegram("Unmuted.")
        except Exception as e:
            print(f"Telegram poll error: {e}")
            import time; time.sleep(5)

threading.Thread(target=telegram_poll, daemon=True).start()

# --- KV6 parsing ---
kv6_namespace = "http://bison.connekt.nl/tmi8/kv6/msg"

def parse_message(msg, ns=kv6_namespace):
    def t(tag): return msg.findtext(f"{{{ns}}}{tag}")
    stop_code = t("userstopcode")
    journey = t("journeynumber")
    return {
        "type": msg.tag.split("}")[1],
        "line": t("lineplanningnumber"),
        "vehicle": t("vehiclenumber"),
        "stop_name": lookup_stop(stop_code) if stop_code else None,
        "headsign": lookup_headsign(journey) if journey else None,
        "location": maps_link(t("rd-x"), t("rd-y"))
    }

# --- subscriber ---
context = zmq.Context()
subscriber = context.socket(zmq.SUB)
subscriber.connect("tcp://pubsub.besteffort.ndovloket.nl:7658")
subscriber.setsockopt_string(zmq.SUBSCRIBE, "/GVB/KV6posinfo")

while True:
    multipart = subscriber.recv_multipart()
    contents = b"".join(multipart[1:])
    try:
        contents = GzipFile("", "r", 0, BytesIO(contents)).read()
        tree = ElementTree.fromstring(contents)
        for kv6 in tree.findall(f"{{{kv6_namespace}}}KV6posinfo"):
            for msg in kv6:
                parsed = parse_message(msg)
                if parsed["vehicle"] in ["2202", "2203"]:
                    text = (f"[{datetime.datetime.now().isoformat(timespec='seconds')}] "
                            f"Vehicle {parsed['vehicle']} {parsed['type']} "
                            f"line {parsed['line']} direction {parsed['headsign']} "
                            f"at {parsed['stop_name']}: {parsed['location']}")
                    alert(text)
    except Exception as ex:
        print(ex)