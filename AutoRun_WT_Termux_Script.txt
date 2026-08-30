pkg update && pkg upgrade -y && pkg install python clang portaudio -y && pip install pyaudio && cat << 'EOF' > walkie.py
#!/usr/bin/env python3

import socket
import pyaudio
import threading
import sys
import struct
import time
import queue


# ================================================================
#                 TERMINAL WALKIE TALKIE
#                 SMOOTH VOICE 4.0
#                 Developer: Samsuddin
# ================================================================

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

# ------------------------------------------------
# Keep CHUNK = 512
# ------------------------------------------------
CHUNK = 512

PORT = 12345

# Microphone gain
GAIN = 0.82

# Voice frequency smoothing
LOW_PASS = 0.92

# Startup microphone buffers to discard
STARTUP_FRAMES = 8

# Receiver jitter buffer
JITTER_PACKETS = 4

# Packet-loss waiting time
PACKET_WAIT = 0.025

# Crossfade samples
FADE_SAMPLES = 24

# UDP header:
# 4 bytes sequence number
HEADER_SIZE = 4


# ================================================================
#                         HEADER
# ================================================================

def print_header():

    print("=" * 62)

    logo = r"""
                 .----------------.
                /                  \
               /   .----------.    \
              |   /    ____    \    |
              |  |    / __ \    |    |
              |  |   | |  | |   |    |
              |  |   | |__| |   |    |
              |   \   \____/   /    |
              |    '----------'     |
              |         ||          |
              |      ___||___       |
              |     |   ||   |      |
              |     |   ||   |      |
              |     |___||___|      |
              |        /  \         |
              |_______/____\________|
                    WALKIE TALKIE
    """

    print(logo)
    print("          TERMINAL WALKIE TALKIE")
    print("          SMOOTH VOICE EDITION 4.0")
    print("          JITTER BUFFER ENABLED")
    print("          POP REDUCTION ENABLED")
    print("          Developer: Samsuddin")
    print("=" * 62)


# ================================================================
#                  SMOOTH MICROPHONE FILTER
# ================================================================

class VoiceFilter:

    def __init__(self):

        self.previous_input = 0.0
        self.previous_output = 0.0
        self.lowpass_state = 0.0

    def process(self, data):

        if not data:
            return b""

        try:

            count = len(data) // 2

            if count <= 0:
                return b""

            samples = struct.unpack(
                "<{}h".format(count),
                data
            )

            result = []

            for sample in samples:

                # ------------------------------------------------
                # DC BLOCK
                # ------------------------------------------------

                value = (
                    sample
                    - self.previous_input
                    + (0.995 * self.previous_output)
                )

                self.previous_input = sample
                self.previous_output = value

                # ------------------------------------------------
                # GENTLE LOW-PASS
                #
                # Removes some very high-frequency hiss.
                # It does NOT hard-mute speech.
                # ------------------------------------------------

                self.lowpass_state = (
                    LOW_PASS * self.lowpass_state
                    + (1.0 - LOW_PASS) * value
                )

                value = self.lowpass_state

                # ------------------------------------------------
                # GENTLE GAIN
                # ------------------------------------------------

                value *= GAIN

                # ------------------------------------------------
                # SOFT LIMITER
                # Prevents very loud clipping.
                # ------------------------------------------------

                if value > 28000:

                    value = (
                        28000
                        + (value - 28000) * 0.12
                    )

                elif value < -28000:

                    value = (
                        -28000
                        + (value + 28000) * 0.12
                    )

                value = max(
                    -32768,
                    min(32767, int(value))
                )

                result.append(value)

            return struct.pack(
                "<{}h".format(len(result)),
                *result
            )

        except Exception:

            return data


# ================================================================
#                       CROSSFADE
# ================================================================

def smooth_packet(previous_data, current_data):

    """
    Smooth the boundary between two audio packets.
    This helps reduce clicks/pops caused by abrupt
    sample changes.
    """

    if not current_data:
        return current_data

    if not previous_data:
        return current_data

    try:

        prev_count = len(previous_data) // 2
        curr_count = len(current_data) // 2

        count = min(
            FADE_SAMPLES,
            prev_count,
            curr_count
        )

        if count <= 0:
            return current_data

        prev_samples = struct.unpack(
            "<{}h".format(prev_count),
            previous_data
        )

        curr_samples = list(
            struct.unpack(
                "<{}h".format(curr_count),
                current_data
            )
        )

        start = prev_samples[-count:]

        for i in range(count):

            # Short linear crossfade
            a = (count - i) / count
            b = i / count

            value = (
                start[i] * a
                + curr_samples[i] * b
            )

            curr_samples[i] = int(value)

        return struct.pack(
            "<{}h".format(curr_count),
            *curr_samples
        )

    except Exception:

        return current_data


# ================================================================
#                  RECEIVER JITTER BUFFER
# ================================================================

class JitterBuffer:

    def __init__(self):

        self.packets = {}
        self.lock = threading.Lock()

        self.started = False
        self.expected = None

    def add(self, sequence, data):

        with self.lock:

            # Ignore duplicate packet
            if sequence in self.packets:
                return

            self.packets[sequence] = data

            # Limit memory
            if len(self.packets) > 30:

                keys = sorted(
                    self.packets.keys()
                )

                for key in keys[:-20]:

                    del self.packets[key]

    def get_next(self):

        with self.lock:

            if self.expected is None:

                if len(self.packets) < JITTER_PACKETS:
                    return None

                self.expected = min(
                    self.packets.keys()
                )

            if self.expected in self.packets:

                data = self.packets.pop(
                    self.expected
                )

                self.expected = (
                    (self.expected + 1)
                    & 0xFFFFFFFF
                )

                return data

            # Packet missing
            return None

    def has_packets(self):

        with self.lock:
            return len(self.packets) > 0

    def force_skip(self):

        with self.lock:

            if self.expected is None:
                return

            self.expected = (
                (self.expected + 1)
                & 0xFFFFFFFF
            )


# ================================================================
#                 FADE MISSING PACKET
# ================================================================

def silent_fade(previous_data):

    """
    When a UDP packet is lost, do not suddenly jump to
    absolute silence. Fade the last packet down smoothly.
    """

    if not previous_data:

        return b"\x00" * (CHUNK * 2)

    try:

        count = len(previous_data) // 2

        samples = struct.unpack(
            "<{}h".format(count),
            previous_data
        )

        result = []

        for i, sample in enumerate(samples):

            factor = 1.0 - (
                i / max(1, count)
            )

            result.append(
                int(sample * factor)
            )

        return struct.pack(
            "<{}h".format(len(result)),
            *result
        )

    except Exception:

        return b"\x00" * (CHUNK * 2)


# ================================================================
#                    RECEIVE NETWORK
# ================================================================

def network_receiver(sock, jitter):

    while True:

        try:

            packet, addr = sock.recvfrom(
                HEADER_SIZE + CHUNK * 2
            )

            if len(packet) <= HEADER_SIZE:
                continue

            sequence = struct.unpack(
                "<I",
                packet[:HEADER_SIZE]
            )[0]

            audio_data = packet[
                HEADER_SIZE:
            ]

            # PCM must contain complete samples
            if len(audio_data) % 2 != 0:
                continue

            # Only accept expected PCM packet size
            if len(audio_data) != CHUNK * 2:
                continue

            jitter.add(
                sequence,
                audio_data
            )

        except OSError:

            break

        except Exception:

            continue


# ================================================================
#                    PLAYBACK ENGINE
# ================================================================

def playback_audio(
    jitter,
    output_stream
):

    previous_data = None
    missing_since = None

    while True:

        try:

            data = jitter.get_next()

            if data is not None:

                # Smooth packet boundary
                data = smooth_packet(
                    previous_data,
                    data
                )

                output_stream.write(
                    data,
                    exception_on_underflow=False
                )

                previous_data = data
                missing_since = None

                continue

            # ------------------------------------------------
            # Wait briefly for delayed UDP packet
            # ------------------------------------------------

            if jitter.started is False:

                time.sleep(0.005)

                continue

            if missing_since is None:

                missing_since = time.monotonic()

            elapsed = (
                time.monotonic()
                - missing_since
            )

            if elapsed < PACKET_WAIT:

                time.sleep(0.002)

                continue

            # ------------------------------------------------
            # Packet was probably lost.
            #
            # Fade instead of producing a sudden click.
            # ------------------------------------------------

            fade_data = silent_fade(
                previous_data
            )

            output_stream.write(
                fade_data,
                exception_on_underflow=False
            )

            previous_data = fade_data

            jitter.force_skip()

            missing_since = None

        except Exception:

            time.sleep(0.005)


# ================================================================
#                    TRANSMIT MICROPHONE
# ================================================================

def transmit_audio(
    sock,
    input_stream,
    target_addr
):

    processor = VoiceFilter()

    sequence = 0

    # ------------------------------------------------
    # Discard Android/PortAudio startup buffers
    # ------------------------------------------------

    for _ in range(STARTUP_FRAMES):

        try:

            input_stream.read(
                CHUNK,
                exception_on_overflow=False
            )

        except Exception:

            pass

    print("Microphone stabilized.")
    print("Smooth voice transmission active.")

    while True:

        try:

            mic_data = input_stream.read(
                CHUNK,
                exception_on_overflow=False
            )

            if not mic_data:
                continue

            # Process voice
            filtered = processor.process(
                mic_data
            )

            if not filtered:
                continue

            # ------------------------------------------------
            # Sequence number + PCM audio
            # ------------------------------------------------

            header = struct.pack(
                "<I",
                sequence
            )

            packet = (
                header
                + filtered
            )

            sock.sendto(
                packet,
                target_addr
            )

            sequence = (
                (sequence + 1)
                & 0xFFFFFFFF
            )

        except KeyboardInterrupt:

            break

        except OSError:

            break

        except Exception:

            time.sleep(0.001)


# ================================================================
#                    OPEN MICROPHONE
# ================================================================

def open_input():

    audio = pyaudio.PyAudio()

    try:

        input_stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
            start=True
        )

        return audio, input_stream

    except Exception:

        audio.terminate()

        raise


# ================================================================
#                     OPEN SPEAKER
# ================================================================

def open_output(audio):

    return audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        output=True,
        frames_per_buffer=CHUNK,
        start=True
    )


# ================================================================
#                         SERVER
# ================================================================

def run_server():

    audio = None
    input_stream = None
    output_stream = None
    sock = None

    try:

        # ------------------------------------------------
        # Open MIC first
        # ------------------------------------------------

        audio, input_stream = open_input()

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )

        sock.bind(
            ("0.0.0.0", PORT)
        )

        print("\n[SERVER MODE]")
        print(
            f"Listening on UDP port {PORT}"
        )
        print(
            "Waiting for client voice..."
        )

        # ------------------------------------------------
        # Wait for REAL audio packet.
        # No beep.
        # No silent packet.
        # ------------------------------------------------

        first_packet, addr = sock.recvfrom(
            HEADER_SIZE + CHUNK * 2
        )

        if len(first_packet) != (
            HEADER_SIZE + CHUNK * 2
        ):

            print("Invalid first packet.")
            return

        print(
            f"\nClient connected: "
            f"{addr[0]}:{addr[1]}"
        )

        # ------------------------------------------------
        # Create jitter buffer
        # ------------------------------------------------

        jitter = JitterBuffer()

        sequence = struct.unpack(
            "<I",
            first_packet[:HEADER_SIZE]
        )[0]

        first_audio = first_packet[
            HEADER_SIZE:
        ]

        jitter.add(
            sequence,
            first_audio
        )

        # ------------------------------------------------
        # Start network receiver
        # ------------------------------------------------

        threading.Thread(
            target=network_receiver,
            args=(sock, jitter),
            daemon=True
        ).start()

        # ------------------------------------------------
        # Start microphone transmitter
        # ------------------------------------------------

        threading.Thread(
            target=transmit_audio,
            args=(
                sock,
                input_stream,
                addr
            ),
            daemon=True
        ).start()

        # ------------------------------------------------
        # Wait for several packets before speaker starts.
        # This creates a small jitter buffer.
        # ------------------------------------------------

        print(
            "Buffering voice for smooth playback..."
        )

        while True:

            with jitter.lock:

                if len(jitter.packets) >= JITTER_PACKETS:
                    break

            time.sleep(0.005)

        # ------------------------------------------------
        # ONLY NOW open speaker
        # ------------------------------------------------

        output_stream = open_output(audio)

        print(
            "Speaker started."
        )
        print(
            "Smooth voice communication active."
        )
        print(
            "Press Ctrl+C to stop."
        )

        jitter.started = True

        playback_audio(
            jitter,
            output_stream
        )

    except KeyboardInterrupt:

        print("\nStopping server...")

    except Exception as e:

        print(
            "\n[SERVER ERROR]"
        )

        print(e)

    finally:

        try:
            if input_stream:
                input_stream.stop_stream()
                input_stream.close()
        except:
            pass

        try:
            if output_stream:
                output_stream.stop_stream()
                output_stream.close()
        except:
            pass

        try:
            if sock:
                sock.close()
        except:
            pass

        try:
            if audio:
                audio.terminate()
        except:
            pass


# ================================================================
#                         CLIENT
# ================================================================

def run_client(server_ip):

    audio = None
    input_stream = None
    output_stream = None
    sock = None

    try:

        # ------------------------------------------------
        # Open microphone
        # ------------------------------------------------

        audio, input_stream = open_input()

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        target_addr = (
            server_ip,
            PORT
        )

        print("\n[CLIENT MODE]")
        print(
            f"Server: {server_ip}:{PORT}"
        )

        print(
            "Starting voice transmission..."
        )

        # ------------------------------------------------
        # Client starts transmitting REAL audio.
        #
        # IMPORTANT:
        # NO silent packet.
        # NO beep.
        # NO test tone.
        # ------------------------------------------------

        threading.Thread(
            target=transmit_audio,
            args=(
                sock,
                input_stream,
                target_addr
            ),
            daemon=True
        ).start()

        # ------------------------------------------------
        # Receiver buffer
        # ------------------------------------------------

        jitter = JitterBuffer()

        threading.Thread(
            target=network_receiver,
            args=(sock, jitter),
            daemon=True
        ).start()

        print(
            "Waiting for server voice..."
        )

        # ------------------------------------------------
        # Wait until real voice packets arrive
        # ------------------------------------------------

        while True:

            with jitter.lock:

                if len(jitter.packets) >= JITTER_PACKETS:
                    break

            time.sleep(0.005)

        # ------------------------------------------------
        # Speaker is opened ONLY after network audio
        # exists.
        # ------------------------------------------------

        output_stream = open_output(audio)

        print(
            "Speaker started."
        )

        print(
            "Smooth voice communication active."
        )

        print(
            "Press Ctrl+C to stop."
        )

        jitter.started = True

        playback_audio(
            jitter,
            output_stream
        )

    except KeyboardInterrupt:

        print("\nStopping client...")

    except Exception as e:

        print(
            "\n[CLIENT ERROR]"
        )

        print(e)

    finally:

        try:
            if input_stream:
                input_stream.stop_stream()
                input_stream.close()
        except:
            pass

        try:
            if output_stream:
                output_stream.stop_stream()
                output_stream.close()
        except:
            pass

        try:
            if sock:
                sock.close()
        except:
            pass

        try:
            if audio:
                audio.terminate()
        except:
            pass


# ================================================================
#                           MAIN
# ================================================================

def main():

    print_header()

    print("\nOptions:")
    print("A. Start as Server")
    print("B. Start as Client")
    print("C. Exit")

    choice = input(
        "\nYour choice (A/B/C): "
    ).strip().upper()

    if choice == "A":

        run_server()

    elif choice == "B":

        server_ip = input(
            "\nEnter Server IP address: "
        ).strip()

        if not server_ip:

            print("Invalid server IP.")
            return

        run_client(
            server_ip
        )

    elif choice == "C":

        print("Exiting.")

    else:

        print("Invalid option.")


# ================================================================
#                         START
# ================================================================

if __name__ == "__main__":

    main()
EOF
python walkie.py
