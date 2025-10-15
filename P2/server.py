import socket
import time
import struct
import os
from threading import Timer

# Variables globales de configuración
SERVER_IP = "127.0.0.1"
SERVER_PORT = 12000
CLIENT_PORT = 12001
BUFFER_SIZE = 1024 # Tamaño del buffer para recibir datos
PAYLOAD_SIZE = 1000 # Controla el tamaño de los bloques de datos
WINDOW_SIZE = 10 # Controla el número máximo de paquetes que se pueden enviar sin recibir un ACK
TIMEOUT = 0.5 # Tiempo de espera para el timeout en segundos

MP3_FILE = "cancion.mp3" # Archivo MP3 a enviar

base = 0 # Primer número de secuencia no reconocido
sig_num_sec = 0 # Siguiente número de secuencia a enviar
paquetes = [] # Lista de paquetes a enviar

HEADER_FORMAT = "!IH" # Formato del encabezado: Número de secuencia (4 bytes), Checksum (2 bytes)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Función para crear un paquete
def construir_paquete(seq_num, data):
    checksum = sum(data) % 65535 
    header = struct.pack(HEADER_FORMAT, seq_num, checksum)
    return header + data

# Función auxiliar para inicializar los paquetes a partir del archivo
def inicializar_paquetes():
    global paquetes
    try:
        with open(MP3_FILE, 'rb') as f:
            data = f.read(PAYLOAD_SIZE)
            while data:
                paquetes.append(data) 
                data = f.read(PAYLOAD_SIZE)
        print(f"Archivo MP3 cargado. Total de paquetes: {len(paquetes)}")
    except FileNotFoundError:
        print(f"ERROR: Archivo '{MP3_FILE}' no encontrado.")
        exit()

timer = None
# Función para iniciar o reiniciar el temporizador
def inicio_tiempo(sock, client_addr):
    global timer
    if timer:
        timer.cancel()
    
    timer = Timer(TIMEOUT, retransmitir, [sock, client_addr])
    timer.start()

# Función para detener el temporizador
def detener_tiempo():
    global timer
    if timer:
        timer.cancel()
        timer = None

# Función de retransmisión en caso de timeout desde 'base'
def retransmitir(sock, client_addr):
    global base, sig_num_sec
    print(f"\nTiempo expirado. Retransmitiendo desde base: {base}")
    for i in range(base, sig_num_sec):
        data_paquete = paquetes[i]
        packet = construir_paquete(i, data_paquete)
        sock.sendto(packet, client_addr)
    inicio_tiempo(sock, client_addr)

def server_main():
    global base, sig_num_sec, paquetes

    # Configuración del socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((SERVER_IP, SERVER_PORT))
    
    inicializar_paquetes()

    # Espera la solicitud del cliente
    print(f"Servidor esperando la solicitud del cliente")
    start_msg, client_addr = sock.recvfrom(BUFFER_SIZE)
    print(f"Cliente conectado desde {client_addr}. Iniciando transferencia...")

    # Configuración de timeout para la recepción de ACKs
    sock.settimeout(TIMEOUT)

    # Bucle principal de envío y control
    while base < len(paquetes):
        # 1. Enviar paquetes mientras la ventana esté abierta
        while sig_num_sec < base + WINDOW_SIZE and sig_num_sec < len(paquetes):
            data_paquete = paquetes[sig_num_sec]
            packet = construir_paquete(sig_num_sec, data_paquete)
            sock.sendto(packet, client_addr)
            print(f"Enviando paquete {sig_num_sec}")

            if base == sig_num_sec:
                inicio_tiempo(sock, client_addr)

            sig_num_sec += 1

        # 2. Esperar ACKs o Timeout
        try:
            paquete_ack, _ = sock.recvfrom(BUFFER_SIZE)
            num_sec_ack = struct.unpack("!I", paquete_ack[:4])[0]
            
            if base <= num_sec_ack:
                print(f"Recibido ACK para seq_num {num_sec_ack} (espera {num_sec_ack})")
                
                base = num_sec_ack
                
                if base < sig_num_sec:
                    inicio_tiempo(sock, client_addr)
                else:
                    detener_tiempo() 
            else:
                print(f"ACK no esperado {num_sec_ack} (Base: {base}). Ignorado.")

        except socket.timeout:
            pass 
        except Exception as e:
            print(f"Error: {e}")
            break

    # 3. Finalización 
    if base == len(paquetes):
        eof_packet = construir_paquete(len(paquetes), b'EOF')
        sock.sendto(eof_packet, client_addr)
        print("Transferencia de archivo completada.")

    if timer:
        timer.cancel()
    sock.close()

if __name__ == "__main__":
    server_main()