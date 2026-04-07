import zmq
import json

def main():
    context = zmq.Context()
    receiver = context.socket(zmq.PULL)
    receiver.bind("tcp://*:5555")
    
    print(" test receiver started...")
    print(" Please speak to QTrobot, and the text will appear here \n")
    
    try:
        while True:
            message = receiver.recv_string()
            data = json.loads(message)
            
            print("="*30)
            print("New speech recognition result:")
            print(f"Timestamp: {data.get('timestamp')}")
            print(f"Language: {data.get('language')}")
            print(f"Text: {data.get('text')}")
            print("="*30)
            
    except KeyboardInterrupt:
        print("\nfinish")
    finally:
        receiver.close()
        context.term()

if __name__ == "__main__":
    main()
