1.টার্মিনালে কমান্ড দিন: nano Walkie_Talkie.py


import socket
import pyaudio
import threading
import sys

# Audio configuration
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
CHUNK = 512

audio = pyaudio.PyAudio()

def print_header():
    print("="*60)
    logo = """
       _______
     _/.-----.\_
    | |       | |
    |_|_______|_|
      /   .   \\
     |____.____|
     |         |
     |         |
     |_________|
    """
    print(logo)
    print("      Terminal Walkie Talkie - Version 1.0       ")
    print("      Developer: Samsuddin                       ")
    print("="*60)

def receive_audio(sock, output_stream):
    while True:
        try:
            data, addr = sock.recvfrom(CHUNK * 2)
            output_stream.write(data)
        except:
            break

def transmit_audio(sock, input_stream, target_addr):
    while True:
        mic_data = input_stream.read(CHUNK)
        sock.sendto(mic_data, target_addr)

def main():
    print_header()
    print("\nOptions:")
    print("A. Start as Server")
    print("B. Start as Client")
    print("C. Set Local IP Manually")
    print("D. Exit")
    
    choice = input("\nYour choice (A/B/C/D): ").upper()

    if choice == 'D':
        print("Exiting program.")
        sys.exit()

    if choice == 'C':
        local_ip = input("Enter your custom local IP to bind: ").strip()
        print(f"Local IP successfully set to: {local_ip}")

    input_stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    output_stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True, frames_per_buffer=CHUNK)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    if choice == 'A':
        sock.bind(('0.0.0.0', 12345))
        print("\n[Device Status: Ready as Server]")
        print("Waiting for client...")
        
        data, addr = sock.recvfrom(CHUNK * 2)
        output_stream.write(data)
        
        threading.Thread(target=receive_audio, args=(sock, output_stream)).start()
        threading.Thread(target=transmit_audio, args=(sock, input_stream, addr)).start()
        
    elif choice == 'B':
        server_ip = input("Enter Server IP address: ").strip()
        target_addr = (server_ip, 12345)
        print("\n[Device Status: Ready as Client]")
        print("Connected to server.")
        
        threading.Thread(target=transmit_audio, args=(sock, input_stream, target_addr)).start()
        threading.Thread(target=receive_audio, args=(sock, output_stream)).start()
    else:
        print("Invalid option selected.")
        sys.exit()

if __name__ == "__main__":
    main()




সেভ করতে Ctrl + O চেপে Enter দিন, তারপর Ctrl + X চেপে বের হয়ে আসুন।



নতুন ফাইল বানিয়ে চালানোর জন্য কমান্ড:

python Walkie_Talkie.py




Termux-এ PyAudio সরাসরি pip install pyaudio দিলে সি-কম্পাইলার না থাকায় প্রায়ই কাজ করে না। তাই PortAudio ডিপেন্ডেন্সিসহ নিচে দেওয়া কমান্ডগুলো ক্রমানুসারে রান করুন:
​ইন্সটলেশন স্টেপসমূহ (Termux এর জন্য):


প্রয়োজনীয় সি-কম্পাইলার ও অডিও ডিপেন্ডেন্সি ইনস্টল করুন

pkg update && pkg upgrade -y
pkg install python clang portaudio -y


এবার pyaudio ইন্সটল করুন:

pip install pyaudio



ইন্সটল সম্পন্ন হলে কোডটি রান করুন:


python Walkie_Talkie.py



​1. Update package lists

pkg update && pkg upgrade -y


2. Install C compiler and PortAudio development libraries

pkg install clang portaudio -y


3. Install PyAudio using pip

pip install pyaudio


##If pip install pyaudio fails, pass the explicit header directory path:

CFLAGS="-I$PREFIX/include" LDFLAGS="-L$PREFIX/lib" pip install pyaudio


