from flask import Flask, Response
import cv2
import numpy as np
import threading
import time
import os
from datetime import datetime
import tflite_runtime.interpreter as tflite
import RPi.GPIO as GPIO
from PIL import Image

# === Konfigurasi Servo ===
servo_pin = 17  # GPIO Pin untuk servo
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(servo_pin, GPIO.OUT)

# Setup PWM untuk servo (50Hz)
pwm = GPIO.PWM(servo_pin, 50)
pwm.start(0)  # Mulai PWM dengan duty cycle 0 (ini akan mengatur posisi awal servo)

# Fungsi untuk mengatur sudut servo
def set_servo_angle(angle):
    duty = (angle / 18) + 2  # Menghitung duty cycle dari sudut
    pwm.ChangeDutyCycle(duty)  # Mengubah duty cycle untuk menggerakkan servo
    time.sleep(1)  # Tunggu sebentar untuk memberikan waktu bagi servo untuk bergerak
    pwm.ChangeDutyCycle(0)  # Matikan PWM untuk menghindari gerakan terus-menerus

# === Konfigurasi Ultrasonik ===
TRIG = 23
ECHO = 24
GPIO.setup(TRIG, GPIO.OUT)
GPIO.setup(ECHO, GPIO.IN)

# Inisialisasi Flask
app = Flask(__name__)
camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 800)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 600)

global_frame = None
frame_lock = threading.Lock()

# Model dan Label
model_path = "model_smartwaste.tflite"
label_path = "labels.txt"
interpreter = tflite.Interpreter(model_path=model_path)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

def load_labels(label_path: str):
    with open(label_path, "r") as f:
        return [line.strip() for line in f.readlines()]

labels = load_labels(label_path)

# Hasil klasifikasi terakhir
last_classification = {
    "label": "Belum ada klasifikasi",
    "confidence": 0.0,
    "timestamp": "-"
}

# Fungsi untuk crop bagian tengah gambar berdasarkan persentase
def center_crop_percentage(img, crop_percent=0.7):
    width, height = img.size
    new_width = int(width * crop_percent)
    new_height = int(height * crop_percent)

    left = (width - new_width) // 2
    top = (height - new_height) // 2
    right = left + new_width
    bottom = top + new_height

    return img.crop((left, top, right, bottom))

def read_distance():
    GPIO.output(TRIG, False)
    time.sleep(0.5)

    GPIO.output(TRIG, True)
    time.sleep(0.00001)
    GPIO.output(TRIG, False)

    pulse_start = time.time()
    timeout = pulse_start + 1
    while GPIO.input(ECHO) == 0:
        pulse_start = time.time()
        if pulse_start > timeout:
            return None

    pulse_end = time.time()
    timeout = pulse_end + 1
    while GPIO.input(ECHO) == 1:
        pulse_end = time.time()
        if pulse_end > timeout:
            return None

    pulse_duration = pulse_end - pulse_start
    distance = pulse_duration * 17150
    return round(distance, 2)

def classify_frame(frame):
    # Konversi frame menjadi PIL Image
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    # Crop gambar menggunakan center crop
    cropped_img = center_crop_percentage(img, crop_percent=0.5)

    # Resize ke 224x224 untuk model
    resized_img = cropped_img.resize((224, 224))

    # Normalisasi gambar
    img_array = np.array(resized_img)
    img_array = img_array.astype(np.float32) / 255.0
    img_array = np.expand_dims(img_array, axis=0)

    interpreter.set_tensor(input_details[0]['index'], img_array)
    interpreter.invoke()
    output_data = interpreter.get_tensor(output_details[0]['index'])

    result = np.argmax(output_data)
    confidence = np.max(output_data)
    label = labels[result]

    print(f"[HASIL] Label: {label}, Confidence: {confidence:.2f}")
    return label, confidence

def camera_capture_thread():
    global global_frame
    while True:
        ret, frame = camera.read()
        if ret:
            with frame_lock:
                global_frame = frame
        else:
            print("[ERROR] Kamera tidak terbaca")
        time.sleep(0.03)

def gen_frames():
    while True:
        with frame_lock:
            if global_frame is None:
                continue
            ret, buffer = cv2.imencode('.jpg', global_frame)
            frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return f"""
    <html>
        <head>
            <title>Live Camera Streaming</title>
            <meta http-equiv="refresh" content="5">
        </head>
        <body>
            <h1>Streaming Kamera Raspberry Pi</h1>
            <img src="/video_feed" width="640" height="480"/>

            <h2>Hasil Klasifikasi Terakhir:</h2>
            <p><strong>Label:</strong> {last_classification["label"]}</p>
            <p><strong>Confidence:</strong> {last_classification["confidence"]}</p>
            <p><strong>Waktu:</strong> {last_classification["timestamp"]}</p>
        </body>
    </html>
    """

def main_loop():
    save_dir = "/home/ievan/Pictures/Hasil Deteksi"
    os.makedirs(save_dir, exist_ok=True)

    # Set posisi awal servo ke 100 derajat
    set_servo_angle(100)

    try:
        while True:
            distance = read_distance()
            if distance is None:
                print("[WARNING] Tidak dapat membaca jarak")
                time.sleep(1)
                continue

            print(f"[INFO] Jarak: {distance} cm")

            # Mengubah minimal jarak deteksi menjadi 10 cm
            if distance < 15:
                print("[DETEKSI] Objek terdeteksi, klasifikasi...")
                for i in range(3, 0, -1):
                    print(f" Mengambil gambar {i} detik...")
                    time.sleep(1)

                with frame_lock:
                    if global_frame is not None:
                        frame_copy = global_frame.copy()
                    else:
                        print("[WARNING] Tidak ada frame")
                        time.sleep(2)
                        continue

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{save_dir}/deteksi_{timestamp}.jpg"
                cv2.imwrite(filename, frame_copy)
                print(f"[SIMPAN] Gambar: {filename}")

                label, confidence = classify_frame(frame_copy)
                last_classification["label"] = label
                last_classification["confidence"] = round(confidence, 2)
                last_classification["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Tentukan posisi servo berdasarkan label
                if label.lower() == "anorganik":
                    set_servo_angle(50)
                    time.sleep(5)  # Tunggu 5 detik
                    set_servo_angle(100)  # Kembali ke 100 derajat

                elif label.lower() == "organik":
                    set_servo_angle(150)
                    time.sleep(5)  # Tunggu 5 detik
                    set_servo_angle(100)  # Kembali ke 100 derajat

                else:
                    print("[SERVO] Label tidak dikenali, servo tidak bergerak")

            time.sleep(2)

    except KeyboardInterrupt:
        print("\n[EXIT] Dihentikan oleh user")

    finally:
        GPIO.cleanup()
        camera.release()

if __name__ == "__main__":
    t = threading.Thread(target=camera_capture_thread, daemon=True)
    t.start()

    from waitress import serve
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False), daemon=True)
    flask_thread.start()

    main_loop()