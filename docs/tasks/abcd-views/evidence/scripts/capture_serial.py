import serial, sys, time, datetime
port = "/dev/cu.usbmodem31301"
out = sys.argv[1]
def log(msg):
    print(msg, flush=True)
with serial.Serial(port, 115200, timeout=0.5, rtscts=False, dsrdtr=False) as ser:
    ser.dtr = False
    ser.rts = False
    log(f"# capture start {port} 115200 {datetime.datetime.now().isoformat(timespec='seconds')}")
    with open(out, "w", buffering=1) as f:
        while True:
            chunk = ser.read(4096)
            if chunk:
                text = chunk.decode("utf-8", "replace")
                f.write(text)
                f.flush()
