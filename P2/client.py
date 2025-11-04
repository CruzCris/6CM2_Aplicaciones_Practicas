import socket
import struct
import io
import time
import os
import pygame

# --- Inicialización de Pygame Mixer ---
try:
    pygame.mixer.init()
    print("[PYGAME] Módulo mixer inicializado correctamente.")
except pygame.error as e:
    # Esto puede fallar si el driver de sonido no está disponible
    print(f"[ERROR PYGAME] No se pudo inicializar el mixer: {e}")

# Variables globales de configuración
SERVER_IP = "127.0.0.1"
SERVER_PORT = 12000
CLIENT_IP = "127.0.0.1"
CLIENT_PORT = 12001
BUFFER_SIZE = 1024

HEADER_FORMAT = "!IH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Nombre del archivo temporal donde se guardará el MP3
OUTPUT_FILE = "cancion_recibida.mp3" 

expected_seq_num = 0 
file_buffer = io.BytesIO() 

# Función auxiliar para validar el checksum
def es_incorrecto(data):
    try:
        seq_num, received_checksum = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        payload = data[HEADER_SIZE:]
        calculated_checksum = sum(payload) % 65535 
        return calculated_checksum != received_checksum
    except struct.error:
        return True

# Función para reproducir el archivo MP3 usando Pygame
def play_mp3_file(filepath):
    if not pygame.mixer.get_init():
        print("ERROR: Pygame mixer no inicializado. No se puede reproducir.")
        return

    print(f"\n--- Reproduciendo {filepath} usando Pygame ---")
    try:
        # 1. Cargar el archivo
        pygame.mixer.music.load(filepath)
        
        # 2. Reproducir la canción (el 0 significa un loop, que reproduce una vez)
        pygame.mixer.music.play(0)
        
        # 3. Esperar a que la reproducción termine (bloqueante)
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
            
        print("--- Reproducción finalizada ---")

    except pygame.error as e:
        print(f"ERROR en la reproducción con Pygame: {e}. Verifique el formato MP3.")
    except Exception as e:
        print(f"ERROR inesperado durante la reproducción: {e}")

def client_main():
    global expected_seq_num, file_buffer

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((CLIENT_IP, CLIENT_PORT))
    
    server_addr = (SERVER_IP, SERVER_PORT)
    
    # 1. Enviar solicitud de inicio al servidor
    print(f"Enviando solicitud al servidor")
    sock.sendto(b"START", server_addr)

    # Bucle principal de recepción y almacenamiento
    print("Iniciando recepcion de paquetes...")
    while True:
        try:
            sock.settimeout(5.0) 
            paquete, addr = sock.recvfrom(BUFFER_SIZE)
            
            if len(paquete) < HEADER_SIZE:
                continue 

            # 2. Extraer información del paquete
            seq_num, checksum = struct.unpack(HEADER_FORMAT, paquete[:HEADER_SIZE])
            payload = paquete[HEADER_SIZE:]

            # 3. Finalización de la Transferencia
            if payload == b'EOF':
                print("Transferencia completa.")
                
                # Guarda el buffer completo en el archivo MP3
                with open(OUTPUT_FILE, 'wb') as f:
                    f.write(file_buffer.getvalue())
                print(f"Archivo guardado como '{OUTPUT_FILE}'.")
                
                # Inicia la reproducción
                play_mp3_file(OUTPUT_FILE)
                
                break
                
            # 4. Verificar si el paquete es correcto y en orden y manejar ACKs
            if not es_incorrecto(paquete) and seq_num == expected_seq_num:
                print(f"Paquete recibido correcto y en orden: {seq_num}")
                
                # Almacenar los datos en el buffer
                file_buffer.write(payload)
                
                # Enviar ACK para el siguiente paquete esperado
                expected_seq_num += 1
                paquete_ack = struct.pack("!I", expected_seq_num)
                sock.sendto(paquete_ack, server_addr)
                print(f"ACK enviado")

            else:
                # Paquete Corrupto o Fuera de Orden
                print(f"Paquete descartado {seq_num}. Esperando {expected_seq_num}")
                
                # Reenvía el ACK para el último paquete correcto
                paquete_ack = struct.pack("!I", expected_seq_num)
                sock.sendto(paquete_ack, server_addr)
                print(f"ACK reenviado")

        except socket.timeout:
            print("El servidor puede haber terminado inesperadamente.")
            break
        except Exception as e:
            print(f"Error: {e}")
            break

    sock.close()

if __name__ == "__main__":
    client_main()