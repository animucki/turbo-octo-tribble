from email.utils import formatdate
from gzip import GzipFile
from io import BytesIO, TextIOWrapper
from pyproj import Transformer
from xml.etree import ElementTree
import csv
import io
import os
import shutil
import time
import urllib.request
import zipfile
import zmq

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
    except urllib.request.HTTPError as e:
        if e.code == 304:
            print("GTFS unchanged, using cached file")
        else:
            raise

    return zipfile.ZipFile(path)

stops, trips = load_gtfs()


# --- helpers to resolve KV6 codes against GTFS ---
def lookup_stop(stop_code, stops):
    # Try bare code first, then common prefixes
    for candidate in [stop_code, f"GVB:{stop_code}"]:
        if candidate in stops:
            return stops[candidate]
    return stop_code  # fall back to raw code

def lookup_headsign(journey_number, trips):
    for trip_id, headsign in trips.items():
        if journey_number in trip_id:
            return headsign
    return None


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
        "stop_code": stop_code,
        "stop_name": lookup_stop(stop_code, stops) if stop_code else None,
        "headsign": lookup_headsign(journey, trips) if journey else None,
        "journey": journey,
        "punctuality_s": t("punctuality"),
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
    if i > 10:
        break
    i += 1

subscriber.close()
context.term()