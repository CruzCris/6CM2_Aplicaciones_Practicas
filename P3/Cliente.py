import socket
import threading
import time
import sys
import os
import random

import modulo_rdt  # Tu módulo P2 refactorizado

try:
    import pygame
    pygame.mixer.init()
    print("[PYGAME] Módulo mixer inicializado.")

    def reproducir_audio(filepath):
        if not pygame.mixer.get_init():
            print("ERROR: Pygame mixer no inicializado.")
            return
        try:
            print(f"\n--- Reproduciendo {filepath} ---")
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play(0)
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            print("--- Reproducción finalizada ---")
        except Exception as e:
            print(f"ERROR en la reproducción: {e}")

except Exception as e:
    print(f"[ERROR PYGAME] No se pudo cargar Pygame. La reproducción de audio fallará. {e}")
    def reproducir_audio(filepath):
        print(f"SIMULACIÓN: Reproduciendo {filepath} (Pygame no disponible)")

# --- Configuración del cliente ---
SERVER_IP = "127.0.0.1"
SERVER_PORT = 12000
SERVER_ADDR = (SERVER_IP, SERVER_PORT)

mi_usuario = ""
salas_activas = set()  # Multi-salas
sala_actual = None      # Sala a la que se envían los mensajes por defecto
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", 0))

archivo_para_enviar_path = None  # Para audio o sticker pendiente

# -------------------- HILO RECEPTOR --------------------
def hilo_receptor(sock):
    global mi_usuario, archivo_para_enviar_path
    while True:
        try:
            data, _ = sock.recvfrom(1024)
            mensaje = data.decode()
            partes = mensaje.split('|', 3)
            comando, remitente, sala_dst, payload = partes

            if comando == "MSG_BCAST":
                if remitente != mi_usuario:
                    print(f"\n[{sala_dst}] {remitente}: {payload}")

            elif comando == "PM_RECV":
                print(f"\n[PM de {remitente}]: {payload}")

                # AUDIO
                if payload.startswith("AUDIO_ACCEPT"):
                    try:
                        _, dest_host, dest_port_str = payload.split('|')
                        dest_port = int(dest_port_str)
                        if archivo_para_enviar_path:
                            threading.Thread(
                                target=modulo_rdt.enviar_archivo_fiable,
                                args=(archivo_para_enviar_path, dest_host, dest_port),
                                daemon=True
                            ).start()
                            archivo_para_enviar_path = None
                    except Exception as e:
                        print(f"[ERROR] AUDIO_ACCEPT: {e}")

                # STICKER
                elif payload.startswith("STICKER_ACCEPT"):
                    try:
                        _, dest_host, dest_port_str = payload.split('|')
                        dest_port = int(dest_port_str)
                        if archivo_para_enviar_path:
                            threading.Thread(
                                target=modulo_rdt.enviar_archivo_fiable,
                                args=(archivo_para_enviar_path, dest_host, dest_port),
                                daemon=True
                            ).start()
                            archivo_para_enviar_path = None
                    except Exception as e:
                        print(f"[ERROR] STICKER_ACCEPT: {e}")

                # AUDIO_REQ o STICKER_REQ
                elif payload.startswith("AUDIO_REQ") or payload.startswith("STICKER_REQ"):
                    tipo, filename = payload.split('|')
                    print(f"\n[ALERTA {tipo}] '{remitente}' quiere enviarte '{filename}'.")
                    print(f"  Escribe: /accept_{tipo.lower()} {remitente} {filename}")

            elif comando == "USERLIST":
                print(f"\n*** Usuarios en [{sala_dst}]: {payload} ***")

            elif comando == "NOTICE":
                print(f"\n*** Noticia [{sala_dst}]: {payload} ***")

        except Exception as e:
            print(f"[ERROR Hilo Receptor]: {e}")
            break

# -------------------- HILO HEARTBEAT --------------------
def hilo_heartbeat(sock, username_provider):
    while True:
        username = username_provider()
        if username:
            try:
                packet = f"HEARTBEAT|{username}||".encode()
                sock.sendto(packet, SERVER_ADDR)
            except Exception as e:
                print(f"[ERROR Hilo Heartbeat]: {e}")
        time.sleep(30)

# -------------------- HILO EMISOR --------------------
def hilo_emisor(sock):
    global mi_usuario, salas_activas, sala_actual, archivo_para_enviar_path

    mi_usuario = input("Ingresa tu nombre de usuario: ")

    while True:
        try:
            mensaje = input(f"[{sala_actual}]> ")

            # --- SALAS ---
            if mensaje.startswith('/join '):
                sala = mensaje.split(' ', 1)[1]
                packet = f"JOIN|{mi_usuario}|{sala}|".encode()
                sock.sendto(packet, SERVER_ADDR)
                salas_activas.add(sala)
                sala_actual = sala
                print(f"Intentando unirse a '{sala}'...")

            elif mensaje.startswith('/leave '):
                sala = mensaje.split(' ', 1)[1]
                if sala in salas_activas:
                    packet = f"LEAVE|{mi_usuario}|{sala}|".encode()
                    sock.sendto(packet, SERVER_ADDR)
                    salas_activas.remove(sala)
                    if sala_actual == sala:
                        sala_actual = next(iter(salas_activas), None)
                    print(f"Saliendo de '{sala}'...")
                else:
                    print(f"No estás en la sala '{sala}'")

            elif mensaje.startswith('/switch '):
                sala = mensaje.split(' ', 1)[1]
                if sala in salas_activas:
                    sala_actual = sala
                    print(f"Sala actual: {sala_actual}")
                else:
                    print(f"No estás en la sala '{sala}'")

            # --- MENSAJES PRIVADOS ---
            elif mensaje.startswith('/pm '):
                partes = mensaje.split(' ', 2)
                if len(partes) == 3:
                    dest_user = partes[1]
                    payload = partes[2]
                    packet = f"PM|{mi_usuario}|{dest_user}|{payload}".encode()
                    sock.sendto(packet, SERVER_ADDR)
                    print(f"PM enviado a {dest_user} (no se muestra).")
                else:
                    print("Uso: /pm <usuario> <mensaje>")

            # --- ENVÍO AUDIO ---
            elif mensaje.startswith('/send_audio '):
                partes = mensaje.split(' ', 2)
                if len(partes) == 3:
                    dest_user = partes[1]
                    filepath = partes[2]
                    if not os.path.exists(filepath):
                        print(f"Archivo '{filepath}' no existe")
                        continue
                    archivo_para_enviar_path = filepath
                    filename = os.path.basename(filepath)
                    payload = f"AUDIO_REQ|{filename}"
                    packet = f"PM|{mi_usuario}|{dest_user}|{payload}".encode()
                    sock.sendto(packet, SERVER_ADDR)
                    print(f"Solicitud de audio enviada a {dest_user}. Esperando aceptación...")

            # --- ENVÍO STICKER ---
            elif mensaje.startswith('/send_sticker '):
                partes = mensaje.split(' ', 2)
                if len(partes) == 3:
                    dest_user = partes[1]
                    filepath = partes[2]
                    if not os.path.exists(filepath):
                        print(f"Archivo '{filepath}' no existe")
                        continue
                    archivo_para_enviar_path = filepath
                    filename = os.path.basename(filepath)
                    payload = f"STICKER_REQ|{filename}"
                    packet = f"PM|{mi_usuario}|{dest_user}|{payload}".encode()
                    sock.sendto(packet, SERVER_ADDR)
                    print(f"Solicitud de sticker enviada a {dest_user}. Esperando aceptación...")

            # --- ACEPTAR AUDIO/STICKER ---
            elif mensaje.startswith('/accept_audio ') or mensaje.startswith('/accept_sticker '):
                partes = mensaje.split(' ', 2)
                if len(partes) == 3:
                    origin_user = partes[1]
                    filename = partes[2]
                    p2p_port = random.randint(15000, 20000)
                    output_path = f"recibido_{filename}"
                    threading.Thread(
                        target=modulo_rdt.recibir_archivo_fiable,
                        args=(p2p_port, output_path),
                        daemon=True
                    ).start()
                    tipo = "AUDIO_ACCEPT" if mensaje.startswith('/accept_audio') else "STICKER_ACCEPT"
                    payload = f"{tipo}|127.0.0.1|{p2p_port}"
                    packet = f"PM|{mi_usuario}|{origin_user}|{payload}".encode()
                    sock.sendto(packet, SERVER_ADDR)
                    print(f"Aceptación enviada a {origin_user}. Escuchando en puerto {p2p_port}...")

            # --- MENSAJES NORMALES ---
            elif mensaje.startswith('@'):
                partes = mensaje.split(' ', 1)
                if len(partes) == 2:
                    dest_user = partes[0][1:]
                    contenido = partes[1]
                    packet = f"PM|{mi_usuario}|{dest_user}|{contenido}".encode()
                    sock.sendto(packet, SERVER_ADDR)
                    print(f"[Privado a {dest_user}] {contenido}")
                else:
                    print("Formato inválido. Usa: @usuario <mensaje>")
            else:
                if sala_actual:
                    packet = f"MSG|{mi_usuario}|{sala_actual}|{mensaje}".encode()
                    sock.sendto(packet, SERVER_ADDR)
                else:
                    print("No estás en ninguna sala. Únete con /join <sala>")

        except KeyboardInterrupt:
            print("\nSaliendo...")
            for sala in list(salas_activas):
                packet = f"LEAVE|{mi_usuario}|{sala}|".encode()
                sock.sendto(packet, SERVER_ADDR)
            sock.close()
            sys.exit(0)
        except Exception as e:
            print(f"[ERROR Hilo Emisor]: {e}")
            sock.close()
            sys.exit(1)

# -------------------- MAIN --------------------
def main():
    threading.Thread(target=hilo_receptor, args=(sock,), daemon=True).start()
    threading.Thread(target=hilo_heartbeat, args=(sock, lambda: mi_usuario), daemon=True).start()
    hilo_emisor(sock)

if __name__ == "__main__":
    main()