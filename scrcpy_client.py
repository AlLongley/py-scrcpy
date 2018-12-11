''' 
Android viewing/controlling SCRCPY client class written in Python.
Emphasis on near-zero latency, and low overhead for use in 
Machine Learning/AI scenarios.

Check out the SCRCPY project here:
https://github.com/Genymobile/scrcpy/

NB: Don't forget to set your path to scrcpy/adb

Running stand-alone spawns an OpenCV2 window to view data real-time.
'''

import socket
import struct
import sys
import os
import subprocess
import io
import time
import numpy as np
import logging

from threading import Thread
from queue import Queue, Empty

SVR_maxSize = 600
SVR_bitRate = 999999999
SVR_tunnelForward = "true"
SVR_crop = "9999:9999:0:0"
SVR_sendFrameMeta = "true"

IP = '127.0.0.1'
PORT = 8080
RECVSIZE = 0x10000
HEADER_SIZE  = 12

SCRCPY_dir = 'C:\\Users\\Al\\Downloads\\scrcpy-win64-v1.5\\scrcpy-win64\\'
FFMPEG_bin = 'ffmpeg'
ADB_bin = os.path.join(SCRCPY_dir,"adb")
#fd = open("savesocksession",'wb')

logger = logging.getLogger(__name__)

class SCRCPY_client():
    def __init__(self):
        self.bytes_sent = 0
        self.bytes_rcvd = 0
        self.images_rcvd = 0
        self.bytes_to_read = 0
        self.FFmpeg_info = []
        self.ACTIVE = True
        self.LANDSCAPE = True
        self.FFMPEGREADY = False
        self.ffoutqueue = Queue()


    def stdout_thread(self):
        logger.info("START STDOUT THREAD")
        while self.ACTIVE:
            rd = self.ffm.stdout.read(self.bytes_to_read)
            if rd:
                self.bytes_rcvd += len(rd)
                self.images_rcvd += 1
                self.ffoutqueue.put(rd)
        logger.info("FINISH STDOUT THREAD")

    def stderr_thread(self):
        logger.info("START STDERR THREAD")
        while self.ACTIVE:
            rd = self.ffm.stderr.readline()
            if rd:
                self.FFmpeg_info.append(rd.decode("utf-8"))
        logger.info("FINISH STDERR THREAD")

    def stdin_thread(self):
        logger.info("START STDIN THREAD")
        
        while self.ACTIVE:
            if SVR_sendFrameMeta:
                header = self.sock.recv(HEADER_SIZE)
                #fd.write(header)
                pts = int.from_bytes(header[:8],
                    byteorder='big', signed=False)
                frm_len = int.from_bytes(header[8:],
                    byteorder='big', signed=False)
                
                
               
                data = self.sock.recv(frm_len)
                #fd.write(data)
                self.bytes_sent += len(data)
                self.ffm.stdin.write(data)
            else:
                data = self.sock.recv(RECVSIZE)
                self.bytes_sent += len(data)
                self.ffm.stdin.write(data)

        logger.info("FINISH STDIN THREAD")

    def get_next_frame(self, most_recent=False):
        if self.ffoutqueue.empty():
            return None
        
        if most_recent:
            frames_skipped = -1
            while not self.ffoutqueue.empty():
                frm = self.ffoutqueue.get()
                frames_skipped +=1
        else:
            frm = self.ffoutqueue.get()

        frm = np.frombuffer(frm, dtype=np.ubyte)
        frm = frm.reshape((self.HEIGHT, self.WIDTH, 3))
        return frm
        # PIL.Image.fromarray(np.uint8(rgb_img*255))

    def connect(self):
        logger.info("Connecting")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((IP, PORT))

        DUMMYBYTE = self.sock.recv(1)
        #fd.write(DUMMYBYTE)
        if not len(DUMMYBYTE):
            raise ConnectionError("Did not recieve Dummy Byte!")
        else:
            logger.info("Connected!")

        # Receive device specs
        devname = self.sock.recv(64)
        #fd.write(devname)
        self.deviceName = devname.decode("utf-8")
        
        if not len(self.deviceName):
            raise ConnectionError("Did not recieve Device Name!")
        logger.info("Device Name: "+self.deviceName)
        
        res = self.sock.recv(4)
        #fd.write(res)
        self.WIDTH, self.HEIGHT = struct.unpack(">HH", res)
        logger.info("WxH: "+str(self.WIDTH)+"x"+str(self.HEIGHT))

        self.bytes_to_read = self.WIDTH * self.HEIGHT * 3
        
        return True
        
    def start_processing(self, connect_attempts=200):
        # Set up FFmpeg 
        ffmpegCmd = [FFMPEG_bin, '-y',
                     '-r', '20', '-i', 'pipe:0',
                     '-vcodec', 'rawvideo',
                     '-pix_fmt', 'rgb24',
                     '-f', 'image2pipe',
                     'pipe:1']
        try:
            self.ffm = subprocess.Popen(ffmpegCmd,
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise FileNotFoundError("Couldn't find FFmpeg at path FFMPEG_bin: "+
                            str(FFMPEG_bin))
        self.ffoutthrd = Thread(target=self.stdout_thread,
                                args=())
        self.fferrthrd = Thread(target=self.stderr_thread,
                                args=())
        self.ffinthrd = Thread(target=self.stdin_thread,
                               args=())
        self.ffoutthrd.daemon = True
        self.fferrthrd.daemon = True
        self.ffinthrd.daemon = True

        self.fferrthrd.start()
        time.sleep(0.25)
        self.ffinthrd.start()
        time.sleep(0.25)
        self.ffoutthrd.start()

        logger.info("Waiting on FFmpeg to detect source")
        for i in range(connect_attempts):
            if any(["Output #0, image2pipe" in x for x in self.FFmpeg_info]):
                logger.info("Ready!")
                self.FFMPEGREADY = True
                break
            time.sleep(1)
            logger.info('still waiting on FFmpeg...')
        else:
            logger.error("FFmpeg error?")
            logger.error(''.join(self.FFmpeg_info))
            raise Exception("FFmpeg could not open stream")
        return True
    
    def kill_ffmpeg(self):
        self.ffm.terminate()
        self.ffm.kill()  
        #self.ffm.communicate()
    def __del__(self):
        
        self.ACTIVE = False
        
        self.fferrthrd.join()
        self.ffinthrd.join()
        self.ffoutthrd.join()
        
def connect_and_forward_scrcpy():
    try:
        logger.info("Upload JAR...")
        adb_push = subprocess.Popen(
            [ADB_bin,'push',
            os.path.join(SCRCPY_dir,'scrcpy-server.jar'),
            '/data/local/tmp/'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=SCRCPY_dir)
        adb_push_comm = ''.join([x.decode("utf-8") for x in adb_push.communicate() if x is not None])
        
        if "error" in adb_push_comm:
            logger.critical("Is your device/emulator visible to ADB?")
            raise Exception(adb_push_comm)
        '''
        ADB Shell is Blocking, don't wait up for it 
        Args for the server are as follows:
        maxSize         (integer, multiple of 8) 0
        bitRate         (integer)
        tunnelForward   (optional, bool) use "adb forward" instead of "adb tunnel"
        crop            (optional, string) "width:height:x:y"
        sendFrameMeta   (optional, bool) 
        
        '''
        logger.info("Run JAR")
        subprocess.Popen(
            [ADB_bin,'shell',
            'CLASSPATH=/data/local/tmp/scrcpy-server.jar',
            'app_process','/','com.genymobile.scrcpy.Server',
            str(SVR_maxSize),str(SVR_bitRate),
            SVR_tunnelForward, SVR_crop, SVR_sendFrameMeta],
            cwd=SCRCPY_dir)
        time.sleep(1)
        
        logger.info("Forward Port")
        subprocess.Popen(
            [ADB_bin,'forward',
            'tcp:8080','localabstract:scrcpy'],
            cwd=SCRCPY_dir).wait()
        time.sleep(1)
    except FileNotFoundError:
        raise FileNotFoundError("Couldn't find ADB at path ADB_bin: "+
                    str(ADB_bin))
    return True
    
    
if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    
    assert connect_and_forward_scrcpy()
        
    SCRCPY = SCRCPY_client()
    SCRCPY.connect()
    SCRCPY.start_processing()
    
    import cv2
    try:
        while True:
            frm = SCRCPY.get_next_frame(most_recent=False)
            if isinstance(frm, (np.ndarray, np.generic)):
                frm = cv2.cvtColor(frm, cv2.COLOR_RGB2BGR)
                cv2.imshow("image", frm)
                cv2.waitKey(1000//60)  # CAP 60FPS
    except KeyboardInterrupt:
        from IPython import embed
        embed()
    finally:
        pass
        #fd.close()
