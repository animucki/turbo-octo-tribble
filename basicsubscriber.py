from email.utils import formatdate
from gzip import GzipFile
from io import BytesIO, TextIOWrapper
from pyproj import Transformer
from xml.etree import ElementTree
import csv
import os
import shutil
import urllib.error
import urllib.request
import zipfile
import zmq

# --- Memory management --- #
def mem_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    return 0

print(f"Before GTFS: {mem_mb()}MB")

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
        mtime = os.path.getmtime(path)
        headers["If-Modified-Since"] = formatdate(mtime, usegmt=True)

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


# --- helpers to resolve KV6 codes against GTFS ---
def lookup_stop(stop_code):
    return stops.get(stop_code, stop_code)  # fall back to raw code

def lookup_headsign(journey_number):
    return trips.get(journey_number)


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

i = 0
while True:
    multipart = subscriber.recv_multipart()
    contents = b"".join(multipart[1:])
    try:
        contents = GzipFile("", "r", 0, BytesIO(contents)).read()
        tree = ElementTree.fromstring(contents)
        for kv6 in tree.findall(f"{{{kv6_namespace}}}KV6posinfo"):
            for msg in kv6:
                print(parse_message(msg))
    except Exception as ex:
        print(ex)
    i += 1
    if i > 10:
        break

subscriber.close()
context.term()