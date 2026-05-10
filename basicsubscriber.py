from gzip import GzipFile
from io import BytesIO
from xml.etree import ElementTree
import zmq

namespace = "http://bison.connekt.nl/tmi8/kv6/msg"

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
        for kv6 in tree.findall(f"{{{namespace}}}KV6posinfo"):
            for msg in kv6:
                vehicle = msg.findtext(f"{{{namespace}}}vehiclenumber")
                msg_type = msg.tag.split("}")[1]  # strips namespace from INIT, ONROUTE etc.
                print(msg_type, vehicle)
    except:
        print("NOT", address, contents)
        raise

subscriber.close()
context.term()
