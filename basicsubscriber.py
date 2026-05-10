from gzip import GzipFile
from io import BytesIO
import zmq

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
        print("GZIP", address, contents)
    except:
        print("NOT", address, contents)
        raise

subscriber.close()
context.term()
