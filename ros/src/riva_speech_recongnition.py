# Copyright (c) 2024 LuxAI S.A.
# 
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

import time
from enum import Enum
import queue
from threading import Event, Thread
import wave
import rospy
from audio_common_msgs.msg import AudioData
from std_msgs.msg import String
import riva.client
import grpc

import math
import numpy as np
import torch

class SileroVAD():
    def __init__(self, confidence_threshold=0.6, rate=16000):
        # Load the pre-trained Silero VAD model
        self.model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                           model='silero_vad',
                                           force_reload=False,
                                           trust_repo=True)

        if rate not in (16000, 8000):
            raise ValueError(f"SileroVAD: audio sample rate must be either 16000 or 8000")

        self.rate = rate
        self.confidence_threshold = confidence_threshold
        (self.get_speech_timestamps,
        self.save_audio,
        self.read_audio,
        self.VADIterator,
        self.collect_chunks) = utils

    def _int2float(self, sound):
        abs_max = np.abs(sound).max()
        sound = sound.astype('float32')
        if abs_max > 0:
            sound *= 1/32768
        sound = sound.squeeze()
        return sound

    def is_voice(self, audio_chunk):
        audio_int16 = np.frombuffer(audio_chunk, np.int16)
        audio_float32 = self._int2float(audio_int16)
        # Calculate confidence
        confidence = self.model(torch.from_numpy(audio_float32), self.rate).item()
        return confidence > self.confidence_threshold


class MicrophoneStream:
    """Opens a recording stream as responses yielding the audio chunks."""
    def __init__(self, 
                 rate=16000,
                 num_samples=512,
                 channels=1,
                 vad: SileroVAD = None,
                 audio_record_file=None) -> None:
        self.vad = vad
        self.rate = rate
        self.channels = channels
        self.num_samples = num_samples

        if audio_record_file: 
            self.wf = wave.open(audio_record_file, 'wb')
            self.wf.setnchannels(channels)
            self.wf.setsampwidth(2)
            self.wf.setframerate(rate)
        else: 
            self.wf = None

        self.stream_buff = queue.Queue(maxsize=math.ceil(60 / (num_samples/rate)))
        self.closed = True
        self.voice_event = Event()  

        if not self.vad:
            rospy.logwarn(f"MicrophoneStream is initialized without VAD!")

    def __enter__(self):
        self.closed = False
        return self

    def __exit__(self, type, value, traceback):        
        self.closed = True
        self.stream_buff.put(None)
        self.voice_event.set()
        if self.wf:
            self.wf.close()

    def __next__(self) -> bytes:
        if self.closed:
            raise StopIteration
        chunk = self.stream_buff.get(timeout=2)
        if chunk is None:
            raise StopIteration
        
        data = [chunk]        
        while True:
            try:
                chunk = self.stream_buff.get(block=False)
                if chunk is None:
                    assert not self.closed
                data.append(chunk)
            except queue.Empty:
                break
        return b''.join(data)

    def __iter__(self):
        return self

    def reset(self, seconds_to_keep=0.5):
        if seconds_to_keep <= 0:
            self.stream_buff.queue.clear()
            self.voice_event.clear()
            return 
        frames_to_keep = math.ceil(seconds_to_keep / (self.num_samples/self.rate))        
        last_two_items = list(self.stream_buff.queue)[-1 * frames_to_keep:]
        self.stream_buff.queue.clear()
        for item in last_two_items:
            self.stream_buff.put(item)
        self.voice_event.clear()

    def put_chunk(self, chunk):
        try:
            self.stream_buff.put_nowait(chunk)
            if self.wf:
                self.wf.writeframes(chunk)

            if not self.vad:                
                self.voice_event.set()
                return 
            
            if self.vad.is_voice(chunk):
                if not self.voice_event.is_set():                    
                    self.reset(seconds_to_keep=1.0)
                self.voice_event.set()
        except:
            pass

    def wait_for_voice(self, timeout=None):        
        if not self.voice_event.wait(timeout=timeout):
            return False
        return not self.closed


class RivaSpeechRecognitionSilero:
    class Event(Enum):
        STARTED = 1
        RECOGNIZING = 2
        RECOGNIZED = 3
        STOPPED = 4
        CANCELED = 5

    def __init__(self, 
              language='zh-CN',  # Default to Chinese
              detection_timeout=5, 
              event_callback=None,
              use_vad=True,
              continuous_recog_callback=None,
              paused=False):
        
        self.use_vad = use_vad
        self.event_callback = event_callback    
        self.continuous_recog_callback = continuous_recog_callback
        self.detection_timeout = detection_timeout
        self.is_paused = paused
        
        self.audio_rate = 16000
        self.language_code = language        
        self.server = 'localhost:50051'
        self.use_ssl = False
        self.ssl_cert = None
        self.profanity_filter = False
        self.automatic_punctuation = True
        self.no_verbatim_transcripts = False
        self.boosted_lm_words = []
        self.boosted_lm_score = 4.0
        self.speaker_diarization = True
        
        self.microphone_stream = MicrophoneStream(vad=SileroVAD(rate=self.audio_rate) if self.use_vad else None)
        self.audio_chunk_iterator = self.microphone_stream.__enter__()

        self.auth = riva.client.Auth(self.ssl_cert, self.use_ssl, self.server)
        self.asr_service = riva.client.ASRService(self.auth)
        self.config = riva.client.StreamingRecognitionConfig(
            config=riva.client.RecognitionConfig(
                encoding=riva.client.AudioEncoding.LINEAR_PCM,
                language_code=self.language_code,
                max_alternatives=1,
                profanity_filter=self.profanity_filter,
                enable_automatic_punctuation=self.automatic_punctuation,
                verbatim_transcripts=not self.no_verbatim_transcripts,
                enable_word_time_offsets=True,
                sample_rate_hertz=self.audio_rate,
                audio_channel_count=1,
            ),
            interim_results=True,
        )
        riva.client.add_word_boosting_to_config(self.config, self.boosted_lm_words, self.boosted_lm_score)
        riva.client.add_speaker_diarization_to_config(self.config, diarization_enable=self.speaker_diarization)        
        
        # Start recognize service
        rospy.Subscriber('/qt_respeaker_app/channel0', AudioData, self._callback_audio_stream, queue_size=10)

        # Subscribe to language changes from dispatcher
        rospy.Subscriber('/qt_ai_assistant/language_config', String, self._language_change_callback, queue_size=10)

        self.asr_event_queue = queue.Queue(maxsize=1)
        self.asr_event_thread = Thread(target=self._proccess_asr_events, daemon=True)        
        self.asr_event_thread.start()

    def _language_change_callback(self, msg):
        new_lang = msg.data
        if new_lang != self.language_code:
            rospy.loginfo(f"Riva ASR switching language from {self.language_code} to {new_lang}")
            self.language_code = new_lang
            self.config = riva.client.StreamingRecognitionConfig(
                config=riva.client.RecognitionConfig(
                    encoding=riva.client.AudioEncoding.LINEAR_PCM,
                    language_code=self.language_code,
                    max_alternatives=1,
                    profanity_filter=self.profanity_filter,
                    enable_automatic_punctuation=self.automatic_punctuation,
                    verbatim_transcripts=not self.no_verbatim_transcripts,
                    enable_word_time_offsets=True,
                    sample_rate_hertz=self.audio_rate,
                    audio_channel_count=1,
                ),
                interim_results=True,
            )
            riva.client.add_word_boosting_to_config(self.config, self.boosted_lm_words, self.boosted_lm_score)
            riva.client.add_speaker_diarization_to_config(self.config, diarization_enable=self.speaker_diarization)
            rospy.loginfo(f" Riva ASR config successfully rebuilt for {new_lang}!")

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def _reinitilize_riva_client(self):
        self.auth = None
        self.asr_service = None
        self.auth = riva.client.Auth(self.ssl_cert, self.use_ssl, self.server)
        self.asr_service = riva.client.ASRService(self.auth)

    def _callback_audio_stream(self, msg):
        if not self.is_paused: 
            self.microphone_stream.put_chunk(bytes(msg.data))

    def _proccess_asr_events(self):
        while not rospy.is_shutdown():
            try:
                evt = self.asr_event_queue.get(timeout=2)
                if evt and self.event_callback:
                    self.event_callback(evt)
            except Exception:
                pass        

    def _asr_event_callback(self, evt):
        try:
            self.asr_event_queue.get_nowait()
        except:
            pass
        finally:
            self.asr_event_queue.put_nowait(evt)

    def recognize_once(self):               
        self.microphone_stream.reset()
        if self.use_vad:
            if not self.microphone_stream.wait_for_voice(timeout=5.0):
                return None, None            
                
        if rospy.is_shutdown():
            return None, None 
        
        self._asr_event_callback(RivaSpeechRecognitionSilero.Event.STARTED)
        start_time = time.time()      
        try:
            responses = self.asr_service.streaming_response_generator(audio_chunks=self.audio_chunk_iterator, streaming_config=self.config)            
            transcript = None
            for response in responses:                
                if response.results:                                        
                    for result in response.results:
                        if not result.alternatives:
                            continue
                        self._asr_event_callback(RivaSpeechRecognitionSilero.Event.RECOGNIZING)
                        transcript = result.alternatives[0].transcript
                        if result.is_final:
                            self._asr_event_callback(RivaSpeechRecognitionSilero.Event.RECOGNIZED)                            
                            return transcript.strip(), self.language_code

                if self.detection_timeout > 0 and not transcript:
                    elapsed_time = time.time() - start_time
                    if elapsed_time > self.detection_timeout:
                        break              
        except Exception as e: 
            if not rospy.is_shutdown():
                code = None
                try: 
                    code = e.code()
                except:
                    pass
                if code == grpc.StatusCode.UNAVAILABLE:
                    rospy.logerr('Riva server is not available. Checking after 10 second...')
                    time.sleep(10)
                    self._reinitilize_riva_client()
                else:
                    rospy.logwarn(str(e))

        self._asr_event_callback(RivaSpeechRecognitionSilero.Event.STOPPED)        
        return None, None

    def process_continuous(self):        
        if self.continuous_recog_callback:
            try:                
                text, lang = self.recognize_once()
                if text:
                    self.continuous_recog_callback(text, lang)
            except Exception as e:
                rospy.logerr(str(e))

    def terminate(self): 
        rospy.loginfo("RivaSpeechRecognitionSilero is terminating..")       
        self.audio_chunk_iterator.__exit__(None, None, None)


# ==========================================
# Main testing block for standalone execution
# ==========================================
if __name__ == "__main__":
    import json
    import zmq

    rospy.init_node("riva_speech_recongnition_node", anonymous=True)
    rospy.loginfo("Starting Riva Speech Recognition Node...")
    
    # Setup ZMQ PUSH socket to send data to Python 3.11 AI Layer
    zmq_context = zmq.Context()
    zmq_socket = zmq_context.socket(zmq.PUSH)
    zmq_socket.connect("tcp://localhost:5555")
    rospy.loginfo("ZMQ PUSH socket connected to tcp://localhost:5555")

    def on_event(event):
        rospy.logdebug(f"ASR Event: {event}")
        
    asr = RivaSpeechRecognitionSilero(
        language='zh-CN',  # Default to Chinese decoding for testing
        use_vad=True,
        event_callback=on_event
    )
    
    rospy.loginfo("Listening... Please speak to the QTrobot microphone.")
    
    try:
        while not rospy.is_shutdown():
            text, lang = asr.recognize_once()
            if text:
                rospy.loginfo(f"Recognized ({lang}): {text}")
                # Pack and push to the AI Assistant
                payload = {
                    "source": "riva_microphone",
                    "text": text,
                    "language": lang,
                    "timestamp": time.time()
                }
                zmq_socket.send_string(json.dumps(payload))
                rospy.loginfo("Pushed transcription to ZMQ.")

    except KeyboardInterrupt:
        pass
    finally:
        asr.terminate()
        zmq_socket.close()
        zmq_context.term()
