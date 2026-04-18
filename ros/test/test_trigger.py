import zmq
import json
import time

def send_payload(socket, act_name, payload):
    print(f"\n[Test] Triggering: {act_name}")
    print(f"       JSON: {json.dumps(payload)}")
    socket.send_string(json.dumps(payload))
    print(" Command sent!\n")

def interactive_menu():
    print("Connecting to local ROS Dispatcher ZMQ port 5556...")
    context = zmq.Context()
    socket = context.socket(zmq.PUSH)
    socket.connect("tcp://127.0.0.1:5556")
    time.sleep(0.5)

    try:
        while True:
            print("="*40)
            print("QTrobot AI Assistant - Manual Test Menu")
            print("="*40)
            print("1. Talk Text")
            print("2. Emotion Show")
            print("3. Set Language")
            print("4. Set Volume")
            print("5. Show ECG")
            print("0. Exit")
            print("="*40)
            
            choice = input(" Enter function code to test (0-5): ").strip()
            
            if choice == "0":
                print("Exiting...")
                break
            elif choice == "1":
                send_payload(socket, "Talk Text", {
                    "action": "talk",
                    "text": "Hello, I am your QTrobot AI Assistant!"
                })
            elif choice == "2":
                send_payload(socket, "Emotion Show", {
                    "action": "function",
                    "function_name": "emotionShow",
                    "function_args": {"emotion": "QT/trhappy"}
                })
            elif choice == "3":
                send_payload(socket, "Set Language", {
                    "action": "function",
                    "function_name": "setLanguage",
                    "function_args": {"lang_code": "en-US", "pitch": 100, "speed": 100}
                })
            elif choice == "4":
                send_payload(socket, "Set Volume", {
                    "action": "function",
                    "function_name": "setVolume",
                    "function_args": {"level": 70}
                })
            elif choice == "5":
                send_payload(socket, "Show ECG", {
                    "action": "function",
                    "function_name": "showECG",
                    "function_args": {
                        "url": "http://localhost:8080/index.html"
                    }
                })
            else:
                print(" Invalid choice. Please enter a number between 0 and 5.\n")
                
    except KeyboardInterrupt:
        print("\nExiting test script...")
    finally:
        socket.close()
        context.term()

if __name__ == "__main__":
    interactive_menu()
