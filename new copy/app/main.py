from fastapi import FastAPI, HTTPException, Form, Request, Depends, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
import openai
import os
import logging
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
# from entity.user import User, HealthData, SensorData
import threading
import bcrypt
from typing import List
import asyncio
import json

logging.basicConfig(level=logging.INFO)

# FastAPI setup
app = FastAPI()
mqtt_client = None
clients: List[WebSocket] = []

# Templates and static files setup
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Load API key from .env file or environment variable
load_dotenv()  # Memuat variabel lingkungan dari file .env
openai.api_key = os.getenv("OPENAI_API_KEY")
env = os.getenv("ENV")

MQTT_URL = os.getenv("MQTT_URL")
MQTT_PORT = os.getenv("MQTT_PORT")
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

# mqtt_settings = {
#     "url": MQTT_URL,
#     "port": MQTT_PORT,
#     "username": MQTT_USERNAME,
#     "password": MQTT_PASSWORD
# }
# data_source = "mqtt"
if env == "production":
    prod = True
elif env == "staging":
    prod = False

if prod:
    # MongoDB Connection
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")  # Default jika tidak ada variabel lingkungan
    client = AsyncIOMotorClient(MONGO_URI)
    db = client["iot_app"]  # Database name
    users_collection = db["users"]  # Collection for users
else:
    users = {}

# Sesi user aktif
current_user = {"name": None}

# Kelas untuk menerima input dari pengguna
class Message(BaseModel):
    user_message: str

# Menyimpan konteks percakapan
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
]

def on_connect(client, userdata, flags, rc):
    logging.info(f"Connected with result code {rc}")
    # client.subscribe("temperature")
    # client.subscribe("location")
    # client.subscribe("position")
    # client.subscribe("heart_rate")
    client.subscribe("safeyou/wristband/heartRate")
    client.subscribe("safeyou/wristband/temperature")
    client.subscribe("safeyou/wristband/position")
    client.subscribe("safeyou/wristband/location")

async def send_message(websocket: WebSocket, message: str):
    try:
        await websocket.send_text(message)
    except Exception as e:
        print(f"Failed to send message to WebSocket: {e}")

# def on_message(client, userdata, msg):
#     logging.info(f"Received message '{msg.payload.decode()}' on topic '{msg.topic}'")
#     message = msg.payload.decode()
    
#     # Send the message to all connected WebSocket clients
#     for ws in clients:
#         asyncio.run(send_message(ws, message))

def on_disconnect(client, userdata, rc):
    logging.info("Disconnected")

def on_message(client, userdata, msg):
    logging.info(f"Received message '{msg.payload.decode()}' on topic '{msg.topic}'")
    message = msg.payload.decode()
    logging.info(f"received {message}")
    message_data = {}
    if msg.topic == "safeyou/wristband/heartRate":
            # Assuming the message is just the heart rate value as a string, convert it to a JSON format
            message_data = {
                "heartRate": message
            }

    if msg.topic == "safeyou/wristband/temperature":
        # Assuming the message is the temperature value, for example in Celsius
        message_data = {
            "temperature": message
        }

    if msg.topic == "safeyou/wristband/position":
        # Assuming the message is position data, e.g., "latitude,longitude"
        # Split the message string into coordinates (or any other structure)
        position_data = message.split(",")
        message_data = {
            "position": message
        }

    # if msg.topic == "safeyou/wristband/location":
    #     # Assuming the message is a location description (e.g., "room, building")
    #     location_data = message.split(",")
    #     message_data = {
    #         "location": {
    #             "room": location_data[0],
    #             "building": location_data[1]
    #         }
    #     }


    # Send the message to all connected WebSocket clients
    # Convert the message to JSON format before sending
    json_message = json.dumps(message_data)
    logging.info(f"Sending message to all clients: {json_message}")
    for ws in clients:
        asyncio.run(send_message(ws, json_message))

def on_disconnect(client, userdata, rc):
    logging.info("Disconnected")

# def connect_mqtt():
#     global mqtt_client
#     mqtt_client = mqtt.Client()
#     mqtt_client.on_connect = on_connect
#     mqtt_client.on_message = on_message
#     mqtt_client.on_disconnect = on_disconnect
#     broker_url = MQTT_URL
#     broker_port = int(MQTT_PORT)
#     broker_username = MQTT_USERNAME
#     broker_password = MQTT_PASSWORD
#     try:
#         mqtt_client.username_pw_set(broker_username, broker_password)
#         mqtt_client.connect(broker_url, broker_port, 60)
#         print(f"Connected to MQTT broker at {broker_url}:{broker_port}")
#     except Exception as e:
#         print(f"Could not connect to MQTT broker: {e}")
#         exit(1)

def connect_mqtt():
    global mqtt_client
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.on_disconnect = on_disconnect
    broker_url = MQTT_URL
    broker_port = int(MQTT_PORT)
    broker_username = MQTT_USERNAME
    broker_password = MQTT_PASSWORD
    try:
        mqtt_client.username_pw_set(broker_username, broker_password)
        mqtt_client.connect(broker_url, broker_port, 60)
    except Exception as e:
        print(f"Could not connect to MQTT broker: {e}")
        exit(1)

def mqtt_loop():
    mqtt_client.loop_forever()

@app.on_event("startup")
async def startup_event():
    connect_mqtt()
    # Jalankan loop MQTT di thread terpisah
    mqtt_thread = threading.Thread(target=mqtt_loop, daemon=True)
    mqtt_thread.start()


@app.get("/", response_class=HTMLResponse)
async def login_register_page(request: Request):
    """Halaman login dan register."""
    return templates.TemplateResponse("login_register.html", {"request": request, "message": ""})


@app.post("/register", response_class=HTMLResponse)
async def register_user(request: Request, username: str = Form(...), password: str = Form(...)):
    """Register user baru."""
    # Periksa apakah user sudah ada
    existing_user = await users_collection.find_one({"username": username})
    if existing_user:
        return templates.TemplateResponse("login_register.html", {"request": request, "message": "User already exists!"})

    # Simpan user ke MongoDB
    new_user = {"username": username, "password": password}
    await users_collection.insert_one(new_user)
    return templates.TemplateResponse("login_register.html", {"request": request, "message": "Registered successfully. Please login."})


@app.post("/login", response_class=HTMLResponse)
async def login_user(request: Request, username: str = Form(...), password: str = Form(...)):
    """Login user."""
    # Periksa kredensial user
    user = await users_collection.find_one({"username": username})
    if not user or user["password"] != password:
        return templates.TemplateResponse("login_register.html", {"request": request, "message": "Invalid username or password."})

    # Set sesi user aktif
    current_user["name"] = username
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Halaman dashboard."""

    # Data IoT dummy
    iot_data = {
        "heart_rate": 75,
        "temperature": 36.6,
        "position": "Standing",
        "location": "6.46° N, 100.50° E",
    }

    if prod:
        if not current_user["name"]:
            return RedirectResponse(url="/", status_code=303)
        return templates.TemplateResponse("dashboard.html", {"request": request, "user": current_user["name"], "data": iot_data})
    else:
        return templates.TemplateResponse("dashboard.html", {"request": request, "user": "dev", "data": iot_data})

@app.post("/chat")
async def chat_with_openai(message: Message):
    try:
        # Menambahkan pesan pengguna ke dalam konteks
        messages.append({"role": "user", "content": message.user_message})

        # Meminta OpenAI untuk melanjutkan percakapan
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages
        )

        # Mendapatkan respons dari model dan menambahkannya ke dalam pesan
        chat_message = response['choices'][0]['message']['content']
        messages.append({"role": "assistant", "content": chat_message})

        return {"ai_response": chat_message}
    except openai.error.OpenAIError as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # Menerima pesan (jika diperlukan)
    except Exception as e:
        logging.error(f"Error in websocket connection: {e}")
    finally:
        clients.remove(websocket)  # Hapus koneksi saat terputus

# @app.get("/mqtt", response_class=HTMLResponse)
# async def mqtt_page(request: Request):
#     """Halaman konfigurasi MQTT."""
#     global mqtt_settings

#     # Mengambil data pengaturan MQTT saat ini
#     mqtt_url = mqtt_settings.get("url", "Not Set")
#     mqtt_port = mqtt_settings.get("port", "Not Set")
#     mqtt_username = mqtt_settings.get("username", "Not Set")
#     mqtt_password = mqtt_settings.get("password", "Not Set")
    
#     # Cek status koneksi MQTT
#     status = "Disconnected"
#     if mqtt_client.is_connected():
#         status = "Connected"

#     # Kirim data ke template
#     return templates.TemplateResponse("mqtt.html", {
#         "request": request,
#         "mqtt_url": mqtt_url,
#         "mqtt_port": mqtt_port,
#         "mqtt_username": mqtt_username,
#         "mqtt_password": mqtt_password,
#         "status": status
#     })

# @app.post("/update_mqtt")
# async def update_mqtt_connection(
#     request: Request,
#     mqtt_url: str = Form(...),
#     mqtt_port: int = Form(...),
#     mqtt_username: str = Form(None),
#     mqtt_password: str = Form(None)  # Pastikan request adalah parameter terakhir
# ):
#     """Endpoint untuk mengupdate koneksi MQTT dan menghubungkannya ulang."""
#     global mqtt_client, mqtt_settings
    
#     # Update pengaturan MQTT
#     mqtt_settings["url"] = mqtt_url
#     mqtt_settings["port"] = mqtt_port
#     mqtt_settings["username"] = mqtt_username
#     mqtt_settings["password"] = mqtt_password

#     # Coba untuk menghentikan koneksi MQTT saat ini dan membuat koneksi baru
#     if mqtt_client.is_connected():
#         mqtt_client.disconnect()

#     try:
#         # Mengonfigurasi ulang client MQTT dengan pengaturan baru
#         mqtt_client = mqtt.Client()
#         if mqtt_settings["username"] and mqtt_settings["password"]:
#             mqtt_client.username_pw_set(mqtt_settings["username"], mqtt_settings["password"])
#         mqtt_client.on_connect = on_connect
#         mqtt_client.on_message = on_message
#         mqtt_client.on_disconnect = on_disconnect
        
#         # Cobalah untuk terhubung kembali
#         mqtt_client.connect(mqtt_settings["url"], mqtt_settings["port"], 60)
        
#         # Jalankan loop MQTT di thread terpisah jika belum ada
#         if not mqtt_thread.is_alive():
#             mqtt_thread = threading.Thread(target=mqtt_loop, daemon=True)
#             mqtt_thread.start()

#         return RedirectResponse(url="/dashboard", status_code=303)
#     except Exception as e:
#         logging.error(f"Error while updating MQTT connection: {e}")
#         return templates.TemplateResponse("dashboard.html", {"request": request, "message": f"Failed to update MQTT connection: {e}", "user": current_user["name"], "data": {}})

# @app.get("/mqtt_status")
# async def mqtt_status(request: Request):
#     """Endpoint untuk melihat status koneksi MQTT."""
#     global mqtt_client
#     status = "Disconnected"
#     if mqtt_client.is_connected():
#         status = "Connected"
    
#     return templates.TemplateResponse("dashboard.html", {
#         "request": request,
#         "user": current_user["name"],
#         "status": status,
#         "data": {}
#     })

# # Variabel global untuk menyimpan pilihan sumber data
# global_data_source = "mqtt"  # Default: MQTT

# @app.post("/update_data_source")
# async def update_data_source(request: Request, data_source: str = Form(...)):
#     """Mengupdate sumber data: MQTT atau manual."""
#     global global_data_source  # Menyatakan bahwa kita menggunakan global_data_source
#     global_data_source = data_source  # Menyimpan pilihan sumber data
#     print(f"Data source updated to: {data_source}")
#     return RedirectResponse(url="/mqtt", status_code=303)

