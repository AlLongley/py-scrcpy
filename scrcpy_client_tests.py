import scrcpy_client
import io
import sys
import numpy as np 
import time
import socket
import unittest
import logging

SHOWFRAMES = False

#~136 frames from the game HyperFlex, with PTS meta enabled
MOCKFILE = "mocksession_hflex_withmeta"

#These were the settings enabled during the saved session
scrcpy_client.SVR_maxSize = 600
scrcpy_client.SVR_bitRate = 999999999
scrcpy_client.SVR_tunnelForward = "true"
scrcpy_client.SVR_crop = "9999:9999:0:0"
scrcpy_client.SVR_sendFrameMeta = "true"

if SHOWFRAMES:
    try:
        import cv2
    except ImportError:
        SHOWFRAMES = False

class MockSocket():
    '''
    Replay a previously recorded socket session from a file
    '''
    def __init__(self, *args):
        #print("Starting Mocked Socket",str(args))
        self.filename=MOCKFILE
        self.fd = None
        
    def connect(self, *args):
        #print("Connecting Mocked Socket",str(args))
        self.fd = open(self.filename,'rb')
        
    def recv(self, buffersize,*args):
        ret = self.fd.read(buffersize)
        
        return ret
    def __del__(self):
        if self.fd:
            self.fd.close()
            

class TestClientMockConnect(unittest.TestCase):
    def setUp(self):

        self.SCRCPY = scrcpy_client.SCRCPY_client()
        # Replace the socket with our mock filebased "socket"
        scrcpy_client.socket.socket = MockSocket
        
        self.assertTrue(self.SCRCPY.connect())
        self.assertTrue(self.SCRCPY.start_processing())
        
        #Give FFmpeg a moment to catch up
        time.sleep(0.1)
    def test_resolution_recieved(self):
        self.assertTrue(self.SCRCPY.WIDTH>1)
        self.assertTrue(self.SCRCPY.HEIGHT>1)
    def test_ffmpeg_running(self):
        self.assertIs(self.SCRCPY.ffm.poll(), None)

    def test_ffmpeg_detected_stream(self):
        ffinfo = ''.join(self.SCRCPY.FFmpeg_info)
        self.assertTrue("Stream #0:0 -> #0:0 (h264 -> rawvideo)" in ffinfo)
    
    def test_frames_recieved(self):
        
        frames_counted = 0
        while True:
            frm=self.SCRCPY.get_next_frame()
            if isinstance(frm, (np.ndarray)):
                self.assertEqual(len(frm.shape),3)
                self.assertTrue(sum(frm.shape)>3)
                frames_counted+=1
                if SHOWFRAMES:
                    frm = cv2.cvtColor(frm, cv2.COLOR_RGB2BGR)
                    cv2.imshow("image", frm)
                    cv2.waitKey(1000//60)  # CAP 60FPS        
            else:
                break
        self.assertTrue(frames_counted>10)
        
        #print("Recieved:",frames_counted)
    
        
if __name__ == '__main__':
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    unittest.main()
    