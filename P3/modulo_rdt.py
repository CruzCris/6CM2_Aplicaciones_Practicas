#
# ARCHIVO: modulo_rdt.py
#
# Este archivo contiene la lógica de tu Práctica 2, 
# refactorizada en funciones que tu cliente de chat (P3) puede importar y usar.
#

import socket
import struct
import os
import time
import io
from threading import Timer

# --- Configuración y Funciones de P2 ---
BUFFER_SIZE = 1024 
PAYLOAD_SIZE = 1000 # Controla el tamaño de los bloques de datos
WINDOW_SIZE = 10 # Controla el número máximo de paquetes que se pueden enviar sin recibir un ACK
TIMEOUT = 0.5 # Tiempo de espera para el timeout en segundos

HEADER_FORMAT = "!IH" # Formato del encabezado: Número de secuencia (4 bytes), Checksum (2 bytes)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# --- Tu función para construir paquetes (de server_main) ---
def construir_paquete(seq_num, data):
    checksum = sum(data) % 65535
    header = struct.pack(HEADER_FORMAT, seq_num, checksum)
    return header + data

# --- Tu función para validar (de client_main) ---
def es_incorrecto(data):
    try:
        seq_num, received_checksum = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        payload = data[HEADER_SIZE:]
        if not payload: # Evitar error de 'sum' en payload vacío (ej. EOF)
            return received_checksum != 0
        calculated_checksum = sum(payload) % 65535 
        return calculated_checksum != received_checksum
    except struct.error:
        return True
    except Exception as e:
        print(f"[RDT es_incorrecto] Error: {e}")
        return True

g_base = 0
g_sig_num_sec = 0
g_paquetes = []
g_timer = None
g_sock = None
g_dest_addr = None

def retransmitir():
    """Función de retransmisión para el Timer (adaptada de tu P2)"""
    global g_base, g_sig_num_sec, g_paquetes, g_timer, g_sock, g_dest_addr
    
    print(f"\n[RDT Emisor] Tiempo expirado. Retransmitiendo desde base: {g_base}")
    if not g_sock:
        return # El socket pudo haberse cerrado
        
    try:
        for i in range(g_base, g_sig_num_sec):
            data_paquete = g_paquetes[i]
            packet = construir_paquete(i, data_paquete)
            g_sock.sendto(packet, g_dest_addr)
        
        # Reiniciar el timer
        g_timer = Timer(TIMEOUT, retransmitir)
        g_timer.start()
    except Exception as e:
        print(f"[RDT retransmitir] Error: {e}")

def detener_tiempo():
    global g_timer
    if g_timer:
        g_timer.cancel()
        g_timer = None

def enviar_archivo_fiable(filepath, host_destino, puerto_destino):
    """
    Esta función es tu 'server_main' de P2, refactorizada.
    Envía un archivo a un destinatario específico.
    """
    global g_base, g_sig_num_sec, g_paquetes, g_timer, g_sock, g_dest_addr
    
    print(f"\n[RDT Emisor] Iniciando envío fiable de '{filepath}' a {host_destino}:{puerto_destino}")
    
    g_dest_addr = (host_destino, puerto_destino)
    
    # --- Reiniciar estado global para este envío ---
    g_base = 0
    g_sig_num_sec = 0
    g_paquetes = []
    detener_tiempo()
    
    # --- Crear un NUEVO socket para esta transferencia ---
    g_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    g_sock.bind(("", 0)) # Usar un puerto efímero
    g_sock.settimeout(TIMEOUT * 2) # Timeout para recibir ACKs
    
    try:
        with open(filepath, 'rb') as f:
            data = f.read(PAYLOAD_SIZE)
            while data:
                g_paquetes.append(data)
                data = f.read(PAYLOAD_SIZE)
        print(f"[RDT Emisor] Archivo cargado. Total de paquetes: {len(g_paquetes)}")
    except FileNotFoundError:
        print(f"[RDT Emisor] ERROR: Archivo '{filepath}' no encontrado.")
        g_sock.close()
        return

    while g_base < len(g_paquetes):
        # 1. Enviar paquetes
        while g_sig_num_sec < g_base + WINDOW_SIZE and g_sig_num_sec < len(g_paquetes):
            data_paquete = g_paquetes[g_sig_num_sec]
            packet = construir_paquete(g_sig_num_sec, data_paquete)
            g_sock.sendto(packet, g_dest_addr)
            print(f"[RDT Emisor] Enviando paquete {g_sig_num_sec}")

            if g_base == g_sig_num_sec:
                detener_tiempo() # Detener timer anterior
                g_timer = Timer(TIMEOUT, retransmitir)
                g_timer.start()

            g_sig_num_sec += 1

        # 2. Esperar ACKs
        try:
            paquete_ack, _ = g_sock.recvfrom(BUFFER_SIZE)
            num_sec_ack = struct.unpack("!I", paquete_ack[:4])[0]
            
            if g_base <= num_sec_ack:
                print(f"[RDT Emisor] Recibido ACK {num_sec_ack}")
                g_base = num_sec_ack
                
                if g_base < g_sig_num_sec:
                    # Aún hay paquetes en vuelo, reiniciar timer
                    detener_tiempo()
                    g_timer = Timer(TIMEOUT, retransmitir)
                    g_timer.start()
                else:
                    # Todos los paquetes enviados han sido confirmados
                    detener_tiempo()
            else:
                print(f"[RDT Emisor] ACK no esperado {num_sec_ack} (Base: {g_base}). Ignorado.")

        except socket.timeout:
            pass # El timer se encargará de la retransmisión
        except Exception as e:
            print(f"[RDT Emisor] Error en ACK: {e}")
            break
            
    # --- Copia tu lógica de 'Finalización' de P2 aquí ---
    print("[RDT Emisor] Transferencia de archivo completada.")
    detener_tiempo()
    
    # Enviar EOF varias veces para asegurar que llegue
    for _ in range(5):
        eof_packet = construir_paquete(len(g_paquetes), b'EOF')
        g_sock.sendto(eof_packet, g_dest_addr)
        time.sleep(0.1)

    g_sock.close()
    g_sock = None
    print("[RDT Emisor] Hilo de envío finalizado.")


# --------------------------------------------------------------------------
#                          (receptor) refactorizada.
# --------------------------------------------------------------------------
def recibir_archivo_fiable(puerto_escucha, output_filename):
    """
    Esta función es tu 'client_main' de P2, refactorizada.
    Escucha en un puerto para recibir un archivo.
    Devuelve True si tiene éxito, False en caso contrario.
    """
    print(f"\n[RDT Receptor] Escuchando en el puerto {puerto_escucha} para recibir '{output_filename}'")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", puerto_escucha))
    except OSError as e:
        print(f"[RDT Receptor] ERROR: No se pudo enlazar al puerto {puerto_escucha}. {e}")
        return False

    expected_seq_num = 0 
    file_buffer = io.BytesIO() 
    transferencia_exitosa = False

    while True:
        try:
            sock.settimeout(10.0) # Timeout si el emisor tarda mucho en empezar/continuar
            paquete, addr = sock.recvfrom(BUFFER_SIZE)
            
            if len(paquete) < HEADER_SIZE:
                continue

            # 3. Finalización de la Transferencia
            # Validamos el EOF
            if not es_incorrecto(paquete):
                seq_num, _ = struct.unpack(HEADER_FORMAT, paquete[:HEADER_SIZE])
                payload = paquete[HEADER_SIZE:]
                if payload == b'EOF' and seq_num >= expected_seq_num:
                    print("[RDT Receptor] Transferencia completa (EOF recibido).")
                    with open(output_filename, 'wb') as f:
                        f.write(file_buffer.getvalue())
                    print(f"[RDT Receptor] Archivo guardado como '{output_filename}'.")
                    transferencia_exitosa = True
                    break
            
            # 4. Verificar paquete y manejar ACKs
            if not es_incorrecto(paquete):
                seq_num, _ = struct.unpack(HEADER_FORMAT, paquete[:HEADER_SIZE])
                
                if seq_num == expected_seq_num:
                    print(f"[RDT Receptor] Paquete {seq_num} OK.")
                    payload = paquete[HEADER_SIZE:]
                    file_buffer.write(payload)
                    
                    expected_seq_num += 1
                    paquete_ack = struct.pack("!I", expected_seq_num)
                    sock.sendto(paquete_ack, addr)
                else:
                    # Paquete fuera de orden (Stop-and-Wait rechaza)
                    print(f"[RDT Receptor] Paquete descartado {seq_num}. Esperando {expected_seq_num}")
                    paquete_ack = struct.pack("!I", expected_seq_num) # Re-enviar ACK del último OK
                    sock.sendto(paquete_ack, addr)
            else:
                # Paquete Corrupto
                print(f"[RDT Receptor] Paquete corrupto. Reenviando ACK para {expected_seq_num}")
                paquete_ack = struct.pack("!I", expected_seq_num)
                sock.sendto(paquete_ack, addr)

        except socket.timeout:
            print("[RDT Receptor] Timeout. El emisor no envió datos.")
            break
        except Exception as e:
            print(f"[RDT Receptor] Error: {e}")
            break

    sock.close()
    return transferencia_exitosa