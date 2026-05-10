from gzip import GzipFile
from io import BytesIO
from pyproj import Transformer
from xml.etree import ElementTree
import zmq

def maps_link(rd_x, rd_y):
    rd_to_wgs84 = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
    lon, lat = rd_to_wgs84.transform(int(rd_x), int(rd_y))
    return f"https://maps.apple.com/?ll={lat},{lon}"


kv6_namespace = "http://bison.connekt.nl/tmi8/kv6/msg"
def parse_message(msg, ns=kv6_namespace):
    def t(tag): return msg.findtext(f"{{{ns}}}{tag}")

    return {
        "type": msg.tag.split("}")[1],
        "line": t("lineplanningnumber"),
        "vehicle": t("vehiclenumber"),
        "stop_code": t("userstopcode"),
        "journey": t("journeynumber"),
        "punctuality_s": t("punctuality"),
        "location": maps_link(t("rd-x"), t("rd-y"))
    }


context = zmq.Context()

subscriber = context.socket(zmq.SUB)
subscriber.connect("tcp://pubsub.besteffort.ndovloket.nl:7658")
subscriber.setsockopt_string(zmq.SUBSCRIBE, "/GVB/KV6posinfo")

while True:
    multipart = subscriber.recv_multipart()
    address = multipart[0]
    contents = b"".join(multipart[1:])
    try:
        contents = GzipFile("", "r", 0, BytesIO(contents)).read()
        # print("GZIP", address, contents)
        tree = ElementTree.fromstring(contents)
        for kv6 in tree.findall(f"{{{kv6_namespace}}}KV6posinfo"):
            for msg in kv6:
                print(parse_message(msg))
    except:
        print("NOT", address, contents)
        raise

subscriber.close()
context.term()
