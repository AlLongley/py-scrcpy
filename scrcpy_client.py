''' 
Android viewing/controlling SCRCPY client class written in Python.
Emphasis on near-zero latency, and low overhead for use in 
Machine Learning/AI scenarios.

Check out the SCRCPY project here:
https://github.com/Genymobile/scrcpy/

NB: must be placed in the same directory as SCRCPY,
with adb and ffmpeg in ya PATH. 

Running stand-alone spawns an OpenCV2 window to view data real-time.
'''

import socket
import struct
import sys
import subprocess
import io
import time
import numpy as np

from threading import Thread
from queue import Queue, Empty

IP = '127.0.0.1'
PORT = 8080
RECVSIZE = 10000


def stdout_thread(self):
    print("START STDOUT THREAD")
    while self.ACTIVE:
        rd = self.ffm.stdout.read(self.bytes_to_read)
        if rd:
            self.bytes_rcvd += len(rd)
            self.images_rcvd += 1
            self.ffoutqueue.put(rd)
    print("FINISH STDOUT THREAD")


def stderr_thread(self):
    print("START STDERR THREAD")
    while self.ACTIVE:
        rd = self.ffm.stderr.readline()
        if rd:
            self.OUT.append(rd.decode("utf-8"))
    print("FINISH STDERR THREAD")


def stdin_thread(self):
    print("START STDIN THREAD")

    while self.ACTIVE:
        data = self.sock.recv(RECVSIZE)
        self.bytes_sent += len(data)
        self.ffm.stdin.write(data)

    print("FINISH STDIN THREAD")


class SCRCPY_client():
    def __init__(self):
        self.bytes_sent = 0
        self.bytes_rcvd = 0
        self.images_rcvd = 0
        self.bytes_to_read = 0
        self.OUT = []
        self.ACTIVE = True
        self.LANDSCAPE = True
        self.FFMPEGREADY = False
        self.ffoutqueue = Queue()

    def get_next_frame(self, skip=0):
        if self.ffoutqueue.empty():
            return None
        frm = self.ffoutqueue.get()

        frm = np.frombuffer(frm, dtype=np.ubyte)
        frm = frm.reshape((self.HEIGHT, self.WIDTH, 3))
        return frm
        # PIL.Image.fromarray(np.uint8(rgb_img*255))

    def connect(self):
        print("Connecting")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((IP, PORT))

        DUMMYBYTE = self.sock.recv(1)
        if not len(DUMMYBYTE):
            print("Failed to connect!")
            exit()
        else:
            print("Connected!")

        # Receive device specs
        self.deviceName = self.sock.recv(64).decode("utf-8")
        print("Device Name:", self.deviceName)

        res = self.sock.recv(4)
        self.WIDTH, self.HEIGHT = struct.unpack(">HH", res)
        print("WxH:", self.WIDTH, "x", self.HEIGHT)

        self.bytes_to_read = self.WIDTH * self.HEIGHT * 3

    def start_processing(self):
        # Start FFPlay in pipe mode
        #ffmpegCmd =['ffmpeg', '-i', '-','-vf', 'scale=1920x1080', 'myout.mp4']

        ffmpegCmd = ['ffmpeg', '-y',
                     '-r', '20', '-i', 'pipe:0',
                     '-vcodec', 'rawvideo',
                     '-pix_fmt', 'rgb24',
                     '-f', 'image2pipe',
                     'pipe:1']

        self.ffm = subprocess.Popen(ffmpegCmd,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)

        self.ffoutthrd = Thread(target=stdout_thread,
                                args=(self,))
        self.fferrthrd = Thread(target=stderr_thread,
                                args=(self,))
        self.ffinthrd = Thread(target=stdin_thread,
                               args=(self,))
        self.ffoutthrd.daemon = self.fferrthrd.daemon = self.ffinthrd.daemon = True

        self.fferrthrd.start()
        time.sleep(0.25)
        self.ffinthrd.start()
        time.sleep(0.25)
        self.ffoutthrd.start()

        print("Waiting on FFmpeg to detect source", end='', flush=True)
        for i in range(20):
            print('.', end='', flush=True)
            if any(["Output #0, image2pipe" in x for x in self.OUT]):
                print("Ready!")
                self.FFMPEGREADY = True
                break
            time.sleep(0.25)
        else:
            print("FFmpeg error?")
            print(self.OUT)


if __name__ == "__main__":
    print("Upload JAR")
    subprocess.Popen("adb push scrcpy-server.jar /data/local/tmp/".split(" "))
    time.sleep(1)
    print("Run JAR")
    subprocess.Popen(
        "adb shell CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / com.genymobile.scrcpy.Server 800 80000000 true".split(" "))
    time.sleep(1)
    print("Forward Port")
    subprocess.Popen("adb forward tcp:8080 localabstract:scrcpy".split(" "))

    SCRCPY = SCRCPY_client()
    SCRCPY.connect()
    SCRCPY.start_processing()

    frameskip = 0
    import cv2
    try:
        while True:
            while True:
                frm = SCRCPY.get_next_frame()
                if isinstance(frm, (np.ndarray, np.generic)):
                    showfrm = frm
                    frameskip += 1
                else:
                    break

            cv2.imshow("image", showfrm)
            cv2.waitKey(1)  # CAP 60FPS
            print("CV2 frameskip =", frameskip)
            frameskip = 0
    except KeyboardInterrupt:
        from IPython import embed
        embed()
